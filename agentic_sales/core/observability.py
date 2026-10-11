"""Append-only, tenant-scoped audit trail answering "why did the AI do this?".

Each decision, tool call and policy outcome is one JSON line carrying a trace id, so a whole
customer turn can be reconstructed. Stored per tenant under <root>/tenants/<id>/audit.jsonl.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import TenantContext

_lock = threading.Lock()


class AuditLog:
    def __init__(self, ctx: TenantContext, root: Path):
        self.ctx = ctx
        self.path = root / "tenants" / ctx.tenant_id / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_trace() -> str:
        return uuid.uuid4().hex[:16]

    def record(self, trace: str, kind: str, **data: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "tenant": self.ctx.tenant_id,
                 "trace": trace, "kind": kind, **data}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def trace(self, trace: str) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [e for e in map(json.loads, fh) if e["trace"] == trace]
