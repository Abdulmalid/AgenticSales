"""Single entry point for understanding a customer message.

Production mode = "union": the LLM extraction (best recall on unseen Nigerian messages, see
docs/ARCHITECTURE.md section 7) plus any rule-detected signals the LLM missed. If the LLM is
unavailable or returns garbage, the rules alone answer, so a model outage never blocks a reply.
"""
from __future__ import annotations

from dataclasses import dataclass

from .analysis import Register, RegisterReading, Signal, detect_register, extract_signals
from .llm_signals import SignalExtractor

_INFORMAL = {Register.FORMAL: 0.1, Register.CASUAL: 0.75, Register.PIDGIN: 0.9, Register.SOCIAL: 0.8}


@dataclass(frozen=True)
class Analysis:
    reading: RegisterReading
    signals: tuple[Signal, ...]
    urgency: str
    source: str   # "llm+rules" | "rules" | "rules(fallback)"

    @property
    def names(self) -> set[str]:
        return {s.name for s in self.signals}


class Analyzer:
    def __init__(self, extractor: SignalExtractor | None = None):
        self.extractor = extractor

    def analyze(self, text: str) -> Analysis:
        rules_sigs = extract_signals(text)
        rules_reading = detect_register(text)
        if self.extractor is None or self.extractor.model is None:
            return Analysis(rules_reading, tuple(rules_sigs), "low", "rules")
        ex = self.extractor.extract(text)
        if ex.source != "llm":
            return Analysis(rules_reading, tuple(rules_sigs), "low", "rules(fallback)")
        merged = list(ex.signals)
        have = {s.name for s in merged}
        merged += [s for s in rules_sigs if s.name not in have]
        reading = RegisterReading(
            primary=ex.register, scores={r.value: (0.8 if r is ex.register else 0.0) for r in Register},
            evidence={r.value: [] for r in Register}, confidence=0.8, mixed=False, informal_prob=None)
        return Analysis(reading, tuple(merged), ex.urgency, "llm+rules")
