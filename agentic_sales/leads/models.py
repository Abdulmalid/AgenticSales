"""Lead profile and stage model."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeadStage(str, Enum):
    NEW = "NEW"
    DISCOVERED = "DISCOVERED"
    CONTACTED = "CONTACTED"
    ENGAGED = "ENGAGED"
    QUALIFIED = "QUALIFIED"
    NEGOTIATING = "NEGOTIATING"
    READY_TO_BUY = "READY_TO_BUY"
    CONVERTED = "CONVERTED"
    RETAINED = "RETAINED"
    LOST = "LOST"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"


# Stages in which a lead is still being worked toward a sale.
OPEN_STAGES = (LeadStage.NEW, LeadStage.DISCOVERED, LeadStage.CONTACTED, LeadStage.ENGAGED,
               LeadStage.QUALIFIED, LeadStage.NEGOTIATING, LeadStage.READY_TO_BUY)


@dataclass
class Lead:
    id: int
    customer_key: str
    source: str                       # channel or 'landing_page'
    stage: LeadStage = LeadStage.NEW
    name: str | None = None
    interest: str | None = None       # sku or free text
    budget_kobo: int | None = None
    intent: str = "low"               # low | medium | high
    objection: str | None = None      # price | trust | payment_terms | delivery
    trust_level: str = "unknown"      # unknown | low | medium | high
    fraud_risk: str = "LOW"           # LOW | MEDIUM | HIGH
    score: int = 0
    band: str = "cold"                # cold | warm | hot
    conversion_probability: float = 0.0   # heuristic, NOT calibrated (see leads/engine.py)
    last_interaction: str | None = None
    created: str | None = None
    attrs: dict = field(default_factory=dict)
