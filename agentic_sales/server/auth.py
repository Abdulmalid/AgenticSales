"""Tenant registry and API keys.

Keys look like `ask_<43 url-safe chars>`; only a SHA-256 hash is stored (the key is shown once at
creation). The key alone identifies the tenant: no /v1 endpoint accepts a tenant id from the
caller, so one tenant cannot even address another's data. Roles: admin (everything) and staff
(operate leads/approvals/content; no config, secrets or key management).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config.business import BusinessConfig
from ..core.types import TenantContext

ROLES = ("admin", "staff")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), key_hash TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL, label TEXT, created TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
"""


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AuthStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        self._con = sqlite3.connect(root / "auth.db", check_same_thread=False)
        self._con.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def tenant_exists(self, tenant_id: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone() is not None

    def create_tenant(self, tenant_id: str, business: dict, label: str = "initial admin") -> str:
        ctx = TenantContext(tenant_id)                      # validates the id
        BusinessConfig.from_dict(business)                  # validates the config before anything is written
        with self._lock:
            if self._con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone():
                raise ValueError("tenant already exists")
            with self._con:
                self._con.execute("INSERT INTO tenants VALUES(?,?)", (tenant_id, datetime.now(timezone.utc).isoformat()))
        path = self._root / "tenants" / ctx.tenant_id / "business.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(business, indent=1), encoding="utf-8")
        return self.issue_key(tenant_id, "admin", label)

    def issue_key(self, tenant_id: str, role: str, label: str = "") -> str:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        key = "ask_" + secrets.token_urlsafe(32)
        with self._lock, self._con:
            self._con.execute("INSERT INTO api_keys(tenant_id,key_hash,role,label,created) VALUES(?,?,?,?,?)",
                              (tenant_id, _hash(key), role, label, datetime.now(timezone.utc).isoformat()))
        return key

    def authenticate(self, token: str | None) -> Principal | None:
        if not token or not token.startswith("ask_") or len(token) > 80:
            return None
        with self._lock:
            r = self._con.execute("SELECT tenant_id, role FROM api_keys WHERE key_hash=? AND revoked=0",
                                  (_hash(token),)).fetchone()
        return Principal(r[0], r[1]) if r else None

    def revoke(self, tenant_id: str, key_id: int) -> bool:
        with self._lock, self._con:
            return self._con.execute("UPDATE api_keys SET revoked=1 WHERE id=? AND tenant_id=?",
                                     (key_id, tenant_id)).rowcount == 1

    def list_keys(self, tenant_id: str) -> list[dict]:
        with self._lock:
            return [dict(id=r[0], role=r[1], label=r[2], created=r[3], revoked=bool(r[4])) for r in self._con.execute(
                "SELECT id, role, label, created, revoked FROM api_keys WHERE tenant_id=?", (tenant_id,))]
