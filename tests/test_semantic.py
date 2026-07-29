"""Offer Semantic Model — deterministic core (plans/OFFER_SEMANTIC_ANALYZER.md). Pure meaning; slug + label
are the P1 consumers."""
import json
import unittest
from pathlib import Path

from stripe_link.domain.documents import DocumentValidationError, validate_semantic_model
from stripe_link.domain.semantic import (
    MODEL_VERSION,
    analyze_offer,
    label_from_model,
    resolve_semantic_model,
    slug_from_model,
)

_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "OfferSemanticModel.schema.json").read_text())


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


def _assert_conforms(test, model):
    """Dependency-free structural conformance against schemas/OfferSemanticModel.schema.json (the repo keeps
    third-party deps out, so no jsonschema): at every documented object level, all `required` keys are present
    and — where `additionalProperties` is false — there are no undocumented keys. Plus the two enums. Catches
    the realistic drift (a field added to the model but not the schema, or renamed) without a JSON-Schema lib."""
    def check(inst, schema, path):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and isinstance(inst, dict):
            test.assertEqual(set(inst) - set(props), set(), f"{path}: undocumented keys")
        for key in schema.get("required", []):
            test.assertIn(key, inst, f"{path}: missing required '{key}'")
        for key, subschema in props.items():
            if isinstance(inst, dict) and key in inst and subschema.get("type") == "object" and "properties" in subschema:
                check(inst[key], subschema, f"{path}.{key}")
    check(model, _SCHEMA, "model")
    entity_enum = _SCHEMA["$defs"]["entity"]["properties"]["type"]["enum"]
    test.assertIn(model["facts"]["entities"]["primary"]["type"], entity_enum)
    test.assertIn(model["interpretation"]["source"],
                  _SCHEMA["properties"]["interpretation"]["properties"]["source"]["enum"])


class SchemaConformanceTests(unittest.TestCase):
    """P4.0: the deterministic analyzer output IS the contract — it must conform to the JSON Schema
    (schemas/OfferSemanticModel.schema.json, what the AI tier's output is checked against) AND pass the runtime
    validate_semantic_model. Locks code and contract together so neither drifts."""

    CASES = [
        ("single", ["p1"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement")}, "Axel Mart"),
        ("shared_bundle", ["p1", "p2"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                         "p2": _prod("p2", "Creatine", "dietary_supplement")}, ""),
        ("mixed_bundle", ["p1", "p2"], {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                                        "p2": _prod("p2", "Yoga Mat", "fitness_gear")}, "Store"),
        ("subscription", ["p1"], {"p1": _prod("p1", "Membership", "software", recurring=True)}, ""),
    ]

    def test_deterministic_output_matches_schema_and_validator(self):
        for name, ids, products, brand in self.CASES:
            with self.subTest(case=name):
                model = analyze_offer(_offer(ids, brand=brand), products)
                _assert_conforms(self, model)     # structural JSON-Schema conformance
                validate_semantic_model(model)    # runtime contract agrees
                self.assertEqual(model["interpretation"]["version"], MODEL_VERSION)

    def test_lead_gen_output_conforms(self):
        model = analyze_offer(_offer(["p1"], intent="lead_generation"), {"p1": _prod("p1", "Free Guide", "ebook")})
        _assert_conforms(self, model)
        validate_semantic_model(model)


class ValidateSemanticModelTests(unittest.TestCase):
    def _model(self):
        return analyze_offer(_offer(["p1"], brand="Axel Mart"), {"p1": _prod("p1", "Whey Protein", "dietary_supplement")})

    def test_valid_model_passes(self):
        validate_semantic_model(self._model())  # no raise

    def test_rejects_non_object(self):
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model("nope")

    def test_rejects_missing_interpretation(self):
        model = self._model()
        del model["interpretation"]
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model(model)

    def test_rejects_bad_entity_type(self):
        model = self._model()
        model["facts"]["entities"]["primary"]["type"] = "wormhole"
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model(model)

    def test_rejects_unknown_source(self):
        model = self._model()
        model["interpretation"]["source"] = "vibes"
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model(model)

    def test_rejects_negative_funnel_count(self):
        model = self._model()
        model["facts"]["commerce"]["funnel"]["upsells"] = -1
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model(model)

    def test_rejects_non_numeric_concept_weight(self):
        model = self._model()
        model["interpretation"]["key_concepts"][0]["weight"] = "heavy"
        with self.assertRaises(DocumentValidationError):
            validate_semantic_model(model)


class ResolveSemanticModelTests(unittest.TestCase):
    """P4.0 read seam: cached AI model wins only when current; everything else recomputes deterministically."""

    def _offer_products(self):
        return _offer(["p1"], brand="Axel Mart"), {"p1": _prod("p1", "Whey Protein", "dietary_supplement")}

    def test_no_cache_recomputes_deterministic(self):
        offer, products = self._offer_products()
        model = resolve_semantic_model(offer, products)
        self.assertEqual(model["interpretation"]["source"], "deterministic")

    def test_current_ai_cache_is_returned(self):
        offer, products = self._offer_products()
        cached = analyze_offer(offer, products)
        cached["interpretation"] = {**cached["interpretation"], "source": "ai", "version": MODEL_VERSION}
        cached["facts"]["entities"]["primary"]["name"] = "AI Enriched Name"
        offer["semantic_model"] = cached
        got = resolve_semantic_model(offer, products)
        self.assertEqual(got["facts"]["entities"]["primary"]["name"], "AI Enriched Name")  # the cache, not a recompute

    def test_deterministic_cache_is_ignored(self):
        # A cached DETERMINISTIC model is never trusted — recompute is cheap and always current.
        offer, products = self._offer_products()
        stale = analyze_offer(offer, products)
        stale["facts"]["entities"]["primary"]["name"] = "Stale Name"  # source stays "deterministic"
        offer["semantic_model"] = stale
        got = resolve_semantic_model(offer, products)
        self.assertEqual(got["facts"]["entities"]["primary"]["name"], "Whey Protein")  # recomputed, not the stale cache

    def test_stale_version_ai_cache_is_ignored(self):
        offer, products = self._offer_products()
        cached = analyze_offer(offer, products)
        cached["interpretation"] = {**cached["interpretation"], "source": "ai", "version": MODEL_VERSION + 1}
        cached["facts"]["entities"]["primary"]["name"] = "Old Version Name"
        offer["semantic_model"] = cached
        got = resolve_semantic_model(offer, products)
        self.assertEqual(got["facts"]["entities"]["primary"]["name"], "Whey Protein")  # version mismatch -> recompute


if __name__ == "__main__":
    unittest.main()
