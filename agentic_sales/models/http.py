"""Shared HTTP helper for model providers: JSON POST with bounded retries, key-safe errors."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .base import ModelError

_RETRY = {408, 429, 500, 502, 503, 504}


def post_json(url: str, headers: dict[str, str], body: dict[str, Any], *, timeout: float = 60.0,
              retries: int = 4, provider: str = "provider") -> dict[str, Any]:
    data = json.dumps(body).encode()
    last = "unknown error"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            detail = ""
            try:
                detail = json.load(e).get("error", {}).get("message", "")[:200]
            except Exception:
                pass
            if e.code not in _RETRY:
                raise ModelError(f"{provider} {last}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = type(e).__name__
        time.sleep(min(2 ** (attempt + 1), 20))
    # never echo the request (customer data) or headers (API key)
    raise ModelError(f"{provider} failed after {retries + 1} attempts ({last})")
