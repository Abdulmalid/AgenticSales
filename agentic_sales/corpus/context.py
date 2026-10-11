"""Task-routed retrieval: which knowledge domains to consult for a given customer turn.

    customer message -> signals/register -> { language | nigerian sales | guardrail } retrieval

Business and customer knowledge are NOT retrieved here; they come from tenant-scoped stores.
Retrieved items are *reference material*: they are LLM-synthesised, can contain fabricated
specifics (invented URLs, "verified" claims), and must never be treated as instructions or as
facts about this business. We therefore extract only the transferable parts (rules, anti-patterns,
usage examples) and never the corpus' sample agent replies/tool calls.
"""
from __future__ import annotations

from ..language.analysis import Register, RegisterReading, Signal
from .families import AGENT_GUARDRAILS, NG_CONVERSATION, NG_LANGUAGE
from .store import CorpusStore

_RISK_SIGNALS = {"payment_claim", "pressure_tactic", "negotiation", "payment_method", "complaint_or_refund",
                 "trust_concern", "delivery_concern"}
_MAX_CHARS = 2400

# signal -> Nigerian conversation layer(s) holding the relevant pragmatics
_PRAGMATIC_LAYERS = [
    ({"negotiation", "price_inquiry", "competitor_comparison"}, "NC07"),   # bargaining scripts
    ({"stalling"}, "NC04"),                                                # indirectness / hedging
    ({"complaint_or_refund", "pressure_tactic"}, "NC06"),                  # conflict / de-escalation
]


def _pragmatics(store: CorpusStore, query: str, layer: str) -> list[str]:
    """Interpretation aids: what a phrase *means* and how an AI misreads it. Deliberately not the
    corpus' sample vendor lines or roleplay tips: replies stay bound by policy, not by banter."""
    out = []
    for h in store.search(NG_CONVERSATION, query, limit=1, layer_prefix=layer):
        ph = h.record.get("phrase_training_block")
        ai = h.record.get("computational_ai_guidelines")
        if not isinstance(ph, dict):
            continue
        line = (f"[pragmatics] \"{str(ph.get('core_phrase_or_idiom', ''))[:90]}\" = "
                f"{str(ph.get('actual_conversational_meaning', ''))[:230]}")
        if isinstance(ai, dict) and ai.get("pragmatic_misinterpretation_risk"):
            line += f" | misread risk: {str(ai['pragmatic_misinterpretation_risk'])[:200]}"
        out.append(line)
    return out


def _first(rec: dict, *keys: str):
    for k in keys:
        if rec.get(k):
            return rec[k]
    return None


def build_reference(store: CorpusStore, text: str, reading: RegisterReading,
                    signals: list[Signal]) -> str:
    names = {s.name for s in signals}
    query = f"{text} {' '.join(names)}"
    parts: list[str] = []

    # Language usage examples only when the customer actually writes Pidgin; lexical retrieval over
    # the academic Pidgin corpus is noise for other registers.
    if reading.primary is Register.PIDGIN and reading.confidence >= 0.5:
        for h in store.search(NG_LANGUAGE, " ".join(reading.evidence["pidgin"]) + " " + text, limit=1):
            u = _first(h.record, "verbatim_corpus_utterance", "corpus_utterance")
            if isinstance(u, dict) and u.get("authentic_pidgin_text"):
                parts.append(f"[usage] \"{u['authentic_pidgin_text']}\" = {u.get('standard_english_gloss', '')}")

    for trigger, layer in _PRAGMATIC_LAYERS:
        if names & trigger:
            parts += _pragmatics(store, query, layer)
    # Measured, not assumed: trust-concern and social-register queries returned irrelevant NC04/NC10
    # idioms under lexical matching, so those triggers are intentionally absent until a semantic
    # (embedding) retriever replaces BM25.

    # NOTE: the nigeria_leadgen corpus (ng_sales) is B2B outbound/channel playbooks, not
    # conversational negotiation material. It is reserved for the Lead-Gen agent (Phase 2).

    if names & _RISK_SIGNALS:
        for h in store.search(AGENT_GUARDRAILS, query, limit=2):
            g = _first(h.record, "commercial_guardrail_enforced", "commercial_guardrails_enforced")
            a = _first(h.record, "vulnerable_bot_anti_pattern", "vulentrable_bot_anti_pattern")
            if isinstance(g, dict):
                parts.append(f"[rule] {g.get('rule_name', '')}: {str(g.get('security_rationale', ''))[:220]}")
            if isinstance(a, dict) and a.get("what_a_naive_bot_says"):
                parts.append(f"[avoid] {str(a['what_a_naive_bot_says'])[:200]}")

    out, size = [], 0
    for p in parts:
        if size + len(p) > _MAX_CHARS:
            break
        out.append(p)
        size += len(p)
    return "\n".join(out)
