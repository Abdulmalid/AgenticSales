"""Score the register and signal detectors on a labelled JSONL file.

    python -m agentic_sales.language.evaluate customer_messages.jsonl

Each line needs `message`. Optional labels (evaluated only where present):
  "register": "formal" | "casual" | "pidgin" | "social"
  "signals":  ["price_inquiry", "negotiation", ...]   (names from language/analysis.py `_SIGNALS`;
                                                       use [] to assert none apply)
  "ready_to_buy": bool, "delivery_concern": bool      (scored against the signal of the same name)
  "urgency": "low"|"medium"|"high"|"critical"         (high/critical = urgent, scored vs `urgency`)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .analysis import detect_register, extract_signals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    rows = [json.loads(l) for l in ap.parse_args().path.read_text(encoding="utf-8").splitlines() if l.strip()]

    reg_rows = [r for r in rows if r.get("register")]
    print(f"{len(rows)} messages, {len(reg_rows)} with register labels")
    if reg_rows:
        conf, ok = Counter(), 0
        for r in reg_rows:
            p = detect_register(r["message"]).primary.value
            conf[(r["register"], p)] += 1
            ok += p == r["register"]
        print(f"register accuracy: {ok / len(reg_rows):.1%}")
        for (gold, pred), n in sorted(conf.items()):
            print(f"  gold={gold:7} pred={pred:7} {n}")
    else:
        print("register distribution (unlabelled):",
              dict(Counter(detect_register(r["message"]).primary.value for r in rows)))

    for r in rows:  # normalise the extra label styles into the `signals` list's vocabulary
        extra = set()
        if r.get("ready_to_buy"): extra.add("ready_to_buy")
        if r.get("delivery_concern"): extra.add("delivery_concern")
        if r.get("urgency") in ("high", "critical"): extra.add("urgency")
        if "signals" in r or any(k in r for k in ("ready_to_buy", "delivery_concern", "urgency")):
            r["signals"] = sorted(set(r.get("signals", [])) | extra)
    sig_rows = [r for r in rows if "signals" in r]
    print(f"{len(sig_rows)} with signal labels")
    if sig_rows:
        tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
        for r in sig_rows:
            got = {s.name for s in extract_signals(r["message"])}
            gold = set(r["signals"])
            for s in got & gold: tp[s] += 1
            for s in got - gold: fp[s] += 1
            for s in gold - got: fn[s] += 1
        print(f"  {'signal':24} prec   recall  (tp/fp/fn)")
        for s in sorted(set(tp) | set(fp) | set(fn)):
            p = tp[s] / (tp[s] + fp[s]) if tp[s] + fp[s] else float("nan")
            r_ = tp[s] / (tp[s] + fn[s]) if tp[s] + fn[s] else float("nan")
            print(f"  {s:24} {p:5.2f}  {r_:5.2f}   ({tp[s]}/{fp[s]}/{fn[s]})")


if __name__ == "__main__":
    main()
