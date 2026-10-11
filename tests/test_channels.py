import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agentic_sales.channels import adapters
from agentic_sales.channels.adapters import ADAPTERS, ChannelUnavailable
from agentic_sales.channels.dispatch import SecretStore, flush_outbox
from agentic_sales.core.types import Channel, TenantContext
from agentic_sales.memory.store import TenantMemory

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def sha256_header(secret: str, raw: bytes) -> dict:
    return {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


WA = {"entry": [{"changes": [{"value": {"messages": [
    {"from": "2348012345678", "id": "wamid.1", "timestamp": "1760000000", "type": "text", "text": {"body": "How much last price?"}},
    {"from": "2348012345678", "id": "wamid.2", "timestamp": "1760000001", "type": "image",
     "image": {"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "see alert"}}],
    "statuses": [{"id": "x", "status": "delivered"}]}}]}]}

IG = {"entry": [{"messaging": [
    {"sender": {"id": "IGSID1"}, "timestamp": 1760000000000, "message": {"mid": "m1", "text": "Is this available?"}},
    {"sender": {"id": "PAGE"}, "timestamp": 1760000001000, "message": {"mid": "m2", "text": "our reply", "is_echo": True}}]}]}

X = {"for_user_id": "ME", "direct_message_events": [
    {"type": "message_create", "id": "1", "created_timestamp": "1760000000000",
     "message_create": {"sender_id": "U1", "target": {"recipient_id": "ME"}, "message_data": {"text": "price abeg"}}},
    {"type": "message_create", "id": "2", "created_timestamp": "1760000001000",
     "message_create": {"sender_id": "ME", "target": {"recipient_id": "U1"}, "message_data": {"text": "my own message"}}}]}


class Meta(unittest.TestCase):
    secrets = {"app_secret": "s3cret", "verify_token": "tok"}

    def test_signature_required_and_exact(self):
        raw = json.dumps(WA).encode()
        wa = ADAPTERS["whatsapp"]
        self.assertTrue(wa.verify_post(sha256_header("s3cret", raw), raw, self.secrets))
        self.assertFalse(wa.verify_post(sha256_header("wrong", raw), raw, self.secrets))
        self.assertFalse(wa.verify_post(sha256_header("s3cret", raw), raw + b" ", self.secrets))   # tampered body
        self.assertFalse(wa.verify_post({}, raw, self.secrets))
        self.assertFalse(wa.verify_post(sha256_header("s3cret", raw), raw, {}))                    # no secret configured

    def test_handshake(self):
        wa = ADAPTERS["whatsapp"]
        self.assertEqual(wa.handshake({"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"}, self.secrets), (200, "42"))
        self.assertEqual(wa.handshake({"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "42"}, self.secrets)[0], 403)

    def test_whatsapp_normalisation(self):
        msgs = ADAPTERS["whatsapp"].parse(WA, self.secrets)
        self.assertEqual(len(msgs), 2)                       # statuses ignored
        self.assertEqual((msgs[0].channel, msgs[0].user_id, msgs[0].message_id), (Channel.WHATSAPP, "2348012345678", "wamid.1"))
        self.assertEqual(msgs[1].attachments[0].kind, "image")
        self.assertEqual(msgs[1].text, "see alert")

    def test_instagram_ignores_own_echoes(self):
        msgs = ADAPTERS["instagram"].parse(IG, self.secrets)
        self.assertEqual([(m.user_id, m.text) for m in msgs], [("IGSID1", "Is this available?")])
        self.assertEqual(msgs[0].channel, Channel.INSTAGRAM)

    def test_send_needs_credentials(self):
        with self.assertRaises(ChannelUnavailable):
            ADAPTERS["whatsapp"].send("234", "hi", {})


class XChannel(unittest.TestCase):
    secrets = {"consumer_secret": "cs"}

    def test_crc_response_matches_documented_scheme(self):
        status, body = ADAPTERS["x"].handshake({"crc_token": "abc"}, self.secrets)
        want = "sha256=" + base64.b64encode(hmac.new(b"cs", b"abc", hashlib.sha256).digest()).decode()
        self.assertEqual((status, json.loads(body)), (200, {"response_token": want}))

    def test_signature_and_self_messages_ignored(self):
        raw = json.dumps(X).encode()
        sig = "sha256=" + base64.b64encode(hmac.new(b"cs", raw, hashlib.sha256).digest()).decode()
        self.assertTrue(ADAPTERS["x"].verify_post({"x-twitter-webhooks-signature": sig}, raw, self.secrets))
        self.assertFalse(ADAPTERS["x"].verify_post({"x-twitter-webhooks-signature": sig}, raw + b"x", self.secrets))
        msgs = ADAPTERS["x"].parse(X, self.secrets)
        self.assertEqual([(m.user_id, m.text) for m in msgs], [("U1", "price abeg")])


class Email(unittest.TestCase):
    secrets = {"webhook_secret": "ws"}

    def test_parse_strips_quoted_reply_and_requires_signature(self):
        payload = {"from": "Ada <ada@example.com>", "subject": "Order enquiry", "message_id": "<1@x>",
                   "text": "Hello, price for 10 units?\n\nOn Mon, 5 Oct 2026, Shop wrote:\n> earlier text"}
        m = ADAPTERS["email"].parse(payload, self.secrets)[0]
        self.assertEqual(m.user_id, "ada@example.com")
        self.assertNotIn("earlier text", m.text)
        self.assertIn("price for 10 units", m.text)
        raw = json.dumps(payload).encode()
        good = {"x-webhook-signature": hmac.new(b"ws", raw, hashlib.sha256).hexdigest()}
        self.assertTrue(ADAPTERS["email"].verify_post(good, raw, self.secrets))
        self.assertFalse(ADAPTERS["email"].verify_post({"x-webhook-signature": "00"}, raw, self.secrets))

    def test_garbage_sender_rejected(self):
        self.assertEqual(ADAPTERS["email"].parse({"from": "not an email", "text": "hi"}, self.secrets), [])

    def test_smtp_send(self):
        cfg = {"smtp_host": "h", "smtp_port": 465, "username": "u", "password": "p", "from_addr": "shop@x.com"}
        with mock.patch.object(adapters.smtplib, "SMTP_SSL") as smtp:
            ADAPTERS["email"].send("ada@example.com", "hello", cfg)
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()


class TikTok(unittest.TestCase):
    def test_tiktok_fails_clearly_not_silently(self):
        self.assertFalse(ADAPTERS["tiktok"].verify_post({}, b"{}", {}))
        with self.assertRaises(ChannelUnavailable):
            ADAPTERS["tiktok"].send("u", "hi", {})


class Dispatch(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.ctx = TenantContext("shop-a")
        self.mem = TenantMemory(self.ctx, root)
        self.secrets = SecretStore(self.ctx, root)

    def seen_customer(self, ckey, at):
        self.mem.add_message("c", ckey, "user", "hi")
        self.mem.con.execute("UPDATE messages SET ts=? WHERE customer_key=?", (at.isoformat(), ckey))

    def test_outside_24h_window_is_parked_not_sent(self):
        self.seen_customer("whatsapp:234", NOW - timedelta(hours=30))
        oid = self.mem.enqueue_message("whatsapp:234", "follow up", "retention_campaign")
        with mock.patch.object(ADAPTERS["whatsapp"], "send") as send:
            rep = flush_outbox(self.mem, self.secrets, NOW)
        send.assert_not_called()
        self.assertEqual(rep.needs_template, 1)
        self.assertEqual(self.mem.con.execute("SELECT status FROM outbox WHERE id=?", (oid,)).fetchone()[0], "needs_template")

    def test_inside_window_sends_and_marks_sent(self):
        self.seen_customer("whatsapp:234", NOW - timedelta(hours=2))
        self.mem.enqueue_message("whatsapp:234", "your order", "purchase_confirmation")
        with mock.patch.object(ADAPTERS["whatsapp"], "send") as send:
            rep = flush_outbox(self.mem, self.secrets, NOW)
        send.assert_called_once_with("234", "your order", {})
        self.assertEqual(rep.sent, 1)

    def test_opt_out_blocks_send(self):
        self.seen_customer("email:a@x.com", NOW)
        self.mem.opt_out("email:a@x.com")
        self.mem.enqueue_message("email:a@x.com", "promo", "retention_campaign")
        with mock.patch.object(ADAPTERS["email"], "send") as send:
            rep = flush_outbox(self.mem, self.secrets, NOW)
        send.assert_not_called()
        self.assertEqual(rep.skipped_opt_out, 1)

    def test_missing_credentials_keeps_message_queued(self):
        self.mem.enqueue_message("email:a@x.com", "hello", "recovery")
        rep = flush_outbox(self.mem, self.secrets, NOW)
        self.assertEqual(rep.unavailable, 1)
        self.assertEqual(len(self.mem.pending_outbox()), 1)

    def test_secret_store_is_per_tenant(self):
        root = self.secrets.path.parents[2]
        self.secrets.set("whatsapp", {"app_secret": "A"})
        other = SecretStore(TenantContext("shop-b"), root)
        self.assertEqual(other.get("whatsapp"), {})


if __name__ == "__main__":
    unittest.main()
