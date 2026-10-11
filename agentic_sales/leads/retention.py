"""Retention & recovery scheduling.

Three jobs, all idempotent (safe to run every few minutes):
  1. schedule_after_purchase: turn the business's configurable retention_schedule into follow-ups.
  2. mark_stale_leads: open leads silent for N days get a one-time recovery follow-up; after M days -> LOST.
  3. run_due: compose and enqueue due follow-ups into the outbox (never sends directly), honouring
     opt-outs and fraud status.

Message text comes from a `Composer` (LLM-backed in production, template fallback), and every
composed message passes the same price/payment guard as live replies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config.business import BusinessConfig
from ..memory.store import TenantMemory
from ..security.reply_guard import check_reply
from .models import OPEN_STAGES, Lead, LeadStage
from .store import LeadStore

RECOVERY = "abandoned_lead_recovery"
STALE_AFTER_DAYS = 3
LOST_AFTER_DAYS = 21
MAX_RECOVERY_PER_LEAD = 1


class Composer(Protocol):
    def compose(self, purpose: str, lead: Lead, facts: dict[str, str], cfg: BusinessConfig) -> str: ...


class TemplateComposer:
    """Deterministic fallback so follow-ups still work with no model configured."""
    T = {
        "purchase_confirmation": "Thank you for your order with {biz}! We'll keep you updated.",
        "satisfaction_check": "Hi, it's {biz}. How are you finding your purchase? Let us know if anything isn't right.",
        "usage_followup": "Hi, {biz} here. Is everything working well for you? Happy to help with any questions.",
        "related_product": "Hi, {biz} here. Since you bought from us, you might like our other products. Want to see them?",
        "retention_campaign": "Hi, it's {biz}. It's been a while! Anything we can help you with this month?",
        RECOVERY: "Hi, it's {biz}. Just checking in on your interest earlier. Still keen? I can answer any question.",
    }

    def compose(self, purpose: str, lead: Lead, facts: dict[str, str], cfg: BusinessConfig) -> str:
        return self.T.get(purpose, "Hi, it's {biz}. Just checking in.").format(biz=cfg.business_name)


def schedule_after_purchase(store: LeadStore, lead: Lead, cfg: BusinessConfig, purchased_at: datetime) -> int:
    n = 0
    for day, purpose in sorted(cfg.retention_schedule.items()):
        n += store.add_followup(lead.id, purchased_at + timedelta(days=day), purpose)
    return n


def mark_stale_leads(store: LeadStore, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    out = {"recovery_scheduled": 0, "lost": 0}
    for lead in store.list(limit=10_000):
        if lead.stage not in OPEN_STAGES or not lead.last_interaction:
            continue
        silent = (now - datetime.fromisoformat(lead.last_interaction)).days
        if silent >= LOST_AFTER_DAYS:
            lead.stage = LeadStage.LOST
            store.save(lead)
            store.event(lead.id, "stage_change", {"to": "LOST", "why": f"silent {silent}d"}, now=now)
            out["lost"] += 1
        elif silent >= STALE_AFTER_DAYS and lead.stage is not LeadStage.NEW and not store.has_followup(lead.id, RECOVERY):
            out["recovery_scheduled"] += store.add_followup(lead.id, now, RECOVERY)
    return out


@dataclass
class RunReport:
    enqueued: int = 0
    skipped_opt_out: int = 0
    skipped_fraud: int = 0
    blocked_by_guard: int = 0


def run_due(store: LeadStore, memory: TenantMemory, cfg: BusinessConfig, composer: Composer | None = None,
            now: datetime | None = None) -> RunReport:
    now = now or datetime.now(timezone.utc)
    composer = composer or TemplateComposer()
    rep = RunReport()
    allowed = {p.price_kobo for p in cfg.products}
    for f in store.due_followups(now):
        lead = store.get(f["lead_id"])
        if lead is None:
            store.set_followup(f["id"], "cancelled")
            continue
        if memory.is_opted_out(lead.customer_key):
            store.set_followup(f["id"], "skipped_opt_out")
            rep.skipped_opt_out += 1
            continue
        if lead.stage is LeadStage.FRAUD_SUSPECTED or lead.fraud_risk == "HIGH":
            store.set_followup(f["id"], "skipped_fraud")
            rep.skipped_fraud += 1
            continue
        text = composer.compose(f["purpose"], lead, memory.facts(lead.customer_key), cfg)
        if check_reply(text, allowed):
            store.set_followup(f["id"], "blocked")
            rep.blocked_by_guard += 1
            continue
        memory.enqueue_message(lead.customer_key, text, f["purpose"])
        store.set_followup(f["id"], "queued")
        store.event(lead.id, "followup_queued", {"purpose": f["purpose"]}, now=now)
        rep.enqueued += 1
    return rep
