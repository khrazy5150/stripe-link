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

from stripe_link.domain import tips
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
    def test_the_charges_must_line_up_with_the_presets(self):
        # One charge per preset, in the same order -- otherwise a card displays one preset's price against
        # another's, which is a wrong number presented as a right one.
        validate_product_document(_product(presets=[500, 1000], preset_charges=[545, 1060]))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[500, 1000], preset_charges=[545]))
        with self.assertRaises(DocumentValidationError):
            # Fees are ADDED to a tip; a charge below what the tenant keeps cannot be honest.
            validate_product_document(_product(presets=[500], preset_charges=[400]))

    def test_the_legacy_shape_is_now_expressible(self):
        # It was not: additionalProperties is false, so these were rejected on write. The schema did not
        # merely omit the right model, it blocked it.
        for field in ("presets", "max_amount", "allow_custom", "allow_recurring", "recurring_interval"):
            self.assertIn(field, SCHEMA["properties"], field)

    def test_the_schema_is_still_closed(self):
        # Widening it must not turn into "anything goes" -- a closed schema is what caught this in the first
        # place, by refusing the fields nobody had modelled.
        self.assertIs(SCHEMA.get("additionalProperties"), False)

    def test_a_preset_stores_both_what_the_tenant_keeps_and_what_the_buyer_pays(self):
        """REVERSES the first reading of this, same day.

        Presets were briefly modelled as charged amounts outright. That made `net_guaranteed` -- "the
        customer covers the fees, you keep the full amount" -- false of every button, since the tenant's
        round $25 became $25 charged and ~$23 kept. The pair is what an ordinary price already stores
        (tenant_keyed_amount beside unit_amount), and what the legacy app stored per preset price
        (`unit_amount` + `_gross_amount`, api_products.py:151).
        """
        self.assertIn("KEEPS", SCHEMA["properties"]["presets"]["description"])
        self.assertIn("BUYER", SCHEMA["properties"]["preset_charges"]["description"])
        self.assertEqual(SCHEMA["properties"]["preset_charges"]["maxItems"],
                         SCHEMA["properties"]["presets"]["maxItems"])

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
    """The range is the PLATFORM's (author, 2026-09-13: "System set range: $1 - $500. Don't allow tenants to
    change it"), so the server does not check what the tenant sent -- it replaces it."""

    def test_the_range_is_imposed_not_accepted(self):
        # A request that names its own range -- which the builder cannot produce, but curl can -- comes back
        # carrying the platform's. Checking instead of setting would leave the rule true only of documents
        # the builder happened to write.
        doc = _product(allow_custom=True, min_amount=1, max_amount=100_000_000)
        validate_product_document(doc)
        self.assertEqual(doc["prices"][0]["min_amount"], tips.MIN_AMOUNT)
        self.assertEqual(doc["prices"][0]["max_amount"], tips.MAX_AMOUNT)

    def test_the_range_is_written_even_when_nobody_asked(self):
        # So the runtime never has to ask "and what if it is absent?"
        doc = _product(presets=[500])
        validate_product_document(doc)
        self.assertEqual(doc["prices"][0]["min_amount"], tips.MIN_AMOUNT)
        self.assertEqual(doc["prices"][0]["max_amount"], tips.MAX_AMOUNT)

    def test_a_preset_outside_the_bounds_is_refused(self):
        # A preset the buyer cannot actually pay is a button that fails at checkout.
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[tips.MIN_AMOUNT - 1]))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[tips.MAX_AMOUNT + 1]))

    def test_presets_must_be_distinct(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[500, 500]))

    def test_there_is_a_ceiling_on_how_many(self):
        # Five buttons fit in the row on a phone, which is the only screen that matters here.
        validate_product_document(_product(presets=[100 * n for n in range(1, 6)]))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(presets=[100 * n for n in range(1, 7)]))

    def test_offering_a_custom_amount_costs_one_of_the_places(self):
        # "Enter your own" is a button too. Four presets plus it is the full row; five plus it overflows.
        validate_product_document(_product(allow_custom=True, presets=[100 * n for n in range(1, 5)]))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(allow_custom=True, presets=[100 * n for n in range(1, 6)]))


class RecurringTests(unittest.TestCase):
    def test_a_recurring_tip_is_expressible(self):
        validate_product_document(
            _product(presets=[500], allow_recurring=True, recurring_interval="month"))

    def test_every_stripe_interval_is_offered(self):
        # Asked for by name (author, 2026-09-13): "daily, weekly, monthly, yearly or whatever Stripe
        # supports". A donation that repeats weekly is as ordinary as one that repeats monthly.
        for interval in ("day", "week", "month", "year"):
            validate_product_document(_product(presets=[500], allow_recurring=True, recurring_interval=interval))

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
