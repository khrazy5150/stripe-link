"""Price integrity: what the buyer agreed to is what Stripe is told, and the browser cannot move it.

plans/LIVE_SHIPPING_RATES.md phase 4. The element sends a QUOTE ID and a SERVICE TOKEN. The amount lives
on the server's own row, so these tests are mostly about what happens when the pair is wrong: stale,
tampered, for another tenant, for a cart that has since changed, or for a country this session will not
accept an address from.
"""
import time
import unittest

from handlers.checkout import build_checkout_payload
from stripe_link.domain.shipping_quotes import build_quote, cache_id
from stripe_link.domain.shipping_quotes import fingerprint as quote_fingerprint

SERVICES = [{"service_token": "ups_ground", "label": "UPS Ground Saver"},
            {"service_token": "usps_ground", "label": "USPS Ground Advantage"}]
LIVE_CONFIG = {
    "enabled_services": SERVICES,
    "boxes": [{"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}],
    "ship_from_address": {"postal_code": "80301", "country": "US", "street1": "1 Main",
                          "city": "Denver", "state": "CO"},
    "provider": {"name": "mock", "api_key_ref": "ref_1"},
    "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}},
              {"destinations": [{"country": "CA"}], "rule": {"type": "flat", "amount": 2500}}],
}
PRODUCTS = {"p1": {"product_id": "p1", "name": "Projector", "product_type": "physical",
                   "fulfillment": {"requires_shipping": True,
                                   "item_dimensions": {"length_in": 8, "width_in": 6, "height_in": 4,
                                                       "weight_lb": 3.0}},
                   "prices": [{"price_id": "pr1", "unit_amount": 5679, "currency": "usd"}]}}
ITEMS = [{"product_id": "p1", "price_id": "pr1", "quantity": 1, "unit_amount": 5679, "currency": "usd"}]
OFFER = {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"}}
TO = {"country": "US", "postal_code": "80202", "region": "CO"}
OPTIONS = [{"service_token": "ups_ground", "carrier": "ups", "label": "UPS Ground Saver", "amount": 642},
           {"service_token": "usps_ground", "carrier": "usps", "label": "USPS Ground Advantage",
            "amount": 718}]


class Store:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.puts = 0

    def get(self, tenant_id, quote_id):
        return self.rows.get((tenant_id, quote_id))

    def put(self, tenant_id, record):
        self.puts += 1
        self.rows[(tenant_id, record["quote_id"])] = record


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


def parcels_for(items=None):
    from handlers.checkout import _quote_parcels

    return _quote_parcels(items or ITEMS, PRODUCTS, LIVE_CONFIG)


def a_stored_quote(*, tenant_id="t1", mode="test", offer_id="o1", items=None, destination=None,
                   options=None, now=None):
    items = items or ITEMS
    destination = destination or TO
    now = int(time.time()) if now is None else now
    fp = quote_fingerprint(offer_id=offer_id, items=items, parcels=parcels_for(items),
                           destination=destination)
    return build_quote(quote_id=cache_id(tenant_id=tenant_id, mode=mode, cart_fingerprint=fp),
                       tenant_id=tenant_id, mode=mode, offer_id=offer_id, destination=destination,
                       parcels=parcels_for(items), items=items, options=options or OPTIONS,
                       source="zone", now=now)


def payload(quote=None, *, service="ups_ground", quote_id=None, store=None, items=None,
            ship_to_country="US"):
    store = store if store is not None else Store()
    if quote:
        store.rows[(quote["tenant_id"], quote["quote_id"])] = quote
    return build_checkout_payload(
        tenant_id="t1", offer=OFFER, products_by_id=PRODUCTS,
        resolved={"items": items or ITEMS, "subtotal": 5679, "currency": "usd"},
        success_url="https://x/s", cancel_url="https://x/c",
        shipping_config=LIVE_CONFIG, ship_to_country=ship_to_country,
        shipping_quote_id=quote_id if quote_id is not None else (quote or {}).get("quote_id", ""),
        shipping_service=service, secret_cipher=Cipher(), quotes_repo=store)


def amounts(built):
    return [v for k, v in sorted(built.items()) if k.endswith("[fixed_amount][amount]")]


def names(built):
    return [v for k, v in sorted(built.items()) if k.endswith("[display_name]")]


class AQuotePricesTheSession(unittest.TestCase):
    def test_the_chosen_service_is_the_only_option_stripe_is_given(self):
        # The buyer already chose on the page. Offering the menu again at the pay button would let them
        # pick a price we did not quote.
        built = payload(a_stored_quote())
        self.assertEqual(amounts(built), ["642"])
        self.assertEqual(names(built), ["UPS Ground Saver"])

    def test_a_different_service_gets_that_services_price(self):
        built = payload(a_stored_quote(), service="usps_ground")
        self.assertEqual(amounts(built), ["718"])

    def test_the_order_records_what_it_transacted_on(self):
        built = payload(a_stored_quote())
        self.assertTrue(built["metadata[shipping_quote_id]"].startswith("shq_"))
        self.assertEqual(built["metadata[shipping_service]"], "ups_ground")
        self.assertEqual(built["metadata[shipping_quoted_amount]"], "642")

    def test_the_quoted_postcode_is_kept_for_the_variance_check(self):
        # Half of the audit pair. The webhook supplies the other half from Stripe's collected address.
        self.assertEqual(payload(a_stored_quote())["metadata[shipping_postal_code]"], "80202")

    def test_a_live_zone_is_now_charged_rather_than_shipped_free(self):
        # The original bug, end to end: a live US zone produced no shipping line at all.
        self.assertTrue(amounts(payload(a_stored_quote())))


class TheBrowserCannotMoveThePrice(unittest.TestCase):
    def test_no_amount_parameter_exists_to_tamper_with(self):
        import inspect

        signature = inspect.signature(build_checkout_payload)
        self.assertNotIn("shipping_amount", signature.parameters)
        self.assertIn("shipping_quote_id", signature.parameters)
        self.assertIn("shipping_service", signature.parameters)

    def test_a_service_that_is_not_in_the_quote_falls_to_its_cheapest(self):
        # A stale page or a tampered token. Either way the amount is one the server computed.
        built = payload(a_stored_quote(), service="fedex_priority_overnight")
        self.assertEqual(amounts(built), ["642"])

    def test_another_tenants_quote_is_refused(self):
        quote = a_stored_quote(tenant_id="t2")
        store = Store({("t1", quote["quote_id"]): dict(quote)})
        built = payload(quote_id=quote["quote_id"], store=store)
        self.assertNotIn("metadata[shipping_quote_id]", built)

    def test_a_live_mode_quote_cannot_price_a_test_checkout(self):
        quote = a_stored_quote(mode="live")
        store = Store({("t1", quote["quote_id"]): quote})
        built = payload(quote_id=quote["quote_id"], store=store)
        self.assertNotIn("metadata[shipping_quote_id]", built)

    def test_a_quote_for_another_offer_is_refused(self):
        quote = a_stored_quote(offer_id="o2")
        store = Store({("t1", quote["quote_id"]): quote})
        built = payload(quote_id=quote["quote_id"], store=store)
        self.assertNotIn("metadata[shipping_quote_id]", built)

    def test_an_unknown_quote_id_falls_back_rather_than_failing(self):
        built = payload(quote_id="shq_does_not_exist")
        self.assertNotIn("metadata[shipping_quote_id]", built)

    def test_a_quote_for_a_country_this_session_will_not_accept_is_refused(self):
        # A price for one country with an address field open to another is the one combination that
        # charges the wrong postage with nobody tampering.
        quote = a_stored_quote(destination={"country": "CA", "postal_code": "K1A0B1", "region": ""})
        built = payload(quote, ship_to_country="US")
        self.assertNotIn("metadata[shipping_quote_id]", built)


class WhenTheQuoteNoLongerDescribesThePurchase(unittest.TestCase):
    def test_a_changed_cart_is_re_quoted_not_reused(self):
        # Two units is a different parcel. The quote was for one.
        quote = a_stored_quote()
        bigger = [dict(ITEMS[0], quantity=2)]
        store = Store({("t1", quote["quote_id"]): quote})
        built = payload(quote_id=quote["quote_id"], store=store, items=bigger)
        self.assertEqual(store.puts, 1, "a re-quote mints a NEW row")
        self.assertTrue(amounts(built))
        self.assertNotEqual(amounts(built), ["642"])

    def test_an_expired_quote_is_re_quoted(self):
        quote = a_stored_quote(now=int(time.time()) - 7200)
        store = Store({("t1", quote["quote_id"]): quote})
        built = payload(quote_id=quote["quote_id"], store=store)
        self.assertEqual(store.puts, 1)
        self.assertTrue(amounts(built))

    def test_a_re_quote_charges_the_fresh_price_not_the_stale_one(self):
        """What is immutable is the AGREEMENT, not the cache row.

        The quote row is keyed by (tenant, mode, cart, destination) so it can serve as its own cache --
        which means a refresh writes over it, by design. The record of what a particular buyer agreed to
        lives on the SESSION (and from there the order): quote id, service, amount and postcode, all
        stamped into metadata below. That is what survives, and what a variance is later measured against.
        """
        stale = a_stored_quote(now=int(time.time()) - 7200,
                               options=[dict(OPTIONS[0], amount=1)])
        store = Store({("t1", stale["quote_id"]): stale})
        built = payload(quote_id=stale["quote_id"], store=store)
        self.assertNotEqual(built.get("metadata[shipping_quoted_amount]"), "1")
        self.assertTrue(amounts(built))

    def test_the_session_records_the_agreement_the_variance_is_measured_against(self):
        built = payload(a_stored_quote())
        for field in ("shipping_quote_id", "shipping_service", "shipping_quoted_amount",
                      "shipping_postal_code"):
            with self.subTest(field=field):
                self.assertIn(f"metadata[{field}]", built)

    def test_a_carrier_outage_at_the_pay_button_does_not_take_the_sale_down(self):
        class Broken:
            def decrypt(self, *a, **k):
                raise RuntimeError("kms down")

        quote = a_stored_quote(now=int(time.time()) - 7200)
        store = Store({("t1", quote["quote_id"]): quote})
        built = build_checkout_payload(
            tenant_id="t1", offer=OFFER, products_by_id=PRODUCTS,
            resolved={"items": ITEMS, "subtotal": 5679, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c", shipping_config=LIVE_CONFIG,
            ship_to_country="US", shipping_quote_id=quote["quote_id"],
            shipping_service="ups_ground", secret_cipher=Broken(), quotes_repo=store)
        self.assertIn("line_items[0][quantity]", built)
        self.assertNotIn("metadata[shipping_quote_id]", built)


class TheOldPathIsUntouched(unittest.TestCase):
    def test_a_buyer_who_never_used_the_element_still_checks_out(self):
        built = payload(quote_id="")
        self.assertIn("line_items[0][quantity]", built)

    def test_a_flat_zone_still_prices_without_any_quote(self):
        built = build_checkout_payload(
            tenant_id="t1", offer=OFFER, products_by_id=PRODUCTS,
            resolved={"items": ITEMS, "subtotal": 5679, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c",
            shipping_config={"enabled_services": SERVICES, "zones": [
                {"destinations": [{"country": "US"}], "rule": {"type": "flat", "amount": 700}}]},
            ship_to_country="US")
        # One option per enabled service, all at the zone's amount -- a flat zone charges the same
        # whatever speed the buyer picks. Differential pricing is what `live` is for.
        self.assertEqual(amounts(built), ["700", "700"])

    def test_the_address_country_is_still_narrowed_to_the_quoted_one(self):
        built = payload(a_stored_quote())
        allowed = [v for k, v in built.items() if k.startswith("shipping_address_collection")]
        self.assertEqual(allowed, ["US"])
