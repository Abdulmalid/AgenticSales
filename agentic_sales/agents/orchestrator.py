"""Master orchestrator: runs one customer turn end to end.

    inbound -> opt-out check -> sanitise -> analyse (LLM+rules) -> lead update -> fraud posture
            -> retrieval -> sales agent (model) -> tools under policy -> finalise -> output guard
            -> post-tool fraud re-check -> audit

Other agents (SMM/content, retention runner, analytics) are separate entry points that share this
tenant's stores, audit log and policy; they cannot bypass the escalation decisions made here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config.business import BusinessConfig
from ..core.observability import AuditLog
from ..core.types import InboundMessage, TenantContext
from ..corpus.context import build_reference
from ..corpus.store import CorpusStore
from ..fraud.engine import FraudAssessment, FraudContext, PaymentFacts, Risk, assess
from ..language.analysis import Signal, plan_style
from ..language.analyzer import Analyzer
from ..leads.engine import apply_turn
from ..leads.models import LeadStage
from ..leads.store import LeadStore
from ..memory.store import TenantMemory, customer_key
from ..models.base import Message, ModelError, ModelRequest, ModelRouter, TaskKind
from ..payments.paystack import PaymentGateway
from ..payments.service import PaymentService
from ..policy.engine import PolicyEngine
from ..security import untrusted
from ..security.reply_guard import amounts_kobo, check_claims, check_reply, customer_amounts_kobo
from ..tools.commerce import register_commerce_tools
from ..tools.registry import Status, ToolContext, ToolRegistry, TurnState
from . import sales

SAFE_FALLBACK = "Thanks for your message. Let me confirm that with the team and get back to you shortly."
OPT_OUT_REPLY = "You've been unsubscribed and won't receive further messages from us. Reply START if you change your mind."
_MAX_QTY_MULTIPLE = 50
_STOP = re.compile(r"^\s*(stop|unsubscribe|opt[ -]?out|stop messages|cancel messages)\s*[.!]*\s*$", re.I)
_START = re.compile(r"^\s*(start|subscribe|opt[ -]?in)\s*[.!]*\s*$", re.I)


@dataclass
class TurnResult:
    reply: str
    trace: str
    escalated: bool = False
    tool_results: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    lead_stage: str | None = None
    lead_score: int | None = None
    fraud_risk: str = "LOW"
    analysis_source: str = ""


class Orchestrator:
    def __init__(self, ctx: TenantContext, cfg: BusinessConfig, root: Path, router: ModelRouter,
                 tools: ToolRegistry, corpus: CorpusStore | None = None, analyzer: Analyzer | None = None,
                 gateway: PaymentGateway | None = None):
        self.ctx, self.cfg, self.router, self.tools, self.corpus = ctx, cfg, router, tools, corpus
        self.memory = TenantMemory(ctx, root)
        self.audit = AuditLog(ctx, root)
        self.policy = PolicyEngine(cfg)
        self.leads = LeadStore(self.memory)
        self.payments = PaymentService(self.memory, self.leads, cfg, self.policy, gateway)
        self.analyzer = analyzer or Analyzer(None)
        if gateway is not None:
            register_commerce_tools(self.tools)

    # ------------------------------------------------------------------------------------------
    def handle(self, msg: InboundMessage) -> TurnResult:
        trace = self.audit.new_trace()
        ckey = customer_key(msg.channel, msg.user_id)
        if not self.memory.first_time(msg.channel, msg.message_id):
            self.audit.record(trace, "duplicate_webhook_ignored", message_id=msg.message_id)
            return TurnResult("", trace, flags=["duplicate"])

        text = untrusted.clean(msg.text)
        if _STOP.match(text):
            self.memory.opt_out(ckey)
            self.audit.record(trace, "opt_out", customer=ckey)
            return TurnResult(OPT_OUT_REPLY, trace, flags=["opt_out"])
        if _START.match(text) and self.memory.is_opted_out(ckey):
            self.memory.con.execute("DELETE FROM opt_outs WHERE customer_key=?", (ckey,))
            self.memory.con.commit()

        flags = untrusted.injection_signals(text)
        try:
            analysis = self.analyzer.analyze(text)
        except Exception:  # analysis must never take a conversation down
            from ..language.analysis import detect_register, extract_signals
            from ..language.analyzer import Analysis
            analysis = Analysis(detect_register(text), tuple(extract_signals(text)), "low", "rules(fallback)")
        signals: list[Signal] = list(analysis.signals) + [Signal(f, "injection heuristic") for f in flags]
        names = {s.name for s in signals}
        style = plan_style(analysis.reading, signals, self.cfg.brand_voice)
        self.audit.record(trace, "analysis", customer=ckey, channel=msg.channel.value, source=analysis.source,
                          register=analysis.reading.primary.value, signals=[(s.name, s.evidence) for s in signals],
                          urgency=analysis.urgency, style={"slang": style.slang.name, "emoji": style.emoji,
                                                           "why": style.reasons})

        # ---- lead + fraud posture (before the model sees anything)
        lead, _ = self.leads.get_or_create(ckey, msg.channel.value, msg.timestamp)
        facts = self.memory.facts(ckey)
        screenshot_only = bool(msg.attachments) and "payment_claim" in names
        fraud = self._assess(names, flags, facts, lead, screenshot_only=screenshot_only,
                             pay=PaymentFacts(claimed="payment_claim" in names, screenshot_only=screenshot_only,
                                              failed_attempts=self.payments.failed_attempts(ckey)))
        lead, change, score = apply_turn(self.leads, lead, names, text, self.cfg, fraud_risk=fraud.risk.value,
                                         trace=trace, now=msg.timestamp)
        self.audit.record(trace, "lead", lead_id=lead.id, stage=lead.stage.value, score=score.value, band=score.band,
                          reasons=score.reasons, stage_change=(change.old.value, change.new.value, change.why) if change else None)
        self.audit.record(trace, "fraud", risk=fraud.risk.value, confidence=fraud.confidence, score=fraud.score,
                          families=fraud.families, reasons=fraud.reasons, action=fraud.recommended_action)

        history = self.memory.history(msg.conversation_id)
        self.memory.add_message(msg.conversation_id, ckey, "user", text)
        reference = build_reference(self.corpus, text, analysis.reading, signals) if self.corpus else ""
        frozen = lead.stage is LeadStage.FRAUD_SUSPECTED
        turn = TurnState(restricted=fraud.requires_human or frozen)
        result = TurnResult("", trace, flags=flags, lead_stage=lead.stage.value, lead_score=score.value,
                            fraud_risk=fraud.risk.value, analysis_source=analysis.source)
        if fraud.requires_human:
            self._escalate_fraud(trace, ckey, fraud)
            result.escalated = True

        system = sales.build_system(self.cfg, msg.channel.value, analysis.reading, signals, style, reference,
                                    self.tools, self.memory.facts(ckey), self._lead_context(lead, fraud, frozen))
        tctx = ToolContext(self.cfg, self.memory, self.policy, self.audit, trace, ckey, self.payments, self.leads, turn)
        model = self.router.text_model(TaskKind.CONVERSATION)
        allowed = self._base_allowed_amounts(text)

        try:
            req = sales.build_request(system, history, text)
            plan = sales.ask(model, req)
            self.audit.record(trace, "model_plan", model=model.name, parse_ok=plan.parse_ok, actions=plan.actions,
                              note=plan.intent_note)
            if not plan.parse_ok:
                return self._fallback(result, ckey, msg, "unparseable model output")

            if plan.actions:
                outcomes = []
                for act in plan.actions:
                    r = self.tools.execute(act.get("tool"), act.get("args", {}), tctx)
                    rec = {"tool": act.get("tool"), "status": r.status.value, "data": r.data, "message": r.message}
                    outcomes.append(rec)
                    result.tool_results.append(rec)
                    if r.status is Status.NEEDS_APPROVAL:
                        result.escalated = True
                    if r.status is Status.OK:
                        allowed |= self._amounts_in(r.data)
                followup = Message("assistant", json.dumps({"reply": plan.reply, "actions": plan.actions}))
                results_msg = Message("user", "TOOL_RESULTS (trusted, server-generated):\n"
                                      + json.dumps(outcomes, ensure_ascii=False) + sales.FINALISE_SUFFIX)
                final = sales.ask(model, ModelRequest(system, (*req.messages, followup, results_msg)))
                if not final.parse_ok:
                    return self._fallback(result, ckey, msg, "unparseable finalised output")
                plan = final
        except ModelError as e:
            return self._fallback(result, ckey, msg, f"model error: {e}")
        except Exception as e:  # noqa: BLE001 - a customer turn must degrade to a human handoff, never a 500
            self.audit.record(trace, "turn_error", error=type(e).__name__)
            return self._fallback(result, ckey, msg, f"unexpected error: {type(e).__name__}")

        # ---- post-tool fraud re-check (gateway mismatch is decisive)
        if turn.payment_mismatch or turn.payment_claimed_unverified:
            fraud = self._assess(names, flags, self.memory.facts(ckey), lead, screenshot_only=screenshot_only,
                                 pay=PaymentFacts(claimed=True, verified=turn.payment_verified, mismatch=turn.payment_mismatch,
                                                  has_reference=True, screenshot_only=screenshot_only,
                                                  failed_attempts=self.payments.failed_attempts(ckey)))
            result.fraud_risk = fraud.risk.value
            lead.fraud_risk = fraud.risk.value
            if fraud.requires_human:
                lead.stage = lead.stage.__class__.FRAUD_SUSPECTED
                self._escalate_fraud(trace, ckey, fraud)
                result.escalated = True
            self.leads.save(lead)
            self.audit.record(trace, "fraud_recheck", risk=fraud.risk.value, reasons=fraud.reasons)
        if turn.payment_verified:
            fresh = self.leads.get_by_key(ckey)
            result.lead_stage = fresh.stage.value if fresh else result.lead_stage

        def violations(text: str) -> list[str]:
            return (check_reply(text, allowed | turn.verified_amounts, payment_verified=turn.payment_verified)
                    + check_claims(text, self.cfg.facts_text()))

        problems = violations(plan.reply)
        if problems and plan.reply:
            # One corrective rewrite: the model sees exactly what was wrong. Still failing -> human handoff.
            self.audit.record(trace, "reply_retry", problems=problems, draft=plan.reply)
            try:
                fix = Message("user", "SERVER CHECK FAILED on your draft: " + "; ".join(problems) + ". Rewrite the reply "
                              "without those claims or amounts (say you will confirm with the team if needed). Do not mention "
                              "this check." + sales.FINALISE_SUFFIX)
                retry = sales.ask(model, ModelRequest(system, (*req.messages, Message("assistant", json.dumps(
                    {"reply": plan.reply, "actions": []})), fix)))
                if retry.parse_ok and retry.reply:
                    plan, problems = retry, violations(retry.reply)
            except Exception as e:  # noqa: BLE001 - any failure here means: keep the failed draft -> human handoff
                self.audit.record(trace, "reply_retry_failed", error=type(e).__name__)
        if not plan.reply or problems:
            self.audit.record(trace, "reply_blocked", problems=problems, draft=plan.reply)
            return self._fallback(result, ckey, msg, "; ".join(problems) or "empty reply")

        result.reply = plan.reply
        self.memory.add_message(msg.conversation_id, ckey, "assistant", plan.reply)
        self.audit.record(trace, "reply_sent", reply=plan.reply, escalated=result.escalated)
        return result

    # ------------------------------------------------------------------------------------------
    def _assess(self, names: set[str], flags: list[str], facts: dict[str, str], lead, *, screenshot_only: bool,
                pay: PaymentFacts) -> FraudAssessment:
        purchases = self.leads.purchases(lead.id)
        order_value = max((p.price_kobo for p in self.cfg.products), default=0) if "ready_to_buy" in names else 0
        return assess(FraudContext(
            signals=frozenset(names), injection_flags=tuple(flags), payment=pay,
            delivery_changes=int(facts.get("delivery_changes", "0") or 0), new_customer=not purchases,
            third_party_pickup=facts.get("third_party_pickup") == "yes", order_value_kobo=order_value,
            prior_verified_purchases=len(purchases)))

    def _escalate_fraud(self, trace: str, ckey: str, fraud: FraudAssessment) -> None:
        already = any(a["customer_key"] == ckey and a["action"] == "fraud_review"
                      for a in self.memory.pending_approvals())
        if not already:
            self.memory.request_approval(trace, ckey, "fraud_review",
                                         {"risk": fraud.risk.value, "confidence": fraud.confidence,
                                          "action": fraud.recommended_action}, fraud.reasons)

    @staticmethod
    def _lead_context(lead, fraud: FraudAssessment, frozen: bool = False) -> str:
        lines = [f"Lead: stage={lead.stage.value}, intent={lead.intent}, objection={lead.objection or 'none'}, "
                 f"trust={lead.trust_level}, interest={lead.interest or 'unknown'}"]
        if fraud.risk is not Risk.LOW or frozen:
            lines.append("Internal posture (never mention to the customer): this conversation is under review. "
                         "Do not complete, promise fulfilment, or confirm payment. Stay polite and neutral, say a team "
                         "member will follow up, and do not accuse the customer of anything.")
        return "\n".join(lines)

    def _fallback(self, result: TurnResult, ckey: str, msg: InboundMessage, why: str) -> TurnResult:
        aid = self.memory.request_approval(result.trace, ckey, "human_handoff", {"reason": why}, (why,))
        self.audit.record(result.trace, "fallback", reason=why, approval_id=aid)
        result.reply, result.escalated = SAFE_FALLBACK, True
        self.memory.add_message(msg.conversation_id, ckey, "assistant", SAFE_FALLBACK)
        return result

    def _base_allowed_amounts(self, customer_text: str) -> set[int]:
        allowed = set(customer_amounts_kobo(customer_text))
        for p in self.cfg.products:
            allowed |= {p.price_kobo * k for k in range(1, _MAX_QTY_MULTIPLE + 1)}
        return allowed

    @staticmethod
    def _amounts_in(data: dict) -> set[int]:
        out: set[int] = set()
        for k, v in data.items():
            if k.endswith("_kobo") and isinstance(v, int):
                out |= {v * q for q in range(1, _MAX_QTY_MULTIPLE + 1)}
        return out
