"""Output-side checks on the model's customer-facing reply (hallucination / unauthorised commitments)."""
from __future__ import annotations

import re

_NAIRA = re.compile(r"(?:₦|\bN(?=\d)|\bNGN\s?)\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m|million|thousand)?", re.I)
_PAYMENT_CONFIRM = re.compile(
    r"\b(payment|transfer|money)\b.{0,30}\b(has been |have been |is |was |don )?(received|confirmed|verified|enter)\b"
    r"|\bi (have |don )?(confirmed|verified|received) (your )?(payment|transfer)\b", re.I)


def _to_kobo(num: str, suffix: str | None) -> int:
    v = float(num.replace(",", ""))
    mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get((suffix or "").lower(), 1)
    return round(v * mult * 100)


def amounts_kobo(text: str) -> set[int]:
    return {_to_kobo(m.group(1), m.group(2)) for m in _NAIRA.finditer(text)}


_BARE_AMOUNT = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(k|m|million|thousand)?(?![\w])", re.I)


def customer_amounts_kobo(text: str) -> set[int]:
    """Amounts a customer wrote, with or without a naira sign ("700k", "450,000"). The agent may echo
    these back; a bare number only counts if it has a k/m suffix or at least four digits."""
    out = set(amounts_kobo(text))
    for m in _BARE_AMOUNT.finditer(text):
        num, suffix = m.group(1), m.group(2)
        if suffix or len(num.replace(",", "").split(".")[0]) >= 4:
            try:
                out.add(_to_kobo(num, suffix))
            except ValueError:
                pass
    return out


def check_reply(reply: str, allowed_kobo: set[int], payment_verified: bool = False) -> list[str]:
    """Return a list of violations; empty means the reply may be sent."""
    problems = []
    unknown = amounts_kobo(reply) - allowed_kobo
    if unknown:
        problems.append("unauthorised price(s): " + ", ".join(f"₦{a / 100:,.0f}" for a in sorted(unknown)))
    if not payment_verified and _PAYMENT_CONFIRM.search(reply):
        problems.append("claims payment confirmed without verification")
    return problems


# ---- unsupported claims about the business ------------------------------------------------------
# A reply may only assert what the owner configured (BusinessConfig.facts_text()). The patterns below
# catch the claims LLMs most often invent when a customer asks "is this legit?" or "can I pay on delivery?".
_CLAIM_PATTERNS = [
    re.compile(r"\bregistered (business|company|firm|brand)\b", re.I),
    re.compile(r"\b(cac|rc)[ -]?(registered|number|certified)\b", re.I),
    re.compile(r"\blicen[sc]ed\b", re.I),
    re.compile(r"\bcertified\b", re.I),
    re.compile(r"\bnafdac\b", re.I),
    re.compile(r"\b100\s?%\s*(safe|secure|protected|guaranteed|genuine|original|authentic|legit)", re.I),
    re.compile(r"\b(money[- ]back|satisfaction)\s+guarantee", re.I),
    re.compile(r"\b(\d+|one|two|three)[- ]?(year|month)s?[' ]?(warranty|guarantee)", re.I),
    re.compile(r"\b(within|in|inside)\s+(\d+|one|two|three|a|an)\s*(hours?|days?|minutes?|working days?)\b", re.I),
    re.compile(r"\b(same|next)[- ]day (delivery|dispatch)\b", re.I),
    re.compile(r"\bfree (delivery|shipping)\b", re.I),
    # "original/genuine" is THE Nigerian trust word: assurances about authenticity must come from the owner's facts
    re.compile(r"\b(genuine|authentic|original)\s+(product|phone|iphone|device|item|goods|brand|electronics)s?\b", re.I),
    re.compile(r"\b(is|are|be|100% )\s*(genuine|authentic|original)\b", re.I),
    re.compile(r"\b(genuine|authentic)\s+(electronics\s+)?(store|shop|business|seller|company)\b", re.I),
]
_POD = re.compile(r"\b(we|you can|you may|you could|i can|our policy)\b[^.?!]{0,40}\b(pay(ment)?[- ]on[- ]delivery|cash on delivery)"
                  r"|\b(don'?t|do not|never|cannot|can'?t|no)\b[^.?!]{0,30}\b(pay(ment)? on delivery|cash on delivery)", re.I)


def check_claims(reply: str, facts_text: str) -> list[str]:
    """Problems = assertions about the business that the owner's configured facts do not support."""
    facts = facts_text.lower()
    problems = []
    for rx in _CLAIM_PATTERNS:
        for m in rx.finditer(reply):
            phrase = m.group(0).lower()
            if phrase not in facts:
                problems.append(f"unsupported claim: '{m.group(0)}'")
    if _POD.search(reply) and "on delivery" not in facts:
        problems.append("states a pay-on-delivery policy that is not configured")
    return list(dict.fromkeys(problems))
