import unittest
from pathlib import Path

from agentic_sales.corpus.families import BY_FILENAME, DOMAINS, NG_CONVERSATION
from agentic_sales.corpus.repair import repair_keys, repair_layer
from agentic_sales.corpus.store import CorpusStore

INDEX, RAW = Path("data/index/corpus.db"), Path("data/corpora/raw")


class Repair(unittest.TestCase):
    def test_systematic_conversation_key_typo_repaired(self):
        fam = BY_FILENAME["master_nigerian_conversation_corpus.jsonl"]
        fixed, extras = repair_keys({"title": "t", "aauthentic_conversation_sample": [1], "junk_key": 1}, fam)
        self.assertIn("authentic_conversation_sample", fixed)
        self.assertIn("junk_key", extras)

    def test_layer_repaired_by_code_prefix(self):
        vocab = ["NE06_BUREAUCRATIC_LEGAL_REGISTER", "NE01_LEXICAL_INNOVATIONS_NEOLOGISMS"]
        self.assertEqual(repair_layer("NE06_BUREAUCR_LEGAL_REGISTER", vocab), vocab[0])
        self.assertIsNone(repair_layer("ZZ99_UNKNOWN", vocab))

    def test_new_domain_registered(self):
        self.assertIn(NG_CONVERSATION, DOMAINS)


@unittest.skipUnless(INDEX.exists(), "build the index first")
class Retrieval(unittest.TestCase):
    def setUp(self):
        self.store = CorpusStore(INDEX, RAW)
        self.addCleanup(self.store.close)

    def test_bargaining_layer_returns_bargaining_pragmatics(self):
        hits = self.store.search(NG_CONVERSATION, "last price abeg reduce", limit=3, layer_prefix="NC07")
        self.assertTrue(hits)
        self.assertTrue(all(h.layer.startswith("NC07") for h in hits))
        self.assertIn("phrase_training_block", hits[0].record)  # typo-repaired family still loads raw record

    def test_domains_are_separated(self):
        for d in DOMAINS:
            for h in self.store.search(d, "price", limit=3):
                self.assertEqual(h.domain, d)


if __name__ == "__main__":
    unittest.main()
