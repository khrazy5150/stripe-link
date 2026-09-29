"""Projecting a page brief from a product the tenant already has (plans/AI_PAGE_BRIEF.md v2 §5).

This is what makes Build with AI a FORK rather than a second wizard. v1 asked nine questions and, measured
against Products.vue, had already been told almost all of them. Nothing here invents: every value is copied
or absent, and an absent one is a sentence `ai_floor` will not let the page contain.
"""
import unittest
from decimal import Decimal

from stripe_link.domain.page_brief import BriefError, validate
from stripe_link.domain.product_brief import brief_from_product, kind_for, missing_for_generation

PRODUCT = {
    "tenant_id": "t1", "product_id": "local_1", "name": "Creatine Gummies",
    "description": "Chewable creatine.", "product_category": "supplements",
    "product_type": "physical", "default_price_id": "price_b",
    "prices": [
        {"price_id": "price_a", "unit_amount": Decimal("9900"), "currency": "usd"},
        {"price_id": "price_b", "unit_amount": Decimal("3900"), "currency": "usd"},
    ],
}


class ProjectionTests(unittest.TestCase):
    def test_the_core_comes_straight_off_the_product(self):
        brief = brief_from_product(PRODUCT)
        self.assertEqual(brief["name"], "Creatine Gummies")
        self.assertEqual(brief["what_it_is"], "Chewable creatine.")
        self.assertEqual(brief["category"], "supplements")
        self.assertEqual(brief["kind"], "physical")
        self.assertEqual(brief["source"], "existing_product")

    def test_the_DEFAULT_price_wins_not_the_first_one(self):
        # A product with a sale price and a full price carries both. Generating copy around whichever
        # happened to be first would put the wrong number on the page.
        self.assertEqual(brief_from_product(PRODUCT)["price"]["unit_amount"], 3900)

    def test_a_stored_Decimal_becomes_a_real_int(self):
        # DynamoDB returns every number as Decimal, and the brief validator requires isinstance(x, int).
        # Fixtures using int() pass while stored documents fail — that mismatch has 404'd pages here before.
        amount = brief_from_product(PRODUCT)["price"]["unit_amount"]
        self.assertIsInstance(amount, int)
        self.assertNotIsInstance(amount, Decimal)

    def test_an_unreadable_price_reaches_the_validator_rather_than_becoming_free(self):
        odd = {**PRODUCT, "prices": [{"price_id": "price_b", "unit_amount": "lots", "currency": "usd"}]}
        with self.assertRaises(BriefError):
            validate({**brief_from_product(odd), "audience": "a", "facts": ["f"]})

    def test_a_recurring_price_is_flattened_for_the_brief(self):
        # Nested on a price, flat on a brief. Conflating the two once made a subscription charge exactly once.
        recurring = {**PRODUCT, "prices": [{"price_id": "price_b", "unit_amount": Decimal("1900"),
                                            "currency": "usd", "recurring": {"interval": "month"}}]}
        price = brief_from_product(recurring)["price"]
        self.assertEqual(price["pricing_model"], "recurring")
        self.assertEqual(price["recurring_interval"], "month")


class PolicyTests(unittest.TestCase):
    def test_the_refund_policy_is_read_from_the_product_OBJECT(self):
        # refund_policy is an object with full_policy/short_label — not a string.
        product = {**PRODUCT, "refund_policy": {"full_policy": "Refunds within 30 days."}}
        self.assertEqual(brief_from_product(product)["guarantee"], "Refunds within 30 days.")

    def test_the_short_label_is_the_fallback(self):
        product = {**PRODUCT, "refund_policy": {"short_label": "30-day refunds"}}
        self.assertEqual(brief_from_product(product)["guarantee"], "30-day refunds")

    def test_a_product_policy_beats_the_tenant_default(self):
        product = {**PRODUCT, "refund_policy": {"full_policy": "Product rule."}}
        brief = brief_from_product(product, tenant_profile={"refund_policy": {"full_policy": "Tenant rule."}})
        self.assertEqual(brief["guarantee"], "Product rule.")

    def test_no_policy_anywhere_licenses_no_guarantee(self):
        # Absent, not invented. The floor then refuses any refund sentence, which is the design.
        self.assertNotIn("guarantee", brief_from_product(PRODUCT))

    def test_a_policy_is_never_assembled_from_its_parts(self):
        # A sentence we composed is a sentence the tenant never agreed to, and `guarantee` licenses a CLAIM.
        product = {**PRODUCT, "refund_policy": {"refund_window": 30, "return_method": "no_return"}}
        self.assertNotIn("guarantee", brief_from_product(product))


class ContextAndOverrideTests(unittest.TestCase):
    def test_stored_context_fills_the_answers_the_product_cannot(self):
        product = {**PRODUCT, "ai_context": {"audience": "Lifters", "facts": ["5g per serving"]}}
        brief = brief_from_product(product)
        self.assertEqual(brief["audience"], "Lifters")
        self.assertEqual(brief["facts"], ["5g per serving"])

    def test_an_override_wins_over_stored_context(self):
        product = {**PRODUCT, "ai_context": {"audience": "Old"}}
        self.assertEqual(brief_from_product(product, overrides={"audience": "New"})["audience"], "New")

    def test_a_BLANK_override_means_unchanged_not_erase(self):
        # The step shows a partial form, so an untouched field arrives as "". Letting that win stripped the
        # audience out of the brief and failed validation before anything ran.
        product = {**PRODUCT, "ai_context": {"audience": "Kept", "facts": ["kept"]}}
        brief = brief_from_product(product, overrides={"audience": "", "facts": []})
        self.assertEqual(brief["audience"], "Kept")
        self.assertEqual(brief["facts"], ["kept"])


class ShippingTests(unittest.TestCase):
    def test_measurements_are_copied_under_the_brief_names(self):
        product = {**PRODUCT, "fulfillment": {"dimensions": {"length_in": Decimal("4"), "width_in": 4},
                                              "weight_lb": Decimal("0.5")}}
        block = brief_from_product(product)["physical"]
        # Coerced to float: isinstance(Decimal, (int, float)) is False, so the obvious guard dropped every
        # measurement a tenant had actually entered.
        self.assertEqual(block["length_in"], 4.0)
        self.assertEqual(block["weight_lb"], 0.5)
        self.assertNotIsInstance(block["weight_lb"], Decimal)

    def test_a_weight_does_not_license_a_shipping_SENTENCE(self):
        # Measurements license no claim: a tenant who gave us a weight has not authorised a sentence about
        # shipping. Only the tenant's own policy text does.
        product = {**PRODUCT, "fulfillment": {"weight_lb": Decimal("0.5")}}
        self.assertNotIn("shipping", brief_from_product(product)["physical"])

    def test_the_shipping_sentence_comes_from_config(self):
        brief = brief_from_product(PRODUCT, shipping_config={"policy_summary": "Ships in 2 days."})
        self.assertEqual(brief["physical"]["shipping"], "Ships in 2 days.")

    def test_a_digital_product_never_gets_a_shipping_block(self):
        digital = {**PRODUCT, "product_type": "digital"}
        brief = brief_from_product(digital, shipping_config={"policy_summary": "Ships in 2 days."})
        self.assertNotIn("physical", brief)


class MissingFieldTests(unittest.TestCase):
    def test_it_names_only_what_the_STEP_can_answer(self):
        # A missing name or price is a broken PRODUCT and belongs in the product wizard, not patched here.
        self.assertEqual(missing_for_generation(brief_from_product(PRODUCT)), ["audience", "facts"])

    def test_nothing_missing_once_context_is_present(self):
        product = {**PRODUCT, "ai_context": {"audience": "Lifters", "facts": ["5g"]}}
        self.assertEqual(missing_for_generation(brief_from_product(product)), [])

    def test_a_complete_projection_validates(self):
        product = {**PRODUCT, "ai_context": {"audience": "Lifters", "facts": ["5g per serving"]}}
        validate(brief_from_product(product))


class KindTests(unittest.TestCase):
    def test_known_types_map(self):
        for product_type, kind in (("physical", "physical"), ("digital", "digital"), ("service", "service")):
            with self.subTest(product_type=product_type):
                self.assertEqual(kind_for({"product_type": product_type}), kind)

    def test_an_unknown_type_is_empty_rather_than_guessed(self):
        # Empty reaches the brief validator and is refused with a message; a guess would generate a page
        # about the wrong kind of thing.
        self.assertEqual(kind_for({"product_type": "mystery"}), "")
        self.assertEqual(kind_for({}), "")


if __name__ == "__main__":
    unittest.main()
