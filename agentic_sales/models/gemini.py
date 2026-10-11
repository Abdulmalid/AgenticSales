"""Google Gemini providers: text (generateContent) and image generation."""
from __future__ import annotations

import base64
import os

from .base import ModelError, ModelRequest, ModelResponse
from .http import post_json

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _key(explicit: str | None) -> str:
    key = explicit or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ModelError("GEMINI_API_KEY is not set")
    return key


class GeminiText:
    def __init__(self, model: str = "gemini-flash-lite-latest", api_key: str | None = None,
                 timeout: float = 60.0):
        self.name = model
        self._key = _key(api_key)
        self._timeout = timeout

    def complete(self, req: ModelRequest) -> ModelResponse:
        contents = [{"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]}
                    for m in req.messages]
        cfg: dict = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
        if req.json_mode:
            cfg["responseMimeType"] = "application/json"
        body = {"contents": contents, "generationConfig": cfg}
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        data = post_json(f"{BASE}/{self.name}:generateContent", {"X-goog-api-key": self._key}, body,
                         timeout=self._timeout, provider="Gemini")
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ModelError(f"Gemini returned no output ({reason})")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata", {})
        return ModelResponse(text, self.name, usage.get("promptTokenCount", 0),
                             usage.get("candidatesTokenCount", 0))


class GeminiImage:
    """MediaModel: text -> PNG/JPEG bytes."""

    def __init__(self, model: str = "gemini-2.5-flash-image", api_key: str | None = None,
                 timeout: float = 120.0):
        self.name = model
        self._key = _key(api_key)
        self._timeout = timeout

    def generate(self, prompt: str, **options: object) -> bytes:
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
        data = post_json(f"{BASE}/{self.name}:generateContent", {"X-goog-api-key": self._key}, body,
                         timeout=self._timeout, provider="Gemini image")
        for cand in data.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise ModelError("Gemini image: no image in response (prompt may have been blocked)")
