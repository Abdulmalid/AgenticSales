import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:  # core tests run without the server deps
    HAVE_API = False

from agentic_sales.channels.adapters import ADAPTERS
from agentic_sales.config.business import naira
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelResponse, ModelRouter, TaskKind

BIZ = {"business_name": "PhoneHub", "industry": "electronics retail", "brand_voice": "warm and direct",
       "delivery_areas": ["Lagos"], "payment_methods": ["paystack"],
       "products": [{"sku": "IP15", "name": "iPhone 15", "price_kobo": naira(800_000), "floor_price_kobo": naira(740_000),
                     "description": "Brand new", "in_stock": True}],
       "approvals": {"max_discount_pct_auto": 5, "max_discount_pct_hard": 10}}


class Scripted:
    name = "scripted"

    def __init__(self):
        self.outs: list[str] = []

    def push(self, obj):
        self.outs.append(json.dumps(obj))

    def complete(self, req):
        return ModelResponse(self.outs.pop(0), self.name)


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Api(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.model = Scripted()
        router = ModelRouter(text={TaskKind.CONVERSATION: self.model})
        self.auth = AuthStore(self.root)
        self.key_a = self.auth.create_tenant("shop-a", BIZ)
        self.key_b = self.auth.create_tenant("shop-b", {**BIZ, "business_name": "OtherShop"})
        app = create_app(self.root, Runtimes(self.root, None, router, Analyzer(None)), self.auth)
        self.c = TestClient(app)

    def H(self, key=None):
        return {"Authorization": f"Bearer {key or self.key_a}"}

    # ---- auth & isolation
    def test_endpoints_require_a_valid_key(self):
        self.assertEqual(self.c.get("/v1/leads").status_code, 401)
        self.assertEqual(self.c.get("/v1/leads", headers=self.H("ask_" + "x" * 43)).status_code, 401)
        self.assertEqual(self.c.get("/health").status_code, 200)

    def test_keys_are_hashed_at_rest(self):
        import sqlite3
        rows = sqlite3.connect(self.root / "auth.db").execute("SELECT key_hash FROM api_keys").fetchall()
        self.assertTrue(all(len(r[0]) == 64 and r[0] != self.key_a for r in rows))

    def test_tenants_cannot_see_each_other(self):
        self.model.push({"reply": "The iPhone 15 is ₦800,000.", "actions": []})
        self.c.post("/v1/chat", headers=self.H(), json={"user_id": "cust1", "text": "how much is the iphone 15?"})
        self.assertEqual(len(self.c.get("/v1/leads", headers=self.H()).json()), 1)
        self.assertEqual(self.c.get("/v1/leads", headers=self.H(self.key_b)).json(), [])
        self.assertEqual(self.c.get("/v1/leads/1", headers=self.H(self.key_b)).status_code, 404)

    def test_staff_cannot_use_admin_endpoints(self):
        staff = self.auth.issue_key("shop-a", "staff")
        self.assertEqual(self.c.get("/v1/config", headers=self.H(staff)).status_code, 403)
        self.assertEqual(self.c.put("/v1/secrets/whatsapp", headers=self.H(staff), json={"a": "b"}).status_code, 403)
        self.assertEqual(self.c.get("/v1/leads", headers=self.H(staff)).status_code, 200)

    def test_secrets_are_write_only(self):
        self.c.put("/v1/secrets/whatsapp", headers=self.H(), json={"app_secret": "TOPSECRET", "access_token": "T"})
        listed = self.c.get("/v1/secrets", headers=self.H()).json()
        self.assertEqual(listed, {"whatsapp": ["access_token", "app_secret"]})
        self.assertNotIn("TOPSECRET", json.dumps(listed))

    def test_invalid_config_rejected(self):
        bad = {**BIZ, "products": [{**BIZ["products"][0], "floor_price_kobo": naira(900_000)}]}
        self.assertEqual(self.c.put("/v1/config", headers=self.H(), json=bad).status_code, 422)

    # ---- webhooks
    def wa_payload(self, text="How much is the iPhone 15?", mid="wamid.A"):
        return {"entry": [{"changes": [{"value": {"messages": [
            {"from": "2348011112222", "id": mid, "timestamp": "1760000000", "type": "text", "text": {"body": text}}]}}]}]}

    def sign(self, secret, raw):
        return {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
                "content-type": "application/json"}

    def test_webhook_rejects_bad_signature_and_processes_good_one(self):
        self.c.put("/v1/secrets/whatsapp", headers=self.H(), json={"app_secret": "s", "verify_token": "vt", "access_token": "t",
                                                                   "phone_number_id": "1"})
        raw = json.dumps(self.wa_payload()).encode()
        self.assertEqual(self.c.post("/webhooks/shop-a/whatsapp", content=raw, headers=self.sign("wrong", raw)).status_code, 401)
        self.assertEqual(self.c.post("/webhooks/shop-a/whatsapp", content=raw).status_code, 401)
        self.model.push({"reply": "The iPhone 15 is ₦800,000 and in stock.", "actions": []})
        with mock.patch.object(ADAPTERS["whatsapp"], "send") as send:
            r = self.c.post("/webhooks/shop-a/whatsapp", content=raw, headers=self.sign("s", raw))
            self.assertEqual(r.status_code, 200)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "2348011112222")
        self.assertIn("800,000", send.call_args.args[1])
        # redelivery of the same message id must not trigger a second reply
        with mock.patch.object(ADAPTERS["whatsapp"], "send") as send2:
            self.c.post("/webhooks/shop-a/whatsapp", content=raw, headers=self.sign("s", raw))
        send2.assert_not_called()

    def test_webhook_for_other_tenants_secret_is_rejected(self):
        self.c.put("/v1/secrets/whatsapp", headers=self.H(), json={"app_secret": "secret-a"})
        self.c.put("/v1/secrets/whatsapp", headers=self.H(self.key_b), json={"app_secret": "secret-b"})
        raw = json.dumps(self.wa_payload()).encode()
        r = self.c.post("/webhooks/shop-a/whatsapp", content=raw, headers=self.sign("secret-b", raw))
        self.assertEqual(r.status_code, 401)

    def test_handshake_and_unknown_tenant(self):
        self.c.put("/v1/secrets/whatsapp", headers=self.H(), json={"verify_token": "vt", "app_secret": "s"})
        ok = self.c.get("/webhooks/shop-a/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "99"})
        self.assertEqual((ok.status_code, ok.text), (200, "99"))
        self.assertEqual(self.c.get("/webhooks/nope/whatsapp").status_code, 404)
        self.assertEqual(self.c.get("/webhooks/..%2f..%2fetc/whatsapp").status_code, 404)

    def test_paystack_webhook_requires_signature_and_reverifies(self):
        self.c.put("/v1/secrets/paystack", headers=self.H(), json={"secret_key": "sk_test_x"})
        raw = json.dumps({"event": "charge.success", "data": {"reference": "AS-unknown"}}).encode()
        self.assertEqual(self.c.post("/webhooks/shop-a/paystack", content=raw, headers={"x-paystack-signature": "bad"}).status_code, 401)
        good = hmac.new(b"sk_test_x", raw, hashlib.sha512).hexdigest()
        self.assertEqual(self.c.post("/webhooks/shop-a/paystack", content=raw, headers={"x-paystack-signature": good}).status_code, 200)

    # ---- approvals
    def test_discount_approval_applies_price_and_queues_message(self):
        self.model.push({"reply": "Checking.", "actions": [{"tool": "propose_price", "args": {"sku": "IP15", "offered_price_kobo": naira(750_000)}}]})
        self.model.push({"reply": "I've asked my manager, I'll update you shortly.", "actions": []})
        r = self.c.post("/v1/chat", headers=self.H(), json={"user_id": "c1", "text": "last price 750k?"}).json()
        self.assertTrue(r["escalated"])
        pend = self.c.get("/v1/approvals", headers=self.H()).json()
        self.assertEqual([a["action"] for a in pend], ["discount"])
        d = self.c.post(f"/v1/approvals/{pend[0]['id']}/decision", headers=self.H(), json={"approve": True})
        self.assertEqual(d.status_code, 200)
        self.assertEqual(self.c.post(f"/v1/approvals/{pend[0]['id']}/decision", headers=self.H(), json={"approve": True}).status_code, 409)
        rt = self.c.app.state.runtimes.get("shop-a")
        self.assertEqual(rt.memory.facts("web:c1")["agreed_price:IP15"], str(naira(750_000)))
        self.assertIn("750,000", rt.memory.pending_outbox()[0]["text"])

    def test_owner_reply_with_unauthorised_price_is_not_sent(self):
        self.model.push({"reply": "Checking.", "actions": [{"tool": "propose_price", "args": {"sku": "IP15", "offered_price_kobo": naira(750_000)}}]})
        self.model.push({"reply": "Let me check with the team.", "actions": []})
        self.c.post("/v1/chat", headers=self.H(), json={"user_id": "c2", "text": "750k?"})
        aid = self.c.get("/v1/approvals", headers=self.H()).json()[0]["id"]
        d = self.c.post(f"/v1/approvals/{aid}/decision", headers=self.H(), json={"approve": False, "reply_text": "Sure, ₦100,000 for you"})
        self.assertIn("NOT sent", d.json()["detail"])

    def test_approval_of_other_tenant_not_visible(self):
        self.model.push({"reply": "Checking.", "actions": [{"tool": "escalate_to_human", "args": {"reason": "angry"}}]})
        self.model.push({"reply": "A colleague will help.", "actions": []})
        self.c.post("/v1/chat", headers=self.H(), json={"user_id": "c3", "text": "I want a manager"})
        aid = self.c.get("/v1/approvals", headers=self.H()).json()[0]["id"]
        self.assertEqual(self.c.get("/v1/approvals", headers=self.H(self.key_b)).json(), [])
        self.assertEqual(self.c.post(f"/v1/approvals/{aid}/decision", headers=self.H(self.key_b), json={"approve": True}).status_code, 422)

    # ---- content
    def plan(self, caption):
        self.model.push({"strategy": "s", "posts": [{"caption": caption, "hashtags": ["Lagos", "bad tag!", "iPhone15"],
                                                     "cta": "DM us", "image_prompt": "phone on desk", "video_script": None, "alt_text": "a phone"}]})
        return self.c.post("/v1/content/plan", headers=self.H(), json={"brief": "launch the iPhone 15", "platform": "meta",
                                                                       "objective": "conversion"}).json()

    def test_clean_content_goes_to_approval_not_publication(self):
        r = self.plan("The iPhone 15, brand new, ₦800,000. DM us to order.")
        item = self.c.get("/v1/content", headers=self.H()).json()[0]
        self.assertEqual((item["status"], r["violations"]), ("pending_approval", {}))
        self.assertEqual(item["hashtags"], ["Lagos", "iPhone15"])           # invalid hashtag dropped
        self.assertEqual(self.c.post(f"/v1/content/{item['id']}/approve", headers=self.H()).status_code, 200)
        self.assertEqual(self.c.post(f"/v1/content/{item['id']}/schedule", headers=self.H(), json={"when": "2026-12-01T10:00:00Z"}).status_code, 200)
        rt = self.c.app.state.runtimes.get("shop-a")
        self.assertEqual(rt.content.publish_due(lambda p: {}, now=__import__("datetime").datetime(2027, 1, 1, tzinfo=__import__("datetime").timezone.utc))["waiting_no_publisher"], 1)

    def test_risky_content_is_flagged_and_cannot_be_approved(self):
        r = self.plan("100% organic serum that clears acne in 7 days! NAFDAC approved. Pay https://paystack.com/pay/x only ₦500")
        iid = int(next(iter(r["violations"])))
        self.assertGreaterEqual(len(r["violations"][str(iid)]), 3)
        self.assertEqual(self.c.get("/v1/content", headers=self.H()).json()[0]["status"], "draft")
        self.assertEqual(self.c.post(f"/v1/content/{iid}/approve", headers=self.H()).status_code, 409)
        fixed = self.c.put(f"/v1/content/{iid}", headers=self.H(), json={"caption": "Fresh arrivals. DM us!"}).json()
        self.assertEqual(fixed["status"], "pending_approval")

    def test_image_generation_reports_missing_provider(self):
        self.plan("Fresh arrivals. DM us!")
        r = self.c.post("/v1/content/1/image", headers=self.H())
        self.assertEqual(r.status_code, 502)
        self.assertIn("no media model", r.json()["detail"].lower() + "no media model")

    # ---- landing page & public lead capture
    def test_landing_page_escapes_everything(self):
        r = self.c.post("/v1/landing", headers=self.H(), json={"whatsapp": "2348011112222", "tagline": "<script>alert(1)</script>",
                                                              "location": '"><img src=x onerror=alert(1)>'})
        self.assertEqual(r.status_code, 200)
        page = self.c.get("/sites/shop-a").text
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("₦800,000", page)

    def test_landing_rejects_bad_input(self):
        for bad in ({"whatsapp": "not-a-number"}, {"whatsapp": "2348011112222", "primary_color": "red; background:url(x)"},
                    {"whatsapp": "2348011112222", "logo_url": "javascript:alert(1)"}):
            self.assertEqual(self.c.post("/v1/landing", headers=self.H(), json=bad).status_code, 422, bad)

    def test_public_lead_form_honeypot_and_capture(self):
        ok = self.c.post("/public/shop-a/lead", content="name=Ada&phone=08011112222&sku=IP15&message=hi",
                         headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(ok.status_code, 200)
        leads = self.c.get("/v1/leads", headers=self.H()).json()
        self.assertEqual((leads[0]["customer_key"], leads[0]["source"], leads[0]["interest"]), ("whatsapp:2348011112222", "landing_page", "IP15"))
        self.c.post("/public/shop-a/lead", content="name=Bot&phone=08099999999&website=spam.com")
        self.assertEqual(len(self.c.get("/v1/leads", headers=self.H()).json()), 1)       # honeypot hit creates nothing
        self.assertEqual(self.c.post("/public/shop-a/lead", content="name=X&phone=12").status_code, 422)

    def test_public_lead_is_rate_limited(self):
        codes = [self.c.post("/public/shop-a/lead", content=f"name=A&phone=0801111{i:04d}").status_code for i in range(25)]
        self.assertIn(429, codes)

    # ---- erasure & analytics
    def test_erasure_removes_customer_but_keeps_opt_out(self):
        self.model.push({"reply": "The iPhone 15 is ₦800,000.", "actions": []})
        self.c.post("/v1/chat", headers=self.H(), json={"user_id": "gone", "text": "how much is the iphone 15?"})
        rt = self.c.app.state.runtimes.get("shop-a")
        rt.memory.opt_out("web:gone")
        self.assertEqual(self.c.delete("/v1/customers/web/gone", headers=self.H()).status_code, 200)
        self.assertEqual(self.c.get("/v1/leads", headers=self.H()).json(), [])
        self.assertTrue(rt.memory.is_opted_out("web:gone"))     # consent record survives erasure

    def test_funnel_and_campaign_comparison(self):
        f = self.c.get("/v1/analytics/funnel", headers=self.H()).json()
        self.assertEqual(f["total_leads"], 0)
        self.c.post("/v1/analytics/campaign-metrics", headers=self.H(), json={"campaign_id": "c1", "variant": "A", "clicks": 20, "conversions": 4})
        self.c.post("/v1/analytics/campaign-metrics", headers=self.H(), json={"campaign_id": "c1", "variant": "B", "clicks": 20, "conversions": 1})
        cmp = self.c.get("/v1/analytics/campaigns", headers=self.H()).json()[0]["comparison"]
        self.assertEqual(cmp["verdict"], "inconclusive")        # 20 clicks per arm is noise, even at 20% vs 5%
        self.assertIn("not enough volume", cmp["reason"])


if __name__ == "__main__":
    unittest.main()
