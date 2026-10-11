import dataclasses
import unittest
from pathlib import Path

from agentic_sales.corpus import facets
from agentic_sales.corpus.families import DOMAINS, SMM
from agentic_sales.corpus.smm import SmmGuidance, compute_cautions, smm_guidance
from agentic_sales.corpus.store import CorpusStore

INDEX, RAW = Path("data/index/corpus.db"), Path("data/corpora/raw")


class Facets(unittest.TestCase):
    def test_objective_variants_collapse(self):
        for raw, want in [("Sales Conversion", "conversion"), ("conversions", "conversion"),
                          ("lead_generation", "lead_generation"), ("Lead Generation", "lead_generation"),
                          ("Brand Awareness", "awareness"), ("Consideration", "consideration"),
                          ("Brand Authority", "trust_building"), ("Objection Handling", "conversion"),
                          ("gibberish", "other"), (None, "other")]:
            self.assertEqual(facets.objective(raw), want, raw)

    def test_industry_variants_collapse(self):
        self.assertEqual(facets.industry("Beauty & Skincare"), "beauty")
        self.assertEqual(facets.industry("e_commerce"), facets.industry("E-Commerce"))
        self.assertEqual(facets.industry("FMCG"), "retail")
        self.assertEqual(facets.industry("Fintech"), "fintech")  # not swallowed by 'tech' -> electronics
        multi = facets.industries(["E-commerce", "Fashion & Apparel", "Fashion"])
        self.assertEqual(multi, "|ecommerce|fashion|")

    def test_surface_per_platform(self):
        self.assertEqual(facets.surface("meta", "META|WHATSAPP|Retail|Conv|x|y"), "whatsapp")
        self.assertEqual(facets.surface("meta", "META|Instagram Reels|Retail"), "instagram_reels")
        self.assertEqual(facets.surface("meta", "META|Facebook Marketplace|Retail"), "facebook_marketplace")
        self.assertEqual(facets.surface("tiktok", "TIKTOK|Short-Form Video|ecommerce"), "short_form")
        self.assertEqual(facets.surface("tiktok", "TIKTOK|LIVE_SELLING|ecommerce"), "live_selling")

    def test_region_collapses_neighbourhoods_to_city(self):
        for raw, want in [("Lagos Mainland", "Lagos"), ("Lagos (Ikeja, Lekki)", "Lagos"), ("Computer Village Ikeja", "Lagos"),
                          ("Abuja FCT", "Abuja"), ("Port_Harcourt", "Port Harcourt"),
                          ("Nationwide (Lagos, Abuja)", "Nationwide"), ("International Trade", "International Trade")]:
            self.assertEqual(facets.region(raw), want, raw)

    def test_register(self):
        self.assertEqual(facets.register("Pidgin English"), "pidgin")
        self.assertEqual(facets.register("Corporate Pidgin"), "mixed")
        self.assertEqual(facets.register("Standard English"), "english")


class Cautions(unittest.TestCase):
    def test_flags_payment_links_claims_and_approvals(self):
        rec = {"platform_specific": {"cta": "Pay here https://paystack.com/pay/glow-sample",
                                     "caption": "100% organic serum, NAFDAC certified? clears acne fast"}}
        text = " ".join(compute_cautions(rec))
        self.assertIn("payment link", text)
        self.assertIn("health", text)
        self.assertNotEqual(compute_cautions({"platform_specific": {"a": "NAFDAC approved"}}), ())

    def test_ordinary_marketing_copy_is_not_flagged(self):
        rec = {"platform_specific": {"cta": "Clear call-to-action. Money-back guarantee. We reply within 24 hours."}}
        self.assertEqual(compute_cautions(rec), ())

    def test_generated_statistics_are_never_exposed(self):
        self.assertNotIn("metrics_and_evidence", {f.name for f in dataclasses.fields(SmmGuidance)})
        self.assertNotIn("metrics_and_evidence", {f.name for f in dataclasses.fields(SmmGuidance)} | {"metrics"})


@unittest.skipUnless(INDEX.exists(), "build the index first")
class Retrieval(unittest.TestCase):
    def setUp(self):
        self.store = CorpusStore(INDEX, RAW)
        self.addCleanup(self.store.close)

    def test_smm_domain_registered(self):
        self.assertIn(SMM, DOMAINS)

    def test_platform_filter_is_exclusive(self):
        for p in ("meta", "tiktok"):
            hits = smm_guidance(self.store, "product video hook", platform=p, limit=5)
            self.assertTrue(hits)
            self.assertTrue(all(h.platform == p for h in hits))

    def test_filters_apply_and_return_structured_guidance(self):
        hits = smm_guidance(self.store, "video hook orders", platform="tiktok", objective="conversion",
                            industry="food_beverage", limit=3)
        self.assertTrue(hits)
        for g in hits:
            self.assertEqual(g.objective, "conversion")
            self.assertEqual(g.dropped_filters, ())
        self.assertTrue(any(g.playbook for g in hits))
        self.assertTrue(all(s.automation in ("automatable", "owner_advisory", "unknown")
                            for g in hits for s in g.playbook))

    def test_relaxation_is_reported_not_hidden(self):
        # no Meta content is a live_selling surface: surface must be dropped, and say so
        hits = smm_guidance(self.store, "comment to dm", platform="meta", surface="live_selling", limit=2)
        self.assertTrue(hits)
        self.assertIn("surface", hits[0].dropped_filters)
        self.assertEqual(smm_guidance(self.store, "comment to dm", platform="meta", surface="live_selling",
                                      relax=False), [])

    def test_bad_arguments_rejected(self):
        with self.assertRaises(ValueError):
            smm_guidance(self.store, "x", platform="myspace")
        with self.assertRaises(ValueError):
            smm_guidance(self.store, "x", objective="vibes")
        with self.assertRaises(ValueError):
            self.store.search(SMM, "x", **{"d.id; DROP TABLE docs": "1"})


if __name__ == "__main__":
    unittest.main()
