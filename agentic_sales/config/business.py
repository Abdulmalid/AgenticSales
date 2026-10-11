"""Per-tenant business configuration. Customer text can never modify this; only the
business owner (via trusted admin paths) can."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import TenantContext

KOBO = 100


def naira(amount_naira: float) -> int:
    """Money is stored as integer kobo everywhere. Never float."""
    return round(amount_naira * KOBO)


@dataclass
class Product:
    sku: str
    name: str
    price_kobo: int
    floor_price_kobo: int          # never sell below this without human approval
    description: str = ""
    in_stock: bool = True


@dataclass
class ApprovalRules:
    max_discount_pct_auto: float = 5.0      # above this -> human approval
    max_discount_pct_hard: float = 15.0     # above this -> denied outright
    refunds_need_approval: bool = True
    high_fraud_risk_needs_approval: bool = True
    large_transaction_kobo: int = naira(1_000_000)
    public_posts_need_approval: bool = True


@dataclass
class BusinessConfig:
    business_name: str
    industry: str
    products: list[Product] = field(default_factory=list)
    brand_voice: str = "professional but warm"
    target_audience: str = ""
    delivery_areas: list[str] = field(default_factory=list)
    payment_methods: list[str] = field(default_factory=list)  # e.g. ["paystack", "bank_transfer"]
    refund_policy: str = ""
    business_facts: list[str] = field(default_factory=list)   # owner-verified statements the agent may assert
    working_hours: str = ""
    preferred_channels: list[str] = field(default_factory=list)
    approvals: ApprovalRules = field(default_factory=ApprovalRules)
    # retention schedule: days after purchase -> message purpose (configurable per business)
    retention_schedule: dict[int, str] = field(default_factory=lambda: {
        0: "purchase_confirmation", 2: "satisfaction_check", 7: "usage_followup",
        21: "related_product", 30: "retention_campaign"})

    def facts_text(self) -> str:
        """Everything the agent is allowed to assert about the business, as one lowercase blob."""
        parts = [self.business_name, self.industry, self.refund_policy, self.working_hours, *self.business_facts,
                 *self.delivery_areas, *self.payment_methods]
        parts += [f"{p.name} {p.description}" for p in self.products]
        return " ".join(parts).lower()

    def product(self, sku: str) -> Product | None:
        return next((p for p in self.products if p.sku == sku), None)

    def validate(self) -> None:
        if not self.business_name.strip():
            raise ValueError("business_name required")
        for p in self.products:
            if p.floor_price_kobo > p.price_kobo:
                raise ValueError(f"{p.sku}: floor price above list price")
        if any(not isinstance(f, str) or len(f) > 300 for f in self.business_facts):
            raise ValueError("business_facts must be strings of at most 300 characters")
        a = self.approvals
        if not 0 <= a.max_discount_pct_auto <= a.max_discount_pct_hard <= 100:
            raise ValueError("discount limits must satisfy 0 <= auto <= hard <= 100")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BusinessConfig":
        d = dict(d)
        d["products"] = [Product(**p) for p in d.get("products", [])]
        d["approvals"] = ApprovalRules(**d.get("approvals", {}))
        if "retention_schedule" in d:
            d["retention_schedule"] = {int(k): v for k, v in d["retention_schedule"].items()}
        cfg = cls(**d)
        cfg.validate()
        return cfg


def load_business_config(ctx: TenantContext, root: Path) -> BusinessConfig:
    path = root / "tenants" / ctx.tenant_id / "business.json"
    return BusinessConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
