"""GET /shipping-quote with a postal code: the first time a buyer's own address reaches a carrier.

plans/LIVE_SHIPPING_RATES.md phase 2. The engine has answered `needs: carrier` for every live zone since
the rule shipped, because nothing in the buyer's path ever asked one. These are the rules of asking.
"""
import json
import unittest

import handlers.checkout as checkout_module
from handlers.checkout import shipping_quote
from stripe_link.domain.shipping_quotes import QUOTE_TTL_SECONDS, cache_id

OFFER = {"offer_id": "o1", "tenant_id": "t1", "items": [{"product_id": "p1", "price_id": "pr1"}]}
PRODUCT = {"product_id": "p1", "name": "Projector", "product_type": "physical",
           "fulfillment": {"requires_shipping": True,
                           "item_dimensions": {"length_in": 8, "width_in": 6, "height_in": 4,
                                               "weight_lb": 3.0}},
           "prices": [{"price_id": "pr1", "unit_amount": 5679, "currency": "usd"}]}
LIVE_CONFIG = {
    "boxes": [{"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}],
    "ship_from_address": {"name": "Shop", "street1": "1 Main", "city": "Denver", "state": "CO",
                          "postal_code": "80301", "country": "US"},
    "provider": {"name": "mock", "api_key_ref": "ref_1"},
    "enabled_services": [{"service_token": "ups_ground", "label": "UPS Ground Saver"},
                         {"service_token": "usps_ground", "label": "USPS Ground Advantage"}],
    "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}}],
}


class Repo:
    def __init__(self, docs):
        self.docs = docs

    def get(self, tenant, doc_id=None):
        return self.docs.get(doc_id or tenant)


class QuoteStore:
    """Stands in for the CARTS_TABLE rows, and counts reads so cache behaviour is observable."""

    def __init__(self):
        self.rows, self.puts, self.gets = {}, 0, 0

    def get(self, tenant_id, quote_id):
        self.gets += 1
        return self.rows.get((tenant_id, quote_id))

    def put(self, tenant_id, record):
        self.puts += 1
        self.rows[(tenant_id, record["quote_id"])] = record


class Cipher:
    def __init__(self, key="mock_key"):
        self.key = key

    def decrypt(self, ref, **_kwargs):
        if self.key is None:
            raise RuntimeError("kms unavailable")
        return self.key


class LiveQuoteTests(unittest.TestCase):
    def setUp(self):
        self._real = checkout_module._tenant_shipping_config
        self.config = dict(LIVE_CONFIG)
        checkout_module._tenant_shipping_config = lambda tenant_id: self.config
        self.store = QuoteStore()

    def tearDown(self):
        checkout_module._tenant_shipping_config = self._real

    def quote(self, country="US", postal_code="80202", region="CO", cipher=None, store=None):
        response = shipping_quote(
            tenant_id="t1", offer_id="o1", product_id="p1", price_id="pr1", quantity="1",
            country=country, postal_code=postal_code, region=region, mode="test",
            offers_repo=Repo({"o1": OFFER}), products_repo=Repo({"p1": PRODUCT}),
            quotes_repo=self.store if store is None else store,
            secret_cipher=Cipher() if cipher is None else cipher)
        return json.loads(response["body"])

    def test_a_country_alone_is_not_an_address(self):
        # The entire reason the element grew a second field.
        body = self.quote(postal_code="")
        self.assertEqual(body["needs"], "postal_code")
        self.assertEqual(body["options"], [])

    def test_a_live_zone_finally_returns_real_prices(self):
        body = self.quote()
        self.assertEqual(body["needs"], "")
        self.assertTrue(body["options"])
        self.assertEqual(body["mode"], "charged")

    def test_only_services_the_tenant_enabled_are_offered(self):
        # MockProvider quotes usps, ups and fedex. The tenant adopted two.
        tokens = {o["service_token"] for o in self.quote()["options"]}
        self.assertEqual(tokens, {"ups_ground", "usps_ground"})

    def test_the_buyer_sees_the_tenants_words(self):
        labels = {o["label"] for o in self.quote()["options"]}
        self.assertEqual(labels, {"UPS Ground Saver", "USPS Ground Advantage"})

    def test_options_carry_a_price_and_an_estimate(self):
        option = self.quote()["options"][0]
        self.assertGreater(option["amount"], 0)
        self.assertIsNotNone(option["transit_days_min"])

    def test_a_quote_id_is_returned_so_checkout_can_price_from_the_server(self):
        body = self.quote()
        self.assertTrue(body["quote_id"].startswith("shq_"))
        self.assertGreater(body["expires_at"], 0)
        self.assertEqual(self.store.puts, 1)

    def test_the_stored_row_holds_the_amounts_the_browser_was_shown(self):
        body = self.quote()
        row = self.store.rows[("t1", body["quote_id"])]
        self.assertEqual(sorted(o["amount"] for o in row["options"]),
                         sorted(o["amount"] for o in body["options"]))
        self.assertEqual(row["destination"], {"country": "US", "postal_code": "80202", "region": "CO"})

    def test_asking_twice_for_the_same_cart_costs_no_second_carrier_call(self):
        # The row IS the cache -- one `get`, no index. A buyer toggling services must not re-rate.
        first = self.quote()
        self.store.puts = 0
        second = self.quote()
        self.assertEqual(first["quote_id"], second["quote_id"])
        self.assertEqual(self.store.puts, 0)
        self.assertEqual([o["amount"] for o in first["options"]],
                         [o["amount"] for o in second["options"]])

    def test_a_different_destination_is_a_different_quote(self):
        self.assertNotEqual(self.quote(postal_code="80202")["quote_id"],
                            self.quote(postal_code="90210")["quote_id"])

    def test_an_expired_row_is_re_rated_rather_than_reused(self):
        body = self.quote()
        row = self.store.rows[("t1", body["quote_id"])]
        row["expires_at"] = 1  # long past
        self.store.puts = 0
        self.quote()
        self.assertEqual(self.store.puts, 1)

    def test_a_carrier_failure_is_named_and_never_rendered_as_free(self):
        self.config = dict(LIVE_CONFIG, provider={"name": "mock", "api_key_ref": ""})
        body = self.quote()
        self.assertEqual(body["needs"], "carrier")
        self.assertEqual(body["rate_error"], "no_provider")
        self.assertEqual(body["options"], [])
        self.assertNotEqual(body["mode"], "free")

    def test_a_missing_ship_from_is_its_own_reason(self):
        self.config = dict(LIVE_CONFIG, ship_from_address={})
        self.assertEqual(self.quote()["rate_error"], "no_ship_from")

    def test_an_unreadable_key_does_not_take_the_page_down(self):
        body = self.quote(cipher=Cipher(key=None))
        self.assertEqual(body["needs"], "carrier")
        self.assertIn("key_unreadable", body["rate_error"])

    def test_rates_that_match_no_enabled_service_say_services_not_carrier(self):
        # Fixed in the Shipping screen, not by connecting a carrier.
        self.config = dict(LIVE_CONFIG, enabled_services=[])
        body = self.quote()
        self.assertEqual(body["needs"], "services")

    def test_a_quote_store_outage_still_lets_the_buyer_see_prices(self):
        class Broken:
            def get(self, *a, **k):
                raise RuntimeError("dynamo down")

            def put(self, *a, **k):
                raise RuntimeError("dynamo down")

        body = self.quote(store=Broken())
        self.assertTrue(body["options"])
        self.assertNotIn("quote_id", body)

    def test_a_non_live_zone_never_touches_a_carrier(self):
        # Tiers 1 and 2 are arithmetic over the tenant's own settings, which is what keeps this endpoint
        # safe to leave public.
        self.config = dict(LIVE_CONFIG,
                           zones=[{"destinations": [{"country": "US"}],
                                   "rule": {"type": "flat", "amount": 500}}])
        body = self.quote(cipher=Cipher(key=None))  # would raise if a carrier were asked
        self.assertEqual(body["options"][0]["amount"], 500)
        self.assertEqual(body["needs"], "")

    def test_a_flat_zone_is_quoted_too_so_checkout_can_price_from_the_server(self):
        self.config = dict(LIVE_CONFIG,
                           zones=[{"destinations": [{"country": "US"}],
                                   "rule": {"type": "flat", "amount": 500}}])
        body = self.quote(cipher=Cipher(key=None))
        self.assertTrue(body["quote_id"].startswith("shq_"))

    def test_the_quote_id_is_derived_not_random(self):
        body = self.quote()
        row = self.store.rows[("t1", body["quote_id"])]
        self.assertEqual(body["quote_id"],
                         cache_id(tenant_id="t1", mode="test", cart_fingerprint=row["fingerprint"]))

    def test_a_test_quote_and_a_live_quote_never_share_a_row(self):
        test_body = self.quote()
        live = shipping_quote(tenant_id="t1", offer_id="o1", product_id="p1", price_id="pr1",
                              quantity="1", country="US", postal_code="80202", region="CO", mode="live",
                              offers_repo=Repo({"o1": OFFER}), products_repo=Repo({"p1": PRODUCT}),
                              quotes_repo=self.store, secret_cipher=Cipher())
        self.assertNotEqual(test_body["quote_id"], json.loads(live["body"])["quote_id"])

    def test_the_price_expires(self):
        body = self.quote()
        row = self.store.rows[("t1", body["quote_id"])]
        self.assertEqual(row["expires_at"] - row["created_at"], QUOTE_TTL_SECONDS)
