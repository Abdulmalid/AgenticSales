"""Channel adapters: normalise inbound platform events into `InboundMessage`, authenticate webhooks,
and send outbound text.

STATUS (important): these follow the platforms' public documentation (Meta Graph API webhooks and
Send APIs, X Account Activity API, generic signed email webhook). They have NOT been run against the
live platforms: that needs app credentials/approval. Unit tests use fixtures written from the docs
and check signature maths and normalisation only. Expect small payload differences on first live run.

Security: every POST must pass `verify_post` (HMAC over the raw body with a per-tenant secret, compared
in constant time) before the body is parsed. Secrets come from the tenant secrets store, never from
the request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import smtplib
import urllib.parse
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Protocol

from ..core.types import Attachment, Channel, InboundMessage
from ..models.http import post_json
from ..models.base import ModelError

GRAPH = "https://graph.facebook.com/v21.0"


class ChannelError(RuntimeError):
    pass


class ChannelUnavailable(ChannelError):
    """The platform offers no API for this operation to businesses."""


class ChannelAdapter(Protocol):
    channel: Channel
    requires_window: bool     # platform restricts proactive messages outside a reply window (24h)

    def handshake(self, query: dict[str, str], secrets: dict) -> tuple[int, str]: ...
    def verify_post(self, headers: dict[str, str], raw: bytes, secrets: dict) -> bool: ...
    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]: ...
    def send(self, to: str, text: str, secrets: dict) -> None: ...


def _hmac_hex(secret: str, raw: bytes, algo=hashlib.sha256) -> str:
    return hmac.new(secret.encode(), raw, algo).hexdigest()


def _ts(value: Any) -> datetime:
    try:
        v = float(value)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _meta_verify(headers: dict[str, str], raw: bytes, secrets: dict) -> bool:
    secret, sig = secrets.get("app_secret"), headers.get("x-hub-signature-256", "")
    if not secret or not sig.startswith("sha256="):
        return False
    return hmac.compare_digest(sig[7:], _hmac_hex(secret, raw))


def _meta_handshake(query: dict[str, str], secrets: dict) -> tuple[int, str]:
    tok = secrets.get("verify_token")
    if tok and query.get("hub.mode") == "subscribe" and hmac.compare_digest(query.get("hub.verify_token", ""), tok):
        return 200, query.get("hub.challenge", "")
    return 403, "forbidden"


# ---------------------------------------------------------------------------------------- WhatsApp
class WhatsAppCloud:
    channel, requires_window = Channel.WHATSAPP, True
    handshake = staticmethod(_meta_handshake)
    verify_post = staticmethod(_meta_verify)

    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]:
        out = []
        for entry in payload.get("entry", []):
            for ch in entry.get("changes", []):
                v = ch.get("value", {})
                for m in v.get("messages", []):
                    kind = m.get("type", "text")
                    text = (m.get("text") or {}).get("body", "")
                    atts: tuple[Attachment, ...] = ()
                    if kind in ("image", "audio", "video", "document", "sticker"):
                        media = m.get(kind) or {}
                        text = text or media.get("caption", "")
                        atts = (Attachment(kind, f"whatsapp-media:{media.get('id', '')}", media.get("mime_type")),)
                    elif kind == "button":
                        text = (m.get("button") or {}).get("text", "")
                    elif kind == "interactive":
                        ir = m.get("interactive") or {}
                        text = ((ir.get("button_reply") or ir.get("list_reply") or {}).get("title", ""))
                    if not text and not atts:
                        continue
                    out.append(InboundMessage(Channel.WHATSAPP, str(m["from"]), str(m["from"]), text,
                                              _ts(m.get("timestamp")), atts, m.get("id")))
        return out

    def send(self, to: str, text: str, secrets: dict) -> None:
        if not (secrets.get("access_token") and secrets.get("phone_number_id")):
            raise ChannelUnavailable("WhatsApp access_token/phone_number_id not configured")
        try:
            post_json(f"{GRAPH}/{secrets['phone_number_id']}/messages", {"Authorization": f"Bearer {secrets['access_token']}"},
                      {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000]}},
                      provider="WhatsApp")
        except ModelError as e:
            raise ChannelError(str(e)) from None


# ------------------------------------------------------------------------- Instagram / Messenger
class _MetaMessaging:
    requires_window = True
    handshake = staticmethod(_meta_handshake)
    verify_post = staticmethod(_meta_verify)
    channel: Channel

    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]:
        out = []
        for entry in payload.get("entry", []):
            for ev in entry.get("messaging", []):
                m = ev.get("message")
                if not m or m.get("is_echo"):
                    continue  # our own outbound echoes must never be treated as customer input
                sender = str((ev.get("sender") or {}).get("id", ""))
                if not sender:
                    continue
                atts = tuple(Attachment(a.get("type", "file"), (a.get("payload") or {}).get("url", ""))
                             for a in m.get("attachments", []))
                if not m.get("text") and not atts:
                    continue
                out.append(InboundMessage(self.channel, sender, sender, m.get("text", ""), _ts(ev.get("timestamp")),
                                          atts, m.get("mid")))
        return out

    def send(self, to: str, text: str, secrets: dict) -> None:
        token = secrets.get("access_token")
        if not token:
            raise ChannelUnavailable(f"{self.channel.value} access_token not configured")
        node = secrets.get("page_id") or "me"
        try:
            post_json(f"{GRAPH}/{node}/messages", {"Authorization": f"Bearer {token}"},
                      {"recipient": {"id": to}, "messaging_type": "RESPONSE", "message": {"text": text[:1000]}},
                      provider=self.channel.value)
        except ModelError as e:
            raise ChannelError(str(e)) from None


class InstagramDM(_MetaMessaging):
    channel = Channel.INSTAGRAM


class FacebookMessenger(_MetaMessaging):
    channel = Channel.FACEBOOK


# ------------------------------------------------------------------------------------------- X
class XDirectMessages:
    channel, requires_window = Channel.X, False

    @staticmethod
    def _sig(secret: str, data: bytes) -> str:
        return "sha256=" + base64.b64encode(hmac.new(secret.encode(), data, hashlib.sha256).digest()).decode()

    def handshake(self, query: dict[str, str], secrets: dict) -> tuple[int, str]:
        crc, secret = query.get("crc_token"), secrets.get("consumer_secret")
        if not crc or not secret:
            return 400, "bad request"
        return 200, json.dumps({"response_token": self._sig(secret, crc.encode())})

    def verify_post(self, headers: dict[str, str], raw: bytes, secrets: dict) -> bool:
        secret, sig = secrets.get("consumer_secret"), headers.get("x-twitter-webhooks-signature", "")
        return bool(secret and sig) and hmac.compare_digest(sig, self._sig(secret, raw))

    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]:
        me = str(payload.get("for_user_id", ""))
        out = []
        for ev in payload.get("direct_message_events", []):
            if ev.get("type") != "message_create":
                continue
            mc = ev.get("message_create", {})
            sender = str(mc.get("sender_id", ""))
            if not sender or sender == me:
                continue
            text = (mc.get("message_data") or {}).get("text", "")
            if text:
                out.append(InboundMessage(Channel.X, sender, sender, text, _ts(ev.get("created_timestamp")),
                                          message_id=str(ev.get("id"))))
        return out

    def send(self, to: str, text: str, secrets: dict) -> None:
        token = secrets.get("user_access_token")
        if not token:
            raise ChannelUnavailable("X user_access_token not configured")
        try:
            post_json(f"https://api.twitter.com/2/dm_conversations/with/{urllib.parse.quote(to)}/messages",
                      {"Authorization": f"Bearer {token}"}, {"text": text[:10000]}, provider="X")
        except ModelError as e:
            raise ChannelError(str(e)) from None


# ---------------------------------------------------------------------------------------- Email
_QUOTE = re.compile(r"^(>|On .{5,80} wrote:|-{2,}\s*Original Message)", re.I | re.M)


class EmailChannel:
    """Inbound: any provider's inbound-parse webhook relayed as JSON and signed with a shared secret
    (header `x-webhook-signature` = hex HMAC-SHA256 of the raw body). Outbound: SMTP over SSL."""
    channel, requires_window = Channel.EMAIL, False

    def handshake(self, query: dict[str, str], secrets: dict) -> tuple[int, str]:
        return 200, "ok"

    def verify_post(self, headers: dict[str, str], raw: bytes, secrets: dict) -> bool:
        secret, sig = secrets.get("webhook_secret"), headers.get("x-webhook-signature", "")
        return bool(secret and sig) and hmac.compare_digest(sig, _hmac_hex(secret, raw))

    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]:
        sender = str(payload.get("from", "")).strip().lower()
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender)
        if not m:
            return []
        body = str(payload.get("text", ""))
        q = _QUOTE.search(body)
        body = (body[:q.start()] if q else body).strip()
        subject = str(payload.get("subject", "")).strip()
        text = f"{subject}\n{body}".strip() if subject and not subject.lower().startswith("re:") else body
        if not text:
            return []
        addr = m.group(0)
        return [InboundMessage(Channel.EMAIL, addr, str(payload.get("thread_id") or addr), text,
                               _ts(payload.get("timestamp")), message_id=payload.get("message_id"))]

    def send(self, to: str, text: str, secrets: dict) -> None:
        need = ("smtp_host", "smtp_port", "username", "password", "from_addr")
        if any(not secrets.get(k) for k in need):
            raise ChannelUnavailable("email SMTP settings not configured")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = secrets["from_addr"], to, secrets.get("subject", "Re: your enquiry")
        msg.set_content(text)
        try:
            with smtplib.SMTP_SSL(secrets["smtp_host"], int(secrets["smtp_port"]), timeout=30) as s:
                s.login(secrets["username"], secrets["password"])
                s.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise ChannelError(f"SMTP failed: {type(e).__name__}") from None


# ---------------------------------------------------------------------------------------- TikTok
class TikTokUnavailable:
    """TikTok does not offer businesses a public API for reading/answering DMs. TikTok support in this
    platform is publishing/analytics (SMM, Phase 5/6) via the Content Posting API, which needs approved
    developer access. This adapter exists so the channel is registered and fails clearly."""
    channel, requires_window = Channel.TIKTOK, False

    def handshake(self, query: dict[str, str], secrets: dict) -> tuple[int, str]:
        return 404, "TikTok DM webhooks are not supported"

    def verify_post(self, headers: dict[str, str], raw: bytes, secrets: dict) -> bool:
        return False

    def parse(self, payload: dict, secrets: dict) -> list[InboundMessage]:
        return []

    def send(self, to: str, text: str, secrets: dict) -> None:
        raise ChannelUnavailable("TikTok has no public DM sending API for businesses")


ADAPTERS: dict[str, ChannelAdapter] = {
    "whatsapp": WhatsAppCloud(), "instagram": InstagramDM(), "facebook": FacebookMessenger(),
    "x": XDirectMessages(), "email": EmailChannel(), "tiktok": TikTokUnavailable(),
}
