import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentic_sales.agents.orchestrator import SAFE_FALLBACK, Orchestrator
from agentic_sales.config.business import ApprovalRules, BusinessConfig, Product, naira
from agentic_sales.core.observability import AuditLog
from agentic_sales.core.types import Channel, InboundMessage, TenantContext
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind
from agentic_sales.policy.engine import PolicyEngine
from agentic_sales.security.reply_guard import check_claims
from agentic_sales.tools.builtin import default_registry
from agentic_sales.tools.registry import ToolContext

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def cfg(**kw) -> BusinessConfig:
    return BusinessConfig("PhoneHub", "electronics", products=[
        Product("IP15", "iPhone 15", naira(800_000), naira(740_000), "Brand new, sealed, 1-year warranty")],
        approvals=ApprovalRules(max_discount_pct_auto=5, max_discount_pct_hard=10), **kw)


class Scripted:
    name = "scripted"

    def __init__(self, *outs):
        self.outs = [json.dumps(o) for o in outs]
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


class Ladder(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.ctx_t = TenantContext("shop-a")
        self.mem = TenantMemory(self.ctx_t, root)
        self.c = cfg()
        self.tools = default_registry()
        self.tc = ToolContext(self.c, self.mem, PolicyEngine(self.c), AuditLog(self.ctx_t, root), "t" * 16, "whatsapp:1")

    def propose(self, kobo):
        return self.tools.execute("propose_price", {"sku": "IP15", "offered_price_kobo": kobo}, self.tc)

    def test_concessions_come_in_steps_never_straight_to_the_limit(self):
        want = [naira(784_000), naira(772_000)]               # 2.0% then 3.5% off an 800k list (auto limit 5%)
        for w in want:
            r = self.propose(naira(770_000))                  # agent tries to give 3.75% off immediately
            self.assertEqual(r.data["accepted"], False)
            self.assertEqual(r.data["counter_offer_kobo"], w)
        r = self.propose(naira(770_000))                      # third rung is 5.0% (760k): 770k is now acceptable
        self.assertEqual(r.data["accepted"], True)
        self.assertEqual(self.mem.facts("whatsapp:1")["agreed_price:IP15"], str(naira(770_000)))

    def test_accepting_the_counter_closes_at_the_counter(self):
        r = self.propose(naira(770_000))
        r2 = self.propose(r.data["counter_offer_kobo"])
        self.assertTrue(r2.data["accepted"])
        self.assertEqual(self.mem.facts("whatsapp:1")["agreed_price:IP15"], str(naira(784_000)))

    def test_beyond_authority_still_needs_approval_or_is_denied(self):
        self.assertEqual(self.propose(naira(740_000)).status.value, "needs_approval")   # 7.5% > auto 5%
        self.assertEqual(self.propose(naira(700_000)).status.value, "denied")           # 12.5% > hard 10%

    def test_model_cannot_reset_the_ladder(self):
        self.propose(naira(770_000))
        r = self.tools.execute("remember_customer_fact", {"key": "neg_round:IP15", "value": "0"}, self.tc)
        self.assertEqual(r.status.value, "denied")

    def test_prompt_never_discloses_authority_limit(self):
        orch = Orchestrator(self.ctx_t, self.c, Path(tempfile.mkdtemp()),
                            ModelRouter(text={TaskKind.CONVERSATION: Scripted({"reply": "Hi", "actions": []})}), default_registry())
        orch.handle(InboundMessage(Channel.WEB, "u", "c", "last price?", timestamp=NOW))
        system = orch.router.text_model(TaskKind.CONVERSATION).requests[0].system
        for leak in ("760,000", "784,000", "772,000", "740,000", "authority"):
            self.assertNotIn(leak, system)


class Claims(unittest.TestCase):
    FACTS = cfg().facts_text()

    def test_invented_trust_claims_are_flagged(self):
        r = ("We are a registered business in Lagos and your funds are 100% protected. "
             "You can pay on delivery, delivery is within 24 hours.")
        problems = check_claims(r, self.FACTS)
        joined = " ".join(problems).lower()
        for needle in ("registered business", "100% protected", "pay-on-delivery", "within 24 hours"):
            self.assertIn(needle, joined)

    def test_configured_facts_may_be_stated(self):
        c = cfg(business_facts=["CAC registered business, RC 1234567", "Delivery within 24 hours in Lagos"])
        r = "We are a CAC registered business, and delivery within 24 hours in Lagos. The phone has a 1-year warranty."
        self.assertEqual(check_claims(r, c.facts_text()), [])

    def test_plain_sales_talk_is_not_flagged(self):
        self.assertEqual(check_claims("Good afternoon! The iPhone 15 is in stock. Shall I send the payment link?", self.FACTS), [])

    def test_business_facts_are_validated(self):
        with self.assertRaises(ValueError):
            BusinessConfig.from_dict({"business_name": "x", "industry": "y", "business_facts": ["z" * 400]})


class RewriteOnce(unittest.TestCase):
    def mk(self, *outs):
        root = Path(tempfile.mkdtemp())
        m = Scripted(*outs)
        return Orchestrator(TenantContext("shop-a"), cfg(), root, ModelRouter(text={TaskKind.CONVERSATION: m}),
                            default_registry()), m

    def say(self, o, text="is this legit?", mid="1"):
        return o.handle(InboundMessage(Channel.WEB, "u", "c", text, timestamp=NOW, message_id=mid))

    def test_bad_draft_is_rewritten_once_and_the_fix_is_sent(self):
        o, m = self.mk({"reply": "We are a registered business, funds are 100% protected!", "actions": []},
                       {"reply": "Fair question. I'll confirm our registration details with the team and send them to you.", "actions": []})
        out = self.say(o)
        self.assertIn("confirm", out.reply)
        self.assertFalse(out.escalated)
        self.assertIn("SERVER CHECK FAILED", m.requests[1].messages[-1].content)
        self.assertIn("reply_retry", {e["kind"] for e in o.audit.trace(out.trace)})

    def test_still_bad_after_rewrite_goes_to_a_human(self):
        o, _ = self.mk({"reply": "We are a registered business!", "actions": []},
                       {"reply": "Yes, we are a licensed company.", "actions": []})
        out = self.say(o)
        self.assertEqual(out.reply, SAFE_FALLBACK)
        self.assertTrue(out.escalated)

    def test_rewrite_failure_does_not_crash_the_turn(self):
        o, _ = self.mk({"reply": "We are a registered business!", "actions": []})   # no second output -> model raises
        self.assertEqual(self.say(o).reply, SAFE_FALLBACK)


if __name__ == "__main__":
    unittest.main()
