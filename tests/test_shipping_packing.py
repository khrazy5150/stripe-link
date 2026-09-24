"""Packing an order into parcels (plans/SHIPPING_PROVIDERS.md P1).

Weight is additive. Dimensions are not. Carriers bill max(actual, dimensional) weight, so three items in
one carton cost neither three parcels nor one item -- which is why a bundle cannot be priced by summing its
products, and why this exists at all.

It is an approximation on purpose: real 3D bin packing is NP-hard and not worth solving for a seller
shipping a few orders a day. The approximation's limits are pinned below so that when estimates come out
wrong, the packer is suspected before the rates.

Shared by the label buyer, the price estimator and the carrier calculator. Three implementations of "what
parcel is this" would disagree, and the one that priced the order would not be the one that bought it.
"""
import unittest

from stripe_link.domain.shipping_packing import (
    DEFAULT_VOID_FILL,
    SOFT_PACK,
    fits_inside,
    pack,
)

BOXES = [
    {"name": "mailer", "length": 9, "width": 6, "height": 3, "empty_weight": 0.1},
    {"name": "medium", "length": 12, "width": 10, "height": 6, "empty_weight": 0.3},
    {"name": "large", "length": 18, "width": 14, "height": 12, "empty_weight": 0.7},
]
JAR = {"product_id": "gummies", "quantity": 1, "weight": 1.0, "length": 4, "width": 4, "height": 5}
FLAT = {"product_id": "print", "quantity": 1, "weight": 0.2, "length": 8, "width": 5, "height": 0.2}


class FitTests(unittest.TestCase):
    def test_an_item_may_be_turned(self):
        # A 10x2x2 rod goes in a 3x3x11 box on its side.
        self.assertTrue(fits_inside((10, 2, 2), (3, 3, 11)))

    def test_volume_alone_would_get_it_wrong(self):
        """40 cubic inches into 216 says yes; the 10-inch side says no. This is why fit is checked per
        dimension and not by volume."""
        self.assertFalse(fits_inside((10, 2, 2), (6, 6, 6)))

    def test_an_exact_fit_counts_as_fitting(self):
        self.assertTrue(fits_inside((4, 4, 5), (5, 4, 4)))


class SingleItemTests(unittest.TestCase):
    def test_a_declared_package_is_never_second_guessed(self):
        """A seller who knows everything goes in a 10x8x4 keeps saying so."""
        parcel = pack([{**JAR, "package": {"length": 10, "width": 8, "height": 4, "weight": 1.4}}], BOXES)[0]
        self.assertEqual(parcel["strategy"], "declared")
        self.assertEqual((parcel["length"], parcel["width"], parcel["height"]), (10.0, 8.0, 4.0))

    def test_the_declared_weight_is_the_shipped_weight_not_an_addition(self):
        # The form asks for the package's weight -- the thing as shipped, box included. Adding the item's
        # weight on top would bill the contents twice.
        parcel = pack([{**JAR, "package": {"length": 10, "width": 8, "height": 4, "weight": 1.4}}], BOXES)[0]
        self.assertEqual(parcel["weight"], 1.4)

    def test_a_declared_package_with_no_weight_falls_back_to_the_item(self):
        parcel = pack([{**JAR, "package": {"length": 10, "width": 8, "height": 4}}], BOXES)[0]
        self.assertEqual(parcel["weight"], 1.0)

    def test_with_no_declared_package_a_box_is_chosen(self):
        parcel = pack([JAR], BOXES)[0]
        self.assertEqual(parcel["strategy"], "packed")
        self.assertEqual(parcel["box"], "medium")

    def test_the_mailer_is_refused_because_the_jar_is_too_tall(self):
        """The mailer has the volume (162 > 80 x 1.25) and not the height: a 5-inch jar does not go in a
        3-inch box. Volume would have chosen it."""
        self.assertNotEqual(pack([JAR], BOXES)[0]["box"], "mailer")

    def test_a_flat_item_gets_the_small_box(self):
        self.assertEqual(pack([FLAT], BOXES)[0]["box"], "mailer")


class BundleTests(unittest.TestCase):
    def test_several_things_go_in_ONE_box(self):
        """The whole point. Summing three products' package dimensions is not a parcel."""
        parcels = pack([{**JAR, "quantity": 3}], BOXES)
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["packed_from"], ["gummies", "gummies", "gummies"])

    def test_quantity_three_is_three_objects_not_one_heavier_one(self):
        parcel = pack([{**JAR, "quantity": 3}], BOXES)[0]
        self.assertAlmostEqual(parcel["weight"], 3.0 + 0.3, places=2)  # + the box's own weight

    def test_the_box_is_not_weightless(self):
        # The carrier bills the whole parcel, cardboard included.
        self.assertAlmostEqual(pack([JAR], BOXES)[0]["weight"], 1.0 + 0.3, places=2)

    def test_void_fill_is_applied_so_the_box_is_not_chosen_by_naked_volume(self):
        # Things do not interlock; packing is not tessellation.
        self.assertGreater(DEFAULT_VOID_FILL, 1.0)
        # 8 jars = 640 in3 raw, 800 with fill -- over medium's 720, so it must step up.
        self.assertEqual(pack([{**JAR, "quantity": 8}], BOXES)[0]["box"], "large")

    def test_something_too_big_for_every_box_falls_back_to_one_parcel_each(self):
        oversized = {"product_id": "surfboard", "quantity": 1, "weight": 12, "length": 84, "width": 22, "height": 4}
        parcels = pack([JAR, oversized], BOXES)
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})
        self.assertEqual(len(parcels), 2)


class FallbackTests(unittest.TestCase):
    def test_no_catalog_means_one_parcel_each(self):
        parcels = pack([JAR, FLAT], [])
        self.assertEqual(len(parcels), 2)
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})

    def test_an_item_with_no_dimensions_of_its_own_uses_its_declared_package(self):
        parcels = pack([{"product_id": "x", "quantity": 1, "weight": 2,
                         "package": {"length": 10, "width": 8, "height": 4}},
                        JAR], BOXES)
        self.assertEqual(len(parcels), 2)
        self.assertEqual(parcels[0]["length"], 10.0)

    def test_nothing_known_invents_nothing(self):
        """A made-up box buys a label at the wrong postage, which the carrier bills for or the parcel
        comes back for. Returning nothing lets the caller say so."""
        self.assertEqual(pack([{"product_id": "x", "quantity": 1, "weight": 1}], BOXES), [])
        self.assertEqual(pack([], BOXES), [])

    def test_zero_and_junk_dimensions_do_not_become_a_parcel(self):
        for bad in ({"length": 0, "width": 5, "height": 5}, {"length": "wide", "width": 5, "height": 5},
                    {"length": 5, "width": 5}):
            with self.subTest(bad=bad):
                self.assertEqual(pack([{"product_id": "x", "quantity": 1, "weight": 1, **bad}], BOXES), [])

    def test_either_dimension_naming_is_accepted(self):
        # The Product document says length_in/width_in/height_in; a parcel says length/width/height.
        parcel = pack([{"product_id": "x", "quantity": 1, "weight": 1,
                        "length_in": 4, "width_in": 4, "height_in": 5}], BOXES)[0]
        self.assertEqual(parcel["box"], "medium")


class WeightLimitTests(unittest.TestCase):
    """A box has a weight limit as well as a size.

    USPS flat rate caps at 70 lb. A carrier refuses an over-weight parcel at the counter -- AFTER the label
    is bought and paid for -- so the limit has to be honoured when the box is chosen, not discovered later.
    """

    FLAT = {"name": "USPS Small Flat Rate", "length": 8.6, "width": 5.4, "height": 1.6,
            "empty_weight": 0.1, "max_weight": 70}
    CARTON = {"name": "heavy carton", "length": 12, "width": 10, "height": 6,
              "empty_weight": 0.5, "max_weight": 150}
    BAR = {"product_id": "bar", "quantity": 1, "weight": 80, "length": 6, "width": 4, "height": 1}

    def test_a_box_it_fits_but_cannot_carry_is_refused(self):
        self.assertEqual(pack([self.BAR], [self.FLAT])[0]["strategy"], "per_item")

    def test_a_box_that_can_carry_it_is_chosen_instead(self):
        self.assertEqual(pack([self.BAR], [self.FLAT, self.CARTON])[0]["box"], "heavy carton")

    def test_the_boxs_own_weight_counts_toward_its_limit(self):
        # 69.95 of contents plus 0.1 of cardboard is over 70.
        heavy = {**self.BAR, "weight": 69.95}
        self.assertEqual(pack([heavy], [self.FLAT])[0]["strategy"], "per_item")

    def test_a_box_with_no_stated_limit_is_not_assumed_to_have_one(self):
        # Most tenant-supplied cartons will not state one; refusing them would be worse than trusting them.
        unlimited = {k: v for k, v in self.CARTON.items() if k != "max_weight"}
        self.assertEqual(pack([self.BAR], [unlimited])[0]["box"], "heavy carton")


class KnownLimitTests(unittest.TestCase):
    def test_two_items_that_each_fit_may_not_fit_together(self):
        """The approximation's known limit, pinned so it is not mistaken for a bug later.

        Two 8-inch rods each fit the mailer, and their volumes clear it, so they are packed together --
        which real packing might not allow. Recorded rather than solved: 3D bin packing is NP-hard, and
        calibration (estimate vs actual label cost) is how we find out whether it matters.
        """
        rod = {"product_id": "rod", "quantity": 2, "weight": 0.1, "length": 8, "width": 1, "height": 1}
        parcels = pack([rod], BOXES)
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["box"], "mailer")


if __name__ == "__main__":
    unittest.main()


POUCH = {"product_id": "beta_alanine", "quantity": 1, "item_weight": 0.9,
         "length": 8, "width": 5, "height": 2, "compressible": True}
MAILER = {"name": "bubble mailer", "kind": "soft_pack", "length": 9, "width": 6, "height": 1,
          "empty_weight": 0.05}


class SoftPackTests(unittest.TestCase):
    """A Beta-Alanine pouch goes in a bubble mailer, not a carton.

    The catalog has had a padded mailer since it was written, which made envelopes LOOK handled. They were
    not: `fits_inside` is strict and axis-aligned, so an 8x5x2 pouch failed a 9x6x1 mailer on `2 > 1` and
    the packer climbed to a carton — overcharging every order containing one.
    """

    def test_a_compressible_item_may_exceed_a_soft_pack_thickness(self):
        self.assertTrue(fits_inside((8, 5, 2), (9, 6, 1), box_kind=SOFT_PACK, compressible=True))

    def test_the_same_item_is_refused_by_a_rigid_box_of_those_dimensions(self):
        # The exception is about the PACKAGING, not about being lenient in general.
        self.assertFalse(fits_inside((8, 5, 2), (9, 6, 1)))

    def test_a_rigid_item_is_still_refused_by_a_soft_pack(self):
        # A jar does not squash. Letting it through fails at the counter, after the label is paid for.
        self.assertFalse(fits_inside((4, 4, 5), (9, 6, 1), box_kind=SOFT_PACK, compressible=True))

    def test_the_two_largest_dimensions_are_still_strict(self):
        # A pouch cannot be longer than the envelope however soft it is.
        self.assertFalse(fits_inside((11, 5, 0.5), (9, 6, 1), box_kind=SOFT_PACK, compressible=True))

    def test_the_thickness_allowance_is_bounded(self):
        # 3x a 1-inch mailer is 3 inches. A 4-inch item does not go in it however soft it is.
        self.assertTrue(fits_inside((8, 5, 3), (9, 6, 1), box_kind=SOFT_PACK, compressible=True))
        self.assertFalse(fits_inside((8, 5, 4), (9, 6, 1), box_kind=SOFT_PACK, compressible=True))

    def test_a_pouch_now_actually_packs_into_the_mailer(self):
        parcel = pack([POUCH], [MAILER, *BOXES])[0]

        self.assertEqual(parcel["strategy"], "packed")
        self.assertEqual(parcel["box"], "bubble mailer")

    def test_without_the_flag_it_climbs_to_a_carton(self):
        # The behaviour before this change, pinned so the cost of getting it wrong stays visible.
        rigid = {**POUCH, "compressible": False}

        self.assertNotEqual(pack([rigid], [MAILER, *BOXES])[0]["box"], "bubble mailer")


class SharedBoxWeightTests(unittest.TestCase):
    """The packaging was billed once per item.

    One weight field meant "the thing as shipped, box included", and the shared-box branch summed it per
    item and then added the shared box on top.
    """

    TUB = {"product_id": "tub", "quantity": 1, "weight": 1.0, "item_weight": 0.85,
           "length": 4, "width": 4, "height": 4}

    def test_bare_weights_are_summed_not_packed_ones(self):
        parcel = pack([self.TUB, {**self.TUB, "product_id": "tub2"},
                       {**self.TUB, "product_id": "tub3"}], BOXES)[0]

        # 3 x 0.85 bare + 0.3 for the box that actually ships = 2.85, not 3 x 1.0 + 0.3 = 3.3.
        self.assertEqual(parcel["weight"], 2.85)

    def test_a_product_with_no_bare_weight_over_estimates_rather_than_guessing(self):
        # Every product stored before `item_weight` existed hits this. Over-estimating is the safe
        # direction: a carrier re-bills or refuses an under-weight parcel after the label is bought.
        no_bare = {k: v for k, v in self.TUB.items() if k != "item_weight"}
        parcel = pack([no_bare, {**no_bare, "product_id": "b"}], BOXES)[0]

        self.assertEqual(parcel["weight"], 2.3)   # 2 x 1.0 packed + 0.3

    def test_the_declared_path_still_uses_the_packed_weight(self):
        # A thing shipping in its own box IS the packed weight; nothing is added to it.
        parcel = pack([{**self.TUB, "ships_alone": True,
                        "package": {"length": 6, "width": 6, "height": 6, "weight": 1.0}}], BOXES)[0]

        self.assertEqual(parcel["weight"], 1.0)


class ShipsAloneTests(unittest.TestCase):
    """A declared box is an exception, so it must not swallow the rest of the order."""

    ALONE = {"product_id": "poster", "quantity": 1, "weight": 2.0, "ships_alone": True,
             "package": {"name": "tube", "length": 26, "width": 4, "height": 4, "weight": 2.0}}

    def test_a_ships_alone_item_gets_its_own_parcel_and_the_rest_still_pack(self):
        parcels = pack([self.ALONE, JAR, {**JAR, "product_id": "jar2"}], BOXES)

        self.assertEqual(len(parcels), 2)
        by_strategy = {p["strategy"]: p for p in parcels}
        self.assertEqual(by_strategy["declared"]["packed_from"], ["poster"])
        self.assertEqual(sorted(by_strategy["packed"]["packed_from"]), ["gummies", "jar2"])

    def test_it_is_the_whole_order_when_nothing_else_is_there(self):
        parcels = pack([self.ALONE], BOXES)

        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["strategy"], "declared")

    def test_a_declared_package_WITHOUT_the_flag_does_not_split_the_order(self):
        # Backwards compatible: before this change a declared package only applied to a lone item, and
        # a multi-item order ignored it. That stays true unless the tenant opts in.
        not_alone = {k: v for k, v in self.ALONE.items() if k != "ships_alone"}
        parcels = pack([not_alone, JAR], BOXES)

        self.assertNotIn("declared", {p["strategy"] for p in parcels})

    def test_the_declared_thickness_is_what_it_will_MEASURE_when_stuffed(self):
        """Not the flat figure on the envelope. Under-declaring thickness is how a carrier re-bills
        dimensional weight after the label is bought."""
        parcel = pack([POUCH], [MAILER])[0]

        # 8x5x2 = 80 cu in, x1.25 void fill = 100, over a 9x6 footprint = 1.85in, not the nominal 1in.
        self.assertEqual(parcel["box"], "bubble mailer")
        self.assertGreater(parcel["height"], 1.0)
        self.assertLessEqual(parcel["height"], 3.0)   # and never beyond the allowance

    def test_a_rigid_item_in_the_order_stops_the_pack_bulging(self):
        # One jar in the envelope and it cannot be squashed for anything.
        parcels = pack([POUCH, {**JAR, "item_weight": 1.0}], [MAILER, *BOXES])

        self.assertNotEqual(parcels[0]["box"], "bubble mailer")
