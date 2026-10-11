"""Landing-page generator: a single static, dependency-free HTML page per business.

Security: every business-supplied string is HTML-escaped; colours and phone numbers are validated;
image URLs must be https; the page ships a strict CSP and no scripts. The lead form posts to the
platform's public endpoint, which rate-limits and honeypots (see server). Product prices come from
BusinessConfig so the page can never advertise a price the agent would not honour.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field

from ..config.business import BusinessConfig

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_DIGITS = re.compile(r"^\d{10,15}$")


@dataclass
class LandingInput:
    whatsapp: str                       # international format, digits only e.g. 2348012345678
    phone: str | None = None
    location: str | None = None
    tagline: str | None = None
    description: str | None = None
    primary_color: str = "#0b6e4f"
    accent_color: str = "#f4a300"
    logo_url: str | None = None
    hero_image_url: str | None = None
    product_images: dict[str, str] = field(default_factory=dict)   # sku -> https image url
    site_url: str | None = None          # canonical URL once hosted


class LandingError(ValueError):
    pass


def _e(x: object) -> str:
    return html.escape(str(x or ""), quote=True)


def _https(url: str | None, what: str) -> str | None:
    if not url:
        return None
    if not url.startswith("https://") or len(url) > 500 or any(c in url for c in " \"'<>"):
        raise LandingError(f"{what} must be a clean https URL")
    return url


def build_landing_page(cfg: BusinessConfig, inp: LandingInput, form_action: str) -> str:
    wa = re.sub(r"\D", "", inp.whatsapp or "")
    if not _DIGITS.match(wa):
        raise LandingError("whatsapp must be 10-15 digits in international format (e.g. 2348012345678)")
    for c in (inp.primary_color, inp.accent_color):
        if not _COLOR.match(c):
            raise LandingError("colours must be #RRGGBB")
    if not (form_action.startswith("/") and not form_action.startswith("//")):
        raise LandingError("form_action must be a same-origin path")
    logo, hero = _https(inp.logo_url, "logo_url"), _https(inp.hero_image_url, "hero_image_url")
    biz = cfg.business_name
    tagline = inp.tagline or f"{biz}: {cfg.industry}"
    desc = (inp.description or f"{biz} serves {', '.join(cfg.delivery_areas) or 'Nigeria'}. Chat with us on WhatsApp to order.")[:300]
    wa_link = f"https://wa.me/{wa}?text=" + urllib.parse.quote(f"Hello {biz}, I'd like to know more.")

    cards = []
    for p in cfg.products:
        if not p.in_stock:
            continue
        img = _https(inp.product_images.get(p.sku), f"image for {p.sku}")
        pw = f"https://wa.me/{wa}?text=" + urllib.parse.quote(f"Hello {biz}, I'm interested in {p.name}.")
        cards.append(
            f'<article class="card">{f"<img src={chr(34)}{_e(img)}{chr(34)} alt={chr(34)}{_e(p.name)}{chr(34)} loading=lazy>" if img else ""}'
            f'<h3>{_e(p.name)}</h3><p>{_e(p.description)}</p><p class="price">₦{p.price_kobo / 100:,.0f}</p>'
            f'<a class="btn" href="{_e(pw)}">Order on WhatsApp</a></article>')
    options = "".join(f'<option value="{_e(p.sku)}">{_e(p.name)}</option>' for p in cfg.products if p.in_stock)
    ld = json.dumps({"@context": "https://schema.org", "@type": "LocalBusiness", "name": biz, "description": desc,
                     "telephone": inp.phone or f"+{wa}", "address": inp.location or "Nigeria",
                     "areaServed": cfg.delivery_areas or ["Nigeria"]}, ensure_ascii=False)
    # make the JSON inert inside a <script> block: no raw <, > or & can survive
    ld = ld.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    canonical = f'<link rel="canonical" href="{_e(inp.site_url)}">' if inp.site_url and _https(inp.site_url, "site_url") else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; form-action {_e(form_action)}; base-uri 'none'">
<title>{_e(biz)}: {_e(tagline)}</title><meta name="description" content="{_e(desc)}">
<meta property="og:title" content="{_e(biz)}"><meta property="og:description" content="{_e(desc)}"><meta property="og:type" content="website">
{f'<meta property="og:image" content="{_e(hero)}">' if hero else ''}{canonical}
<script type="application/ld+json">{ld}</script>
<style>:root{{--p:{inp.primary_color};--a:{inp.accent_color}}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,sans-serif;color:#1b1b1b;background:#fafafa}}
header{{background:var(--p);color:#fff;padding:2rem 1rem;text-align:center}}header img.logo{{height:56px}}h1{{margin:.5rem 0}}
main{{max-width:960px;margin:auto;padding:1rem}}.hero{{width:100%;max-height:320px;object-fit:cover;border-radius:12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}}.card{{background:#fff;border-radius:12px;padding:1rem;box-shadow:0 1px 4px #0002}}
.card img{{width:100%;height:180px;object-fit:cover;border-radius:8px}}.price{{font-weight:700;color:var(--p)}}
.btn,button{{display:inline-block;background:var(--a);color:#000;padding:.7rem 1.1rem;border-radius:8px;text-decoration:none;border:0;font-weight:700;cursor:pointer}}
form{{display:grid;gap:.6rem;max-width:480px}}input,select,textarea{{padding:.7rem;border:1px solid #ccc;border-radius:8px;font:inherit}}.hp{{position:absolute;left:-9999px}}
.wa{{position:fixed;right:16px;bottom:16px}}footer{{text-align:center;padding:2rem;color:#555}}</style></head>
<body><header>{f'<img class="logo" src="{_e(logo)}" alt="{_e(biz)} logo"><br>' if logo else ''}<h1>{_e(biz)}</h1><p>{_e(tagline)}</p>
<a class="btn" href="{_e(wa_link)}">Chat on WhatsApp</a></header>
<main>{f'<img class="hero" src="{_e(hero)}" alt="{_e(biz)}">' if hero else ''}<h2>Our products</h2><section class="grid">{''.join(cards) or '<p>Products coming soon.</p>'}</section>
<h2>Get a call back</h2><form method="post" action="{_e(form_action)}"><input name="name" placeholder="Your name" required maxlength="80">
<input name="phone" placeholder="WhatsApp number e.g. 0801 234 5678" required maxlength="20" inputmode="tel">
<select name="sku"><option value="">What are you interested in?</option>{options}</select><textarea name="message" placeholder="Message (optional)" maxlength="500"></textarea>
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true"><button type="submit">Send</button>
<small>By submitting you agree to be contacted about your enquiry. Reply STOP anytime to opt out.</small></form></main>
<footer>{_e(inp.location or '')} {_e(inp.phone or '')}<br>Delivery: {_e(', '.join(cfg.delivery_areas) or 'Nationwide')}. Payment: {_e(', '.join(cfg.payment_methods) or 'on request')}.</footer>
<a class="btn wa" href="{_e(wa_link)}">WhatsApp us</a></body></html>"""
