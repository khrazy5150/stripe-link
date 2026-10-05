"""One parcel, one label — grouping an order with its upsells.

plans/FULFILMENT_GROUPS.md. A real funnel on 2026-10-04 collected **$6.20** of shipping from the buyer and
was offered **$18.20** of labels: three boxes to one address, $12 lost on a $113 sale, surfacing on a
carrier invoice weeks later rather than anywhere near the order.

The upsells were charged **$0 because they ride in the same parcel** — `combined_delta` re-packs the
order's lines together with the upsell, re-rates, and charges the difference, which is correctly nothing.
That is only honest if one parcel actually ships. The margin bug and the screen bug are one bug.
"""
import unittest

from stripe_link.domain.fulfilment import product_index
from stripe_link.domain.fulfilment_groups import (
    destination_key,
    group_key,
    group_lines,
    group_orders,
    group_parcels,
)

TINY = {"length_in": 2, "width_in": 2, "height_in": 1, "weight_lb": 0.2}
PRODUCTS = [
    {"product_id": "p_gummies", "name": "Creatine Gummies",
     "prices": [{"stripe_price_id": "price_g"}],
     "fulfillment": {"requires_shipping": True, "weight_lb": 0.3, "item_dimensions": TINY}},
    {"product_id": "p_whey", "name": "Whey Protein", "prices": [{"stripe_price_id": "price_w"}],
     "fulfillment": {"requires_shipping": True, "weight_lb": 0.3, "item_dimensions": TINY}},
    {"product_id": "p_nad", "name": "NAD Supplement", "prices": [{"stripe_price_id": "price_n"}],
     "fulfillment": {"requires_shipping": True, "weight_lb": 0.3, "item_dimensions": TINY}},
]
BY_ID = {p["product_id"]: p for p in PRODUCTS}
INDEX = product_index(PRODUCTS)
BOXES = [{"name": "Small box", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15}]
ADDRESS = {"street1": "1493 Osage St", "city": "Denver", "state": "CO", "postal_code": "80204",
           "country": "US"}

# A Stripe line item carries `stripe_price_id` and a NAME — never our `product_id`.
PARENT = {"order_id": "order_cs_1", "session_id": "cs_1", "shipping_address": ADDRESS,
          "line_items": [{"name": "Creatine Gummies", "stripe_price_id": "price_g", "quantity": 1},
                         {"name": "Whey Protein", "stripe_price_id": "price_w", "quantity": 1}]}
UPSELL = {"order_id": "order_cs_1_upsell_1", "session_id": "cs_1", "shipping_address": ADDRESS,
          "product": {"product_id": "p_nad", "name": "NAD Supplement"}}


class WhatMakesTwoOrdersOneParcelTests(unittest.TestCase):
    def test_the_session_they_share(self):
        """No new identity: `order_reference` already derives `-U1` from exactly this."""
        self.assertEqual(group_key(PARENT), group_key(UPSELL))

    def test_an_order_with_no_session_is_its_OWN_group(self):
        """An invoice or a legacy row must not join a bucket of everything else that also lacks one —
        grouping unrelated buyers' parcels would be far worse than the bug being fixed."""
        a = {"order_id": "order_a"}
        b = {"order_id": "order_b"}
        self.assertNotEqual(group_key(a), group_key(b))
        self.assertEqual(len(group_orders([a, b])), 2)

    def test_the_parent_leads_its_group(self):
        """The shipment is keyed on it: `shipment_id_for` derives the id, and that derivation is the
        idempotency key stopping a double-clicked Buy Label from becoming two labels."""
        [group] = group_orders([UPSELL, PARENT])
        self.assertEqual(group[0]["order_id"], "order_cs_1")

    def test_a_different_destination_SPLITS_the_group(self):
        """Checked rather than assumed: nothing stops an upsell carrying a different address, and packing
        two destinations into one box puts a parcel through the wrong door."""
        elsewhere = dict(UPSELL, shipping_address=dict(ADDRESS, postal_code="90210"))
        self.assertNotEqual(destination_key(PARENT), destination_key(elsewhere))
        self.assertEqual(len(group_orders([PARENT, elsewhere])), 2)


class TheUnIONIsWhatGetsPackedTests(unittest.TestCase):
    """Exactly what `combined_delta` packed to decide the upsell added nothing — so for the first time the
    number the buyer was charged and the boxes the tenant buys come from one computation."""

    def test_cart_items_resolve_through_their_stripe_price(self):
        """A first version read `product_id` straight off the line and silently dropped every cart item,
        packing only the upsells — the exact failure `resolve_order_lines` warns about."""
        lines = group_lines([PARENT, UPSELL], INDEX)
        self.assertEqual(sorted(line["product_id"] for line in lines),
                         ["p_gummies", "p_nad", "p_whey"])

    def test_an_upsells_product_block_is_included(self):
        self.assertIn("p_nad", [line["product_id"] for line in group_lines([UPSELL], INDEX)])

    def test_without_the_index_the_cart_lines_cannot_resolve(self):
        # Held so the dependency is explicit: no catalogue, no product ids, no parcel.
        self.assertEqual(group_lines([PARENT], {}), [])


class OneGroupOneSetOfBoxesTests(unittest.TestCase):
    def test_everything_that_fits_goes_in_one_box(self):
        [group] = group_orders([PARENT, UPSELL])
        parcels = group_parcels(group, products_by_id=BY_ID, boxes=BOXES, index=INDEX)
        self.assertEqual(len(parcels), 1)

    def test_each_parcel_names_its_box_and_contents(self):
        """"Medium box: Creatine Gummies, Whey Protein" is a packing slip. "Medium box: 2 items" is a
        number the tenant has to go and look up."""
        [group] = group_orders([PARENT, UPSELL])
        [parcel] = group_parcels(group, products_by_id=BY_ID, boxes=BOXES, index=INDEX)
        self.assertEqual(parcel["box"], "Small box")
        self.assertEqual(sorted(parcel["contents"]),
                         ["Creatine Gummies", "NAD Supplement", "Whey Protein"])

    def test_more_than_fits_becomes_more_parcels(self):
        """As few as the items allow — the packer's job, and why the tenant is not asked to decide."""
        big = dict(PARENT, line_items=[{"name": "Whey Protein", "stripe_price_id": "price_w",
                                        "quantity": 40}])
        parcels = group_parcels([big], products_by_id=BY_ID, boxes=BOXES, index=INDEX)
        self.assertGreater(len(parcels), 1)

    def test_a_group_with_nothing_shippable_needs_no_boxes(self):
        self.assertEqual(group_parcels([{"order_id": "o"}], products_by_id=BY_ID, boxes=BOXES), [])


class TheListMarksThemTests(unittest.TestCase):
    def _attach(self, orders):
        from handlers.orders import _attach_fulfilment_groups

        _attach_fulfilment_groups(orders, {"products_by_id": BY_ID, "index": INDEX,
                                           "config": {"boxes": BOXES}})
        return orders

    def test_the_parent_carries_the_group_and_the_children_point_at_it(self):
        parent, upsell = self._attach([dict(PARENT), dict(UPSELL)])
        self.assertEqual(parent["fulfilment_group"]["order_ids"],
                         ["order_cs_1", "order_cs_1_upsell_1"])
        self.assertEqual(len(parent["fulfilment_group"]["parcels"]), 1)
        self.assertEqual(upsell["ships_with"], "order_cs_1")

    def test_an_order_that_ships_alone_gains_nothing(self):
        """A row that was already one parcel needs no expander and no extra shape."""
        [alone] = self._attach([dict(PARENT)])
        self.assertNotIn("fulfilment_group", alone)
        self.assertNotIn("ships_with", alone)

    def test_a_grouping_failure_never_costs_the_order_list(self):
        orders = [dict(PARENT), dict(UPSELL)]
        from handlers.orders import _attach_fulfilment_groups

        _attach_fulfilment_groups(orders, {"products_by_id": None, "index": None, "config": None})
        self.assertEqual(len(orders), 2)
