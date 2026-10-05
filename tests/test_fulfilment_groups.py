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


class TheScreenShowsOneRowPerBOXTests(unittest.TestCase):
    """An upsell is its own ORDER because it is its own charge, but it is not its own PARCEL — it ships in
    the buyer's existing box, which is why it was charged $0 for postage. Listing it as a peer is how a
    funnel that collected $6.20 was offered $18.20 of labels."""

    ORDERS_VUE = (__import__("pathlib").Path(__file__).resolve().parents[1]
                  / "dashboard" / "src" / "components" / "Orders.vue").read_text()

    def test_children_are_folded_into_their_parent(self):
        self.assertIn("orders.value.filter((o) => !o.ships_with)", self.ORDERS_VUE)

    def test_the_expander_appears_only_for_a_group(self):
        self.assertIn('v-if="order.fulfilment_group"', self.ORDERS_VUE)

    def test_each_parcel_names_its_box_and_contents(self):
        self.assertIn('parcel.box || "Custom box"', self.ORDERS_VUE)
        self.assertIn("(parcel.contents || []).join", self.ORDERS_VUE)

    def test_rates_are_cached_per_parcel_not_per_order(self):
        """A group needing two boxes gets two quotes; keying them together would show the second box the
        first box's price."""
        self.assertIn("const parcelKey = (order, index)", self.ORDERS_VUE)
        self.assertIn("${order.order_id}#${index}", self.ORDERS_VUE)

    def test_the_price_is_shown_before_it_is_spent(self):
        # The same two-step the single-order button uses: a label is money that cannot be un-spent by
        # refreshing the page.
        block = self.ORDERS_VUE.split("async function labelParcel", 1)[1].split("\n}", 1)[0]
        self.assertLess(block.index("/shipping/rates"), block.index("/shipping/labels"))

    def test_the_parcel_index_travels_to_both_calls(self):
        block = self.ORDERS_VUE.split("async function labelParcel", 1)[1].split("\n}", 1)[0]
        self.assertEqual(block.count("parcel_index: index"), 2)


class TheServerRatesAndBuysPerParcelTests(unittest.TestCase):
    SHIPPING_PY = (__import__("pathlib").Path(__file__).resolve().parents[1]
                   / "src" / "handlers" / "shipping.py").read_text()

    def test_rating_packs_the_whole_group(self):
        block = self.SHIPPING_PY.split("def quote_rates", 1)[1][:4000]
        self.assertIn("_fulfilment_group_for(order, tenant_id, orders)", block)
        self.assertIn("group_parcels(group", block)

    def test_the_multi_parcel_refusal_is_gone(self):
        """It used to refuse the whole order and tell the tenant to post it by hand. A group needing three
        boxes is now three lines, three rates and three labels."""
        self.assertNotIn("multi_parcel", self.SHIPPING_PY)

    def test_each_parcel_gets_its_own_shipment_id(self):
        """`sequence` already existed for a deliberate split and is exactly this: a double-clicked Buy
        Label still loses the conditional write on its OWN parcel rather than buying a second label."""
        self.assertIn('shipment_id_for(order_id, sequence=max(1, int(body.get("parcel_index") or 0) + 1))',
                      self.SHIPPING_PY)

    def test_an_out_of_range_parcel_is_refused(self):
        self.assertIn("no_such_parcel", self.SHIPPING_PY)

    def test_a_group_lookup_failure_falls_back_to_the_order_alone(self):
        from handlers.shipping import _fulfilment_group_for

        class Exploding:
            def list_for_tenant(self, _t):
                raise RuntimeError("dynamo down")

        order = {"order_id": "order_1", "session_id": "cs_1"}
        self.assertEqual(_fulfilment_group_for(order, "t1", Exploding()), [order])
