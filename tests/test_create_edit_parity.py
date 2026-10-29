"""What the wizard lets a tenant SET, the edit form must let them change.

A create flow and an edit form are two views of one document, and they drift apart quietly: the wizard
gains a step, the edit form keeps an older idea of which fields that kind of product has, and the result
is a value a tenant can write exactly once and never correct. Nothing fails, nothing logs, and the only
way to find it is to go back and try.

The one this file was written for: every WIZARD_FLOWS entry ends in "image", so all three intents are
offered a picture when they are created -- but the edit form's image section was gated on
`product_intent === 'transaction'`. A lead magnet or a tip jar could be given an image and then never
change or remove it. A Roundup, whose entire job is to rank in search, was stuck with the lead-action
glyph for good.
"""

import pathlib
import re
import unittest

PRODUCTS = (pathlib.Path(__file__).resolve().parents[1]
            / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")


class ImageParityTests(unittest.TestCase):
    def test_every_intent_is_offered_an_image_at_creation(self):
        flows = PRODUCTS.split("const WIZARD_FLOWS = {", 1)[1].split("};", 1)[0]
        for intent in ("transaction", "lead_gen", "tip_jar"):
            line = next(row for row in flows.splitlines() if row.strip().startswith(f"{intent}:"))
            self.assertIn('"image"', line, intent)

    def test_the_edit_form_lets_every_intent_change_it(self):
        """The gate that made it a one-way door. Asserted on the SECTION wrapping the field, because that
        is where it sat -- the field itself never carried a condition."""
        section = re.search(r'<section([^>]*)class="modal-form-section">\s*\n\s*<ProductImagesField',
                            PRODUCTS)
        self.assertIsNotNone(section, "the edit form's image section moved; this test needs updating")
        self.assertNotIn("product_intent", section.group(1),
                         "the image section is gated by intent again — creation offers one to all three")

    def test_the_sections_that_are_gated_are_gated_for_a_reason(self):
        """Not an argument that gating is wrong, which would be false: a lead magnet has no price and
        nothing to post, so pricing and shipping genuinely do not apply to it. An image does."""
        self.assertIn('''v-if="form.product_intent === 'transaction' && form.product_type === 'physical'"''',
                      PRODUCTS)


class SellingPointParityTests(unittest.TestCase):
    """The one-line reason to buy (`Product.selling_point`), asked once on the product.

    A product description is usually pasted from a supplier and written for a marketplace listing, so a
    page that ranks this product beside others cannot argue for it from that alone. Asked here rather than
    on each page because it describes the THING -- every page that lists the product inherits the same
    sentence instead of the tenant rewriting one per listing.

    Both forms, for the reason this file exists: a value that can be set at creation and not corrected
    afterwards is a one-way door, and nothing fails when it closes.
    """

    def test_both_forms_offer_it(self):
        self.assertEqual(PRODUCTS.count('v-model.trim="form.selling_point"'), 2,
                         "the selling point must be in BOTH the wizard and the edit form")

    def test_it_is_capped_where_it_is_typed(self):
        """150 characters. It is printed verbatim beside a product, and a paragraph there reads as a
        second description -- the server rejects a longer one, so the form must not let one be typed."""
        self.assertEqual(PRODUCTS.count('maxlength="150"'), 2)

    def test_it_round_trips_through_the_form(self):
        """A field the form sends but never loads back is a value that silently empties on the next save."""
        self.assertIn('selling_point: product.selling_point || ""', PRODUCTS)
        self.assertIn('selling_point: "",', PRODUCTS)

    def test_the_store_omits_it_when_blank(self):
        """An empty string is authored-but-blank: it would suppress the Roundup entry's fallback instead
        of letting it apply."""
        store = (pathlib.Path(__file__).resolve().parents[1]
                 / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")
        self.assertIn('...(String(form.selling_point || "").trim()', store)


class SellingPointIsAValidProductFieldTests(unittest.TestCase):
    """`Product.schema.json` is `additionalProperties: false`, so a field the schema does not know about
    is a document the schema calls invalid -- and the validator is what the API actually enforces."""

    def test_the_schema_knows_it(self):
        import json
        with (pathlib.Path(__file__).resolve().parents[1] / "schemas" / "Product.schema.json").open() as handle:
            schema = json.load(handle)
        self.assertIn("selling_point", schema["properties"])
        self.assertEqual(schema["properties"]["selling_point"]["maxLength"], 150)

    def test_the_validator_accepts_one(self):
        from stripe_link.domain.documents import validate_product_document
        validate_product_document(_product(selling_point="Catches what a doorbell cam misses."))

    def test_the_validator_accepts_a_product_without_one(self):
        from stripe_link.domain.documents import validate_product_document
        validate_product_document(_product())

    def test_the_validator_refuses_a_paragraph(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_product_document
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(selling_point="x" * 151))

    def test_it_survives_the_canonical_field_ordering(self):
        """`order_product_document` rebuilds the document from a field list. A field missing from that
        list still survives (unknown keys are appended), but it lands after `tags` -- so it is named
        there deliberately, next to the description it stands beside."""
        from stripe_link.domain.documents import PRODUCT_FIELD_ORDER
        self.assertIn("selling_point", PRODUCT_FIELD_ORDER)
        self.assertEqual(PRODUCT_FIELD_ORDER.index("selling_point"),
                         PRODUCT_FIELD_ORDER.index("description") + 1)


def _product(**extra):
    """The shipped example product, with the field under test applied.

    Built from `schemas/examples/` rather than hand-rolled, for the reason test_cogs_at_checkout records
    after failing three times on fields it had no opinion about: a fixture assembled by hand drifts from
    what the validator actually requires, and then the test is about the fixture.
    """
    import json
    examples = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples"
    document = json.loads(next(examples.glob("product-*.json")).read_text(encoding="utf-8"))
    document.update(extra)
    return document
