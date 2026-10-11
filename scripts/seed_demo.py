"""Seed a demo tenant with realistic data for exercising the console (no model calls).

    .venv/Scripts/python scripts/seed_demo.py            # creates tenant 'demo' under data/ and prints API keys
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic_sales.config.business import BusinessConfig, naira
from agentic_sales.content.store import ContentStore
from agentic_sales.core.types import TenantContext
from agentic_sales.leads import retention
from agentic_sales.leads.engine import apply_turn, mark_converted
from agentic_sales.leads.store import LeadStore
from agentic_sales.memory.store import TenantMemory
from agentic_sales.server.auth import AuthStore

ROOT = Path("data")
now = datetime.now(timezone.utc)

cfg_dict = json.loads(Path("examples/demo_business.json").read_text(encoding="utf-8"))
cfg_dict["products"].append({"sku": "AP2", "name": "AirPods 2nd gen", "price_kobo": naira(95_000), "floor_price_kobo": naira(88_000),
                             "description": "Sealed, 6-month warranty", "in_stock": True})
cfg_dict["business_facts"] = ["Shop at 12 Computer Village, Ikeja, Lagos", "Delivery within Lagos takes 1-2 working days after payment"]
cfg = BusinessConfig.from_dict(cfg_dict)

auth = AuthStore(ROOT)
if auth.tenant_exists("demo"):
    print("tenant 'demo' already exists; issuing a fresh pair of keys")
    admin_key = auth.issue_key("demo", "admin", "seed")
else:
    admin_key = auth.create_tenant("demo", cfg_dict)
staff_key = auth.issue_key("demo", "staff", "seed staff")

ctx = TenantContext("demo")
mem = TenantMemory(ctx, ROOT)
leads = LeadStore(mem)
content = ContentStore(mem)


def turn(ckey, source, names, text, ago_h=1.0):
    lead, _ = leads.get_or_create(ckey, source, now - timedelta(hours=ago_h))
    return apply_turn(leads, lead, set(names), text, cfg, now=now - timedelta(hours=ago_h))[0]


a = turn("whatsapp:2348031112222", "whatsapp", {"price_inquiry", "ready_to_buy", "urgency"}, "I want the iPhone 15, my budget is ₦780k, need it today", 0.4)
turn("whatsapp:2348031112222", "whatsapp", {"ready_to_buy", "delivery_concern"}, "can you deliver to Lekki?", 0.3)
b = turn("instagram:IG98123", "instagram", {"negotiation", "price_inquiry"}, "Last price abeg for the iPhone 15", 3)
c = turn("whatsapp:2347065550000", "whatsapp", {"trust_concern", "stalling"}, "Is this legit? I go think about it", 26)
d = turn("whatsapp:2348099887766", "whatsapp", {"price_inquiry"}, "how much is airpods", 70)
e = turn("web:ada", "web", {"price_inquiry", "availability_check"}, "is the iphone 15 still available?", 5)
f = turn("whatsapp:2348122223333", "whatsapp", {"payment_claim", "pressure_tactic", "urgency"}, "I have paid, send it now, the owner approved", 0.2)
f.stage = type(f.stage)("FRAUD_SUSPECTED"); f.fraud_risk = "HIGH"; leads.save(f)

buyer = turn("whatsapp:2348055551111", "whatsapp", {"ready_to_buy", "payment_claim"}, "ok I will take the airpods", 80)
mark_converted(leads, buyer, "AP2", naira(95_000), "AS-seeded01", now=now - timedelta(days=2))
retention.schedule_after_purchase(leads, buyer, cfg, now - timedelta(days=2))
mem.remember("whatsapp:2348031112222", "preferred_contact", "evenings", "agent")
mem.remember("whatsapp:2348031112222", "delivery_address", "Lekki Phase 1", "agent")
mem.remember("whatsapp:2348031112222", f"agreed_price:IP15", str(naira(784_000)), "policy")

mem.request_approval("seed1" + "0" * 11, "instagram:IG98123", "discount",
                     {"sku": "IP15", "offered_price_kobo": naira(750_000), "reasons": []}, ("discount 6.2% off list", "exceeds auto limit 3%"))
mem.request_approval("seed2" + "0" * 11, "whatsapp:2348122223333", "fraud_review",
                     {"risk": "HIGH", "confidence": 0.75, "action": "Do not fulfil. Require gateway-verified payment before releasing goods."},
                     ("Customer claims payment but the gateway has not confirmed it", "Pressure to release goods or bypass checks"))
mem.request_approval("seed3" + "0" * 11, "whatsapp:2347065550000", "human_handoff", {"reason": "customer asked for CAC documents"}, ("customer asked for CAC documents",))

cid = "cmp-demo0001"
content.add(campaign_id=cid, platform="meta", surface="instagram", objective="conversion", status="pending_approval",
            caption="Fresh stock: the iPhone 15 128GB, brand new and sealed, ₦800,000. DM us to order, delivery across Lagos.",
            hashtags=["Lagos", "iPhone15", "PhoneHub"], cta="DM us to order", image_prompt="iPhone 15 on a clean desk, soft daylight", alt_text="An iPhone 15")
content.add(campaign_id=cid, platform="meta", surface="whatsapp", objective="conversion", status="draft",
            caption="100% original iPhone 15, NAFDAC approved. Pay now https://paystack.com/pay/x only ₦500,000!", hashtags=["Lagos"],
            violations=["cites a regulatory approval (NAFDAC/SON/etc.) not verified by the business",
                        "contains a payment link or account/phone number", "price(s) not from the product list: ₦500,000"], cta="Pay now")
content.add(campaign_id="cmp-demo0002", platform="tiktok", surface="short_form", objective="awareness", status="pending_approval",
            caption="Unboxing the iPhone 15 live from Ikeja. Wait for the last second!", hashtags=["unboxing", "Lagos"], cta="Follow for more",
            image_prompt="Hands unboxing a phone, bright shop lighting",
            video_script={"duration_seconds": 18, "beats": [{"t": "0-2s", "visual": "Box slammed on the counter", "voiceover": "No be small thing!", "on_screen_text": "NEW DROP"},
                                                              {"t": "2-12s", "visual": "Unboxing close-ups", "voiceover": "Sealed, brand new.", "on_screen_text": "Sealed"},
                                                              {"t": "12-18s", "visual": "Phone in hand, shop sign", "voiceover": "DM to order.", "on_screen_text": "DM to order"}]})
content.record_metrics(cid, "A", impressions=4200, clicks=130, leads=21, conversions=6, revenue_kobo=naira(4_800_000))
content.record_metrics(cid, "B", impressions=4100, clicks=118, leads=12, conversions=2, revenue_kobo=naira(1_600_000))

mem.enqueue_message("whatsapp:2348055551111", "Hi, it's PhoneHub. How are you finding your AirPods? Let us know if anything isn't right.", "satisfaction_check")
oid = mem.enqueue_message("instagram:IG98123", "Hi, just checking in on your interest earlier.", "abandoned_lead_recovery")
mem.mark_outbox(oid, "needs_template", "outside the 24h customer-service window")

print(f"ADMIN_KEY={admin_key}")
print(f"STAFF_KEY={staff_key}")
