"""A declared shipping box belongs only to a product that ships in one.

The builder used to write `fulfillment.dimensions` onto EVERY physical product, defaulting to 10x8x4 at
1 lb whenever the fields were empty — and those fields are hidden unless "Always ships in its own box" is
ticked. So a box the tenant never chose, could not see, and could not be warned about was dictating
parcels. In one real catalogue 12 of 13 products carried it (2026-10-06).

The damage was not the box. A declared PACKED WEIGHT outranks the item's own, so an Electric Scooter
weighing 37 lb was rated at the default-derived 26.5, and 2 lb of whey at 1 lb. A carrier re-bills an
under-weight parcel weeks after the label is paid for.
"""
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_product_document
from stripe_link.domain.shipping import packable_items
from stripe_link.domain.shipping_packing import _weight


def product(product_id, *, ships_alone=False, package=None, packed_lb=None, bare_lb=None):
    fulfillment = {
        "requires_shipping": True, "ship_from": None, "ships_alone": ships_alone,
        "weight_lb": packed_lb, "dimensions": package,
        "item_dimensions": {"length_in": 4, "width_in": 4, "height_in": 4, "weight_lb": bare_lb}
        if bare_lb is not None else None,
    }
    return {"product_id": product_id, "name": product_id, "product_type": "physical",
            "fulfillment": fulfillment}


BOX = {"length_in": 10, "width_in": 8, "height_in": 4}


class WeightCannotShrinkTests(unittest.TestCase):
    def test_a_box_never_makes_its_contents_lighter(self):
        """The scooter: 26.5 lb declared, 37 lb of scooter inside it. Arithmetic, not a safety margin."""
        self.assertEqual(_weight({"weight": 26.5, "item_weight": 37}), 37.0)

    def test_a_believable_packed_weight_still_wins(self):
        """A real packed weight exceeds the bare one — it includes the box — and must not be discarded."""
        self.assertEqual(_weight({"weight": 1.0, "item_weight": 0.4}), 1.0)

    def test_a_declared_package_weight_still_wins_when_believable(self):
        self.assertEqual(_weight({"package": {"weight": 115}, "item_weight": 114}), 115.0)

    def test_with_no_packed_weight_the_bare_weight_carries_the_parcel(self):
        """Zero is the one answer a parcel must never have: a carrier refuses the label or re-bills it."""
        self.assertEqual(_weight({"item_weight": 0.4}), 0.4)

    def test_nothing_known_is_still_zero(self):
        """Unchanged, and handled upstream — an unmeasured product ships free rather than being guessed."""
        self.assertEqual(_weight({}), 0.0)


class DeclaredPackageIsOptInTests(unittest.TestCase):
    def test_a_box_is_ignored_unless_the_product_ships_alone(self):
        """Gated here as well as in the builder, because the stale documents already exist — this makes
        them inert without waiting for anything to be re-saved."""
        items = packable_items([{"product_id": "p", "quantity": 1}],
                               {"p": product("p", ships_alone=False, package=BOX, packed_lb=1, bare_lb=0.4)})
        self.assertNotIn("package", items[0])

    def test_a_box_is_used_when_the_product_does_ship_alone(self):
        items = packable_items([{"product_id": "p", "quantity": 1}],
                               {"p": product("p", ships_alone=True, package=BOX, packed_lb=1, bare_lb=0.4)})
        self.assertEqual(items[0]["package"]["length"], 10)


class ValidationAllowsNoBoxTests(unittest.TestCase):
    """`None` is the ordinary case. It used to be mandatory, which is exactly why the builder invented a
    default to satisfy it."""

    def _document(self, package):
        return {
            "document_type": "product", "schema_version": "2026-05-29", "tenant_id": "t",
            "product_id": "p", "name": "P", "product_type": "physical", "status": "active",
            "canonical": {"name": "P"}, "default_price_id": "pr1",
            "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 100}],
            "fulfillment": {"requires_shipping": True, "ship_from": None, "weight_lb": None,
                            "dimensions": package},
        }

    def test_a_product_with_no_declared_box_validates(self):
        try:
            validate_product_document(self._document(None))
        except DocumentValidationError as exc:
            if "dimensions" in str(exc):
                self.fail(f"a null box must be allowed: {exc}")

    def test_a_partial_box_is_still_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(self._document({"length_in": 10, "width_in": 8}))


if __name__ == "__main__":
    unittest.main()


class TheBuilderStopsInventingABoxTests(unittest.TestCase):
    """Asserted on the source that writes the document, because this is where the defaults lived:
    `Number(form.length_in || 10)`, `|| 8`, `|| 4`, `|| 1` — applied to every physical product."""

    from pathlib import Path as _Path
    STORE = (_Path(__file__).resolve().parents[1] / "dashboard" / "src" / "stores" / "products.js"
             ).read_text(encoding="utf-8")
    FIELD = (_Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components" / "products"
             / "ProductVariantsField.vue").read_text(encoding="utf-8")

    def test_the_legacy_dimension_defaults_are_gone(self):
        for default in ("form.length_in || 10", "form.width_in || 8", "form.height_in || 4",
                        "form.weight_lb || 1"):
            with self.subTest(default=default):
                self.assertNotIn(default, self.STORE)

    def test_the_box_is_written_only_when_the_product_ships_alone(self):
        block = self.STORE.split("function declaredPackage", 1)[1].split("\n}", 1)[0]
        self.assertIn("form.ships_alone", block)
        self.assertIn("dimensions: null", block)

    def test_a_partial_box_writes_nothing(self):
        """Saved and hidden, it would rate parcels from numbers nobody finished entering."""
        block = self.STORE.split("function declaredPackage", 1)[1].split("\n}", 1)[0]
        self.assertIn("sides.some", block)

    def test_unticking_clears_the_four_fields(self):
        """Anything left behind is invisible to the tenant and still live to the packer."""
        block = self.FIELD.split("watch(() => props.form.ships_alone", 1)[1].split("});", 1)[0]
        for field in ("length_in", "width_in", "height_in", "weight_lb"):
            with self.subTest(field=field):
                self.assertIn(f"props.form.{field} = null", block)

    def test_an_incomplete_box_is_called_out(self):
        self.assertIn("declaredBoxIncomplete", self.FIELD)
