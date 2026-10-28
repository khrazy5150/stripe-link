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
