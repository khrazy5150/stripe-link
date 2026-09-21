"""A product's OWN size, distinct from the box it ships in.

`fulfillment.dimensions` has always been the BOX — ProductVariantsField heads it "Package Dimensions" and
its docstring calls it "the box the thing ships in", and the default 10x8x4 is box-shaped. That works for a
single-item order and is exactly why a bundle cannot be packed: three products each declaring a box do not
compose, because boxes do not add.

So item_dimensions is ADDED rather than the existing field being reinterpreted. Every stored value out
there is a box; reading them as item sizes would choose a box big enough to hold a box and oversize every
parcel.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_product_document
from stripe_link.domain.shipping import packable_items
from stripe_link.domain.shipping_packing import pack

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"
BOXES = [{"name": "medium", "length": 12, "width": 10, "height": 6, "empty_weight": 0.3}]


def _product(**fulfillment):
    base = {"requires_shipping": True, "ship_from": None, "weight_lb": 1,
            "dimensions": {"length_in": 10, "width_in": 8, "height_in": 4}}
    return {"fulfillment": {**base, **fulfillment}}


class ValidationTests(unittest.TestCase):
    """Through the real entry point with a real fixture, so a failure is THIS rule failing rather than an
    unrelated required field missing from a hand-built product."""

    FIXTURE = json.loads((ROOT / "schemas/examples/product-simple-coffee.json").read_text(encoding="utf-8"))

    def _product_with(self, item_dimensions):
        product = json.loads(json.dumps(self.FIXTURE))
        product["fulfillment"]["item_dimensions"] = item_dimensions
        return product

    def test_the_fixture_is_valid_to_begin_with(self):
        # Guards the guard: if the fixture stopped validating, every refusal below would pass for the
        # wrong reason.
        validate_product_document(json.loads(json.dumps(self.FIXTURE)))

    def test_item_dimensions_are_optional(self):
        # A tenant who only ever ships one thing at a time never needs them.
        self.assertNotIn("item_dimensions", self.FIXTURE["fulfillment"])

    def test_a_complete_item_size_is_accepted(self):
        validate_product_document(self._product_with({"length_in": 4, "width_in": 4, "height_in": 5}))

    def test_absent_sides_mean_unmeasured_and_are_allowed(self):
        validate_product_document(self._product_with({"length_in": None, "width_in": None, "height_in": None}))

    def test_zero_is_refused_rather_than_treated_as_unknown(self):
        """A zero-sized item fits anything and would quietly choose a box far too small for what is
        actually in it. The message names the field, or a tenant cannot tell which number is wrong."""
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_document(self._product_with({"length_in": 0, "width_in": 4, "height_in": 5}))
        self.assertIn("item_dimensions.length_in", str(caught.exception))

    def test_junk_is_refused_by_name_too(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_document(self._product_with({"length_in": "big", "width_in": 4, "height_in": 5}))
        self.assertIn("item_dimensions.length_in", str(caught.exception))

    def test_a_non_object_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(self._product_with("4x4x5"))


class PackablesTests(unittest.TestCase):
    PRODUCTS = {
        "jar": _product(item_dimensions={"length_in": 4, "width_in": 4, "height_in": 5}),
        "ebook": {"fulfillment": {"requires_shipping": False, "weight_lb": None,
                                  "dimensions": {"length_in": None, "width_in": None, "height_in": None}}},
        "unmeasured": _product(),
    }

    def test_a_download_is_not_a_parcel(self):
        items = packable_items([{"product_id": "ebook", "quantity": 1}], self.PRODUCTS)
        self.assertEqual(items, [])

    def test_one_item_still_honours_the_declared_box(self):
        """The seller knows their own operation and is not second-guessed."""
        parcels = pack(packable_items([{"product_id": "jar", "quantity": 1}], self.PRODUCTS), BOXES)
        self.assertEqual(parcels[0]["strategy"], "declared")
        self.assertEqual((parcels[0]["length"], parcels[0]["width"], parcels[0]["height"]), (10.0, 8.0, 4.0))

    def test_several_items_pack_into_one_box_now_that_sizes_exist(self):
        parcels = pack(packable_items([{"product_id": "jar", "quantity": 3}], self.PRODUCTS), BOXES)
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["strategy"], "packed")

    def test_an_unmeasured_product_falls_back_rather_than_guessing(self):
        # No item size, so the order ships as separate parcels — over-estimating, which is the safe way.
        parcels = pack(packable_items([{"product_id": "jar", "quantity": 1},
                                       {"product_id": "unmeasured", "quantity": 1}], self.PRODUCTS), BOXES)
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})

    def test_quantity_reaches_the_packer(self):
        items = packable_items([{"product_id": "jar", "quantity": 4}], self.PRODUCTS)
        self.assertEqual(items[0]["quantity"], 4)


class FormTests(unittest.TestCase):
    FIELD = (DASH / "components/products/ProductVariantsField.vue").read_text(encoding="utf-8")
    STORE = (DASH / "stores/products.js").read_text(encoding="utf-8")
    PAGE = (DASH / "components/Products.vue").read_text(encoding="utf-8")

    def test_the_two_sections_are_distinguishable(self):
        """Both are three numbers in inches. Unlabelled, a tenant cannot tell which is which — and the
        wrong one silently oversizes every parcel."""
        self.assertIn("Package Dimensions", self.FIELD)
        self.assertIn("Item Size", self.FIELD)
        self.assertIn("The product's own size, out of its box", self.FIELD)

    def test_item_size_is_marked_optional(self):
        self.assertIn("field-optional", self.FIELD)

    def test_the_item_size_has_no_default(self):
        """10x8x4 is a reasonable guess at a BOX and a meaningless guess at a product. A guessed item size
        would pick a box for contents nobody measured."""
        self.assertIn("item_length_in: null", self.PAGE)
        self.assertNotIn("item_length_in: 10", self.PAGE)

    def test_a_partial_item_size_is_not_saved(self):
        # Half a measurement packs against a box chosen from an incomplete shape.
        block = self.STORE.split("function itemDimensions(", 1)[1][:400]
        self.assertIn("every((value) => Number.isFinite(value) && value > 0)", block)
        self.assertIn("return null", block)

    def test_editing_a_product_without_one_leaves_the_field_blank(self):
        self.assertIn("itemDimensions.length_in ?? null", self.PAGE)


if __name__ == "__main__":
    unittest.main()
