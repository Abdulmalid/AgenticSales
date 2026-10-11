"""Content items: drafts -> pending_approval -> approved -> scheduled -> published (or rejected)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..memory.store import TenantMemory

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items(
  id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, platform TEXT NOT NULL, surface TEXT, objective TEXT,
  caption TEXT NOT NULL, hashtags TEXT NOT NULL DEFAULT '[]', cta TEXT, image_prompt TEXT, video_script TEXT,
  alt_text TEXT, media_path TEXT, status TEXT NOT NULL, violations TEXT NOT NULL DEFAULT '[]',
  guidance_ids TEXT NOT NULL DEFAULT '[]', brief TEXT, created TEXT NOT NULL, decided_by TEXT, decided TEXT,
  scheduled_for TEXT, published_ref TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS campaign_metrics(
  id INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL, variant TEXT NOT NULL DEFAULT 'A', ts TEXT NOT NULL,
  impressions INTEGER NOT NULL DEFAULT 0, clicks INTEGER NOT NULL DEFAULT 0, leads INTEGER NOT NULL DEFAULT 0,
  conversions INTEGER NOT NULL DEFAULT 0, revenue_kobo INTEGER NOT NULL DEFAULT 0);
"""
STATUSES = ("draft", "pending_approval", "approved", "scheduled", "published", "rejected")


class ContentStore:
    def __init__(self, memory: TenantMemory):
        self._con = memory.con
        self._con.executescript(_SCHEMA)

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        for k in ("hashtags", "violations", "guidance_ids"):
            d[k] = json.loads(d[k])
        d["video_script"] = json.loads(d["video_script"]) if d["video_script"] else None
        return d

    def add(self, **f) -> int:
        cols = dict(created=datetime.now(timezone.utc).isoformat(), **f)
        for k in ("hashtags", "violations", "guidance_ids"):
            if k in cols:
                cols[k] = json.dumps(cols[k], ensure_ascii=False)
        if cols.get("video_script") is not None:
            cols["video_script"] = json.dumps(cols["video_script"], ensure_ascii=False)
        with self._con:
            cur = self._con.execute(f"INSERT INTO content_items({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                    tuple(cols.values()))
        return int(cur.lastrowid)

    def get(self, item_id: int) -> dict | None:
        r = self._con.execute("SELECT * FROM content_items WHERE id=?", (item_id,)).fetchone()
        return self._row(r) if r else None

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        sql, args = "SELECT * FROM content_items", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        return [self._row(r) for r in self._con.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def update(self, item_id: int, **f) -> None:
        for k in ("hashtags", "violations"):
            if k in f:
                f[k] = json.dumps(f[k], ensure_ascii=False)
        with self._con:
            self._con.execute(f"UPDATE content_items SET {', '.join(k + '=?' for k in f)} WHERE id=?",
                              (*f.values(), item_id))

    def transition(self, item_id: int, allowed_from: tuple[str, ...], to: str, by: str | None = None) -> bool:
        """Atomic status change; False if the item is not in an allowed source status."""
        with self._con:
            cur = self._con.execute(
                f"UPDATE content_items SET status=?, decided_by=COALESCE(?, decided_by), decided=? "
                f"WHERE id=? AND status IN ({','.join('?' * len(allowed_from))})",
                (to, by, datetime.now(timezone.utc).isoformat(), item_id, *allowed_from))
        return cur.rowcount == 1

    # ---- campaign metrics
    def record_metrics(self, campaign_id: str, variant: str = "A", *, impressions=0, clicks=0, leads=0,
                       conversions=0, revenue_kobo=0) -> None:
        with self._con:
            self._con.execute("INSERT INTO campaign_metrics(campaign_id,variant,ts,impressions,clicks,leads,conversions,revenue_kobo)"
                              " VALUES(?,?,?,?,?,?,?,?)",
                              (campaign_id, variant, datetime.now(timezone.utc).isoformat(), impressions, clicks, leads,
                               conversions, revenue_kobo))

    def metrics(self, campaign_id: str | None = None) -> list[dict]:
        sql = ("SELECT campaign_id, variant, SUM(impressions) impressions, SUM(clicks) clicks, SUM(leads) leads, "
               "SUM(conversions) conversions, SUM(revenue_kobo) revenue_kobo FROM campaign_metrics")
        args: tuple = ()
        if campaign_id:
            sql += " WHERE campaign_id=?"
            args = (campaign_id,)
        return [dict(r) for r in self._con.execute(sql + " GROUP BY campaign_id, variant", args)]
