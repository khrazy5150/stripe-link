"""Which tier sold — recorded, at last, from a pointer that was always in the payload.

A tiered offer prices 1 / 2 / 3 of a thing as three **Prices of the same product**. Stripe therefore
reports every one of them as `quantity: 1` under the product's name, so an order could not say which the
buyer chose — and "which tier converts" is most of why a tenant builds a tiered offer.

The key back was never missing. `build_price_params` stamps our own `price_id` into every Stripe Price's
metadata, and the webhook's line-item fetch already expands `data.price`. It was simply discarded.
"""
import unittest

from handlers.stripe_webhook import order_line_items_from_stripe
from stripe_link.domain.pricing import offer_price_tiers


OFFER = {"items": [{"product_id": "nad", "selectable_prices": [
    {"price_id": "price_one", "quantity": 1, "label": "1 Item"},
    {"price_id": "price_two", "quantity": 2, "label": "2 Items"},
    {"price_id": "price_three", "quantity": 3, "label": "3 Items"},
]}]}


def stripe_line(local_price_id, *, stripe_price_id="price_stripe", amount=4159, name="NAD Supplement"):
    return {"description": name, "amount_subtotal": amount, "amount_total": amount, "quantity": 1,
            "currency": "usd",
            "price": {"id": stripe_price_id, "metadata": {"price_id": local_price_id}}}


class OfferPriceTiersTests(unittest.TestCase):
    def test_it_reads_size_and_label_from_the_offer_alone(self):
        tiers = offer_price_tiers(OFFER)
        self.assertEqual(tiers["price_two"], {"quantity": 2, "label": "2 Items"})

    def test_a_choice_with_no_label_still_carries_its_size(self):
        tiers = offer_price_tiers({"items": [{"selectable_prices": [{"price_id": "p", "quantity": 4}]}]})
        self.assertEqual(tiers["p"], {"quantity": 4})

    def test_an_absent_offer_is_no_tiers_rather_than_an_error(self):
        """An order whose offer has been deleted records its lines exactly as it did before."""
        self.assertEqual(offer_price_tiers(None), {})
        self.assertEqual(offer_price_tiers({}), {})


class LinesCarryTheTierTests(unittest.TestCase):
    def _line(self, local_price_id, tiers=None):
        return order_line_items_from_stripe(
            [stripe_line(local_price_id)], set(), "usd", tiers if tiers is not None else offer_price_tiers(OFFER))[0]

    def test_a_multi_unit_tier_is_recorded(self):
        line = self._line("price_two")
        self.assertEqual(line["unit_quantity"], 2)
        self.assertEqual(line["tier_label"], "2 Items")

    def test_the_single_tier_records_its_label_but_no_unit_quantity(self):
        """A 1 nobody chose is indistinguishable from the Stripe quantity already on the line, so it is
        not written; the tenant's label still is, because it is their words."""
        line = self._line("price_one")
        self.assertNotIn("unit_quantity", line)
        self.assertEqual(line["tier_label"], "1 Item")

    def test_the_local_price_id_is_recorded_even_with_no_tier(self):
        """The only durable key from a Stripe line back to the catalogue. A report grouping by price
        needs it whether or not anything is tiered."""
        line = self._line("price_untiered", tiers={})
        self.assertEqual(line["price_id"], "price_untiered")
        self.assertNotIn("unit_quantity", line)
        self.assertNotIn("tier_label", line)

    def test_a_line_with_no_metadata_is_unchanged(self):
        """Older Stripe Prices, and anything created outside our sync."""
        bare = {"description": "X", "amount_total": 100, "quantity": 1, "price": {"id": "price_x"}}
        line = order_line_items_from_stripe([bare], set(), "usd", offer_price_tiers(OFFER))[0]
        self.assertNotIn("price_id", line)
        self.assertEqual(line["name"], "X")

    def test_bump_flagging_still_works_alongside(self):
        line = order_line_items_from_stripe(
            [stripe_line("price_two", stripe_price_id="price_bump")], {"price_bump"}, "usd",
            offer_price_tiers(OFFER))[0]
        self.assertTrue(line["is_order_bump"])
        self.assertEqual(line["unit_quantity"], 2)

    def test_tiers_are_optional_so_every_existing_caller_is_unaffected(self):
        line = order_line_items_from_stripe([stripe_line("price_two")], set(), "usd")[0]
        self.assertNotIn("unit_quantity", line)
        self.assertEqual(line["price_id"], "price_two")


class TheLabelCannotBeStampedOnThePriceTests(unittest.TestCase):
    """Why this is resolved from the offer rather than copied into Stripe metadata at sync time.

    The label belongs to the (offer, price) PAIR. Real data, 2026-10-06: `price_NxQYoPLerzo` is "1 Item"
    in one offer and "Every day" in another. A label stamped on the Price would describe the second
    offer's orders in the first offer's words.
    """

    def test_one_price_two_offers_two_labels(self):
        shared = {"price_id": "shared", "quantity": 1}
        a = offer_price_tiers({"items": [{"selectable_prices": [{**shared, "label": "1 Item"}]}]})
        b = offer_price_tiers({"items": [{"selectable_prices": [{**shared, "label": "Every day"}]}]})
        self.assertNotEqual(a["shared"]["label"], b["shared"]["label"])


if __name__ == "__main__":
    unittest.main()


class ATierIsThatManyThingsInTheBoxTests(unittest.TestCase):
    """The packer has to count units, not Stripe line items.

    A tiered offer prices 3 of something as ONE Stripe Price, so Stripe reports `quantity: 1`. The packer
    read that and sized the parcel for a single unit -- a box too small and a label too cheap, which the
    carrier re-bills weeks later. The BUYER's quote was right all along (the landing page passes the
    tier's quantity to `shipping_quote`), so the two halves of one sale disagreed and only the label said
    so. Invisible until `unit_quantity` existed to compare against (2026-10-06).
    """

    INDEX = {"sp": {"product_id": "nad"}}

    def _packed(self, quantity, unit_quantity=None):
        from stripe_link.domain.fulfilment import resolve_order_lines

        line = {"name": "NAD", "quantity": quantity, "stripe_price_id": "sp"}
        if unit_quantity:
            line["unit_quantity"] = unit_quantity
        return resolve_order_lines({"line_items": [line]}, self.INDEX)[0]["quantity"]

    def test_a_three_item_tier_packs_three(self):
        self.assertEqual(self._packed(1, 3), 3)

    def test_two_of_a_three_item_tier_packs_six(self):
        """Multiplied, not replaced: a buyer can take two of the same tier."""
        self.assertEqual(self._packed(2, 3), 6)

    def test_an_untiered_line_is_untouched(self):
        self.assertEqual(self._packed(1), 1)
        self.assertEqual(self._packed(4), 4)

    def test_a_single_unit_tier_changes_nothing(self):
        self.assertEqual(self._packed(2, 1), 2)


class ThePackingSlipCountsRatherThanRepeatsTests(unittest.TestCase):
    def test_three_of_one_thing_reads_as_three(self):
        from stripe_link.domain.fulfilment_groups import parcel_contents

        contents = parcel_contents({"packed_from": ["nad", "nad", "nad"]},
                                   {"nad": {"name": "NAD Supplement"}})
        self.assertEqual(contents, ["NAD Supplement x3"])

    def test_different_things_are_still_listed(self):
        from stripe_link.domain.fulfilment_groups import parcel_contents

        contents = parcel_contents({"packed_from": ["a", "b", "a"]},
                                   {"a": {"name": "Gummies"}, "b": {"name": "Whey"}})
        self.assertEqual(contents, ["Gummies x2", "Whey"])

    def test_order_of_first_appearance_is_kept(self):
        """A packing slip read top to bottom should match the order the packer picks them."""
        from stripe_link.domain.fulfilment_groups import parcel_contents

        contents = parcel_contents({"packed_from": ["b", "a", "b"]},
                                   {"a": {"name": "Gummies"}, "b": {"name": "Whey"}})
        self.assertEqual(contents, ["Whey x2", "Gummies"])
