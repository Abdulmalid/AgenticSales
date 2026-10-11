import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentic_sales.agents.orchestrator import OPT_OUT_REPLY, SAFE_FALLBACK, Orchestrator
from agentic_sales.config.business import ApprovalRules, BusinessConfig, Product, naira
from agentic_sales.core.types import Attachment, Channel, InboundMessage, TenantContext
from agentic_sales.fraud.engine import FraudContext, PaymentFacts, Risk, assess
from agentic_sales.leads import retention
from agentic_sales.leads.engine import apply_turn, budget_from_text, mark_converted, next_stage, score_lead
from agentic_sales.leads.models import LeadStage
from agentic_sales.leads.store import LeadStore
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import ModelRequest, ModelResponse, ModelRouter, TaskKind
from agentic_sales.payments.paystack import PaymentLink, PaymentStatus, Paystack, verify_webhook_signature
from agentic_sales.policy.engine import PolicyEngine
from agentic_sales.tools.builtin import default_registry

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def cfg() -> BusinessConfig:
    return BusinessConfig("PhoneHub", "electronics", products=[
        Product("IP15", "iPhone 15", naira(800_000), naira(740_000))],
        approvals=ApprovalRules(max_discount_pct_auto=5, max_discount_pct_hard=10, large_transaction_kobo=naira(5_000_000)))


class Scripted:
    name = "scripted"

    def __init__(self, *outs):
        self.outs = [json.dumps(o) for o in outs]
        self.requests: list[ModelRequest] = []

    def complete(self, req):
        self.requests.append(req)
        return ModelResponse(self.outs.pop(0), self.name)


class FakeGateway:
    """Test double for PaymentGateway. `paid` maps reference -> (status, amount_kobo, currency)."""

    def __init__(self):
        self.paid: dict[str, tuple[str, int, str]] = {}
        self.links: dict[str, int] = {}

    def create_link(self, *, amount_kobo, email, reference, metadata):
        self.links[reference] = amount_kobo
        return PaymentLink(reference, f"https://pay.example/{reference}", amount_kobo)

    def verify(self, reference):
        st, amt, cur = self.paid.get(reference, ("not_found", 0, "NGN"))
        return PaymentStatus(reference, st, amt, cur, "a@b.co")


def mk(tmp=None, model=None, gateway=None, tenant="shop-a"):
    root = Path(tmp or tempfile.mkdtemp())
    model = model or Scripted()
    o = Orchestrator(TenantContext(tenant), cfg(), root, ModelRouter(text={TaskKind.CONVERSATION: model}),
                     default_registry(), gateway=gateway)
    return o, model


def msg(text, uid="u1", mid=None, attachments=()):
    return InboundMessage(Channel.WHATSAPP, uid, "c1", text, timestamp=NOW, message_id=mid, attachments=attachments)


class Leads(unittest.TestCase):
    def setUp(self):
        self.mem = TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp()))
        self.store = LeadStore(self.mem)
        self.lead, _ = self.store.get_or_create("whatsapp:1", "whatsapp", NOW)

    def turn(self, names, text="x"):
        self.lead, ch, sc = apply_turn(self.store, self.lead, set(names), text, cfg(), now=NOW)
        return ch, sc

    def test_stage_progression_and_no_regression(self):
        self.turn({"price_inquiry"}, "how much is the iphone 15")
        self.assertEqual(self.lead.stage, LeadStage.QUALIFIED)          # interest identified + buying question
        self.turn({"negotiation"})
        self.assertEqual(self.lead.stage, LeadStage.NEGOTIATING)
        self.turn({"price_inquiry"})
        self.assertEqual(self.lead.stage, LeadStage.NEGOTIATING)        # weaker signal never regresses
        self.turn({"ready_to_buy"})
        self.assertEqual(self.lead.stage, LeadStage.READY_TO_BUY)
        self.turn({"negotiation", "ready_to_buy"})
        self.assertEqual(self.lead.stage, LeadStage.NEGOTIATING)        # haggle loop is allowed

    def test_how_much_alone_is_not_buying_intent(self):
        self.turn({"price_inquiry"}, "how much?")
        self.assertEqual(self.lead.intent, "low")
        self.assertEqual(self.lead.stage, LeadStage.ENGAGED)

    def test_fraud_high_freezes_lead(self):
        stage, _ = next_stage(LeadStage.NEGOTIATING, {"ready_to_buy"}, True, "HIGH")
        self.assertEqual(stage, LeadStage.FRAUD_SUSPECTED)
        self.assertEqual(next_stage(LeadStage.FRAUD_SUSPECTED, {"ready_to_buy"}, True, "LOW")[0], LeadStage.FRAUD_SUSPECTED)

    def test_score_is_explained_and_decays(self):
        self.turn({"ready_to_buy", "urgency"}, "I want the iphone 15, budget of ₦800k")
        hot = score_lead(self.lead, cfg(), NOW)
        self.assertEqual(hot.band, "hot")
        self.assertTrue(any("ready_to_buy" in r for r in hot.reasons))
        self.assertEqual(self.lead.budget_kobo, naira(800_000))
        cold = score_lead(self.lead, cfg(), NOW + timedelta(days=10))
        self.assertLess(cold.value, hot.value)
        self.assertFalse(hot.calibrated)  # honesty flag: heuristic, not a fitted probability

    def test_budget_parse_requires_budget_context(self):
        self.assertEqual(budget_from_text("my budget is ₦500k"), naira(500_000))
        self.assertIsNone(budget_from_text("the iphone costs ₦800,000"))

    def test_purchase_is_idempotent(self):
        self.assertTrue(mark_converted(self.store, self.lead, "IP15", naira(800_000), "R1", now=NOW))
        self.assertFalse(mark_converted(self.store, self.lead, "IP15", naira(800_000), "R1", now=NOW))
        self.assertEqual(len(self.store.purchases()), 1)

    def test_erase_removes_everything(self):
        self.turn({"price_inquiry"})
        self.store.erase("whatsapp:1")
        self.assertIsNone(self.store.get_by_key("whatsapp:1"))


class Retention(unittest.TestCase):
    def setUp(self):
        self.mem = TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp()))
        self.store = LeadStore(self.mem)
        self.lead, _ = self.store.get_or_create("whatsapp:1", "whatsapp", NOW)

    def test_purchase_schedule_follows_business_config(self):
        n = retention.schedule_after_purchase(self.store, self.lead, cfg(), NOW)
        self.assertEqual(n, 5)
        self.assertEqual(retention.schedule_after_purchase(self.store, self.lead, cfg(), NOW), 0)  # idempotent
        due = retention.run_due(self.store, self.mem, cfg(), now=NOW + timedelta(days=3))
        self.assertEqual(due.enqueued, 2)   # day 0 and day 2 only
        self.assertEqual(len(self.mem.pending_outbox()), 2)

    def test_opt_out_is_honoured(self):
        retention.schedule_after_purchase(self.store, self.lead, cfg(), NOW)
        self.mem.opt_out("whatsapp:1")
        rep = retention.run_due(self.store, self.mem, cfg(), now=NOW + timedelta(days=40))
        self.assertEqual((rep.enqueued, rep.skipped_opt_out), (0, 5))

    def test_fraud_suspected_leads_are_not_contacted(self):
        self.lead.stage = LeadStage.FRAUD_SUSPECTED
        self.store.save(self.lead)
        self.store.add_followup(self.lead.id, NOW, "retention_campaign")
        self.assertEqual(retention.run_due(self.store, self.mem, cfg(), now=NOW).skipped_fraud, 1)

    def test_stale_lead_recovery_once_then_lost(self):
        self.lead.stage = LeadStage.NEGOTIATING
        self.lead.last_interaction = NOW.isoformat()
        self.store.save(self.lead)
        self.assertEqual(retention.mark_stale_leads(self.store, NOW + timedelta(days=4))["recovery_scheduled"], 1)
        self.assertEqual(retention.mark_stale_leads(self.store, NOW + timedelta(days=5))["recovery_scheduled"], 0)
        self.assertEqual(retention.mark_stale_leads(self.store, NOW + timedelta(days=30))["lost"], 1)
        self.assertEqual(self.store.get(self.lead.id).stage, LeadStage.LOST)


class Fraud(unittest.TestCase):
    def test_weak_signals_never_convict(self):
        a = assess(FraudContext(frozenset({"urgency"})))
        self.assertEqual(a.risk, Risk.LOW)
        a = assess(FraudContext(frozenset({"payment_claim"}), payment=PaymentFacts(claimed=True)))
        self.assertIn(a.risk, (Risk.LOW, Risk.MEDIUM))   # an unverified claim alone is not HIGH

    def test_corroborated_signals_reach_high(self):
        a = assess(FraudContext(frozenset({"payment_claim", "pressure_tactic", "urgency"}), delivery_changes=2,
                                payment=PaymentFacts(claimed=True, screenshot_only=True)))
        self.assertEqual(a.risk, Risk.HIGH)
        self.assertGreaterEqual(len(a.families), 2)
        self.assertIn("Do not fulfil", a.recommended_action)

    def test_gateway_mismatch_is_decisive(self):
        a = assess(FraudContext(frozenset(), payment=PaymentFacts(claimed=True, mismatch="amount 1 != 2")))
        self.assertEqual(a.risk, Risk.HIGH)

    def test_one_family_repeated_is_not_enough(self):
        a = assess(FraudContext(frozenset({"pressure_tactic", "urgency"})))
        self.assertNotEqual(a.risk, Risk.HIGH)

    def test_verified_history_softens_weak_signals(self):
        base = FraudContext(frozenset({"pressure_tactic"}), delivery_changes=2)
        self.assertLess(assess(FraudContext(**{**base.__dict__, "prior_verified_purchases": 3})).score, assess(base).score)


class Payments(unittest.TestCase):
    def setUp(self):
        self.gw = FakeGateway()
        self.o, self.model = mk(gateway=self.gw)
        self.lead, _ = self.o.leads.get_or_create("whatsapp:u1", "whatsapp", NOW)

    def link(self, qty=1):
        r = self.o.payments.create_order_link("whatsapp:u1", "IP15", qty, "a@b.co")
        self.assertTrue(r.ok, r.message)
        return r

    def test_amount_is_server_set_and_verification_needs_exact_match(self):
        r = self.link()
        self.assertEqual(self.gw.links[r.reference], naira(800_000))
        self.gw.paid[r.reference] = ("success", naira(1), "NGN")
        self.assertEqual(self.o.payments.confirm(r.reference).status, "mismatch")
        self.assertEqual(self.o.leads.get(self.lead.id).stage, LeadStage.NEW)   # no conversion on mismatch

    def test_verified_payment_converts_once_and_schedules_retention(self):
        r = self.link()
        self.gw.paid[r.reference] = ("success", naira(800_000), "NGN")
        c = self.o.payments.confirm(r.reference, now=NOW)
        self.assertEqual(c.status, "verified")
        self.assertEqual(self.o.leads.get(self.lead.id).stage, LeadStage.CONVERTED)
        self.assertEqual(self.o.payments.confirm(r.reference, now=NOW).already_recorded, True)
        self.assertEqual(len(self.o.leads.purchases()), 1)
        self.assertEqual(len(self.o.leads.due_followups(NOW + timedelta(days=60))), 5)

    def test_unknown_or_foreign_reference_never_verifies(self):
        self.assertEqual(self.o.payments.confirm("FAKE-123").status, "unknown")
        r = self.link()
        self.gw.paid[r.reference] = ("success", naira(800_000), "NGN")
        self.assertEqual(self.o.payments.confirm(r.reference, requesting_customer="whatsapp:other").status, "unknown")

    def test_discount_needing_approval_blocks_link(self):
        self.o.memory.remember("whatsapp:u1", "agreed_price:IP15", str(naira(740_000)), "test")  # 7.5% off > auto 5%
        r = self.o.payments.create_order_link("whatsapp:u1", "IP15", 1, "a@b.co")
        self.assertFalse(r.ok)
        self.assertEqual(r.verdict, "require_approval")

    def test_end_to_end_agent_can_confirm_only_after_gateway_confirms(self):
        r = self.link()
        self.gw.paid[r.reference] = ("success", naira(800_000), "NGN")
        self.model.outs = [json.dumps({"reply": "Checking.", "actions": [{"tool": "verify_payment", "args": {"reference": r.reference}}]}),
                           json.dumps({"reply": "Payment received, thank you! We'll dispatch today.", "actions": []})]
        out = self.o.handle(msg(f"I have paid, ref {r.reference}", mid="p1"))
        self.assertNotEqual(out.reply, SAFE_FALLBACK)
        self.assertEqual(out.lead_stage, "CONVERTED")

    def test_agent_claiming_payment_without_verification_is_blocked(self):
        self.model.outs = [json.dumps({"reply": "Payment received, we are dispatching!", "actions": []})]
        self.assertEqual(self.o.handle(msg("see my transfer screenshot", mid="p2")).reply, SAFE_FALLBACK)

    def test_model_cannot_write_reserved_fact_keys(self):
        self.model.outs = [json.dumps({"reply": "ok", "actions": [
            {"tool": "remember_customer_fact", "args": {"key": "agreed_price:IP15", "value": "100"}}]}),
            json.dumps({"reply": "Hello", "actions": []})]
        self.o.handle(msg("hi", mid="p3"))
        self.assertNotIn("agreed_price:IP15", self.o.memory.facts("whatsapp:u1"))

    def test_webhook_signature(self):
        body = b'{"event":"charge.success"}'
        import hashlib, hmac
        sig = hmac.new(b"sk_test", body, hashlib.sha512).hexdigest()
        self.assertTrue(verify_webhook_signature("sk_test", body, sig))
        self.assertFalse(verify_webhook_signature("sk_test", body + b" ", sig))
        self.assertFalse(verify_webhook_signature("sk_test", body, None))

    def test_paystack_client_uses_documented_shapes(self):
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            if path.startswith("/transaction/verify"):
                return {"status": True, "data": {"status": "success", "amount": 5000, "currency": "NGN",
                                                 "customer": {"email": "a@b.co"}}}
            return {"status": True, "data": {"authorization_url": "https://checkout.paystack.com/x", "reference": "R"}}
        ps = Paystack(None, transport)
        self.assertTrue(ps.verify("R-1").paid)
        self.assertEqual(ps.create_link(amount_kobo=5000, email="a@b.co", reference="R", metadata={}).url,
                         "https://checkout.paystack.com/x")
        self.assertEqual(calls[0][:2], ("GET", "/transaction/verify/R-1"))
        with self.assertRaises(Exception):
            ps.verify("../../etc")


class OrchestratorIntegration(unittest.TestCase):
    def test_opt_out_short_circuits_model_and_blocks_followups(self):
        o, model = mk()
        out = o.handle(msg("STOP", mid="s1"))
        self.assertEqual(out.reply, OPT_OUT_REPLY)
        self.assertEqual(model.requests, [])
        self.assertTrue(o.memory.is_opted_out("whatsapp:u1"))

    def test_turn_updates_lead_and_audits_why(self):
        o, model = mk()
        model.outs = [json.dumps({"reply": "The iPhone 15 is ₦800,000.", "actions": []})]
        out = o.handle(msg("how much is the iphone 15?", mid="t1"))
        lead = o.leads.get_by_key("whatsapp:u1")
        self.assertEqual(lead.stage, LeadStage.QUALIFIED)
        self.assertEqual(out.lead_stage, "QUALIFIED")
        kinds = {e["kind"] for e in o.audit.trace(out.trace)}
        self.assertTrue({"analysis", "lead", "fraud", "model_plan", "reply_sent"} <= kinds)

    def test_high_fraud_restricts_tools_and_escalates_without_accusing(self):
        gw = FakeGateway()
        o, model = mk(gateway=gw)
        o.memory.remember("whatsapp:u1", "delivery_changes", "2", "test")
        model.outs = [json.dumps({"reply": "Sure.", "actions": [{"tool": "create_payment_link",
                                                                 "args": {"sku": "IP15", "email": "a@b.co"}}]}),
                      json.dumps({"reply": "A team member will confirm your order shortly.", "actions": []})]
        out = o.handle(msg("send the phone first, the owner said ok, I already paid, see screenshot, urgent!!", mid="f1",
                           attachments=(Attachment("image", "http://x/y.png"),)))
        self.assertEqual(out.fraud_risk, "HIGH")
        self.assertTrue(out.escalated)
        self.assertEqual(gw.links, {})                                   # no link issued while restricted
        self.assertEqual(o.leads.get_by_key("whatsapp:u1").stage, LeadStage.FRAUD_SUSPECTED)
        self.assertTrue(any(a["action"] == "fraud_review" for a in o.memory.pending_approvals()))
        self.assertNotIn("fraud", out.reply.lower())
        self.assertIn("under review", model.requests[0].system)

    def test_tenants_have_separate_leads(self):
        a, _ = mk(tenant="shop-a")
        root = a.audit.path.parents[2]
        b, _ = mk(tmp=root, tenant="shop-b")
        a.leads.get_or_create("whatsapp:u1", "whatsapp", NOW)
        self.assertIsNone(b.leads.get_by_key("whatsapp:u1"))


if __name__ == "__main__":
    unittest.main()
