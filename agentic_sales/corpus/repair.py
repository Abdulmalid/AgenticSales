"""Repair and normalise raw corpus records.

The raw files were produced by an LLM and contain corrupted keys (e.g.
``vulentrable_bot_anti_pattern``), corrupted layer labels
(``AG03_BOOKOSNG_CALENDAR_INSPECTIONS``), duplicate report_ids and records with
missing fields. We repair what can be repaired deterministically, and drop what
cannot, rather than silently searching over broken data.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable

from .families import Family

_CUTOFF = 0.82


def repair_keys(record: dict[str, Any], family: Family) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (canonical_record, extras). Unknown keys go to extras, never into canonical."""
    canon = set(family.canonical_keys)
    out: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in record.items():
        k = key.strip(" ,")
        target = k if k in canon else family.aliases.get(k)
        if target is None:
            match = difflib.get_close_matches(k, family.canonical_keys, n=1, cutoff=_CUTOFF)
            target = match[0] if match else None
        if target and "." in target:  # alias into a nested field, e.g. customer_profile.tone
            parent, child = target.split(".", 1)
            out.setdefault(parent, {})
            if isinstance(out[parent], dict):
                out[parent].setdefault(child, value)
            continue
        if target and target not in out:
            out[target] = value
        else:
            extras[key] = value
    return out, extras


def build_layer_vocabulary(layers: Iterable[str | None]) -> list[str]:
    """Canonical layers = those seen at least 50 times (typos appear a handful of times)."""
    counts = Counter(l for l in layers if l)
    return [l for l, c in counts.items() if c >= 50]


def repair_layer(layer: str | None, vocab: list[str]) -> str | None:
    if not layer:
        return None
    if layer in vocab:
        return layer
    # normalise case first (L3_Nurture_Systems), then fuzzy match
    for v in vocab:
        if v.lower() == layer.lower():
            return v
    # layer ids start with a stable code (NE06_, AG03_, L7_): trust it when it is unambiguous
    code = re.match(r"^[A-Za-z]+\d+_", layer)
    if code:
        same = [v for v in vocab if v.upper().startswith(code.group(0).upper())]
        if len(same) == 1:
            return same[0]
    match = difflib.get_close_matches(layer, vocab, n=1, cutoff=0.85)
    return match[0] if match else None


def flatten_text(value: Any) -> str:
    """Flatten arbitrarily nested JSON values to searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(t for t in (flatten_text(v) for v in value.values()) if t)
    if isinstance(value, (list, tuple)):
        return " ".join(t for t in (flatten_text(v) for v in value) if t)
    return str(value)


def content_hash(title: str, body: str) -> str:
    return hashlib.sha1(f"{title}\x00{body}".encode("utf-8")).hexdigest()


def dump(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))
