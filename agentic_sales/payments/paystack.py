"""Paystack integration (verify + initialize), written against Paystack's documented REST API.

NOT yet exercised against the live API (no Paystack key available). The request/response shapes
follow the public docs; unit tests use a fake transport. Before go-live, run one test-mode
transaction end to end.

Security properties:
  * Amounts are computed by the server (price x quantity from business config / policy-approved
    price); the model never supplies an amount.
  * Verification compares the *gateway-reported* amount and currency with what we expected.
  * Webhook bodies are authenticated with HMAC-SHA512 over the raw body using the secret key
    (`x-paystack-signature`).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

API = "https://api.paystack.co"


class PaymentError(RuntimeError):
    pass


class NotConfigured(PaymentError):
    pass


@dataclass(frozen=True)
class PaymentStatus:
    reference: str
    gateway_status: str          # success | failed | abandoned | pending | ...
    amount_kobo: int
    currency: str
    customer_email: str | None

    @property
    def paid(self) -> bool:
        return self.gateway_status == "success"


@dataclass(frozen=True)
class PaymentLink:
    reference: str
    url: str
    amount_kobo: int


class PaymentGateway(Protocol):
    def verify(self, reference: str) -> PaymentStatus: ...
    def create_link(self, *, amount_kobo: int, email: str, reference: str, metadata: dict) -> PaymentLink: ...


Transport = Callable[[str, str, dict | None], dict]   # (method, path, json_body) -> parsed json


def _http(secret: str) -> Transport:
    def call(method: str, path: str, body: dict | None) -> dict:
        req = urllib.request.Request(API + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise PaymentError(f"Paystack HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise PaymentError(f"Paystack unreachable: {type(e).__name__}") from None
    return call


class Paystack:
    def __init__(self, secret_key: str | None, transport: Transport | None = None):
        if not secret_key and transport is None:
            raise NotConfigured("Paystack secret key not configured")
        self._call = transport or _http(secret_key)  # type: ignore[arg-type]

    def verify(self, reference: str) -> PaymentStatus:
        if not reference or not all(c.isalnum() or c in "-_." for c in reference) or len(reference) > 100:
            raise PaymentError("invalid payment reference")
        res = self._call("GET", f"/transaction/verify/{reference}", None)
        d = res.get("data") or {}
        if not res.get("status") or "amount" not in d:
            return PaymentStatus(reference, "not_found", 0, "NGN", None)
        return PaymentStatus(reference, str(d.get("status")), int(d["amount"]), str(d.get("currency", "NGN")),
                             (d.get("customer") or {}).get("email"))

    def create_link(self, *, amount_kobo: int, email: str, reference: str, metadata: dict) -> PaymentLink:
        res = self._call("POST", "/transaction/initialize",
                         {"amount": amount_kobo, "email": email, "reference": reference, "currency": "NGN",
                          "metadata": metadata})
        d = res.get("data") or {}
        if not res.get("status") or not d.get("authorization_url"):
            raise PaymentError("Paystack did not return a payment link")
        return PaymentLink(d.get("reference", reference), d["authorization_url"], amount_kobo)


def verify_webhook_signature(secret_key: str, raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
