import unittest
from pathlib import Path

from agentic_sales.language.analysis import Register, Slang, detect_register, extract_signals, plan_style
from agentic_sales.language.train import MODEL_PATH, is_test, load_labelled

RAW = Path("data/corpora/raw")


@unittest.skipUnless(MODEL_PATH.exists() and (RAW / "master_agent_guardrails_corpus.jsonl").exists(),
                     "needs trained model + raw corpus")
class RegisterModel(unittest.TestCase):
    def test_heldout_accuracy_floor(self):
        """Guards against regressions. Labels are synthetic: this is agreement with the corpus, not
        real-world accuracy."""
        test = [(t, l) for rid, t, l in load_labelled(RAW) if is_test(rid, t)]
        ok = sum({"social": "casual"}.get(detect_register(t).primary.value, detect_register(t).primary.value) == l
                 for t, l in test)
        self.assertGreater(ok / len(test), 0.72)

    def test_english_dont_is_not_pidgin(self):
        r = detect_register("I don't know, I don't think so")
        self.assertEqual(r.evidence["pidgin"], [])

    def test_confidence_is_calibrated_not_saturated(self):
        self.assertLess(detect_register("I don't want to send money and nothing come").confidence, 0.9)

    def test_style_mirrors_informal_but_not_formal(self):
        for text, slang in [("Good afternoon, sir. I would like to confirm if the product is still available.", Slang.NONE),
                            ("Boss, is this thing still available?", Slang.LIGHT)]:
            self.assertEqual(plan_style(detect_register(text), extract_signals(text)).slang, slang, text)


if __name__ == "__main__":
    unittest.main()
