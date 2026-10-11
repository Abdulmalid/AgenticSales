"""Fraud risk assessment.

Principles (from the product spec): weak signals never convict anyone. The output is a risk band
with a confidence, internal reasons, and a recommended action: never an accusation, and the
customer-facing reply must stay neutral and polite. HIGH requires corroboration from at least two
independent signal families, or one decisive fact (verified payment mismatch).

Families (independence matters: five "pressure" phrases are still one family):
  payment  - claims of payment without gateway verification, screenshot-only evidence, amount mismatch
  pressure - urgency + "send first / owner approved / pay after" style coercion
  identity - delivery details changing, third-party pickup, inconsistent names
  system   - prompt-injection or tool-abuse attempts against the agent
  pattern  - repeated failed payments, repeated claims, burst of messages
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Risk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class PaymentFacts:
    claimed: bool = False                # customer says they have paid
    verified: bool = False               # gateway confirmed success for the expected amount
    mismatch: str | None = None          # e.g. "gateway amount 500000 != expected 800000"
    has_reference: bool = False
    screenshot_only: bool = False        # an image attachment but no reference
    failed_attempts: int = 0


@dataclass(frozen=True)
class FraudContext:
    signals: frozenset[str]
    injection_flags: tuple[str, ...] = ()
    payment: PaymentFacts = field(default_factory=PaymentFacts)
    delivery_changes: int = 0            # times the delivery address/recipient changed
    third_party_pickup: bool = False
    new_customer: bool = True
    order_value_kobo: int = 0
    large_order_kobo: int = 100_000_000  # NGN 1,000,000
    messages_last_hour: int = 0
    prior_verified_purchases: int = 0


@dataclass(frozen=True)
class FraudAssessment:
    risk: Risk
    confidence: float                    # 0..1 confidence in the *band*, not a probability of fraud
    score: int
    families: tuple[str, ...]
    reasons: tuple[str, ...]
    recommended_action: str

    @property
    def requires_human(self) -> bool:
        return self.risk is Risk.HIGH


def assess(ctx: FraudContext) -> FraudAssessment:
    pts: dict[str, int] = {}
    why: list[str] = []

    def add(family: str, points: int, reason: str) -> None:
        pts[family] = min(pts.get(family, 0) + points, 60)
        why.append(reason)

    p, s = ctx.payment, ctx.signals
    if p.mismatch:
        add("payment", 70, f"Gateway-reported payment does not match the order ({p.mismatch})")
    if (p.claimed or "payment_claim" in s) and not p.verified:
        add("payment", 25, "Customer claims payment but the gateway has not confirmed it")
        if p.screenshot_only:
            add("payment", 15, "Evidence is a screenshot/alert only, with no payment reference")
        elif not p.has_reference:
            add("payment", 5, "No payment reference supplied")
    if p.failed_attempts >= 2:
        add("pattern", 20, f"{p.failed_attempts} failed payment attempts")
    if "pressure_tactic" in s:
        add("pressure", 25, "Pressure to release goods or bypass checks")
    if "urgency" in s and (p.claimed or "payment_claim" in s) and not p.verified:
        add("pressure", 10, "Urgency combined with an unverified payment claim")
    if ctx.delivery_changes >= 2:
        add("identity", 20, f"Delivery details changed {ctx.delivery_changes} times")
    elif ctx.delivery_changes == 1 and ctx.new_customer:
        add("identity", 5, "Delivery details changed once for a new customer")
    if ctx.third_party_pickup and ctx.new_customer:
        add("identity", 10, "Third-party pickup/delivery for a new customer")
    if ctx.injection_flags:
        add("system", 30, "Attempt to manipulate the agent's instructions: " + ", ".join(ctx.injection_flags))
    if ctx.messages_last_hour >= 20:
        add("pattern", 15, "Unusual message burst")
    if ctx.order_value_kobo >= ctx.large_order_kobo and ctx.new_customer:
        add("pattern", 10, "Large first order")

    # Established customers with verified history get benefit of the doubt on weak signals only.
    total = sum(pts.values())
    if ctx.prior_verified_purchases >= 2 and not p.mismatch:
        total = int(total * 0.6)
        if why:
            why.append("Reduced weight: customer has verified purchase history")

    families = tuple(sorted(f for f, v in pts.items() if v >= 15))
    decisive = bool(p.mismatch)
    if decisive or (total >= 60 and len(families) >= 2):
        risk, conf = Risk.HIGH, 0.9 if decisive else 0.75
    elif total >= 30 or len(families) >= 2:
        risk, conf = Risk.MEDIUM, 0.6
    else:
        risk, conf = Risk.LOW, 0.8 if total == 0 else 0.6

    if risk is Risk.HIGH:
        action = ("Do not fulfil. Require gateway-verified payment (or human review) before releasing goods; "
                  "keep replies neutral and polite, and escalate to the owner.")
    elif risk is Risk.MEDIUM:
        action = ("Proceed normally but require gateway payment verification before fulfilment; "
                  "do not rely on screenshots or alerts.")
    else:
        action = "No action needed."
    return FraudAssessment(risk, conf, total, families, tuple(why), action)
