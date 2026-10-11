"""Normalise free-text facets in the SMM corpora into small controlled vocabularies.

The raw `coverage`/`nigeria_context` values are LLM-written and inconsistent
(`Instagram`/`instagram`, `WHATSAPP`/`WhatsApp`, `e_commerce`/`E-Commerce`, `conversion`/
`conversions`/`sales conversion`). Filtering on the raw strings would silently miss most
records, so we map each to a canonical value at index time. Unknown values fall into "other"
(objective/industry) or a slug (surface) rather than being guessed.
"""
from __future__ import annotations

import re


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


# ---- objective -------------------------------------------------------------------------------
OBJECTIVES = ("awareness", "consideration", "engagement", "lead_generation", "conversion", "retention", "trust_building")
_OBJ_RULES = [  # first match wins; order matters (e.g. "brand trust" before "brand")
    ("trust", "trust_building"), ("credib", "trust_building"), ("risk", "trust_building"),
    ("compliance", "trust_building"), ("authority", "trust_building"),
    ("consideration", "consideration"), ("objection", "conversion"), ("clearance", "conversion"),
    ("growth", "awareness"), ("viral", "awareness"), ("traffic", "lead_generation"), ("positioning", "awareness"),
    ("awareness", "awareness"), ("reach", "awareness"), ("visibility", "awareness"),
    ("lead", "lead_generation"), ("acqui", "lead_generation"), ("prospect", "lead_generation"),
    ("retention", "retention"), ("loyal", "retention"), ("repeat", "retention"), ("reactivat", "retention"),
    ("convers", "conversion"), ("sales", "conversion"), ("revenue", "conversion"),
    ("purchase", "conversion"), ("checkout", "conversion"), ("sell", "conversion"),
    ("engage", "engagement"), ("community", "engagement"), ("interaction", "engagement"),
]


def objective(value: object) -> str:
    s = slug(value)
    for needle, canon in _OBJ_RULES:
        if needle in s:
            return canon
    return "other"


# ---- industry --------------------------------------------------------------------------------
_IND_RULES = [
    ("real_estate", "real_estate"), ("property", "real_estate"), ("estate", "real_estate"),
    ("fintech", "fintech"), ("financ", "fintech"), ("bank", "fintech"), ("payment", "fintech"),
    ("insur", "fintech"), ("lend", "fintech"),
    ("beauty", "beauty"), ("skin", "beauty"), ("cosmetic", "beauty"), ("hair", "beauty"), ("makeup", "beauty"),
    ("fashion", "fashion"), ("apparel", "fashion"), ("cloth", "fashion"), ("shoe", "fashion"),
    ("food", "food_beverage"), ("restaurant", "food_beverage"), ("beverage", "food_beverage"),
    ("culinary", "food_beverage"), ("cater", "food_beverage"), ("bak", "food_beverage"),
    ("electronic", "electronics"), ("gadget", "electronics"), ("phone", "electronics"),
    ("tech", "electronics"), ("software", "electronics"), ("saas", "electronics"),
    ("educat", "education"), ("edtech", "education"), ("school", "education"), ("training", "education"),
    ("health", "health"), ("pharma", "health"), ("wellness", "health"), ("medical", "health"),
    ("automotive", "automotive"), ("car_", "automotive"), ("cars", "automotive"), ("vehicle", "automotive"),
    ("agri", "agriculture"), ("farm", "agriculture"),
    ("travel", "travel_hospitality"), ("hotel", "travel_hospitality"), ("hospitality", "travel_hospitality"),
    ("tour", "travel_hospitality"), ("logistic", "logistics"), ("deliver", "logistics"),
    ("professional", "professional_services"), ("consult", "professional_services"),
    ("service", "professional_services"),
    ("fmcg", "retail"), ("goods", "retail"), ("merchandise", "retail"), ("wholesale", "retail"),
    ("luxury", "retail"), ("home", "retail"), ("decor", "retail"), ("handmade", "retail"), ("craft", "retail"),
    ("footwear", "fashion"), ("leather", "fashion"), ("accessor", "fashion"), ("personal_care", "beauty"),
    ("telecom", "electronics"), ("creator", "media_digital"), ("entertain", "media_digital"),
    ("media", "media_digital"), ("digital", "media_digital"), ("agency", "professional_services"),
    ("all_industries", "general"), ("general", "general"),
    ("commerce", "ecommerce"), ("online_store", "ecommerce"), ("retail", "retail"), ("consumer", "retail"),
]


def industry(value: object) -> str:
    s = slug(value)
    for needle, canon in _IND_RULES:
        if needle in s:
            return canon
    return "other"


def industries(values: object) -> str:
    """Stored as '|a|b|' so a LIKE '%|a|%' matches any of a record's industries."""
    items = values if isinstance(values, list) else [values]
    canon = []
    for v in items:
        c = industry(v)
        if c not in canon:
            canon.append(c)
    return "|" + "|".join(canon) + "|"


# ---- surface ---------------------------------------------------------------------------------
_META_SURFACES = [
    ("reel", "instagram_reels"), ("marketplace", "facebook_marketplace"), ("group", "facebook_groups"),
    ("instagram", "instagram"), ("facebook", "facebook"), ("whatsapp", "whatsapp"), ("whats_app", "whatsapp"),
    ("thread", "threads"), ("messenger", "messenger"),
]
_TT_SURFACES = [("live", "live_selling"), ("ugc", "ugc_brief"), ("short", "short_form"),
                ("story", "storytime"), ("skit", "skit"), ("talking", "talking_head")]


def surface(platform: str, cell_key: object) -> str | None:
    parts = str(cell_key or "").split("|")
    raw = slug(parts[1]) if len(parts) > 1 else ""
    if not raw:
        return None
    for needle, canon in (_META_SURFACES if platform == "meta" else _TT_SURFACES):
        if needle in raw:
            return canon
    return raw


# ---- register --------------------------------------------------------------------------------
def register(value: object) -> str | None:
    s = slug(value)
    if not s:
        return None
    if "pidgin" in s or "naija" in s or "slang" in s:
        plain = any(w in s for w in ("corporate", "professional", "standard", "formal", "business", "english_mix"))
        return "mixed" if plain else "pidgin"
    return "english"


_REGION_RULES = [
    ("nationwide", "Nationwide"), ("national", "Nationwide"),
    ("lagos", "Lagos"), ("ikeja", "Lagos"), ("lekki", "Lagos"), ("victoria island", "Lagos"), ("yaba", "Lagos"),
    ("surulere", "Lagos"), ("ikoyi", "Lagos"), ("computer village", "Lagos"), ("balogun", "Lagos"), ("ajah", "Lagos"),
    ("abuja", "Abuja"), ("fct", "Abuja"), ("maitama", "Abuja"), ("wuse", "Abuja"), ("garki", "Abuja"),
    ("port harcourt", "Port Harcourt"), ("ibadan", "Ibadan"), ("kano", "Kano"), ("aba", "Aba"),
    ("enugu", "Enugu"), ("onitsha", "Onitsha"), ("benin", "Benin City"), ("kaduna", "Kaduna"),
]


def region(value: object) -> str | None:
    s = str(value or "").strip().lower().replace("_", " ")
    if not s:
        return None
    for needle, canon in _REGION_RULES:
        if re.search("(?<![a-z])" + re.escape(needle) + "(?![a-z])", s):
            return canon
    return str(value).strip().title()


def first_region(nigeria_context: object) -> str | None:
    if isinstance(nigeria_context, dict):
        r = nigeria_context.get("region_focus")
        if isinstance(r, list) and r:
            return region(r[0])
        if isinstance(r, str):
            return region(r)
    return None
