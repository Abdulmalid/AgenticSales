"""Phase-1 built-in tools. External-effect tools (payments, posting, messaging) are Phase 3+."""
from __future__ import annotations

from ..policy.engine import Verdict
from .registry import Status, ToolContext, ToolRegistry, ToolResult, ToolSpec


def _lookup_product(ctx: ToolContext, a: dict) -> ToolResult:
    p = ctx.cfg.product(a["sku"])
    if p is None:
        return ToolResult(Status.ERROR, message="no such product")
    return ToolResult(Status.OK, {"sku": p.sku, "name": p.name, "price_kobo": p.price_kobo,
                                  "in_stock": p.in_stock, "description": p.description})


def _propose_price(ctx: ToolContext, a: dict) -> ToolResult:
    """Customer asks for a lower price. Policy decides; the model only relays the outcome."""
    p = ctx.cfg.product(a["sku"])
    if p is None:
        return ToolResult(Status.ERROR, message="no such product")
    qty = a.get("quantity", 1)
    d = ctx.policy.check_discount(p, a["offered_price_kobo"], qty)
    data = {"sku": p.sku, "offered_price_kobo": a["offered_price_kobo"], "reasons": list(d.reasons)}
    if d.verdict is Verdict.ALLOW:
        facts = ctx.memory.facts(ctx.customer_key)
        rnd = int(facts.get(f"neg_round:{p.sku}", "0") or 0)
        rung = ctx.policy.ladder_price(p, rnd)
        offered = a["offered_price_kobo"]
        if offered < rung and offered < p.price_kobo:
            # Within authority but deeper than the current rung: counter at the rung and advance the ladder.
            ctx.memory.remember(ctx.customer_key, f"neg_round:{p.sku}", str(rnd + 1), f"policy:{ctx.trace}")
            return ToolResult(Status.OK, {"sku": p.sku, "accepted": False, "counter_offer_kobo": rung,
                                          "instruction": "offer exactly the counter price; do not go lower"},
                              "counter-offer")
        ctx.memory.remember(ctx.customer_key, f"agreed_price:{p.sku}", str(offered), f"policy:{ctx.trace}")
        data["accepted"] = True
        return ToolResult(Status.OK, data, "price within agent authority")
    if d.verdict is Verdict.REQUIRE_APPROVAL:
        aid = ctx.memory.request_approval(ctx.trace, ctx.customer_key, "discount", data, d.reasons)
        return ToolResult(Status.NEEDS_APPROVAL, {**data, "approval_id": aid},
                          "queued for human approval")
    return ToolResult(Status.DENIED, data, "; ".join(d.reasons))


def _remember_fact(ctx: ToolContext, a: dict) -> ToolResult:
    key = a["key"]
    if key.startswith(("agreed_price:", "order:", "payment_", "approved_", "fraud_", "neg_round:")):
        # reserved namespaces are written only by trusted code paths (policy/payments), never by the model
        return ToolResult(Status.DENIED, message="reserved key")
    if key == "delivery_address":
        facts = ctx.memory.facts(ctx.customer_key)
        old = facts.get("delivery_address")
        if old and old.strip().lower() != a["value"].strip().lower():
            n = int(facts.get("delivery_changes", "0") or 0) + 1
            ctx.memory.remember(ctx.customer_key, "delivery_changes", str(n), f"system:{ctx.trace}")
    ctx.memory.remember(ctx.customer_key, key, a["value"], f"agent:{ctx.trace}")
    return ToolResult(Status.OK)


def _escalate(ctx: ToolContext, a: dict) -> ToolResult:
    aid = ctx.memory.request_approval(ctx.trace, ctx.customer_key, "human_handoff",
                                      {"reason": a["reason"]}, (a["reason"],))
    return ToolResult(Status.NEEDS_APPROVAL, {"approval_id": aid}, "handed to a human")


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolSpec("lookup_product", "Get authoritative price/stock for a product SKU.",
                        {"sku": str}, ("sku",), _lookup_product))
    r.register(ToolSpec("propose_price",
                        "Offer a lower price for a product. Policy decides; reply only with the outcome.",
                        {"sku": str, "offered_price_kobo": int, "quantity": int},
                        ("sku", "offered_price_kobo"), _propose_price, side_effect="write"))
    r.register(ToolSpec("remember_customer_fact",
                        "Store a durable fact about this customer (preference, objection, budget).",
                        {"key": str, "value": str}, ("key", "value"), _remember_fact, side_effect="write"))
    r.register(ToolSpec("escalate_to_human", "Hand the conversation to a human with a reason.",
                        {"reason": str}, ("reason",), _escalate, side_effect="write"))
    return r
