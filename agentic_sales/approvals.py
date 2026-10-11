"""Human-in-the-loop: resolve queued approvals and carry out the consequence.

The owner decides; this module applies the decision with the same guards as the live agent:
a free-text reply from the owner passes the price/payment guard before it reaches a customer, and
every decision is atomic (an approval can be decided exactly once).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .config.business import BusinessConfig
from .core.observability import AuditLog
from .leads.models import LeadStage
from .leads.store import LeadStore
from .memory.store import TenantMemory
from .security.reply_guard import amounts_kobo, check_reply


@dataclass(frozen=True)
class Decision:
    ok: bool
    detail: str


def _inr(kobo: int) -> str:
    return f"₦{kobo / 100:,.0f}"


def decide(memory: TenantMemory, leads: LeadStore, cfg: BusinessConfig, audit: AuditLog, approval_id: int,
           approve: bool, by: str, reply_text: str | None = None) -> Decision:
    ap = memory.get_approval(approval_id)
    if ap is None:
        return Decision(False, "no such approval")
    if not memory.decide_approval(approval_id, "approved" if approve else "denied"):
        return Decision(False, "already decided")
    payload = json.loads(ap["payload"])
    ckey, action = ap["customer_key"], ap["action"]
    audit.record(ap["trace"] or "approval", "approval_decided", approval_id=approval_id, action=action,
                 approved=approve, by=by)

    if reply_text:
        allowed = {p.price_kobo for p in cfg.products} | {payload.get("offered_price_kobo", 0)}
        problems = check_reply(reply_text, allowed, payment_verified=False)
        if problems:
            return Decision(True, "decision recorded, but the reply was NOT sent: " + "; ".join(problems))
        memory.enqueue_message(ckey, reply_text, f"owner_reply:{action}")

    if action == "discount":
        sku, price = payload.get("sku"), payload.get("offered_price_kobo")
        product = cfg.product(sku) if sku else None
        if approve and product and isinstance(price, int) and 0 < price < product.price_kobo and price >= product.floor_price_kobo:
            memory.remember(ckey, f"agreed_price:{sku}", str(price), f"approval:{approval_id}:{by}")
            if not reply_text:
                memory.enqueue_message(ckey, f"Good news: we can do {_inr(price)} for the {product.name}. "
                                             "Shall I send you the payment link?", "discount_approved")
        elif approve:
            return Decision(False, "approved price is outside the allowed range (below floor or above list); not applied")
        elif product and not reply_text:
            memory.enqueue_message(ckey, f"Thanks for your patience. After checking, {_inr(product.price_kobo)} is the best "
                                         f"we can do on the {product.name}. Happy to get you started if that works.",
                                   "discount_denied")
    elif action == "order":
        if approve:
            memory.remember(ckey, f"approved_order:{payload.get('sku')}", str(payload.get("qty", 1)), f"approval:{approval_id}:{by}")
            if not reply_text:
                memory.enqueue_message(ckey, "Your order has been approved. Please share your email address and I'll send "
                                             "your secure payment link.", "order_approved")
    elif action == "fraud_review":
        lead = leads.get_by_key(ckey)
        if lead:
            if approve:       # owner clears the customer
                lead.stage, lead.fraud_risk = LeadStage.ENGAGED, "LOW"
                memory.remember(ckey, "fraud_cleared_by", by, f"approval:{approval_id}")
            else:             # owner confirms the concern: stays frozen and is excluded from outreach
                lead.stage = LeadStage.FRAUD_SUSPECTED
                memory.opt_out(ckey)
            leads.save(lead)
            leads.event(lead.id, "fraud_review", {"cleared": approve, "by": by, "approval": approval_id})
    return Decision(True, "applied")
