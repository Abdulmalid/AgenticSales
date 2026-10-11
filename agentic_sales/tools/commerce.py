"""Payment tools. Registered only for tenants with a configured payment gateway."""
from __future__ import annotations

from .registry import Status, ToolContext, ToolRegistry, ToolResult, ToolSpec


def _create_link(ctx: ToolContext, a: dict) -> ToolResult:
    if ctx.turn.restricted:
        return ToolResult(Status.DENIED, message="held for human review; do not offer to complete the order")
    r = ctx.payments.create_order_link(ctx.customer_key, a["sku"], a.get("quantity", 1), a["email"], trace=ctx.trace)
    if r.ok:
        ctx.turn.verified_amounts.add(r.amount_kobo)
        return ToolResult(Status.OK, {"payment_url": r.url, "reference": r.reference, "amount_kobo": r.amount_kobo,
                                      "note": "send this exact link; the customer pays on the gateway page"})
    if r.verdict == "require_approval":
        return ToolResult(Status.NEEDS_APPROVAL, {"approval_id": r.approval_id, "reasons": r.message},
                          "order needs human approval")
    if r.verdict == "deny":
        return ToolResult(Status.DENIED, {"reasons": r.message}, r.message)
    return ToolResult(Status.ERROR, message=r.message)


def _verify(ctx: ToolContext, a: dict) -> ToolResult:
    r = ctx.payments.confirm(a["reference"], trace=ctx.trace, requesting_customer=ctx.customer_key)
    data = {"status": r.status, "detail": r.detail}
    if r.status == "verified":
        ctx.turn.payment_verified = True
        if r.amount_kobo:
            data["amount_kobo"] = r.amount_kobo
    elif r.status == "mismatch":
        ctx.turn.payment_mismatch = r.detail
        ctx.memory.request_approval(ctx.trace, ctx.customer_key, "payment_mismatch", data, (r.detail,))
    elif r.status in ("pending", "failed", "unknown"):
        ctx.turn.payment_claimed_unverified = True
    if r.status == "error":
        return ToolResult(Status.ERROR, message=r.detail)
    return ToolResult(Status.OK, data)


def register_commerce_tools(registry: ToolRegistry) -> None:
    if registry.has("create_payment_link"):
        return
    registry.register(ToolSpec(
        "create_payment_link",
        "Create a secure payment link for a product. The server sets the amount; you cannot. Needs the customer's email.",
        {"sku": str, "quantity": int, "email": str}, ("sku", "email"), _create_link, side_effect="external"))
    registry.register(ToolSpec(
        "verify_payment",
        "Check a payment reference with the payment gateway. Only a result of status 'verified' means money was received.",
        {"reference": str}, ("reference",), _verify, side_effect="read"))
