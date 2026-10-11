"""Structured retrieval of social-media-marketing (SMM) knowledge for the future SMM/Content agents.

Source: the Meta (Instagram, Facebook, WhatsApp, Threads) and TikTok corpora, indexed together in
the `smm` domain with normalised facets (platform, surface, objective, industry, region, register).

What this returns, and what it deliberately does not:
  * Returns playbook steps (with an agent-automation rating), anti-patterns, platform specs
    (format, hook, script beats, caption blueprint), and Nigerian market context.
  * Does NOT return `metrics_and_evidence`. Those figures are LLM-generated ("74.2% retention across
    50 Lagos accounts") and must never be quoted to a business as fact.
  * Attaches `cautions` wherever example copy contains product/health/efficacy claims, regulatory
    names, or sample payment links. Examples are *style*, not text to publish: the business must
    substantiate any claim (NAFDAC/ARCON/FCCPC rules apply) and use its own payment links.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import facets
from .families import SMM
from .store import CorpusStore, Hit

PLATFORMS = ("meta", "tiktok")

_CLAIM = re.compile(
    # health/efficacy, absolute ingredient/authenticity claims, and earnings/returns promises.
    # Deliberately NOT: "clear CTA", "money-back guarantee", "reply within 24 hours" (ordinary business copy).
    r"(\b(cures?|heals?|treats?)\b|"
    r"\b(clears?|removes?|eliminates?|fades?) (up )?(your )?(acne|tan|pimples|dark spots?|stains?|wrinkles?|sunburn|hyperpigmentation|scars?)\b|"
    r"\brepairs? (uv|skin|hair|sun)\b|\bdermatolog\w*|\bclinically (proven|tested)\b|"
    r"\b100\s?% (organic|natural|botanical|safe|genuine|original|authentic|pure|effective)\b|"
    r"\b(lose|drop) \d+\s?(kg|pounds|lbs)\b|\bpermanent(ly)? (results?|removal|whitening|cure)\b|"
    r"\b(guaranteed|assured) (returns?|profit|income|results?)\b|\b(double|triple) your (money|income)\b|"
    r"\b(earn|make) (₦|n|ngn)?\s?\d[\d,]*\s?(k|m)?\s?(daily|weekly|monthly|per (day|week|month))\b)", re.I)
_REGULATORY = re.compile(r"\b(nafdac|son certified|cac registered|fda approved|ncc approved|cbn licensed)\b", re.I)
_PAYLINK = re.compile(r"(paystack\.com/pay/\S+|flutterwave\.com/\S+|https?://\S*(pay|checkout)\S*)", re.I)


@dataclass(frozen=True)
class Step:
    n: int | None
    action: str
    rationale: str
    automation: str          # "automatable" | "owner_advisory" | "unknown"
    success_signal: str


@dataclass(frozen=True)
class SmmGuidance:
    report_id: str | None
    title: str
    platform: str | None
    surface: str | None
    objective: str | None
    layer: str | None
    situation: str
    summary: str
    principles: tuple[str, ...]
    playbook: tuple[Step, ...]
    anti_patterns: tuple[dict, ...]
    when_to_apply: str
    how_to_apply: str
    what_to_avoid: str
    platform_specific: dict
    market: dict
    cautions: tuple[str, ...]
    dropped_filters: tuple[str, ...] = ()
    score: float = 0.0


def _s(x: Any, n: int = 600) -> str:
    return x.strip()[:n] if isinstance(x, str) else ""


def _strs(x: Any, n: int = 400) -> tuple[str, ...]:
    if isinstance(x, list):
        return tuple(_s(i, n) for i in x if isinstance(i, str) and i.strip())
    return ()


def _automation(v: Any) -> str:
    u = str(v or "").upper()
    if u.startswith("FULLY"):
        return "automatable"
    if u.startswith("ADVISORY"):
        return "owner_advisory"
    return "unknown"


def _steps(pb: Any) -> tuple[Step, ...]:
    out = []
    for i, st in enumerate(pb if isinstance(pb, list) else []):
        if isinstance(st, dict) and _s(st.get("action")):
            n = st.get("step_number")
            out.append(Step(n if isinstance(n, int) else i + 1, _s(st["action"]), _s(st.get("rationale")),
                            _automation(st.get("agent_automation")), _s(st.get("success_signal"))))
    return tuple(out)


def _anti(ap: Any) -> tuple[dict, ...]:
    out = []
    for a in ap if isinstance(ap, list) else []:
        if isinstance(a, dict) and _s(a.get("pattern")):
            out.append({"pattern": _s(a["pattern"]), "why_it_fails": _s(a.get("why_it_fails")),
                        "correct_alternative": _s(a.get("correct_alternative"))})
    return tuple(out)


def _market(nc: Any) -> dict:
    if not isinstance(nc, dict):
        return {}
    pc = nc.get("pricing_context") if isinstance(nc.get("pricing_context"), dict) else {}
    band = pc.get("price_band_ngn") if isinstance(pc.get("price_band_ngn"), dict) else {}
    return {"regions": nc.get("region_focus") if isinstance(nc.get("region_focus"), list) else [],
            "language_register": _s(nc.get("language_register"), 120), "age_segment": _s(nc.get("age_segment"), 40),
            "income_tier": _s(nc.get("income_tier"), 60), "price_band_ngn": band or None,
            "price_sensitivity": _s(pc.get("price_sensitivity"), 40),
            "trust_barriers": list(_strs(nc.get("trust_barriers"), 160)),
            "seasonal_trigger": _s(nc.get("seasonal_trigger"), 160), "cultural_notes": _s(nc.get("cultural_notes"), 500)}


def _flat(x: Any) -> str:
    if isinstance(x, dict):
        return " ".join(_flat(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return " ".join(_flat(v) for v in x)
    return str(x) if x is not None else ""


def compute_cautions(rec: dict) -> tuple[str, ...]:
    """Scan example copy (platform specs, instructions, QA) for things an agent must not republish."""
    text = _flat([rec.get("platform_specific"), rec.get("agent_instructions"), rec.get("qa_pairs"), rec.get("playbook")])
    out = []
    if _CLAIM.search(text):
        out.append("Example copy contains product/health/earnings or guarantee-style claims. Treat as style only; "
                   "the business must be able to substantiate any claim it publishes.")
    if _REGULATORY.search(text):
        out.append("Example copy cites regulatory approvals (e.g. NAFDAC/SON). Never claim an approval the business "
                   "has not provided evidence of.")
    if _PAYLINK.search(text):
        out.append("Example copy contains a sample payment link. Never reuse it; use only the business's own payment link.")
    return tuple(out)


def _to_guidance(h: Hit, dropped: tuple[str, ...]) -> SmmGuidance:
    r = h.record
    cov = r.get("coverage") if isinstance(r.get("coverage"), dict) else {}
    ai = r.get("agent_instructions") if isinstance(r.get("agent_instructions"), dict) else {}
    ps = r.get("platform_specific") if isinstance(r.get("platform_specific"), dict) else {}
    return SmmGuidance(
        report_id=r.get("report_id"), title=h.title, platform=h.platform, surface=h.surface,
        objective=h.objective, layer=h.layer, situation=_s(cov.get("situation")), summary=_s(r.get("summary")),
        principles=_strs(r.get("key_principles")), playbook=_steps(r.get("playbook")),
        anti_patterns=_anti(r.get("anti_patterns")), when_to_apply=_s(ai.get("when_to_apply")),
        how_to_apply=_s(ai.get("how_to_apply")), what_to_avoid=_s(ai.get("what_to_avoid")),
        platform_specific=ps, market=_market(r.get("nigeria_context")), cautions=compute_cautions(r),
        dropped_filters=dropped, score=h.score)


def smm_guidance(store: CorpusStore, query: str, *, platform: str | None = None, objective: str | None = None,
                 industry: str | None = None, surface: str | None = None, region: str | None = None,
                 register: str | None = None, layer_prefix: str | None = None, limit: int = 3,
                 relax: bool = True) -> list[SmmGuidance]:
    """Find SMM guidance for a campaign situation.

    Filters use the normalised vocabularies in `facets` (objective in facets.OBJECTIVES, industry such as
    'fashion' / 'food_beverage', register in english|pidgin|mixed, region like 'Lagos'). With `relax=True`,
    if the filters match nothing they are dropped one at a time (region, register, surface, industry,
    objective) and `dropped_filters` on each result says which were given up, so callers never mistake a
    loose match for an exact one.
    """
    if platform is not None and platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    if objective is not None and objective not in facets.OBJECTIVES:
        raise ValueError(f"objective must be one of {facets.OBJECTIVES}")
    active = {"region": region, "register": register, "surface": surface, "industry": industry,
              "objective": objective}
    dropped: list[str] = []
    while True:
        hits = store.search(SMM, query, limit=limit, platform=platform, layer_prefix=layer_prefix,
                            **{k: v for k, v in active.items() if k != "industry" and v},
                            industry=active["industry"])
        if hits or not relax:
            return [_to_guidance(h, tuple(dropped)) for h in hits]
        nxt = next((k for k in ("region", "register", "surface", "industry", "objective") if active[k]), None)
        if nxt is None:
            return []
        active[nxt] = None
        dropped.append(nxt)
