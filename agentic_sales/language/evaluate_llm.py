"""Compare rules vs LLM vs hybrid signal extraction on labelled files.

    python -m agentic_sales.language.evaluate_llm --model gemini-flash-lite-latest build-shots
    python -m agentic_sales.language.evaluate_llm --model gemini-flash-lite-latest dev
    python -m agentic_sales.language.evaluate_llm --model gemini-flash-lite-latest sealed   # acceptance: run sparingly

Few-shot examples are drawn ONLY from data/eval/customer_messages_holdout_dev.jsonl and are excluded
from every score. The sealed file is never printed, only scored.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from ..config.env import load_env
from ..models.gemini import GeminiText
from .analysis import extract_signals
from .llm_signals import SHOTS_PATH, SignalExtractor

EVAL = Path("data/eval")
FIVE = {"price_inquiry", "negotiation", "trust_concern", "payment_claim", "stalling"}
EIGHT = FIVE | {"ready_to_buy", "delivery_concern", "urgency"}


def gold_set(r: dict) -> set[str]:
    g = set(r.get("signals", []))
    if r.get("ready_to_buy"): g.add("ready_to_buy")
    if r.get("delivery_concern"): g.add("delivery_concern")
    if r.get("urgency") in ("high", "critical"): g.add("urgency")
    return g


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_shots(n: int) -> list[dict]:
    """Greedy cover: pick examples so every signal and register is represented, favouring multi-label ones."""
    rows = load(EVAL / "customer_messages_holdout_dev.jsonl")
    chosen, covered = [], defaultdict(int)
    pool = sorted(rows, key=lambda r: (-len(gold_set(r)), r["message"]))
    while len(chosen) < n and pool:
        best = max(pool, key=lambda r: (sum(1 / (1 + covered[s]) for s in gold_set(r) | {"reg:" + r["register"]}), -len(r["message"])))
        pool.remove(best)
        chosen.append(best)
        for s in gold_set(best) | {"reg:" + best["register"]}:
            covered[s] += 1
    return [{"message": r["message"], "register": r["register"], "signals": sorted(gold_set(r) - {"urgency"}),
             "urgency": r.get("urgency", "low")} for r in chosen]


def score(rows: list[dict], preds: list[set[str]], regs: list[str], labelled: set[str]) -> dict:
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for r, p in zip(rows, preds):
        g, p = gold_set(r) & labelled, p & labelled
        for s in p & g: tp[s] += 1
        for s in p - g: fp[s] += 1
        for s in g - p: fn[s] += 1
    per = {}
    for s in sorted(labelled):
        pr = tp[s] / (tp[s] + fp[s]) if tp[s] + fp[s] else 0.0
        rc = tp[s] / (tp[s] + fn[s]) if tp[s] + fn[s] else 0.0
        per[s] = (pr, rc, 2 * pr * rc / (pr + rc) if pr + rc else 0.0, tp[s] + fn[s])
    T, F, N = sum(tp.values()), sum(fp.values()), sum(fn.values())
    micro = 2 * T / max(2 * T + F + N, 1)
    acc = sum(a == r["register"] for a, r in zip(regs, rows)) / len(rows)
    return {"per": per, "micro_f1": micro, "register_acc": acc, "n": len(rows)}


def report(title: str, res: dict) -> None:
    print(f"  {title:14} n={res['n']:3} register={res['register_acc']:.0%} microF1={res['micro_f1']:.2f}  recall: " +
          " ".join(f"{s[:6]}={v[1]:.2f}" for s, v in res["per"].items() if v[3]))


def run(path: Path, extractor: SignalExtractor, labelled: set[str], exclude: set[str]) -> None:
    rows = [r for r in load(path) if r["message"] not in exclude]
    texts = [r["message"] for r in rows]
    llm = extractor.extract_many(texts, workers=3)
    fb = sum(e.source != "llm" for e in llm)
    errs = sorted({e.error for e in llm if e.error})
    rules = [{s.name for s in extract_signals(t)} for t in texts]
    llm_sets = [e.names for e in llm]
    print(f"{path.name} (fallbacks to rules: {fb} {errs if fb else ''})")
    from .analysis import detect_register
    rule_regs = [detect_register(t).primary.value for t in texts]
    report("rules", score(rows, rules, rule_regs, labelled))
    report("llm", score(rows, llm_sets, [e.register.value for e in llm], labelled))
    report("union", score(rows, [a | b for a, b in zip(rules, llm_sets)], [e.register.value for e in llm], labelled))
    detail = score(rows, llm_sets, [e.register.value for e in llm], labelled)["per"]
    print("  llm per-signal  " + "  ".join(f"{s}: P={v[0]:.2f} R={v[1]:.2f} (n={v[3]})" for s, v in detail.items() if v[3]))


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    ap.add_argument("--shots", type=int, default=20)
    ap.add_argument("cmd", choices=["build-shots", "dev", "sealed"])
    a = ap.parse_args()
    if a.cmd == "build-shots":
        shots = build_shots(a.shots)
        SHOTS_PATH.write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {len(shots)} few-shot examples -> {SHOTS_PATH}")
        return
    shots = json.loads(SHOTS_PATH.read_text(encoding="utf-8"))
    exclude = {s["message"] for s in shots}
    ex = SignalExtractor(GeminiText(a.model), shots, cache_dir=EVAL / "_llm_cache")
    if a.cmd == "dev":
        run(EVAL / "customer_messages_naija.jsonl", ex, FIVE, exclude)          # only 5 types labelled here
        run(EVAL / "customer_messages_holdout_dev.jsonl", ex, EIGHT, exclude)   # shots excluded
    else:
        run(EVAL / "sealed" / "customer_messages_sealed.jsonl", ex, EIGHT, exclude)


if __name__ == "__main__":
    main()
