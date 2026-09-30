"""What the AI is LICENSED to say about a product (plans/AI_PAGE_BRIEF.md v2 §4).

The field exists because of a gap found while designing the fork: `audience`, `facts`, `evidence`, `tone`,
`must_say` and `must_not_say` lived only in a transient brief, so a tenant regenerating a page would have
retyped every one of them. It lives on the PRODUCT rather than the page because these describe the thing
being sold — a second page for it, an A/B variant or a seasonal landing page, inherits them.

Validated strictly for a reason that is easy to forget: every entry here ends up inside a model prompt, and
anything that survives the field floor ends up on a public page.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import (AI_CONTEXT_BOOL_FIELDS, AI_CONTEXT_LIST_FIELDS,
                                          AI_CONTEXT_TEXT_FIELDS, DocumentValidationError,
                                          validate_product_ai_context)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AiContextValidationTests(unittest.TestCase):
    def test_a_product_without_it_is_valid(self):
        # Entirely optional. A product with none simply produces a thinner, more cautious page, because the
        # floor refuses any claim the brief does not license.
        validate_product_ai_context({})
        validate_product_ai_context({"ai_context": None})

    def test_a_full_context_is_accepted(self):
        validate_product_ai_context({"ai_context": {
            "audience": "Distance runners training for a first marathon",
            "facts": ["5g of creatine per serving", "30 gummies per tub"],
            "evidence": "Third-party lab assay, batch 2026-03.",
            "certifications": ["Informed Sport"],
            "tone": "direct",
            "must_say": ["Made in Australia"],
            "must_not_say": ["cures"],
            "updated_at": 1790000000,
        }})

    def test_an_unknown_field_is_refused(self):
        # Not pedantry: an unrecognised key is a field someone believed would reach the model and which
        # silently would not, which is indistinguishable from the AI ignoring an instruction.
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_ai_context({"ai_context": {"dosage": "5g"}})
        self.assertIn("dosage", str(caught.exception))

    def test_every_text_field_is_bounded(self):
        for field, limit in AI_CONTEXT_TEXT_FIELDS.items():
            with self.subTest(field=field):
                validate_product_ai_context({"ai_context": {field: "x" * limit}})
                with self.assertRaises(DocumentValidationError):
                    validate_product_ai_context({"ai_context": {field: "x" * (limit + 1)}})

    def test_every_list_field_is_bounded(self):
        # Every entry is a sentence the page is then licensed to write. An unbounded list is both a
        # prompt-size problem and an unreviewable one.
        for field, cap in AI_CONTEXT_LIST_FIELDS.items():
            with self.subTest(field=field):
                validate_product_ai_context({"ai_context": {field: ["ok"] * cap}})
                with self.assertRaises(DocumentValidationError):
                    validate_product_ai_context({"ai_context": {field: ["ok"] * (cap + 1)}})

    def test_a_blank_entry_is_refused(self):
        # A blank fact licenses nothing and reads to the model as an empty instruction.
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                with self.assertRaises(DocumentValidationError):
                    validate_product_ai_context({"ai_context": {"facts": [value]}})

    def test_wrong_shapes_are_refused(self):
        for context in ({"facts": "one fact"}, {"audience": ["runners"]}, {"updated_at": "yesterday"}):
            with self.subTest(context=context):
                with self.assertRaises(DocumentValidationError):
                    validate_product_ai_context({"ai_context": context})
        with self.assertRaises(DocumentValidationError):
            validate_product_ai_context({"ai_context": "runners"})


class SchemaAgreementTests(unittest.TestCase):
    """The JSON Schema and the Python validator must describe the same field.

    `Product.schema.json` is `additionalProperties: false`, so a field the schema does not know about is
    rejected before the validator ever sees it — and a validator that knows about fields the schema does not
    would pass tests while production refused the document.
    """

    def setUp(self):
        with (ROOT / "schemas" / "Product.schema.json").open() as handle:
            self.schema = json.load(handle)

    def test_the_schema_declares_ai_context(self):
        self.assertIn("ai_context", self.schema["properties"])
        self.assertNotIn("ai_context", self.schema["required"], "it is optional")

    def test_both_sides_know_the_same_fields(self):
        declared = set(self.schema["properties"]["ai_context"]["properties"])
        validated = (set(AI_CONTEXT_LIST_FIELDS) | set(AI_CONTEXT_TEXT_FIELDS)
                     | set(AI_CONTEXT_BOOL_FIELDS) | {"updated_at"})
        self.assertEqual(declared, validated)

    def test_the_schema_refuses_unknown_fields_too(self):
        self.assertFalse(self.schema["properties"]["ai_context"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()


class TrustBadgeChoiceTests(unittest.TestCase):
    """A badge is a claim, so it is CHOSEN, never defaulted (author, 2026-09-30).

    The builder seeded "Ships from USA" and "Satisfaction Guarantee" on every page — a checkable claim about
    provenance and a policy the tenant may not offer. The field floor already forbids the AI from authoring
    badges; defaulting them is the platform asserting through the back door what the floor stops at the front.
    """

    def _badges(self, context, **kwargs):
        from stripe_link.domain.ai_provision import chosen_badges

        return chosen_badges(context, **kwargs)

    def test_nothing_is_claimed_by_default(self):
        self.assertEqual(self._badges({}), [])
        self.assertEqual(self._badges(None), [])

    def test_an_explicit_NO_claims_nothing(self):
        self.assertEqual(self._badges({"ships_from_us": False, "money_back_badge": False}), [])

    def test_saying_yes_to_shipping_adds_exactly_one_badge(self):
        badges = self._badges({"ships_from_us": True})
        self.assertEqual(len(badges), 1)
        self.assertEqual(badges[0]["label"], "Ships from USA")

    def test_the_money_back_badge_is_labelled_from_the_tenants_OWN_policy(self):
        badges = self._badges({"money_back_badge": True},
                              refund_policy={"short_label": "30-day refunds"})
        self.assertEqual(badges[0]["label"], "30-day refunds")

    def test_no_window_is_INVENTED_when_the_policy_has_no_short_label(self):
        # `guarantee` is a numeric-grounded claim class, so a badge asserting "30 days" the policy never
        # said would be a fabricated number on a public page.
        badges = self._badges({"money_back_badge": True},
                              refund_policy={"full_policy": "Refunds within 30 days of delivery."})
        self.assertEqual(badges[0]["label"], "Money-back guarantee")
        self.assertNotIn("30", badges[0]["label"])

    def test_both_choices_produce_both_badges(self):
        badges = self._badges({"ships_from_us": True, "money_back_badge": True})
        self.assertEqual(len(badges), 2)

    def test_the_booleans_are_valid_product_context(self):
        validate_product_ai_context({"ai_context": {"ships_from_us": True, "money_back_badge": False}})
        with self.assertRaises(DocumentValidationError):
            validate_product_ai_context({"ai_context": {"ships_from_us": "yes"}})
