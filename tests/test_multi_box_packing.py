"""Packing an order into SEVERAL catalog boxes, not one or none.

plans/SHIPPING_ELEMENT.md phase 7. The packer had two outcomes: everything in one shared box, or *"one parcel
per thing... the honest fallback"* with no box at all. The gap between them is where a bundle lives — a cart
that outgrows one box but that a warehouse would obviously pack into two.

That gap had a cost: the per-item fallback assigns no box, so a flat-rate-box price has nothing to look up and
a bundle could not be quoted at all.

First-fit-decreasing, reusing `_best_box` rather than testing fit a second way — this module's own docstring
warns that two implementations of "what parcel is this" would disagree, and the one that priced the order would
not be the one that bought the label.
"""
import unittest

from stripe_link.domain.shipping_packing import pack

SMALL = {"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15}
MEDIUM = {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}
CATALOG = [SMALL, MEDIUM]

# Fits a Medium, not a Small. Two of them cannot share.
BIG = {"product_id": "big", "quantity": 1, "weight": 2.0, "item_weight": 2.0,
       "length": 9, "width": 7, "height": 5}
TINY = {"product_id": "tiny", "quantity": 1, "weight": 0.5, "item_weight": 0.4,
        "length": 3, "width": 2, "height": 2}
OVERSIZE = {"product_id": "crate", "quantity": 1, "weight": 30.0, "item_weight": 30.0,
            "length": 40, "width": 30, "height": 20}


def units(*specs):
    out = []
    for spec, count in specs:
        for index in range(count):
            out.append(dict(spec, product_id=f"{spec['product_id']}{index}"))
    return out


class ItFillsTheGapBetweenOneBoxAndNone(unittest.TestCase):
    def test_one_item_still_takes_the_single_box_path(self):
        parcels = pack(units((BIG, 1)), CATALOG)
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["box"], "Medium")
        self.assertEqual(parcels[0]["strategy"], "packed")

    def test_two_that_cannot_share_become_two_named_parcels(self):
        parcels = pack(units((BIG, 2)), CATALOG)
        self.assertEqual([p["box"] for p in parcels], ["Medium", "Medium"])
        self.assertEqual({p["strategy"] for p in parcels}, {"multi_box"})

    def test_every_parcel_names_its_box_which_is_the_whole_point(self):
        """A parcel with no box has no flat rate to look up."""
        for parcel in pack(units((BIG, 3)), CATALOG):
            self.assertTrue(parcel["box"])

    def test_smaller_items_fill_boxes_already_open(self):
        """First-fit-DECREASING: the big items claim parcels, then the small ones tuck in rather than opening
        parcels of their own."""
        parcels = pack(units((BIG, 2), (TINY, 2)), CATALOG)
        self.assertEqual(len(parcels), 2)
        self.assertEqual({p["box"] for p in parcels}, {"Medium"})

    def test_each_parcel_carries_its_own_box_weight(self):
        """A box is not weightless and the carrier bills the whole parcel -- once per parcel, not once per
        order."""
        parcels = pack(units((BIG, 2)), CATALOG)
        for parcel in parcels:
            self.assertAlmostEqual(parcel["weight"], 2.0 + 0.35, places=3)

    def test_what_packed_from_records(self):
        parcels = pack(units((BIG, 2)), CATALOG)
        packed_from = sorted(pid for parcel in parcels for pid in parcel["packed_from"])
        self.assertEqual(packed_from, ["big0", "big1"])


class WhenItMustNotApply(unittest.TestCase):
    def test_an_oversized_item_falls_through_to_per_item(self):
        """Splitting the rest into boxes and leaving one homeless would report a parcel count nobody can
        actually post."""
        parcels = pack(units((OVERSIZE, 1), (BIG, 2)), CATALOG)
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})
        self.assertEqual({p["box"] for p in parcels}, {""})

    def test_no_catalog_still_falls_back(self):
        parcels = pack(units((BIG, 2)), [])
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})

    def test_items_without_dimensions_produce_NO_parcels_at_all(self):
        """The module's own rule: *"Returns [] when nothing is known rather than inventing a parcel: a
        made-up box buys a label at the wrong postage."* Multi-box must not soften that -- an empty list is
        what makes `packed_box_price` answer `no_dimensions` instead of guessing."""
        self.assertEqual(pack([{"product_id": "x", "quantity": 2, "weight": 1.0}], CATALOG), [])

    def test_a_single_group_is_never_reported_as_multi_box(self):
        """Strategy 2 already tried one box and failed; re-reporting one group here would claim a different
        answer to the same question."""
        for parcel in pack(units((TINY, 3)), CATALOG):
            self.assertNotEqual(parcel["strategy"], "multi_box")

    def test_a_weight_limit_is_respected_per_box(self):
        """A carrier refuses an over-weight parcel at the counter -- after the label is paid for."""
        capped = [dict(MEDIUM, max_weight=3.0)]
        parcels = pack(units((BIG, 2)), capped)
        # 2.0 + 0.35 fits one; two would not, so they must not share.
        self.assertEqual(len(parcels), 2)
        for parcel in parcels:
            self.assertLessEqual(parcel["weight"], 3.0)


class TheSingleBoxPathIsUnchanged(unittest.TestCase):
    """`_best_box` was extracted from the existing strategy, so its answers must not move."""

    def test_several_small_items_still_share_one_box(self):
        parcels = pack(units((TINY, 3)), CATALOG)
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["strategy"], "packed")

    def test_the_smallest_sufficient_box_is_still_chosen(self):
        parcels = pack(units((TINY, 1)), CATALOG)
        self.assertEqual(parcels[0]["box"], "Small")


if __name__ == "__main__":
    unittest.main()
