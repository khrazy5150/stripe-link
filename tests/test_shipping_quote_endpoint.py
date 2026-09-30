"""The public shipping quote: what shipping would cost, and where it may be sent.

plans/SHIPPING_ELEMENT.md phase 6. A page element needs two answers — which countries this tenant ships to,
and what the chosen one costs — and a published page is a static S3 artifact, so it must ASK rather than carry
them. Carrying them would be the stale-snapshot problem the plan forbids: a tenant who adds a zone would not
see it until republish.

It lives on the checkout function because it needs exactly what checkout already loads. For tiers 1 and 2 it
makes NO carrier call, so it is a cached config read plus arithmetic — which is why it can ship before the
throttle that tier 3 will require.
"""
import json
import unittest

import handlers.checkout as checkout_module
from handlers.checkout import handler, shipping_quote

OFFER = {"offer_id": "o1", "tenant_id": "t1", "items": [{"product_id": "p1", "price_id": "pr1"}]}
PRODUCT = {"product_id": "p1", "name": "Shirt", "product_type": "physical",
           "fulfillment": {"requires_shipping": True, "weight_lb": 0.5,
                           "item_dimensions": {"length_in": 3, "width_in": 2, "height_in": 2,
                                               "weight_lb": 0.4}},
           "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}
CONFIG = {
    "boxes": [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15,
               "flat_rate": {"US": 699}}],
    "enabled_services": [{"service_token": "ground", "label": "Ground",
                          "transit_days_min": 5, "transit_days_max": 7}],
    "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}},
              {"destinations": [{"country": "CA"}], "rule": {"type": "flat", "amount": 1299}},
              {"destinations": [{"country": "*"}], "rule": {"type": "free"}}],
}


class Repo:
    def __init__(self, docs):
        self.docs = docs

    def get(self, tenant, doc_id=None):
        return self.docs.get(doc_id or tenant)


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self._real = checkout_module._tenant_shipping_config
        checkout_module._tenant_shipping_config = lambda tenant_id: self.config
        self.config = CONFIG

    def tearDown(self):
        checkout_module._tenant_shipping_config = self._real

    def quote(self, country="", offer=None, quantity="1"):
        response = shipping_quote(
            tenant_id="t1", offer_id="o1", product_id="p1", price_id="pr1", quantity=quantity,
            country=country, mode="test",
            offers_repo=Repo({"o1": offer or OFFER}), products_repo=Repo({"p1": PRODUCT}))
        return json.loads(response["body"])

    def test_it_lists_the_countries_the_tenant_ships_to(self):
        self.assertEqual(self.quote()["countries"], ["US", "CA"])

    def test_without_a_country_it_prices_nothing_and_says_why(self):
        """Zones ARE destinations, so a country is required to price anything. Returning the list without a
        price is the honest answer to 'what are my choices'."""
        body = self.quote()
        self.assertEqual(body["needs"], "country")
        self.assertEqual(body["options"], [])

    def test_no_zones_at_all_says_zones_not_country(self):
        """Caught by hitting the deployed endpoint against a real tenant: `needs: country` alongside
        `countries: []` is advice nobody can act on, and an element would render an empty dropdown. The two
        are different facts -- "choose one of these" versus "the tenant has configured nowhere to ship"."""
        self.config = {"boxes": [], "enabled_services": []}
        body = self.quote("US")
        self.assertEqual(body["countries"], [])
        self.assertEqual(body["needs"], "zones")
        self.assertTrue(body["ships"])

    def test_a_by_box_zone_prices_from_the_packed_box(self):
        body = self.quote("US")
        self.assertEqual([(o["label"], o["amount"]) for o in body["options"]], [("Ground", 699)])
        self.assertEqual(body["needs"], "")

    def test_a_flat_zone_prices_from_the_zone(self):
        self.assertEqual([o["amount"] for o in self.quote("CA")["options"]], [1299])

    def test_transit_days_travel_so_the_element_can_show_them(self):
        option = self.quote("US")["options"][0]
        self.assertEqual((option["transit_days_min"], option["transit_days_max"]), (5, 7))

    def test_a_country_the_tenant_does_not_serve_is_not_honoured(self):
        body = self.quote("GB")
        self.assertEqual(body["needs"], "country")
        self.assertEqual(body["country"], "")

    def test_an_offer_that_does_not_ship_says_so_and_offers_no_dropdown(self):
        """An element rendering this must show no selector at all, not an empty one."""
        body = self.quote("US", offer=dict(OFFER, shipping={"eligibility": "none"}))
        self.assertFalse(body["ships"])
        self.assertEqual(body["countries"], [])

    def test_a_live_zone_asks_for_a_carrier_rather_than_quoting_zero(self):
        self.config = dict(CONFIG, zones=[
            {"destinations": [{"country": "US"}], "rule": {"type": "live"}},
            {"destinations": [{"country": "*"}], "rule": {"type": "free"}}])
        body = self.quote("US")
        self.assertEqual(body["needs"], "carrier")
        self.assertEqual(body["options"], [])

    def test_an_unpriced_box_says_box_price_and_names_the_reason(self):
        self.config = dict(CONFIG, boxes=[{"name": "Small", "length": 6, "width": 4, "height": 4,
                                           "empty_weight": 0.15}])
        body = self.quote("US")
        self.assertEqual(body["needs"], "box_price")
        self.assertEqual(body["box_reason"], "no_price")

    def test_needs_is_never_a_zero_price(self):
        """The load-bearing rule: a page rendering an unknown as 'Free shipping' makes a promise the tenant
        did not."""
        self.config = dict(CONFIG, zones=[
            {"destinations": [{"country": "US"}], "rule": {"type": "live"}},
            {"destinations": [{"country": "*"}], "rule": {"type": "free"}}])
        self.assertEqual(self.quote("US")["options"], [])

    def test_quantity_changes_a_by_box_price_when_it_changes_the_box(self):
        """The element recalculating on a tier change is the whole point of quoting per cart."""
        self.config = dict(CONFIG, boxes=[
            {"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15,
             "flat_rate": {"US": 699}},
            {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35,
             "flat_rate": {"US": 899}}])
        self.assertEqual(self.quote("US", quantity="1")["options"][0]["amount"], 699)
        self.assertEqual(self.quote("US", quantity="12")["options"][0]["amount"], 899)

    def test_a_missing_offer_is_a_404_not_a_crash(self):
        response = shipping_quote(tenant_id="t1", offer_id="nope", product_id="", price_id="",
                                  quantity="1", country="US", mode="test",
                                  offers_repo=Repo({}), products_repo=Repo({"p1": PRODUCT}))
        self.assertEqual(response["statusCode"], 404)

    def test_nonsense_quantity_does_not_crash(self):
        self.assertEqual(self.quote("US", quantity="abc")["options"][0]["amount"], 699)


class RoutedThroughTheHandler(unittest.TestCase):
    def setUp(self):
        self._real = checkout_module._tenant_shipping_config
        checkout_module._tenant_shipping_config = lambda tenant_id: CONFIG

    def tearDown(self):
        checkout_module._tenant_shipping_config = self._real

    def test_the_resource_path_reaches_the_quote(self):
        """A quote needs no success_url, so it must branch BEFORE checkout's redirect-url validation."""
        response = handler({"httpMethod": "GET", "resource": "/shipping-quote",
                            "queryStringParameters": {"clientID": "t1", "offer": "o1", "country": "US"}},
                           None, offers_repo=Repo({"o1": OFFER}), products_repo=Repo({"p1": PRODUCT}))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["options"][0]["amount"], 699)

    def test_a_normal_checkout_still_requires_its_redirect_urls(self):
        response = handler({"httpMethod": "GET", "resource": "/checkout",
                            "queryStringParameters": {"clientID": "t1", "offer": "o1"}},
                           None, offers_repo=Repo({"o1": OFFER}), products_repo=Repo({"p1": PRODUCT}))
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
