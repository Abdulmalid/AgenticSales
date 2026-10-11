"""Lead qualification: stage transitions, intent/objection inference and transparent scoring.

Scoring is an additive, auditable heuristic (every point has a reason). `conversion_probability`
is a monotone transform of the score, NOT a calibrated probability: there is no conversion history
to calibrate on yet. Replace `probability()` with a fitted model once purchases accumulate
(`LeadStore.purchases`, `lead_events`).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config.business import BusinessConfig
from ..security.reply_guard import _to_kobo, amounts_kobo
from .models import Lead, LeadStage
from .store import LeadStore

# ---- scoring -------------------------------------------------------------------------------
SIGNAL_POINTS = {
    "ready_to_buy": 35, "payment_claim": 15, "negotiation": 15, "delivery_concern": 10, "urgency": 10,
    "price_inquiry": 8, "availability_check": 5, "bulk_or_reseller": 10, "returning_customer": 10,
    "referral": 8, "stalling": -8, "trust_concern": -5, "competitor_comparison": -3,
    "complaint_or_refund": -10, "pressure_tactic": -10,
}
_RANK = {LeadStage.NEW: 0, LeadStage.DISCOVERED: 1, LeadStage.CONTACTED: 2, LeadStage.ENGAGED: 3,
         LeadStage.QUALIFIED: 4, LeadStage.NEGOTIATING: 5, LeadStage.READY_TO_BUY: 6}
_FROZEN = (LeadStage.CONVERTED, LeadStage.RETAINED, LeadStage.FRAUD_SUSPECTED)  # leave only via explicit events
_BUDGET = re.compile(r"(budget|i have|i get|my money|not more than|cannot pay more than|dey get|i fit pay|i can pay|"
                     r"i can afford|i go pay|i wan pay|i'?ll pay|i will pay|my max)[^\d₦nN]{0,20}"
                     r"(?:₦|\bN|\bNGN\s?)?\s?(\d[\d,]*(?:\.\d+)?)\s?(?:(k|m|million|thousand)\b)?", re.I)


@dataclass(frozen=True)
class ScoreBreakdown:
    value: int
    band: str
    probability: float
    reasons: tuple[str, ...]
    calibrated: bool = False


@dataclass(frozen=True)
class StageChange:
    old: LeadStage
    new: LeadStage
    why: str


def probability(score: int) -> float:
    return round(1 / (1 + math.exp(-(score - 50) / 15)), 3)


def score_lead(lead: Lead, cfg: BusinessConfig | None = None, now: datetime | None = None) -> ScoreBreakdown:
    now = now or datetime.now(timezone.utc)
    reasons, pts = [], 0
    for name, count in sorted((lead.attrs.get("signals_seen") or {}).items()):
        w = SIGNAL_POINTS.get(name)
        if w:
            add = round(w * (1.0 if count == 1 else 1.5))
            pts += add
            reasons.append(f"{name} x{count}: {add:+d}")
    if lead.interest:
        pts += 8
        reasons.append("specific product interest: +8")
    if lead.budget_kobo:
        pts += 5
        reasons.append("stated budget: +5")
    if (lead.attrs.get("messages") or 0) >= 3:
        pts += 5
        reasons.append("sustained conversation: +5")
    if lead.trust_level == "high":
        pts += 5
        reasons.append("high trust: +5")
    if lead.last_interaction:
        age = (now - datetime.fromisoformat(lead.last_interaction)).total_seconds() / 86400
        decay = 0 if age <= 1 else -5 if age <= 3 else -15 if age <= 7 else -30
        if decay:
            pts += decay
            reasons.append(f"inactive {age:.0f}d: {decay}")
    if lead.fraud_risk == "HIGH":
        pts -= 50
        reasons.append("high fraud risk: -50")
    elif lead.fraud_risk == "MEDIUM":
        pts -= 15
        reasons.append("medium fraud risk: -15")
    value = max(0, min(100, pts))
    band = "hot" if value >= 50 else "warm" if value >= 25 else "cold"
    return ScoreBreakdown(value, band, probability(value), tuple(reasons))


# ---- inference -----------------------------------------------------------------------------
def budget_from_text(text: str) -> int | None:
    """Only when the sentence is about what the customer can pay. Bare small numbers ("I have 2") are ignored:
    the amount needs a ₦ sign, a k/m suffix, or at least 4 digits."""
    for m in _BUDGET.finditer(text):
        num, suffix = m.group(2), m.group(3)
        has_currency = bool(re.search(r"(₦|\bN\s?\d|\bNGN)", m.group(0), re.I))
        if has_currency or suffix or len(num.replace(",", "").split(".")[0]) >= 4:
            return _to_kobo(num, suffix)
    return None


def product_from_text(text: str, cfg: BusinessConfig) -> str | None:
    low = text.lower()
    for p in cfg.products:
        words = [w for w in re.findall(r"[a-z0-9]+", p.name.lower()) if len(w) > 2]
        if p.sku.lower() in low or (words and sum(w in low for w in words) >= max(1, math.ceil(len(words) / 2))):
            return p.sku
    return None


def infer_intent(names: set[str]) -> str:
    if names & {"ready_to_buy", "payment_claim"}:
        return "high"
    if names & {"negotiation", "delivery_concern", "bulk_or_reseller", "returning_customer"}:
        return "medium"
    return "low"


def infer_objection(names: set[str]) -> str | None:
    for sig, obj in (("trust_concern", "trust"), ("negotiation", "price"), ("stalling", "payment_terms"),
                     ("delivery_concern", "delivery")):
        if sig in names:
            return obj
    return None


def next_stage(cur: LeadStage, names: set[str], has_interest: bool, fraud_risk: str) -> tuple[LeadStage, str]:
    if cur is LeadStage.FRAUD_SUSPECTED:
        return cur, "frozen: human review required"
    if fraud_risk == "HIGH":
        return LeadStage.FRAUD_SUSPECTED, "high fraud risk"
    if cur in (LeadStage.CONVERTED, LeadStage.RETAINED):
        return cur, "already a customer"
    target = cur
    if cur is LeadStage.LOST:
        target, why = LeadStage.ENGAGED, "lost lead re-engaged"
    else:
        why = "inbound message"
    if names & {"ready_to_buy", "payment_claim"} and "negotiation" not in names:
        target, why = LeadStage.READY_TO_BUY, "expressed purchase intent / payment"
    elif "negotiation" in names:
        target, why = LeadStage.NEGOTIATING, "negotiating price/terms"
    elif has_interest and names & {"price_inquiry", "availability_check", "delivery_concern", "urgency"}:
        target, why = LeadStage.QUALIFIED, "specific product interest with buying questions"
    elif cur in (LeadStage.NEW, LeadStage.DISCOVERED, LeadStage.CONTACTED, LeadStage.LOST):
        target, why = LeadStage.ENGAGED, why
    # never move backwards, except the haggle loop READY_TO_BUY <-> NEGOTIATING
    if cur in _RANK and target in _RANK and _RANK[target] < _RANK[cur]:
        if {cur, target} != {LeadStage.READY_TO_BUY, LeadStage.NEGOTIATING}:
            return cur, "no regression"
    return target, why


def apply_turn(store: LeadStore, lead: Lead, names: set[str], text: str, cfg: BusinessConfig, *,
               fraud_risk: str = "LOW", trace: str | None = None, now: datetime | None = None
               ) -> tuple[Lead, StageChange | None, ScoreBreakdown]:
    now = now or datetime.now(timezone.utc)
    seen = lead.attrs.setdefault("signals_seen", {})
    for n in names:
        seen[n] = min(seen.get(n, 0) + 1, 3)
    lead.attrs["messages"] = (lead.attrs.get("messages") or 0) + 1
    lead.last_interaction = now.isoformat()
    sku = product_from_text(text, cfg)
    if sku:
        lead.interest = sku
    budget = budget_from_text(text)
    if budget:
        lead.budget_kobo = budget
    lead.intent = max(lead.intent, infer_intent(names), key=("low", "medium", "high").index)
    lead.objection = infer_objection(names) or lead.objection
    if "trust_concern" in names and lead.trust_level != "high":
        lead.trust_level = "low"
    if names & {"returning_customer", "referral"}:
        lead.trust_level = "high"
    lead.fraud_risk = fraud_risk
    new_stage, why = next_stage(lead.stage, names, bool(lead.interest), fraud_risk)
    change = None
    if new_stage is not lead.stage:
        change = StageChange(lead.stage, new_stage, why)
        lead.stage = new_stage
    sc = score_lead(lead, cfg, now)
    lead.score, lead.band, lead.conversion_probability = sc.value, sc.band, sc.probability
    store.save(lead)
    store.event(lead.id, "turn", {"signals": sorted(names), "stage": lead.stage.value, "score": sc.value,
                                  "intent": lead.intent, "objection": lead.objection}, trace, now)
    if change:
        store.event(lead.id, "stage_change", {"from": change.old.value, "to": change.new.value, "why": change.why},
                    trace, now)
    return lead, change, sc


def mark_converted(store: LeadStore, lead: Lead, sku: str | None, amount_kobo: int, reference: str | None,
                   trace: str | None = None, now: datetime | None = None) -> bool:
    """Record a verified purchase. Idempotent per payment reference."""
    now = now or datetime.now(timezone.utc)
    if not store.record_purchase(lead.id, sku, amount_kobo, reference, now):
        return False
    old = lead.stage
    lead.stage = LeadStage.RETAINED if old in (LeadStage.CONVERTED, LeadStage.RETAINED) else LeadStage.CONVERTED
    lead.trust_level = "high"
    lead.fraud_risk = "LOW" if lead.fraud_risk != "HIGH" else lead.fraud_risk
    store.save(lead)
    store.event(lead.id, "purchase", {"sku": sku, "amount_kobo": amount_kobo, "reference": reference,
                                      "from": old.value, "to": lead.stage.value}, trace, now)
    return True
