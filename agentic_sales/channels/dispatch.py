"""Outbox dispatcher and per-tenant secrets.

Compliance behaviour built in:
  * Opted-out customers are never messaged.
  * WhatsApp / Instagram / Messenger only allow free-form proactive messages within 24 hours of the
    customer's last message. Outside that window the item is parked as `needs_template` (it needs a
    platform-approved template message, which the business must create) rather than sent and rejected.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.types import TenantContext
from ..memory.store import TenantMemory
from .adapters import ADAPTERS, ChannelError, ChannelUnavailable

WINDOW = timedelta(hours=24)


class SecretStore:
    """Per-tenant channel/gateway credentials at <root>/tenants/<id>/secrets.json.
    NOTE: stored as plaintext JSON protected by file permissions only; encrypt at rest (KMS/secret
    manager) before multi-tenant production hosting."""

    def __init__(self, ctx: TenantContext, root: Path):
        self.path = root / "tenants" / ctx.tenant_id / "secrets.json"

    def _all(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, section: str) -> dict:
        v = self._all().get(section, {})
        return v if isinstance(v, dict) else {}

    def set(self, section: str, values: dict) -> None:
        data = self._all()
        data[section] = values
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")


@dataclass
class FlushReport:
    sent: int = 0
    failed: int = 0
    needs_template: int = 0
    skipped_opt_out: int = 0
    unavailable: int = 0


def _last_inbound(memory: TenantMemory, ckey: str) -> datetime | None:
    r = memory.con.execute("SELECT MAX(ts) FROM messages WHERE customer_key=? AND role='user'", (ckey,)).fetchone()
    return datetime.fromisoformat(r[0]) if r and r[0] else None


def flush_outbox(memory: TenantMemory, secrets: SecretStore, now: datetime | None = None) -> FlushReport:
    now = now or datetime.now(timezone.utc)
    rep = FlushReport()
    for item in memory.pending_outbox():
        ckey = item["customer_key"]
        channel, _, user_id = ckey.partition(":")
        adapter = ADAPTERS.get(channel)
        if adapter is None or not user_id:
            memory.mark_outbox(item["id"], "failed", "unknown channel")
            rep.failed += 1
            continue
        if memory.is_opted_out(ckey) and item["purpose"] != "opt_out_confirmation":
            memory.mark_outbox(item["id"], "skipped_opt_out")
            rep.skipped_opt_out += 1
            continue
        if adapter.requires_window:
            last = _last_inbound(memory, ckey)
            if last is None or now - last > WINDOW:
                memory.mark_outbox(item["id"], "needs_template", "outside the 24h customer-service window")
                rep.needs_template += 1
                continue
        try:
            adapter.send(user_id, item["text"], secrets.get(channel))
            memory.mark_outbox(item["id"], "sent")
            rep.sent += 1
        except ChannelUnavailable as e:
            memory.mark_outbox(item["id"], "pending", str(e))   # stays queued until credentials exist
            rep.unavailable += 1
        except ChannelError as e:
            memory.mark_outbox(item["id"], "failed", str(e))
            rep.failed += 1
    return rep
