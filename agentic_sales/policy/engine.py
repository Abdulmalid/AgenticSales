"""Deterministic business-policy enforcement.

The model may *propose* actions; this module decides. Policy is code plus tenant config,
never prompt text, so a persuasive customer cannot talk the agent past it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config.business import BusinessConfig, Product


class Verdict(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reasons: tuple[str, ...]


class PolicyEngine:
    def __init__(self, cfg: BusinessConfig):
        self.cfg = cfg

    def check_discount(self, product: Product, offered_price_kobo: int,
                       quantity: int = 1) -> Decision:
        a = self.cfg.approvals
        if offered_price_kobo <= 0 or quantity < 1:
            return Decision(Verdict.DENY, ("invalid price or quantity",))
        if offered_price_kobo >= product.price_kobo:
            return Decision(Verdict.ALLOW, ("price at or above list",))
        pct = (product.price_kobo - offered_price_kobo) / product.price_kobo * 100
        reasons = [f"discount {pct:.1f}% off list"]
        if offered_price_kobo < product.floor_price_kobo or pct > a.max_discount_pct_hard:
            return Decision(Verdict.DENY, (*reasons, "below floor price / hard discount limit"))
        verdict = Verdict.ALLOW
        if pct > a.max_discount_pct_auto:
            verdict = Verdict.REQUIRE_APPROVAL
            reasons.append(f"exceeds auto limit {a.max_discount_pct_auto}%")
        if offered_price_kobo * quantity >= a.large_transaction_kobo:
            verdict = Verdict.REQUIRE_APPROVAL
            reasons.append("large transaction")
        return Decision(verdict, tuple(reasons))

    # Concession ladder: within its authority the agent concedes in steps, never straight to the limit.
    # Rung r offers (max_discount_pct_auto * LADDER[r]) percent off; the model is never told the final rung.
    LADDER = (0.4, 0.7, 1.0)

    def ladder_price(self, product: Product, round_idx: int) -> int:
        pct = self.cfg.approvals.max_discount_pct_auto * self.LADDER[max(0, min(round_idx, len(self.LADDER) - 1))]
        return round(product.price_kobo * (1 - pct / 100))

    def check_refund(self) -> Decision:
        if self.cfg.approvals.refunds_need_approval:
            return Decision(Verdict.REQUIRE_APPROVAL, ("refunds require human approval",))
        return Decision(Verdict.ALLOW, ())

    def check_fulfilment(self, fraud_risk: str) -> Decision:
        if fraud_risk.upper() == "HIGH" and self.cfg.approvals.high_fraud_risk_needs_approval:
            return Decision(Verdict.REQUIRE_APPROVAL, ("high fraud risk",))
        return Decision(Verdict.ALLOW, ())
