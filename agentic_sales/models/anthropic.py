"""Anthropic Messages API provider (stdlib only, no SDK dependency)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import ModelError, ModelRequest, ModelResponse

API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicText:
    def __init__(self, model: str, api_key: str | None = None, timeout: float = 60.0):
        self.name = model
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._key:
            raise ModelError("ANTHROPIC_API_KEY is not set")
        self._timeout = timeout

    def complete(self, req: ModelRequest) -> ModelResponse:
        body = {
            "model": self.name,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "system": req.system,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        headers = {"content-type": "application/json", "x-api-key": self._key,
                   "anthropic-version": "2023-06-01"}
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")  # required for keys not scoped to a workspace
        if workspace:
            headers["anthropic-workspace-id"] = workspace
        http = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(http, timeout=self._timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            # never echo the request (contains customer data) or the key
            detail = ""
            try:
                detail = json.load(e).get("error", {}).get("message", "")[:160]
            except Exception:
                pass
            raise ModelError(f"Anthropic API error {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(f"Anthropic API unreachable: {type(e).__name__}") from None
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return ModelResponse(text, data.get("model", self.name),
                             usage.get("input_tokens", 0), usage.get("output_tokens", 0))
