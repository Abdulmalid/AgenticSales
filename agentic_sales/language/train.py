"""Train the register classifier from the corpora.

    python -m agentic_sales.language.train [--raw data/corpora/raw]

Training data: customer-side messages from the guardrails corpus, labelled by the corpus' own
`customer_profile.language_blend` (formal | casual | pidgin). Mixed/ambiguous blends are excluded
from training rather than guessed. Labels are synthetic (LLM-generated), so reported accuracy
measures agreement with the corpus' labels, not real-world accuracy: validate on real chats
before trusting it for decisions. Split is deterministic by report_id hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

MODEL_PATH = Path(__file__).with_name("register_nb.json")
CLASSES = ("formal", "casual", "pidgin")
_TOK = re.compile(r"[a-zA-Z₦']+|\d+[kKmM]\b")


def features(text: str) -> list[str]:
    toks = [t.lower() for t in _TOK.findall(text)]
    feats = list(toks)
    feats += [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    return feats


def label_from_blend(blend: str | None) -> str | None:
    """Map the corpus' free-text language_blend to a class; None = mixed/ambiguous (excluded)."""
    if not isinstance(blend, str):
        return None
    b = blend.lower().replace("pidgin english", "pidgin")
    pidgin, english = "pidgin" in b, "english" in b
    if pidgin:
        return "pidgin" if not english else None
    if "slang" in b:
        return "casual"
    if any(w in b for w in ("formal", "corporate", "professional", "standard", "business")):
        return "formal"
    return None


def load_labelled(raw: Path) -> list[tuple[str, str, str]]:
    """(report_id, text, label)"""
    rows = []
    with (raw / "master_agent_guardrails_corpus.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            cp, text = d.get("customer_profile"), d.get("authentic_customer_inbound")
            if not isinstance(cp, dict) or not isinstance(text, str):
                continue
            lab = label_from_blend(cp.get("language_blend"))
            if lab:
                rows.append((str(d.get("report_id")), text, lab))
    return rows


def is_test(report_id: str, text: str) -> bool:
    return int(hashlib.md5(f"{report_id}|{text}".encode()).hexdigest(), 16) % 5 == 0


def fit(rows: list[tuple[str, str]], min_count: int = 3) -> dict:
    counts = {c: Counter() for c in CLASSES}
    docs = Counter()
    for text, lab in rows:
        docs[lab] += 1
        counts[lab].update(set(features(text)))
    total = Counter()
    for c in CLASSES:
        total.update(counts[c])
    vocab = sorted(f for f, n in total.items() if n >= min_count)
    return {
        "classes": list(CLASSES),
        "prior": {c: math.log(docs[c] / sum(docs.values())) for c in CLASSES},
        "vocab": {f: {c: round(math.log((counts[c][f] + 0.5) / (docs[c] + 1.0)), 4) for c in CLASSES}
                  for f in vocab},
        "absent": {c: round(math.log(0.5 / (docs[c] + 1.0)), 4) for c in CLASSES},
        "n_train": dict(docs),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/corpora/raw", type=Path)
    a = ap.parse_args()
    rows = load_labelled(a.raw)
    train = [(t, l) for rid, t, l in rows if not is_test(rid, t)]
    model = fit(train)
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"trained on {len(train)} ({model['n_train']}), vocab {len(model['vocab'])} -> {MODEL_PATH}")


if __name__ == "__main__":
    main()
