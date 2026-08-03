"""Multi-line cart checkout handler (plans/LISTICLE_AND_CART.md L2 Slice C)."""
import json
import unittest
from urllib.parse import parse_qs

from handlers.cart_checkout import handler
from stripe_link.domain.cart import CartError, resolved_items_for_checkout
from stripe_link.domain.fees import clear_config_cache


def _product(pid, price_id, amount):
    return {
        "schema_version": "2026-05-29", "document_type": "product", "tenant_id": "t1", "product_id": pid,
        "name": pid.upper(), "product_type": "physical", "status": "active",
        "default_price_id": price_id,
        "prices": [{"price_id": price_id, "stripe_price_id": None, "currency": "usd", "unit_amount": amount, "quantity": 1, "context": "standard"}],
    }


def _offer():
    return {
        "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
        "name": "Best Sellers", "offer_type": "listicle", "product_intent": "transaction",
        "stripe_mode": "test", "status": "active", "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
        "items": [
            {"product_id": "prod_a", "default_price_id": "price_a"},
            {"product_id": "prod_b", "default_price_id": "price_b"},
        ],
    }


def _cart(lines):
    return {
        "schema_version": 1, "document_type": "cart", "tenant_id": "t1", "cart_id": "cartabc123",
        "offer_id": "off_1", "line_items": lines, "created_at": 1000,
    }


def _tiered_product():
    return {
        "schema_version": "2026-05-29", "document_type": "product", "tenant_id": "t1", "product_id": "prod_t",
        "name": "Tiered", "product_type": "physical", "status": "active", "default_price_id": "price_1",
        "prices": [
            {"price_id": "price_1", "stripe_price_id": None, "currency": "usd", "unit_amount": 1000, "quantity": 1, "context": "standard"},
            {"price_id": "price_3", "stripe_price_id": None, "currency": "usd", "unit_amount": 2400, "quantity": 3, "context": "standard"},
        ],
    }


def _tiered_offer():
    return {
        "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
        "name": "Tiered", "offer_type": "listicle", "product_intent": "transaction",
        "stripe_mode": "test", "status": "active", "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
        "items": [{"product_id": "prod_t", "default_price_id": "price_1", "selectable_prices": [
            {"price_id": "price_1", "quantity": 1}, {"price_id": "price_3", "quantity": 3},
        ]}],
    }


class ResolvedItemsForCheckoutTests(unittest.TestCase):
    def test_chosen_tier_reaches_checkout_not_single_unit(self):
        # A cart line at the 3-pack tier must check out at that tier's price, NOT collapse to single-unit
        # (plans/LANDING_CAROUSEL_FIXES.md — the tier the buyer picked must reach Stripe).
        cart = _cart([{"product_id": "prod_t", "service_id": "", "price_id": "price_3", "qty": 1,
                       "unit_amount": 2400, "currency": "usd", "line_id": "l1"}])
        items = resolved_items_for_checkout(cart, _tiered_offer(), {"prod_t": _tiered_product()}, {})
        self.assertEqual(items[0]["price_id"], "price_3")
        self.assertEqual(items[0]["unit_amount"], 2400)


class FakeRepo:
    def __init__(self, id_field, documents):
        self.id_field = id_field
        self.documents = {(d["tenant_id"], d[id_field]): d for d in documents}

    def get(self, tenant_id, document_id):
        return self.documents.get((tenant_id, document_id))


class FakeStripeKeysRepository:
    def get(self, tenant_id, mode="test"):
        return {"tenant_id": tenant_id, "mode": mode, "secret_key_ref": "sk_test_demo"}


class FakeCipher:
    def decrypt(self, secret_ref, *, tenant_id, mode, field):
        return secret_ref


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"url": "https://checkout.stripe.com/c/pay/session"}).encode("utf-8")


class CartCheckoutDomainTests(unittest.TestCase):
    def test_resolved_items_reprice_and_shape(self):
        cart = _cart([{"line_id": "l1", "product_id": "prod_a", "price_id": "price_a", "qty": 2, "unit_amount": 1, "currency": "usd"}])
        items = resolved_items_for_checkout(cart, _offer(), {"prod_a": _product("prod_a", "price_a", 1999)}, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["unit_amount"], 1999)   # re-resolved, not the stored 1
        self.assertEqual(items[0]["quantity"], 2)

    def test_service_line_rejected(self):
        cart = _cart([{"line_id": "l1", "service_id": "svc_1", "price_id": "p", "qty": 1, "unit_amount": 100, "currency": "usd"}])
        with self.assertRaises(CartError):
            resolved_items_for_checkout(cart, _offer(), {}, {})

    def test_empty_cart_rejected(self):
        with self.assertRaises(CartError):
            resolved_items_for_checkout(_cart([]), _offer(), {}, {})


class CartCheckoutHandlerTests(unittest.TestCase):
    def setUp(self):
        clear_config_cache()
        self.requests = []

    def tearDown(self):
        clear_config_cache()

    def opener(self, request, timeout=20):
        self.requests.append(request)
        return FakeResponse()

    def _call(self, cart, body_extra=None, pages_repo=None):
        body = {"tenant_id": "t1", "cart_id": "cartabc123",
                "success_url": "https://p.example.com/thanks", "cancel_url": "https://p.example.com/buy"}
        body.update(body_extra or {})
        return handler(
            {"httpMethod": "POST", "body": json.dumps(body)}, None,
            carts_repo=FakeRepo("cart_id", [cart]),
            offers_repo=FakeRepo("offer_id", [_offer()]),
            products_repo=FakeRepo("product_id", [_product("prod_a", "price_a", 1999), _product("prod_b", "price_b", 2599)]),
            services_repo=FakeRepo("service_id", []),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=FakeRepo("tenant_id", [{"tenant_id": "t1", "billing_status": "active"}]),
            pages_repo=pages_repo,
            secret_cipher=FakeCipher(),
            opener=self.opener,
        )

    def _stripe_payload(self):
        return parse_qs(self.requests[0].data.decode("utf-8"))

    def test_multi_line_session_built_from_cart(self):
        cart = _cart([
            {"line_id": "l1", "product_id": "prod_a", "price_id": "price_a", "qty": 2, "unit_amount": 1999, "currency": "usd"},
            {"line_id": "l2", "product_id": "prod_b", "price_id": "price_b", "qty": 1, "unit_amount": 2599, "currency": "usd"},
        ])
        resp = self._call(cart)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["url"], "https://checkout.stripe.com/c/pay/session")
        payload = self._stripe_payload()
        # Two line items, priced inline from the re-resolved amounts, with the cart quantity.
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], ["1999"])
        self.assertEqual(payload["line_items[0][quantity]"], ["2"])
        self.assertEqual(payload["line_items[1][price_data][unit_amount]"], ["2599"])
        self.assertEqual(payload["metadata[cart_id]"], ["cartabc123"])

    def test_billing_hold_blocks_checkout(self):
        resp = handler(
            {"httpMethod": "POST", "body": json.dumps({"tenant_id": "t1", "cart_id": "cartabc123", "success_url": "https://p/s", "cancel_url": "https://p/c"})},
            None,
            carts_repo=FakeRepo("cart_id", [_cart([{"line_id": "l1", "product_id": "prod_a", "price_id": "price_a", "qty": 1, "unit_amount": 1999, "currency": "usd"}])]),
            offers_repo=FakeRepo("offer_id", [_offer()]),
            products_repo=FakeRepo("product_id", [_product("prod_a", "price_a", 1999)]),
            services_repo=FakeRepo("service_id", []),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=FakeRepo("tenant_id", [{"tenant_id": "t1", "billing_status": "suspended"}]),
            secret_cipher=FakeCipher(), opener=self.opener,
        )
        self.assertEqual(resp["statusCode"], 402)
        self.assertEqual(self.requests, [])

    def test_draft_page_blocks_cart_checkout(self):
        # The cart CTA now sends its page_id; a draft page must refuse the transaction (403, no Stripe call).
        cart = _cart([{"line_id": "l1", "product_id": "prod_a", "price_id": "price_a", "qty": 1, "unit_amount": 1999, "currency": "usd"}])
        resp = handler(
            {"httpMethod": "POST", "body": json.dumps({
                "tenant_id": "t1", "cart_id": "cartabc123", "page_id": "page_draft",
                "success_url": "https://p/s", "cancel_url": "https://p/c"})},
            None,
            carts_repo=FakeRepo("cart_id", [cart]),
            offers_repo=FakeRepo("offer_id", [_offer()]),
            products_repo=FakeRepo("product_id", [_product("prod_a", "price_a", 1999)]),
            services_repo=FakeRepo("service_id", []),
            stripe_repo=FakeStripeKeysRepository(),
            tenant_repo=FakeRepo("tenant_id", [{"tenant_id": "t1", "billing_status": "active"}]),
            pages_repo=FakeRepo("page_id", [{"tenant_id": "t1", "page_id": "page_draft", "status": "draft"}]),
            secret_cipher=FakeCipher(), opener=self.opener,
        )
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "page_not_published")
        self.assertEqual(self.requests, [])

    def test_published_page_allows_cart_checkout(self):
        cart = _cart([{"line_id": "l1", "product_id": "prod_a", "price_id": "price_a", "qty": 1, "unit_amount": 1999, "currency": "usd"}])
        resp = self._call(cart, body_extra={"page_id": "page_live"},
                          pages_repo=FakeRepo("page_id", [{"tenant_id": "t1", "page_id": "page_live", "status": "published"}]))
        self.assertEqual(resp["statusCode"], 200)

    def test_empty_cart_is_404(self):
        resp = self._call(_cart([]))
        self.assertEqual(resp["statusCode"], 404)

    def test_missing_redirect_urls_rejected(self):
        resp = handler(
            {"httpMethod": "POST", "body": json.dumps({"tenant_id": "t1", "cart_id": "cartabc123"})},
            None, carts_repo=FakeRepo("cart_id", []), opener=self.opener,
        )
        self.assertEqual(resp["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
