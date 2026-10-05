"""The builder's half of the order-bump postage surcharge.

The server enforces that `shipping_surcharge` only exists on an `order_bump` price (any other price can be
bought as an ordinary cart line, which is already inside the live shipping quote, so folding postage in
would charge it twice). A builder that could write one anywhere would turn that rule into a save error the
tenant cannot explain, so the same confinement is asserted here on the source that writes the document.
"""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRICING_STORE = ROOT / "dashboard" / "src" / "stores" / "pricing.js"
PRICE_FORM = ROOT / "dashboard" / "src" / "utils" / "priceForm.js"
PRICING_CARD = ROOT / "dashboard" / "src" / "components" / "shared" / "PricingCard.vue"


class BumpPostageBuilderTests(unittest.TestCase):
    def test_the_document_writer_confines_the_surcharge_to_order_bump(self):
        source = PRICING_STORE.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r'price\.context === "order_bump"[^\n]*price\.shipping_surcharge',
            "the surcharge must only be written onto an order_bump price",
        )

    def test_the_document_writer_omits_a_zero_surcharge(self):
        """Absent, not zero. Nearly every price has no postage folded in, and a stored 0 on all of them
        would be noise in every product document for the sake of one field on one kind of price."""
        source = PRICING_STORE.read_text(encoding="utf-8")
        self.assertIn("bumpPostage > 0", source)

    def test_the_form_round_trips_cents_to_dollars(self):
        source = PRICE_FORM.read_text(encoding="utf-8")
        self.assertIn("shipping_surcharge: 0", source, "the form needs a default")
        self.assertRegex(
            source, r"shipping_surcharge:[^\n]*shipping_surcharge \|\| 0\)\) / 100",
            "the stored value is cents and the field is dollars",
        )

    def test_the_field_is_only_offered_where_it_can_apply(self):
        """A bump price on something that physically ships. Offering it anywhere else invites a save the
        server will refuse."""
        source = PRICING_CARD.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"v-if=\"price\.context === 'order_bump' && productType === 'physical'\"",
            "the surcharge input must be gated on an order_bump price for a physical product",
        )
        self.assertIn('v-model.number="price.shipping_surcharge"', source)

    def test_the_field_explains_why_it_exists(self):
        """The tenant has no way to discover that Stripe fixes shipping before the bump is offered, so the
        field has to say it. A bare number here would read as an arbitrary upcharge."""
        source = PRICING_CARD.read_text(encoding="utf-8")
        note = re.search(r"Extra postage for this bump(.*?)</label>", source, re.S)
        self.assertIsNotNone(note, "the surcharge field is missing")
        self.assertIn("field-note", note.group(1), "the field needs its explanation")
        self.assertIn("already", note.group(1).lower())


if __name__ == "__main__":
    unittest.main()
