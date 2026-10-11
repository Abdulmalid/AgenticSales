"""Tenant-scoped memory: short-term conversation, customer memory, approvals queue.

Isolation is structural: each tenant gets its own SQLite file, derived solely from the trusted
TenantContext. There is no tenant_id column to forget in a WHERE clause, and no API that
accepts a tenant id from a caller other than the constructor.

Business memory (products/policies) lives in BusinessConfig; organisational/long-term analytics
memory is Phase 6. Customer facts carry a source and can be erased (NDPR right to erasure).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..core.types import Channel, TenantContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, customer_key TEXT NOT NULL,
  role TEXT NOT NULL, text TEXT NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS msg_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS customer_facts(
  customer_key TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
  ts TEXT NOT NULL, PRIMARY KEY(customer_key, key));
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, trace TEXT NOT NULL, customer_key TEXT NOT NULL, action TEXT NOT NULL,
  payload TEXT NOT NULL, reasons TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created TEXT NOT NULL, decided TEXT);
CREATE TABLE IF NOT EXISTS seen_messages(channel TEXT, message_id TEXT, PRIMARY KEY(channel, message_id));
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY, customer_key TEXT NOT NULL, text TEXT NOT NULL, purpose TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', error TEXT, trace TEXT, created TEXT NOT NULL, sent TEXT);
CREATE TABLE IF NOT EXISTS opt_outs(customer_key TEXT PRIMARY KEY, ts TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def customer_key(channel: Channel, user_id: str) -> str:
    return f"{channel.value}:{user_id}"


class TenantMemory:
    def __init__(self, ctx: TenantContext, root: Path):
        self.ctx = ctx
        path = root / "tenants" / ctx.tenant_id / "memory.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_SCHEMA)

    @property
    def con(self) -> sqlite3.Connection:
        """Shared tenant connection for repositories (leads, content, ...). Same file, same isolation."""
        return self._con

    # ---- consent (NDPR): customers who say STOP are never contacted proactively
    def opt_out(self, ckey: str) -> None:
        with self._con:
            self._con.execute("INSERT OR REPLACE INTO opt_outs VALUES(?,?)", (ckey, _now()))

    def is_opted_out(self, ckey: str) -> bool:
        return self._con.execute("SELECT 1 FROM opt_outs WHERE customer_key=?", (ckey,)).fetchone() is not None

    # ---- outbox: every proactive/async message goes through here, then a channel dispatcher sends it
    def enqueue_message(self, ckey: str, text: str, purpose: str, trace: str | None = None) -> int:
        with self._con:
            cur = self._con.execute("INSERT INTO outbox(customer_key,text,purpose,trace,created) VALUES(?,?,?,?,?)",
                                    (ckey, text, purpose, trace, _now()))
        return int(cur.lastrowid)

    def pending_outbox(self) -> list[dict]:
        return [dict(r) for r in self._con.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY id")]

    def mark_outbox(self, oid: int, status: str, error: str | None = None) -> None:
        with self._con:
            self._con.execute("UPDATE outbox SET status=?, error=?, sent=? WHERE id=?",
                              (status, error, _now() if status == "sent" else None, oid))

    # ---- approvals: decisions
    def get_approval(self, aid: int) -> dict | None:
        r = self._con.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None

    def decide_approval(self, aid: int, status: str) -> bool:
        """Atomically move pending -> approved|denied. False if already decided (no double-spend)."""
        with self._con:
            cur = self._con.execute("UPDATE approvals SET status=?, decided=? WHERE id=? AND status='pending'",
                                    (status, _now(), aid))
        return cur.rowcount == 1

    # ---- idempotency (webhooks redeliver)
    def first_time(self, channel: Channel, message_id: str | None) -> bool:
        if not message_id:
            return True
        try:
            with self._con:
                self._con.execute("INSERT INTO seen_messages VALUES(?,?)", (channel.value, message_id))
            return True
        except sqlite3.IntegrityError:
            return False

    # ---- short-term
    def add_message(self, conversation_id: str, ckey: str, role: str, text: str) -> None:
        with self._con:
            self._con.execute(
                "INSERT INTO messages(conversation_id,customer_key,role,text,ts) VALUES(?,?,?,?,?)",
                (conversation_id, ckey, role, text, _now()))

    def history(self, conversation_id: str, limit: int = 12) -> list[tuple[str, str]]:
        rows = self._con.execute(
            "SELECT role,text FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit)).fetchall()
        return [(r["role"], r["text"]) for r in reversed(rows)]

    # ---- customer memory
    def remember(self, ckey: str, key: str, value: str, source: str) -> None:
        with self._con:
            self._con.execute(
                "INSERT INTO customer_facts VALUES(?,?,?,?,?) ON CONFLICT(customer_key,key) "
                "DO UPDATE SET value=excluded.value, source=excluded.source, ts=excluded.ts",
                (ckey, key[:64], value[:500], source, _now()))

    def facts(self, ckey: str) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._con.execute(
            "SELECT key,value FROM customer_facts WHERE customer_key=?", (ckey,))}

    def erase_customer(self, ckey: str) -> None:
        with self._con:
            for table in ("messages", "customer_facts", "approvals"):
                self._con.execute(f"DELETE FROM {table} WHERE customer_key=?", (ckey,))

    # ---- human-in-the-loop queue
    def request_approval(self, trace: str, ckey: str, action: str, payload: dict,
                         reasons: tuple[str, ...]) -> int:
        with self._con:
            cur = self._con.execute(
                "INSERT INTO approvals(trace,customer_key,action,payload,reasons,created) "
                "VALUES(?,?,?,?,?,?)",
                (trace, ckey, action, json.dumps(payload), json.dumps(reasons), _now()))
        return int(cur.lastrowid)

    def pending_approvals(self) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM approvals WHERE status='pending' ORDER BY id")]
