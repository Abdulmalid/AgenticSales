"""Business analytics: funnel, revenue attribution, campaign comparison.

Honesty rules: small samples are labelled as such, and A/B "winners" are only declared when a
two-proportion z-test supports it AND both arms have enough volume. Anything else is "inconclusive".
"""
from __future__ import annotations

import math
from datetime import datetime

from .content.store import ContentStore
from .leads.models import LeadStage
from .leads.store import LeadStore

MIN_SAMPLE = 100          # visitors per arm before a winner may be called
Z_CRIT = 1.96             # ~95% two-sided


def funnel(leads: LeadStore) -> dict:
    allv = leads.list(limit=100_000)
    by_stage = {s.value: 0 for s in LeadStage}
    by_source: dict[str, dict] = {}
    for l in allv:
        by_stage[l.stage.value] += 1
        src = by_source.setdefault(l.source, {"leads": 0, "converted": 0})
        src["leads"] += 1
        src["converted"] += l.stage in (LeadStage.CONVERTED, LeadStage.RETAINED)
    purchases = leads.purchases()
    converted = sum(by_stage[s] for s in ("CONVERTED", "RETAINED"))
    days = []
    for l in allv:
        ps = leads.purchases(l.id)
        if ps and l.created:
            days.append((datetime.fromisoformat(ps[0]["ts"]) - datetime.fromisoformat(l.created)).total_seconds() / 86400)
    return {
        "total_leads": len(allv), "by_stage": by_stage, "converted": converted,
        "conversion_rate": round(converted / len(allv), 4) if allv else 0.0,
        "revenue_kobo": sum(p["amount_kobo"] for p in purchases), "orders": len(purchases),
        "avg_days_to_convert": round(sum(days) / len(days), 2) if days else None,
        "hot_leads": sum(1 for l in allv if l.band == "hot" and l.stage in (LeadStage.QUALIFIED, LeadStage.NEGOTIATING, LeadStage.READY_TO_BUY)),
        "fraud_suspected": by_stage["FRAUD_SUSPECTED"], "by_source": by_source,
    }


def _ztest(c1: int, n1: int, c2: int, n2: int) -> float:
    if min(n1, n2) == 0:
        return 0.0
    p1, p2, p = c1 / n1, c2 / n2, (c1 + c2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se else 0.0


def compare_variants(rows: list[dict], metric: str = "conversions", base: str = "clicks") -> dict:
    """rows: ContentStore.metrics() for one campaign, one row per variant."""
    arms = [r for r in rows if r.get(base, 0) > 0]
    out = {"arms": [{"variant": r["variant"], "n": r[base], "successes": r[metric],
                     "rate": round(r[metric] / r[base], 4)} for r in arms], "verdict": "inconclusive", "reason": ""}
    if len(arms) < 2:
        out["reason"] = "need at least two variants with traffic"
        return out
    a, b = sorted(arms, key=lambda r: r[metric] / r[base], reverse=True)[:2]
    if min(a[base], b[base]) < MIN_SAMPLE:
        out["reason"] = f"not enough volume (< {MIN_SAMPLE} per arm); results are noise"
        return out
    z = _ztest(a[metric], a[base], b[metric], b[base])
    out["z"] = round(z, 2)
    if abs(z) >= Z_CRIT:
        out.update(verdict=f"variant {a['variant']} is better", reason=f"z={z:.2f} (>= {Z_CRIT})")
    else:
        out["reason"] = f"difference not statistically significant (z={z:.2f})"
    return out


def campaign_report(content: ContentStore) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for m in content.metrics():
        by.setdefault(m["campaign_id"], []).append(m)
    rep = []
    for cid, rows in by.items():
        imp, clk = sum(r["impressions"] for r in rows), sum(r["clicks"] for r in rows)
        rep.append({"campaign_id": cid, "impressions": imp, "clicks": clk, "ctr": round(clk / imp, 4) if imp else None,
                    "leads": sum(r["leads"] for r in rows), "conversions": sum(r["conversions"] for r in rows),
                    "revenue_kobo": sum(r["revenue_kobo"] for r in rows), "comparison": compare_variants(rows)})
    return rep
