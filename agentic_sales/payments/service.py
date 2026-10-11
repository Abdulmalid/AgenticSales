"""Order + payment lifecycle on top of a PaymentGateway.

Invariants (each has a test):
  * Only references WE issued count as payments. A customer-supplied reference we never created is "unknown".
  * Amounts come from the business config / policy-approved price, never from the model or customer.
  * A payment is verified only if the gateway says success AND amount == expected AND currency == NGN.
  * Confirmation is idempotent (webhook + tool + retries cannot double-count a purchase).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config.business import BusinessConfig
from ..leads.engine import mark_converted
from ..leads.retention import schedule_after_purchase
from ..leads.store import LeadStore
from ..memory.store import TenantMemory
from ..policy.engine import PolicyEngine, Verdict
from .paystack import PaymentError, PaymentGateway

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders(
  reference TEXT PRIMARY KEY, customer_key TEXT NOT NULL, sku TEXT NOT NULL, qty INTEGER NOT NULL,
  amount_kobo INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_payment', created TEXT NOT NULL, paid_at TEXT);
"""


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    verdict: str                    # allow | require_approval | deny | error
    reference: str | None = None
    url: str | None = None
    amount_kobo: int | None = None
    message: str = ""
    approval_id: int | None = None


@dataclass(frozen=True)
class ConfirmResult:
    status: str                     # verified | pending | failed | mismatch | unknown | error
    reference: str
    detail: str = ""
    amount_kobo: int | None = None
    expected_kobo: int | None = None
    customer_key: str | None = None
    already_recorded: bool = False


class PaymentService:
    def __init__(self, memory: TenantMemory, leads: LeadStore, cfg: BusinessConfig, policy: PolicyEngine,
                 gateway: PaymentGateway | None):
        self.memory, self.leads, self.cfg, self.policy, self.gateway = memory, leads, cfg, policy, gateway
        memory.con.executescript(_SCHEMA)

    # ---- order + link ------------------------------------------------------------------------
    def create_order_link(self, customer_key: str, sku: str, qty: int, email: str, *, trace: str | None = None
                          ) -> OrderResult:
        if self.gateway is None:
            return OrderResult(False, "error", message="payments are not configured for this business")
        product = self.cfg.product(sku)
        if product is None or not product.in_stock:
            return OrderResult(False, "error", message="product unavailable")
        if not (1 <= qty <= 1000):
            return OrderResult(False, "error", message="invalid quantity")
        if "@" not in email or len(email) > 120 or " " in email:
            return OrderResult(False, "error", message="a valid email is required")
        agreed = self.memory.facts(customer_key).get(f"agreed_price:{sku}")
        unit = int(agreed) if agreed and agreed.isdigit() else product.price_kobo
        d = self.policy.check_discount(product, unit, qty)
        if d.verdict is Verdict.DENY:
            return OrderResult(False, "deny", message="; ".join(d.reasons))
        approved_qty = self.memory.facts(customer_key).get(f"approved_order:{sku}")
        if d.verdict is Verdict.REQUIRE_APPROVAL and approved_qty and approved_qty.isdigit() and int(approved_qty) >= qty:
            self.memory.remember(customer_key, f"approved_order:{sku}", "0", "consumed")   # single use
            d = type(d)(Verdict.ALLOW, (*d.reasons, "owner approved"))
        if d.verdict is Verdict.REQUIRE_APPROVAL:
            aid = self.memory.request_approval(trace or "", customer_key, "order",
                                               {"sku": sku, "qty": qty, "unit_kobo": unit}, d.reasons)
            return OrderResult(False, "require_approval", message="; ".join(d.reasons), approval_id=aid)
        amount = unit * qty
        ref = "AS-" + secrets.token_hex(8)
        try:
            link = self.gateway.create_link(amount_kobo=amount, email=email, reference=ref,
                                            metadata={"customer_key": customer_key, "sku": sku, "qty": qty})
        except PaymentError as e:
            return OrderResult(False, "error", message=str(e))
        with self.memory.con:
            self.memory.con.execute("INSERT INTO orders(reference,customer_key,sku,qty,amount_kobo,created) VALUES(?,?,?,?,?,?)",
                                    (ref, customer_key, sku, qty, amount, datetime.now(timezone.utc).isoformat()))
        return OrderResult(True, "allow", ref, link.url, amount)

    def order(self, reference: str) -> dict | None:
        r = self.memory.con.execute("SELECT * FROM orders WHERE reference=?", (reference,)).fetchone()
        return dict(r) if r else None

    def failed_attempts(self, customer_key: str) -> int:
        return self.memory.con.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_key=? AND status IN ('failed','mismatch')", (customer_key,)
        ).fetchone()[0]

    # ---- verification ------------------------------------------------------------------------
    def confirm(self, reference: str, *, trace: str | None = None, now: datetime | None = None,
                requesting_customer: str | None = None) -> ConfirmResult:
        order = self.order(reference)
        if order is None:
            return ConfirmResult("unknown", reference, "no order was issued with this reference")
        if requesting_customer and order["customer_key"] != requesting_customer:
            # a customer cannot claim someone else's payment
            return ConfirmResult("unknown", reference, "reference does not belong to this customer")
        if order["status"] == "paid":
            return ConfirmResult("verified", reference, "already confirmed", order["amount_kobo"], order["amount_kobo"],
                                 order["customer_key"], already_recorded=True)
        if self.gateway is None:
            return ConfirmResult("error", reference, "payments are not configured")
        try:
            st = self.gateway.verify(reference)
        except PaymentError as e:
            return ConfirmResult("error", reference, str(e), customer_key=order["customer_key"])
        exp = order["amount_kobo"]
        if st.gateway_status in ("not_found", "pending", "ongoing", "abandoned", "queued"):
            return ConfirmResult("pending", reference, f"gateway status: {st.gateway_status}", st.amount_kobo, exp,
                                 order["customer_key"])
        if not st.paid:
            self._set_status(reference, "failed")
            return ConfirmResult("failed", reference, f"gateway status: {st.gateway_status}", st.amount_kobo, exp,
                                 order["customer_key"])
        if st.amount_kobo != exp or st.currency != "NGN":
            self._set_status(reference, "mismatch")
            return ConfirmResult("mismatch", reference, f"gateway amount {st.amount_kobo} {st.currency} != expected {exp} NGN",
                                 st.amount_kobo, exp, order["customer_key"])
        now = now or datetime.now(timezone.utc)
        with self.memory.con:
            self.memory.con.execute("UPDATE orders SET status='paid', paid_at=? WHERE reference=? AND status!='paid'",
                                    (now.isoformat(), reference))
        lead = self.leads.get_by_key(order["customer_key"])
        recorded = False
        if lead is not None:
            recorded = mark_converted(self.leads, lead, order["sku"], exp, reference, trace, now)
            if recorded:
                schedule_after_purchase(self.leads, lead, self.cfg, now)
        if recorded:
            self.memory.enqueue_message(order["customer_key"], f"Payment confirmed. Thank you for your order with "
                                        f"{self.cfg.business_name}! We'll update you on delivery.", "purchase_confirmation", trace)
        return ConfirmResult("verified", reference, "gateway confirmed amount and currency", st.amount_kobo, exp,
                             order["customer_key"], already_recorded=not recorded)

    def _set_status(self, reference: str, status: str) -> None:
        with self.memory.con:
            self.memory.con.execute("UPDATE orders SET status=? WHERE reference=?", (status, reference))
