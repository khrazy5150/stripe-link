"""Why that box — the explanation, not the decision.

A correct packing answer can read exactly like a bug. A single Protein Shaker Bottle rated as a 14x11x8
Large box was reported as broken on 2026-10-05, and the packer was right: the bottle is 10.2in tall, the
tenant's Medium box's longest side is 10in, and it misses by **two tenths of an inch**. Nothing on screen
could say so, so "the software is wrong" was the only conclusion available.

`box_shortfall` changes no packing decision. It only answers the question the screen could not.
"""
import unittest

from stripe_link.domain.shipping_packing import box_shortfall, pack


BOXES = [
    {"name": "Small box (6x4x4)", "length": 6, "width": 4, "height": 4},
    {"name": "Medium box (10x8x6)", "length": 10, "width": 8, "height": 6},
    {"name": "Large box (14x11x8)", "length": 14, "width": 11, "height": 8},
    {"name": "Extra large box (18x14x12)", "length": 18, "width": 14, "height": 12},
]


def unit(product_id, length, width, height, **extra):
    return {"product_id": product_id, "quantity": 1, "weight": 1,
            "length": length, "width": width, "height": height, **extra}


class BoxShortfallTests(unittest.TestCase):
    def test_the_real_case_two_tenths_of_an_inch(self):
        """The bottle the author reported. 10.2in against a 10in box."""
        bottle = [unit("bottle", 3.7, 3.7, 10.2)]
        parcels = pack(bottle, BOXES)
        chosen = parcels[0].get("box_name") or parcels[0].get("box")
        self.assertEqual(chosen, "Large box (14x11x8)", "precondition: the Large really is the only fit")

        reason = box_shortfall(bottle, BOXES, chosen)
        self.assertEqual(reason["product_id"], "bottle")
        self.assertEqual(reason["box"], "Medium box (10x8x6)")
        self.assertEqual(reason["longest_in"], 10.2)
        self.assertEqual(reason["over_by"], 0.2)

    def test_it_reports_against_the_next_box_down_not_the_smallest(self):
        """The near miss is the actionable one. "It does not fit your Small box" explains nothing."""
        reason = box_shortfall([unit("bottle", 3.7, 3.7, 10.2)], BOXES, "Large box (14x11x8)")
        self.assertEqual(reason["box"], "Medium box (10x8x6)")

    def test_an_item_that_fits_the_smaller_box_has_nothing_to_explain(self):
        """Something else put it in that box — quantity, or another item — and naming a dimension that
        fits would be an explanation that is simply untrue."""
        self.assertIsNone(box_shortfall([unit("small", 2, 2, 2)], BOXES, "Large box (14x11x8)"))

    def test_the_smallest_box_has_no_smaller_box_to_miss(self):
        self.assertIsNone(box_shortfall([unit("tiny", 1, 1, 1)], BOXES, "Small box (6x4x4)"))

    def test_it_blames_the_item_with_the_largest_overhang(self):
        """With several misfits the one that forced the box is the worst one, not the first one seen."""
        units = [unit("slightly", 3, 3, 10.4), unit("badly", 3, 3, 13)]
        reason = box_shortfall(units, BOXES, "Large box (14x11x8)")
        self.assertEqual(reason["product_id"], "badly")
        self.assertEqual(reason["over_by"], 3.0)

    def test_it_measures_the_way_the_fit_test_measures(self):
        """Both sorted, compared axis by axis — a 10.2x3.7x3.7 item is over by 0.2, not by 10.2 - 6."""
        reason = box_shortfall([unit("bottle", 10.2, 3.7, 3.7)], BOXES, "Large box (14x11x8)")
        self.assertEqual(reason["over_by"], 0.2)

    def test_an_unmeasured_item_is_skipped_rather_than_guessed_at(self):
        units = [{"product_id": "nodims", "quantity": 1}, unit("bottle", 3.7, 3.7, 10.2)]
        reason = box_shortfall(units, BOXES, "Large box (14x11x8)")
        self.assertEqual(reason["product_id"], "bottle")

    def test_an_unknown_chosen_box_explains_nothing(self):
        self.assertIsNone(box_shortfall([unit("bottle", 3.7, 3.7, 10.2)], BOXES, "Not a box"))


class BoxReasonInThePreviewTests(unittest.TestCase):
    """Single-parcel only: with several parcels "which box and why" has several answers, and picking one
    turns a helpful note into a misleading one."""

    def test_it_is_withheld_when_there_is_more_than_one_parcel(self):
        from handlers.shipping import _box_reason

        products = {"bottle": {"name": "Protein Shaker Bottle", "product_type": "physical",
                               "fulfillment": {"item_dimensions": {
                                   "length_in": 3.7, "width_in": 3.7, "height_in": 10.2, "weight_lb": 0.4}}}}
        lines = [{"product_id": "bottle", "quantity": 1}]
        two = [{"box_name": "Large box (14x11x8)"}, {"box_name": "Large box (14x11x8)"}]
        self.assertEqual(_box_reason(lines, products, two, BOXES), {})

    def test_it_names_the_product_a_tenant_would_recognise(self):
        from handlers.shipping import _box_reason

        products = {"bottle": {"name": "Protein Shaker Bottle", "product_type": "physical",
                               "fulfillment": {"item_dimensions": {
                                   "length_in": 3.7, "width_in": 3.7, "height_in": 10.2, "weight_lb": 0.4}}}}
        lines = [{"product_id": "bottle", "quantity": 1}]
        out = _box_reason(lines, products, [{"box_name": "Large box (14x11x8)"}], BOXES)
        self.assertEqual(out["box_reason"]["product_name"], "Protein Shaker Bottle")
        self.assertEqual(out["box_reason"]["over_by"], 0.2)


if __name__ == "__main__":
    unittest.main()
