"""The tip-jar price model: what `customer_chooses` is allowed to say.

plans/PAY_WHAT_YOU_WANT.md §1a. The half-imported version modelled a tip jar as a SALE with two decorative
extra fields -- `Price.schema.json` carried `pricing_model`, `min_amount` and `suggested_amount`, was
`additionalProperties: false` so the rest of the legacy shape could not even be stored, and every runtime path
read `unit_amount`, described as "sale amount charged to the customer". So a tip jar saved cleanly and then
sold at whatever the tenant typed in the Sales price field: a plausible wrong answer, which is the worst
failure shape, and a regression against stripe-cart which ships this feature.

This is the model landing first, ahead of the product wizard, because the wizard's tip-jar branch would
otherwise write fields the schema rejects.
"""
import copy
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_product_document

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "Price.schema.json").read_text(encoding="utf-8"))
BASE = json.loads((ROOT / "schemas" / "examples" / "product-simple-coffee.json").read_text(encoding="utf-8"))


def _product(**price):
    doc = copy.deepcopy(BASE)
    doc["default_price_id"] = "pr"
    doc["prices"] = [{"price_id": "pr", "currency": "usd", "quantity": 1,
                      "pricing_model": "customer_chooses", **price}]
    return doc


class SchemaTests(unittest.TestCase):
    def test_the_legacy_shape_is_now_expressible(self):
        # It was not: additionalProperties is false, so these were rejected on write. The schema did not
        # merely omit the right model, it blocked it.
        for field in ("presets", "max_amount", "allow_custom", "allow_recurring", "recurring_interval"):
            self.assertIn(field, SCHEMA["properties"], field)

    def test_the_schema_is_still_closed(self):
        # Widening it must not turn into "anything goes" -- a closed schema is what caught this in the first
        # place, by refusing the fields nobody had modelled.
        self.assertIs(SCHEMA.get("additionalProperties"), False)

    def test_presets_are_documented_as_charged_amounts(self):
        # DECIDED (author, 2026-09-13). The stored number includes the platform fee, exactly as unit_amount
        # does for a fixed price under split/net_guaranteed -- so the button and the card statement agree.
        self.assertIn("CHARGED", SCHEMA["properties"]["presets"]["description"])

    def test_suggested_amount_is_marked_deprecated_not_deleted(self):
        # Existing documents carry it; deleting it from the schema would fail them on their next save.
        self.assertIn("DEPRECATED", SCHEMA["properties"]["suggested_amount"]["description"])


class ChoiceRequiredTests(unittest.TestCase):
    def test_a_tip_jar_must_offer_a_way_to_choose(self):
        # The rule that stops the original bug recurring: without it, a customer_chooses price validates while
        # being unusable, and the runtime falls back to a fixed amount nobody intended.
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_document(_product())
        self.assertIn("nothing to choose", str(caught.exception))

    def test_presets_alone_are_enough(self):
        validate_product_document(_product(presets=[200, 500, 1000]))

    def test_a_custom_amount_alone_is_enough(self):
        validate_product_document(_product(allow_custom=True))

    def test_a_legacy_suggested_amount_still_counts(self):
        # Migration comfort: documents saved before presets existed keep validating until it is folded in.
        validate_product_document(_product(suggested_amount=500))


class BoundsTests(unittest.TestCase):
    def test_a_preset_outside_the_bounds_is_refused(self):
        # A preset the buyer cannot actually pay is a button that fails at checkout.
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[50], min_amount=100))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[9999], max_amount=5000))

    def test_the_bounds_must_be_the_right_way_round(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(allow_custom=True, min_amount=500, max_amount=100))

    def test_presets_must_be_distinct(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[500, 500]))

    def test_there_is_a_ceiling_on_how_many(self):
        # Eight buttons is already a lot on a phone, which is the only screen that matters here.
        validate_product_document(_product(presets=[100 * n for n in range(1, 9)]))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[100 * n for n in range(1, 10)]))


class RecurringTests(unittest.TestCase):
    def test_a_recurring_tip_is_expressible(self):
        validate_product_document(
            _product(presets=[500], allow_recurring=True, recurring_interval="month"))

    def test_the_interval_is_constrained(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[500], recurring_interval="weekly"))


class UnchangedForOtherModelsTests(unittest.TestCase):
    def test_a_fixed_price_still_requires_an_amount(self):
        # None of this may loosen the ordinary path: a one_time price with no unit_amount is still an error.
        doc = copy.deepcopy(BASE)
        doc["default_price_id"] = "pr"
        doc["prices"] = [{"price_id": "pr", "currency": "usd", "quantity": 1, "pricing_model": "one_time"}]
        with self.assertRaises(DocumentValidationError):
            validate_product_document(doc)


if __name__ == "__main__":
    unittest.main()
