"""Per-tenant lead repository (same SQLite file as tenant memory, so isolation is identical)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..memory.store import TenantMemory
from .models import Lead, LeadStage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, customer_key TEXT NOT NULL UNIQUE, source TEXT NOT NULL, stage TEXT NOT NULL,
  name TEXT, interest TEXT, budget_kobo INTEGER, intent TEXT NOT NULL DEFAULT 'low', objection TEXT,
  trust_level TEXT NOT NULL DEFAULT 'unknown', fraud_risk TEXT NOT NULL DEFAULT 'LOW',
  score INTEGER NOT NULL DEFAULT 0, band TEXT NOT NULL DEFAULT 'cold', prob REAL NOT NULL DEFAULT 0,
  last_interaction TEXT, created TEXT NOT NULL, attrs TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS lead_events(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, ts TEXT NOT NULL, kind TEXT NOT NULL,
  data TEXT NOT NULL, trace TEXT);
CREATE INDEX IF NOT EXISTS lead_events_lead ON lead_events(lead_id, id);
CREATE TABLE IF NOT EXISTS purchases(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, sku TEXT, amount_kobo INTEGER NOT NULL,
  reference TEXT UNIQUE, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS followups(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, due TEXT NOT NULL, purpose TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL, UNIQUE(lead_id, due, purpose));
"""


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


class LeadStore:
    def __init__(self, memory: TenantMemory):
        self._con = memory.con
        self._con.executescript(_SCHEMA)

    @staticmethod
    def _lead(r: sqlite3.Row) -> Lead:
        return Lead(r["id"], r["customer_key"], r["source"], LeadStage(r["stage"]), r["name"], r["interest"],
                    r["budget_kobo"], r["intent"], r["objection"], r["trust_level"], r["fraud_risk"], r["score"],
                    r["band"], r["prob"], r["last_interaction"], r["created"], json.loads(r["attrs"]))

    def get_or_create(self, customer_key: str, source: str, now: datetime | None = None) -> tuple[Lead, bool]:
        r = self._con.execute("SELECT * FROM leads WHERE customer_key=?", (customer_key,)).fetchone()
        if r:
            return self._lead(r), False
        ts = now_iso(now)
        with self._con:
            self._con.execute("INSERT INTO leads(customer_key,source,stage,created,last_interaction) VALUES(?,?,?,?,?)",
                              (customer_key, source, LeadStage.NEW.value, ts, ts))
        return self.get_by_key(customer_key), True  # type: ignore[return-value]

    def get_by_key(self, customer_key: str) -> Lead | None:
        r = self._con.execute("SELECT * FROM leads WHERE customer_key=?", (customer_key,)).fetchone()
        return self._lead(r) if r else None

    def get(self, lead_id: int) -> Lead | None:
        r = self._con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return self._lead(r) if r else None

    def save(self, lead: Lead) -> None:
        with self._con:
            self._con.execute(
                "UPDATE leads SET stage=?, name=?, interest=?, budget_kobo=?, intent=?, objection=?, trust_level=?, "
                "fraud_risk=?, score=?, band=?, prob=?, last_interaction=?, attrs=? WHERE id=?",
                (lead.stage.value, lead.name, lead.interest, lead.budget_kobo, lead.intent, lead.objection,
                 lead.trust_level, lead.fraud_risk, lead.score, lead.band, lead.conversion_probability,
                 lead.last_interaction, json.dumps(lead.attrs), lead.id))

    def event(self, lead_id: int, kind: str, data: dict, trace: str | None = None,
              now: datetime | None = None) -> None:
        with self._con:
            self._con.execute("INSERT INTO lead_events(lead_id,ts,kind,data,trace) VALUES(?,?,?,?,?)",
                              (lead_id, now_iso(now), kind, json.dumps(data, ensure_ascii=False), trace))

    def events(self, lead_id: int, limit: int = 100) -> list[dict]:
        return [dict(r) | {"data": json.loads(r["data"])} for r in self._con.execute(
            "SELECT * FROM lead_events WHERE lead_id=? ORDER BY id DESC LIMIT ?", (lead_id, limit))]

    def list(self, stage: LeadStage | None = None, band: str | None = None, limit: int = 100) -> list[Lead]:
        sql, args = "SELECT * FROM leads WHERE 1=1", []
        if stage:
            sql += " AND stage=?"
            args.append(stage.value)
        if band:
            sql += " AND band=?"
            args.append(band)
        sql += " ORDER BY score DESC, last_interaction DESC LIMIT ?"
        args.append(limit)
        return [self._lead(r) for r in self._con.execute(sql, args)]

    # ---- purchases / follow-ups
    def record_purchase(self, lead_id: int, sku: str | None, amount_kobo: int, reference: str | None,
                        now: datetime | None = None) -> bool:
        """False if this payment reference was already recorded (idempotent against replays)."""
        try:
            with self._con:
                self._con.execute("INSERT INTO purchases(lead_id,sku,amount_kobo,reference,ts) VALUES(?,?,?,?,?)",
                                  (lead_id, sku, amount_kobo, reference, now_iso(now)))
            return True
        except sqlite3.IntegrityError:
            return False

    def purchases(self, lead_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM purchases" + (" WHERE lead_id=?" if lead_id else "") + " ORDER BY id"
        return [dict(r) for r in self._con.execute(sql, (lead_id,) if lead_id else ())]

    def add_followup(self, lead_id: int, due: datetime, purpose: str) -> bool:
        try:
            with self._con:
                self._con.execute("INSERT INTO followups(lead_id,due,purpose,created) VALUES(?,?,?,?)",
                                  (lead_id, due.isoformat(), purpose, now_iso()))
            return True
        except sqlite3.IntegrityError:
            return False

    def due_followups(self, now: datetime) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM followups WHERE status='pending' AND due<=? ORDER BY due", (now.isoformat(),))]

    def set_followup(self, fid: int, status: str) -> None:
        with self._con:
            self._con.execute("UPDATE followups SET status=? WHERE id=?", (status, fid))

    def has_followup(self, lead_id: int, purpose: str) -> bool:
        return self._con.execute("SELECT 1 FROM followups WHERE lead_id=? AND purpose=?", (lead_id, purpose)
                                 ).fetchone() is not None

    def erase(self, customer_key: str) -> None:
        lead = self.get_by_key(customer_key)
        if not lead:
            return
        with self._con:
            for t in ("lead_events", "purchases", "followups"):
                self._con.execute(f"DELETE FROM {t} WHERE lead_id=?", (lead.id,))
            self._con.execute("DELETE FROM leads WHERE id=?", (lead.id,))
