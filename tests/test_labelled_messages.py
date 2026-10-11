import json
import unittest
from pathlib import Path

from agentic_sales.language.analysis import detect_register, extract_signals

NAIJA = Path("data/eval/customer_messages_naija.jsonl")
DEV2 = Path("data/eval/customer_messages_holdout_dev.jsonl")  # tuned on too; sealed half is never tested here
LABELLED = {"price_inquiry", "negotiation", "trust_concern", "payment_claim", "stalling"}


@unittest.skipUnless(NAIJA.exists(), "labelled set missing")
class NigerianLabelled(unittest.TestCase):
    """REGRESSION guard, not a generalisation measure: the rules were tuned while looking at these
    115 messages. Use a fresh held-out batch for an honest accuracy number."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(l) for f in (NAIJA, DEV2) if f.exists()
                    for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_register_floor(self):
        ok = sum(detect_register(r["message"]).primary.value == r["register"] for r in self.rows)
        self.assertGreater(ok / len(self.rows), 0.80)

    def test_formal_is_never_mistaken_for_informal(self):
        for r in self.rows:
            if r["register"] == "formal":
                self.assertEqual(detect_register(r["message"]).primary.value, "formal", r["message"])

    def test_signal_f1_floors(self):
        tp, fp, fn = {}, {}, {}
        for r in self.rows:
            got = {s.name for s in extract_signals(r["message"])} & LABELLED
            gold = set(r["signals"])
            for s in got & gold: tp[s] = tp.get(s, 0) + 1
            for s in got - gold: fp[s] = fp.get(s, 0) + 1
            for s in gold - got: fn[s] = fn.get(s, 0) + 1
        for s in LABELLED:
            f1 = 2 * tp.get(s, 0) / max(2 * tp.get(s, 0) + fp.get(s, 0) + fn.get(s, 0), 1)
            self.assertGreater(f1, 0.60, f"{s} f1={f1:.2f}")


if __name__ == "__main__":
    unittest.main()
