"""A real carrier price with no destination beyond the country — tier 2.

plans/SHIPPING_ELEMENT.md phase 4. The author's insight, 2026-09-30: *"merchants choose UPS flat rate for
parcels that meet a certain criteria. The flat rate applies to anywhere in the United States."* A flat-rate
service is destination-independent domestically, so its price is a function of the BOX and the weight tier
rather than of where it is going — which makes a real price showable from a dropdown instead of a form.

**The reach of this tier is carts that fit ONE listed box.** The packer either puts everything in one shared
box or falls back to one parcel per item with no box at all, so anything larger cannot be flat-rated. I
assumed multi-parcel would price by summing and it does not — that is how carriers bill, not how this packer
allocates.
"""
import unittest

from handlers.checkout import build_checkout_payload
from stripe_link.domain.shipping_charges import checkout_shipping, packed_box_price, resolve_options

SMALL = {"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15,
         "flat_rate": {"US": 699}}
MEDIUM = {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35,
          "flat_rate": {"US": 899, "CA": 1499}}
CONFIG = {"boxes": [SMALL, MEDIUM],
          "enabled_services": [{"service_token": "ground", "label": "Ground"}],
          "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}},
                    {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}

TRINKET = {"product_id": "p1", "name": "Trinket", "product_type": "physical",
           "fulfillment": {"requires_shipping": True, "weight_lb": 0.5,
                           "item_dimensions": {"length_in": 3, "width_in": 2, "height_in": 2,
                                               "weight_lb": 0.4}},
           "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}
UNMEASURED = {"product_id": "p2", "name": "Mystery", "product_type": "physical",
              "fulfillment": {"requires_shipping": True},
              "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}
CRATE = {"product_id": "p3", "name": "Crate", "product_type": "physical",
         "fulfillment": {"requires_shipping": True, "weight_lb": 30,
                         "item_dimensions": {"length_in": 40, "width_in": 30, "height_in": 20,
                                             "weight_lb": 30}},
         "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}
PRODUCTS = {p["product_id"]: p for p in (TRINKET, UNMEASURED, CRATE)}


def price(product_id="p1", quantity=1, country="US", config=None):
    return packed_box_price([{"product_id": product_id, "quantity": quantity}], PRODUCTS,
                            config if config is not None else CONFIG, country)


class PricingFromTheBoxItPacksInto(unittest.TestCase):
    def test_a_small_cart_costs_the_small_box(self):
        self.assertEqual(price()["amount"], 699)

    def test_several_items_sharing_one_box_still_cost_one_box(self):
        """The whole point of a box catalogue: three trinkets go in one Small, not three parcels."""
        result = price(quantity=3)
        self.assertEqual(result["amount"], 699)
        self.assertEqual(result["boxes"], ["Small"])

    def test_the_price_is_per_COUNTRY(self):
        """Flat rate is domestic by definition, so one number cannot serve two countries."""
        self.assertEqual(price(country="CA")["reason"], "no_price")
        self.assertIsNone(price(country="CA")["amount"])


class WhatItCannotPriceAndWhy(unittest.TestCase):
    """Each reason is distinct because each needs a different thing from the tenant."""

    def test_unmeasured_products_cannot_be_packed(self):
        """The packer returns nothing rather than inventing a parcel -- a made-up box buys postage at the
        wrong price. Its restraint is correct and it means we cannot quote."""
        result = price(product_id="p2")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["reason"], "no_dimensions")

    def test_something_fitting_no_listed_box_says_no_box(self):
        result = price(product_id="p3")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["reason"], "no_box")

    def test_a_fitting_box_with_no_price_for_the_country_says_no_price(self):
        result = price(country="CA")
        self.assertEqual(result["reason"], "no_price")
        self.assertIn("Small", result["boxes"])

    def test_no_boxes_at_all_cannot_price(self):
        self.assertIsNone(price(config={"boxes": []})["amount"])

    def test_none_is_never_confused_with_free(self):
        """The load-bearing property of this whole plan family."""
        for case in (price(product_id="p2"), price(product_id="p3"), price(country="CA")):
            self.assertIsNone(case["amount"])
            self.assertNotEqual(case["amount"], 0)


class OneBoxIsTheCeiling(unittest.TestCase):
    """The reach of this tier, stated as a test because I got it wrong first.

    I expected multi-parcel to price by summing -- two boxes, two flat rates, which is how carriers bill. But
    `shipping_packing` has only two strategies: everything in one shared box, or *"one parcel per thing...
    the honest fallback"* when anything does not fit. The per-item fallback assigns NO box, so there is no
    rate to sum. A cart bigger than one listed box needs tier 3 or a tenant-set flat amount.
    """

    BIG = {"product_id": "big", "product_type": "physical",
           "fulfillment": {"requires_shipping": True, "weight_lb": 2,
                           "item_dimensions": {"length_in": 9, "width_in": 7, "height_in": 5,
                                               "weight_lb": 2}}}

    def price(self, quantity):
        return packed_box_price([{"product_id": "big", "quantity": quantity}], {"big": self.BIG},
                                CONFIG, "US")

    def test_one_of_them_fits_the_medium_and_prices(self):
        result = self.price(1)
        self.assertEqual(result["boxes"], ["Medium"])
        self.assertEqual(result["amount"], 899)

    def test_two_of_them_fit_no_single_box_and_cannot_be_priced(self):
        result = self.price(2)
        self.assertIsNone(result["amount"])
        self.assertEqual(result["reason"], "no_box")

    def test_and_that_is_reported_as_unpriceable_not_as_free(self):
        self.assertNotEqual(self.price(2)["amount"], 0)


class ThroughTheResolver(unittest.TestCase):
    def test_the_resolver_takes_the_AMOUNT_not_the_box(self):
        """`resolve_options` stays pure and knows nothing about packing: the caller works out the number."""
        result = resolve_options({}, CONFIG, country="US", box_amount=699)
        self.assertEqual([o["amount"] for o in result["options"]], [699])
        self.assertEqual(result["needs"], "")

    def test_no_amount_means_needs_box_price_not_free(self):
        result = resolve_options({}, CONFIG, country="US", box_amount=None)
        self.assertEqual(result["options"], [])
        self.assertEqual(result["needs"], "box_price")


class ThroughCheckout(unittest.TestCase):
    def payload(self, config, quantity=1):
        return build_checkout_payload(
            tenant_id="t1",
            offer={"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"}},
            products_by_id=PRODUCTS,
            resolved={"items": [{"product_id": "p1", "price_id": "pr1", "quantity": quantity,
                                 "unit_amount": 2000, "currency": "usd"}],
                      "subtotal": 2000 * quantity, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c", shipping_config=config)

    def amounts(self, built):
        return [v for k, v in built.items() if k.endswith("[fixed_amount][amount]")]

    def test_a_single_country_by_box_zone_charges_the_box_price(self):
        self.assertEqual(self.amounts(self.payload(CONFIG)), ["699"])

    def test_two_countries_with_different_box_prices_charge_NOTHING(self):
        """Stripe shows one list to every buyer, so a box costing $6.99 in the US and $14.99 in Canada has no
        single right answer at session-creation time."""
        config = dict(CONFIG, zones=[
            {"destinations": [{"country": "US"}, {"country": "CA"}], "rule": {"type": "flat_rate_box"}},
            {"destinations": [{"country": "*"}], "rule": {"type": "free"}}])
        self.assertEqual(self.amounts(self.payload(config)), [])
        decision = checkout_shipping({}, config, items=[{"product_id": "p1", "quantity": 1}],
                                     products_by_id=PRODUCTS)
        self.assertTrue(decision["reason"])

    def test_the_cart_reaches_the_pricer(self):
        """A regression guard: checkout_shipping needs the items to pack, and the wiring to pass them was
        written twice before it took."""
        decision = checkout_shipping({}, CONFIG, items=[{"product_id": "p1", "quantity": 1}],
                                     products_by_id=PRODUCTS)
        self.assertEqual([o["amount"] for o in decision["options"]], [699])
        # Without the cart there is nothing to pack, so it cannot price -- which is what a missing wire looks
        # like, and why the test above matters.
        self.assertEqual(checkout_shipping({}, CONFIG)["options"], [])


if __name__ == "__main__":
    unittest.main()
