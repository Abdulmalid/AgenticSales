"""Handling of untrusted (customer-controlled) text.

Customer text is data, never instructions. We (1) normalise and bound it, (2) fence it so it
cannot forge prompt structure, and (3) flag injection attempts as a *risk signal* for the
fraud/escalation path. Flagging is heuristic; the real protection is that policy and tool
authorisation are enforced in code (see policy/ and tools/), not by the prompt.
"""
from __future__ import annotations

import re
import unicodedata

MAX_CUSTOMER_CHARS = 2000
_FENCE = "customer_message"

_INJECTION = [
    (re.compile(r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)", re.I),
     "override_instructions"),
    (re.compile(r"(you are now|act as|pretend (to be|you are)|from now on you)", re.I), "role_hijack"),
    (re.compile(r"(system prompt|developer message|your instructions|reveal.{0,20}(prompt|rules))", re.I),
     "prompt_extraction"),
    (re.compile(r"(set|make|change).{0,20}(price|discount).{0,20}(to|at)\s*(0|zero|free|₦?\s?1\b)", re.I),
     "price_manipulation"),
    (re.compile(r"((approved|authori[sz]ed) (by|from) (the )?(owner|manager|admin|ceo))"
                r"|((the )?(owner|manager|admin|ceo) (has |already )?(approved|authori[sz]ed|agreed))", re.I),
     "false_authority"),
    (re.compile(r"</?\s*(system|assistant|tool|customer_message)\b", re.I), "tag_forgery"),
]


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # drop control and zero-width/format chars (invisible-instruction smuggling), keep \n and \t
    text = "".join(ch for ch in text
                   if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs"))
    return text.strip()[:MAX_CUSTOMER_CHARS]


def injection_signals(text: str) -> list[str]:
    return sorted({label for rx, label in _INJECTION if rx.search(text)})


def fence(text: str) -> str:
    """Wrap customer text so it cannot close or forge the fence."""
    safe = re.sub(rf"<\s*/?\s*{_FENCE}\s*>", "[tag removed]", text, flags=re.I)
    return f"<{_FENCE}>\n{safe}\n</{_FENCE}>"
