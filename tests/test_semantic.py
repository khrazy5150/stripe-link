"""Offer Semantic Model — deterministic core (plans/OFFER_SEMANTIC_ANALYZER.md). Pure meaning; slug + label
are the P1 consumers."""
import unittest

from stripe_link.domain.semantic import analyze_offer, label_from_model, slug_from_model


def _prod(pid, name, category, product_type="physical", recurring=False):
    price = {"price_id": f"{pid}_p", "unit_amount": 1000, "currency": "usd", "quantity": 1, "context": "standard"}
    if recurring:
        price["pricing_model"] = "recurring"
    return {"product_id": pid, "name": name, "product_category": category, "product_type": product_type,
            "default_price_id": f"{pid}_p", "prices": [price]}


def _offer(product_ids, brand="", intent="transaction"):
    return {"product_intent": intent, "presentation": {"brand": brand},
            "items": [{"product_id": p, "quantity": 1} for p in product_ids]}


class AnalyzeOfferTests(unittest.TestCase):
    def test_single_product_facts(self):
        m = analyze_offer(_offer(["p1"], brand="Axel Mart"), {"p1": _prod("p1", "Whey Protein", "dietary_supplement")})
        facts = m["facts"]
        self.assertEqual(facts["entities"]["primary"], {"type": "product", "name": "Whey Protein"})
        self.assertEqual(facts["entities"]["secondary"], [])
        self.assertEqual(facts["brand"], {"name": "Axel Mart"})
        self.assertEqual(facts["taxonomy"]["hierarchy"], ["Dietary Supplement"])
        self.assertEqual(facts["intent"]["commercial"], "transaction")
        self.assertEqual(facts["intent"]["fulfillment"], "physical")
        self.assertEqual(facts["commerce"]["pricing_model"], "single")
        self.assertEqual(facts["commerce"]["purchase_model"], "one_time")
        self.assertEqual(m["interpretation"]["source"], "deterministic")
        # key concepts: brand strongest, product next
        concepts = {c["value"]: c["weight"] for c in m["interpretation"]["key_concepts"]}
        self.assertGreater(concepts["axel"], concepts["whey"])

    def test_bundle_shared_category(self):
        m = analyze_offer(_offer(["p1", "p2"]), {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                                 "p2": _prod("p2", "Creatine", "dietary_supplement")})
        facts = m["facts"]
        self.assertEqual(facts["entities"]["primary"], {"type": "bundle", "name": "Dietary Supplement"})
        self.assertEqual([s["name"] for s in facts["entities"]["secondary"]], ["Creatine"])
        self.assertEqual(facts["taxonomy"]["hierarchy"], ["Dietary Supplement"])
        self.assertEqual(facts["commerce"]["pricing_model"], "multi")

    def test_mixed_bundle_has_no_hierarchy(self):
        m = analyze_offer(_offer(["p1", "p2"]), {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                                 "p2": _prod("p2", "Yoga Mat", "fitness_gear")})
        self.assertEqual(m["facts"]["taxonomy"]["hierarchy"], [])
        self.assertEqual(m["facts"]["entities"]["primary"]["name"], "Whey Protein")

    def test_subscription_and_lead_gen(self):
        sub = analyze_offer(_offer(["p1"]), {"p1": _prod("p1", "Membership", "software", recurring=True)})
        self.assertEqual(sub["facts"]["commerce"]["purchase_model"], "subscription")
        lead = analyze_offer(_offer(["p1"], intent="lead_generation"), {"p1": _prod("p1", "Free Guide", "ebook")})
        self.assertEqual(lead["facts"]["entities"]["primary"]["type"], "lead_generation")


class LabelFromModelTests(unittest.TestCase):
    def _label(self, ids, products):
        return label_from_model(analyze_offer(_offer(ids), products))

    def test_single_uses_product_name(self):
        self.assertEqual(self._label(["p1"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement")}), "Whey Protein")

    def test_shared_category_bundle(self):
        self.assertEqual(
            self._label(["p1", "p2"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                       "p2": _prod("p2", "Creatine", "dietary_supplement")}),
            "Dietary Supplement Bundle",
        )

    def test_mixed_bundle_names_both(self):
        self.assertEqual(
            self._label(["p1", "p2"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                       "p2": _prod("p2", "Yoga Mat", "fitness_gear")}),
            "Whey Protein + Yoga Mat Bundle",
        )


class SlugMatchesLabelSourceTests(unittest.TestCase):
    def test_slug_and_label_read_the_same_entity(self):
        # The whole point: slug and label can't diverge because both read entities.primary.
        m = analyze_offer(_offer(["p1", "p2"], brand="Axel Mart"),
                          {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                           "p2": _prod("p2", "Creatine", "dietary_supplement")})
        self.assertEqual(slug_from_model(m), "axel-mart-dietary-supplement-bundle")
        self.assertEqual(label_from_model(m), "Dietary Supplement Bundle")


if __name__ == "__main__":
    unittest.main()
