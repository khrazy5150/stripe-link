"""A cart is what gets posted, so a cart is what gets quoted and charged.

Found by the author 2026-10-01 on a listicle page: the shipping figure did not move as items were added,
and checkout charged no postage at all. Two separate faults, both money:

1. The shipping element quoted the selected PRICE CARD. On a cart page that is one item out of several,
   so a basket of three was shown one item's postage and the number never changed.
2. `handlers/cart_checkout` passed NO shipping parameters to `build_checkout_payload`, so `shipping_config`
   defaulted to None, zones could not be read, and every cart collected an address and charged nothing --
   while the single-offer path beside it quoted and charged correctly.
"""
import json
import pathlib
import unittest

import handlers.checkout as checkout_module
from handlers.checkout import _cart_lines, shipping_quote

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
CART_CHECKOUT = (ROOT / "src/handlers/cart_checkout.py").read_text(encoding="utf-8")

DIMS = {"length_in": 4, "width_in": 3, "height_in": 2, "weight_lb": 1.0}


def product(pid, name):
    return {"product_id": pid, "name": name, "product_type": "physical",
            "fulfillment": {"requires_shipping": True, "weight_lb": 1.0, "item_dimensions": DIMS},
            "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}


OFFER = {"offer_id": "o1", "tenant_id": "t1",
         "items": [{"product_id": "a", "price_id": "pr1"}, {"product_id": "b", "price_id": "pr1"}]}
PRODUCTS = {"a": product("a", "Gummies"), "b": product("b", "NAD")}
CONFIG = {
    "boxes": [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15},
              {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}],
    "enabled_services": [{"service_token": "usps_ground", "label": "Ground"}],
    "ship_from_address": {"postal_code": "80301", "country": "US", "city": "Denver", "state": "CO"},
    "provider": {"name": "mock", "api_key_ref": "ref_1"},
    "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}}],
}


class Repo:
    def __init__(self, docs):
        self.docs = docs

    def get(self, tenant_id, doc_id=None):
        return self.docs.get(doc_id or tenant_id)


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


class CartLinesTests(unittest.TestCase):
    CART = {"cart_id": "c1", "line_items": [
        {"product_id": "a", "price_id": "pr1", "quantity": 1},
        {"product_id": "b", "price_id": "pr1", "quantity": 2},
        {"service_id": "s1", "quantity": 1},
    ]}

    def test_it_reads_the_carts_product_lines(self):
        lines = _cart_lines("t1", "c1", "test", carts_repo=Repo({"c1": self.CART}))
        self.assertEqual([(l["product_id"], l["quantity"]) for l in lines], [("a", 1), ("b", 2)])

    def test_service_lines_have_no_parcel_and_are_skipped(self):
        lines = _cart_lines("t1", "c1", "test", carts_repo=Repo({"c1": self.CART}))
        self.assertTrue(all(l["product_id"] for l in lines))

    def test_an_unreadable_cart_falls_back_rather_than_failing(self):
        class Broken:
            def get(self, *a, **k):
                raise RuntimeError("dynamo down")

        self.assertEqual(_cart_lines("t1", "c1", "test", carts_repo=Broken()), [])


class TheQuoteFollowsTheCartTests(unittest.TestCase):
    def setUp(self):
        self._real = checkout_module._tenant_shipping_config
        checkout_module._tenant_shipping_config = lambda tenant_id: CONFIG

    def tearDown(self):
        checkout_module._tenant_shipping_config = self._real

    def quote(self, cart_id="", cart=None):
        return json.loads(shipping_quote(
            tenant_id="t1", offer_id="o1", product_id="a", price_id="pr1", quantity="1",
            country="US", postal_code="80202", region="CO", mode="test", cart_id=cart_id,
            offers_repo=Repo({"o1": OFFER}), products_repo=Repo(PRODUCTS),
            carts_repo=Repo({"c1": cart} if cart else {}),
            quotes_repo=None, secret_cipher=Cipher())["body"])

    def test_a_bigger_cart_costs_more_to_post(self):
        # The symptom the author saw: the figure never moved as items were added.
        one = {"cart_id": "c1", "line_items": [{"product_id": "a", "price_id": "pr1", "quantity": 1}]}
        many = {"cart_id": "c1", "line_items": [{"product_id": "a", "price_id": "pr1", "quantity": 1},
                                                {"product_id": "b", "price_id": "pr1", "quantity": 4}]}
        small = self.quote(cart_id="c1", cart=one)["options"][0]["amount"]
        big = self.quote(cart_id="c1", cart=many)["options"][0]["amount"]
        self.assertGreater(big, small)

    def test_no_cart_still_quotes_the_selected_card(self):
        # A plain buy-now page has no server cart, and the card is the only cart there is.
        self.assertTrue(self.quote()["options"])


class TheCartCheckoutChargesItTests(unittest.TestCase):
    def test_it_passes_the_shipping_config(self):
        self.assertIn("shipping_config=_tenant_shipping_config(tenant_id)", CART_CHECKOUT)

    def test_it_passes_the_buyers_quote_and_service(self):
        self.assertIn('shipping_quote_id=str(body.get("shipping_quote")', CART_CHECKOUT)
        self.assertIn('shipping_service=str(body.get("shipping_service")', CART_CHECKOUT)

    def test_it_narrows_the_country_like_the_single_offer_path(self):
        self.assertIn('ship_to_country=str(body.get("ship_to_country")', CART_CHECKOUT)

    def test_it_may_read_the_zones_it_now_obeys(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  CartCheckoutFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("!Ref ShippingConfigTable", block)


class ThePageWiresItTests(unittest.TestCase):
    def test_the_element_sends_the_cart_id(self):
        self.assertIn("'&cart_id=' + encodeURIComponent(window.__jbCartId)", HTML)

    def test_the_cart_island_publishes_it(self):
        self.assertIn("window.__jbCartId = getCartId()", HTML)

    def test_the_element_requotes_when_the_cart_changes(self):
        self.assertIn("document.addEventListener('sl:cart-changed'", HTML)
        self.assertIn("sl:cart-changed", HTML.split("const publishCart", 1)[1][:300])

    def test_the_minicart_checkout_carries_the_quote(self):
        body = HTML.split("cartEndpoint + '/checkout'", 1)[1][:600]
        for field in ("ship_to_country", "shipping_quote", "shipping_service"):
            self.assertIn(field, body)

    def test_it_still_never_sends_an_amount(self):
        body = HTML.split("cartEndpoint + '/checkout'", 1)[1][:600]
        self.assertNotIn("shipping_amount", body)
