"""Server-side cart — domain resolution + public handler (plans/LISTICLE_AND_CART.md L2)."""
import json
import unittest

from handlers.cart import handler
from stripe_link.domain.cart import (
    CartError,
    add_line,
    cart_token_doc,
    cart_token_valid,
    new_cart,
    normalize_email,
    resolve_cart_line,
)
from stripe_link.domain.documents import DocumentValidationError, validate_cart, validate_cart_token
from tests.fakes import FakeDocumentRepository


def _product(pid="prod_a", price_id="price_a", amount=1999):
    return {
        "schema_version": "2026-05-29", "document_type": "product", "tenant_id": "t1", "product_id": pid,
        "name": pid.upper(), "images": [f"https://img.example.com/{pid}.webp"], "default_price_id": price_id,
        "prices": [{"price_id": price_id, "unit_amount": amount, "currency": "usd", "quantity": 1, "context": "standard"}],
    }


def _offer():
    return {
        "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
        "name": "Best Sellers", "offer_type": "listicle", "product_intent": "transactional",
        "stripe_mode": "test", "status": "active",
        "items": [
            {"product_id": "prod_a", "default_price_id": "price_a"},
            {"product_id": "prod_b", "default_price_id": "price_b"},
        ],
    }


class CartDomainTests(unittest.TestCase):
    def test_resolve_line_uses_server_single_unit_price(self):
        line = resolve_cart_line(_offer(), {"prod_a": _product()}, {}, product_id="prod_a", qty=2)
        self.assertEqual(line["price_id"], "price_a")
        self.assertEqual(line["unit_amount"], 1999)
        self.assertEqual(line["qty"], 2)
        self.assertEqual(line["name"], "PROD_A")

    def test_resolve_line_rejects_item_not_in_offer(self):
        with self.assertRaises(CartError):
            resolve_cart_line(_offer(), {"prod_z": _product("prod_z")}, {}, product_id="prod_z")

    def test_add_line_merges_quantity_and_totals(self):
        cart = new_cart("t1", "cart1", "off_1", now=1000)
        line = resolve_cart_line(_offer(), {"prod_a": _product()}, {}, product_id="prod_a", qty=2)
        add_line(cart, line)
        add_line(cart, resolve_cart_line(_offer(), {"prod_a": _product()}, {}, product_id="prod_a", qty=1))
        self.assertEqual(len(cart["line_items"]), 1)
        self.assertEqual(cart["line_items"][0]["qty"], 3)
        self.assertEqual(cart["total_amount"], 3 * 1999)
        self.assertEqual(cart["item_count"], 3)

    def test_validate_cart_rejects_bad_qty(self):
        cart = new_cart("t1", "cart1", "off_1", now=1000)
        cart["line_items"] = [{"product_id": "prod_a", "price_id": "price_a", "qty": 0, "unit_amount": 1999}]
        with self.assertRaises(DocumentValidationError):
            validate_cart(cart)


class CartHandlerTests(unittest.TestCase):
    def setUp(self):
        self.carts = FakeDocumentRepository("cart_id")
        self.offers = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.services = FakeDocumentRepository("service_id")
        self.tokens = FakeDocumentRepository("token")
        self.offers.put(_offer())
        self.products.put(_product("prod_a", "price_a", 1999))
        self.products.put(_product("prod_b", "price_b", 2599))

    def _post(self, body, now=1000):
        return handler(
            {"httpMethod": "POST", "body": json.dumps(body)}, None,
            carts_repo=self.carts, offers_repo=self.offers, products_repo=self.products,
            services_repo=self.services, cart_tokens_repo=self.tokens, now_fn=lambda: now,
        )

    def test_add_creates_cart_and_ignores_client_amount(self):
        # Client sends a bogus amount; the server re-resolves and ignores it.
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a", "qty": 2, "unit_amount": 1})
        self.assertEqual(resp["statusCode"], 201)
        payload = json.loads(resp["body"])
        cart_id = payload["cart_id"]
        self.assertTrue(cart_id)
        line = payload["cart"]["line_items"][0]
        self.assertEqual(line["unit_amount"], 1999)
        self.assertEqual(line["qty"], 2)
        self.assertEqual(payload["cart"]["total_amount"], 3998)
        # Persisted under the returned id, and carries a TTL for abandonment cleanup.
        stored = self.carts.get("t1", cart_id)
        self.assertIsNotNone(stored)
        self.assertIn("retention_expires_at", stored)

    def test_second_add_with_cart_id_merges(self):
        first = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a", "qty": 1})["body"])
        cart_id = first["cart_id"]
        second = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "cart_id": cart_id, "product_id": "prod_a", "qty": 1})["body"])
        self.assertEqual(second["cart_id"], cart_id)
        self.assertEqual(len(second["cart"]["line_items"]), 1)
        self.assertEqual(second["cart"]["line_items"][0]["qty"], 2)

    def test_add_distinct_products_makes_two_lines(self):
        first = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a"})["body"])
        cart_id = first["cart_id"]
        second = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "cart_id": cart_id, "product_id": "prod_b"})["body"])
        self.assertEqual(len(second["cart"]["line_items"]), 2)
        self.assertEqual(second["cart"]["total_amount"], 1999 + 2599)

    def test_add_rejects_item_not_in_offer(self):
        self.products.put(_product("prod_z", "price_z", 500))
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_z"})
        self.assertEqual(resp["statusCode"], 400)

    def test_add_missing_offer_is_404(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "nope", "product_id": "prod_a"})
        self.assertEqual(resp["statusCode"], 404)

    def test_add_rejects_malformed_cart_id(self):
        resp = self._post({"tenant_id": "t1", "offer_id": "off_1", "cart_id": "bad id!", "product_id": "prod_a"})
        self.assertEqual(resp["statusCode"], 400)

    def test_get_returns_cart(self):
        cart_id = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a"})["body"])["cart_id"]
        resp = handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", "cart_id": cart_id}},
            None, carts_repo=self.carts,
        )
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["cart"]["cart_id"], cart_id)

    def test_get_missing_cart_is_404(self):
        resp = handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", "cart_id": "deadbeefdeadbeef"}},
            None, carts_repo=self.carts,
        )
        self.assertEqual(resp["statusCode"], 404)

    def _add(self, product_id="prod_a", cart_id=None, qty=1):
        body = {"tenant_id": "t1", "offer_id": "off_1", "product_id": product_id, "qty": qty}
        if cart_id:
            body["cart_id"] = cart_id
        return json.loads(self._post(body)["body"])

    def _patch(self, line_id, cart_id, qty):
        return handler(
            {"httpMethod": "PATCH", "pathParameters": {"line_id": line_id},
             "body": json.dumps({"tenant_id": "t1", "cart_id": cart_id, "qty": qty})},
            None, carts_repo=self.carts, now_fn=lambda: 2000,
        )

    def test_patch_sets_quantity(self):
        added = self._add("prod_a")
        line_id = added["cart"]["line_items"][0]["line_id"]
        resp = self._patch(line_id, added["cart_id"], 5)
        self.assertEqual(resp["statusCode"], 200)
        cart = json.loads(resp["body"])["cart"]
        self.assertEqual(cart["line_items"][0]["qty"], 5)
        self.assertEqual(cart["total_amount"], 5 * 1999)

    def test_patch_zero_qty_removes_line(self):
        added = self._add("prod_a")
        line_id = added["cart"]["line_items"][0]["line_id"]
        cart = json.loads(self._patch(line_id, added["cart_id"], 0)["body"])["cart"]
        self.assertEqual(cart["line_items"], [])
        self.assertEqual(cart["total_amount"], 0)

    def test_delete_removes_line(self):
        added = self._add("prod_a", qty=2)
        added = self._add("prod_b", cart_id=added["cart_id"])
        line_id = added["cart"]["line_items"][0]["line_id"]
        resp = handler(
            {"httpMethod": "DELETE", "pathParameters": {"line_id": line_id},
             "queryStringParameters": {"tenant_id": "t1", "cart_id": added["cart_id"]}},
            None, carts_repo=self.carts, now_fn=lambda: 2000,
        )
        self.assertEqual(resp["statusCode"], 200)
        cart = json.loads(resp["body"])["cart"]
        self.assertEqual(len(cart["line_items"]), 1)

    def test_patch_unknown_line_is_404(self):
        added = self._add("prod_a")
        resp = self._patch("nosuchline", added["cart_id"], 3)
        self.assertEqual(resp["statusCode"], 404)

    def test_explicit_email_is_stamped_on_cart(self):
        added = self._add("prod_a")
        # Re-post with an email; the cart persists it (not echoed in the public response).
        self._post({"tenant_id": "t1", "offer_id": "off_1", "cart_id": added["cart_id"], "product_id": "prod_a", "email": "Buyer@Example.com "})
        stored = self.carts.get("t1", added["cart_id"])
        self.assertEqual(stored["email"], "buyer@example.com")

    def test_identified_link_token_stamps_email(self):
        self.tokens.put(cart_token_doc("t1", "tok_abc", "vip@example.com", "off_1", now=500))
        added = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a", "ct": "tok_abc"}, now=1000)["body"])
        self.assertEqual(self.carts.get("t1", added["cart_id"])["email"], "vip@example.com")

    def test_expired_token_does_not_stamp(self):
        self.tokens.put(cart_token_doc("t1", "tok_old", "vip@example.com", "off_1", now=0, ttl_seconds=100))
        added = json.loads(self._post({"tenant_id": "t1", "offer_id": "off_1", "product_id": "prod_a", "ct": "tok_old"}, now=1000)["body"])
        self.assertEqual(self.carts.get("t1", added["cart_id"])["email"], "")


class CartTokenDomainTests(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(normalize_email(" A@B.com "), "a@b.com")
        self.assertEqual(normalize_email("nope"), "")
        self.assertEqual(normalize_email("a@b"), "")

    def test_token_validity(self):
        doc = cart_token_doc("t1", "tok", "a@b.com", "off", now=1000, ttl_seconds=100)
        self.assertTrue(cart_token_valid(doc, now=1050))
        self.assertFalse(cart_token_valid(doc, now=2000))   # expired
        self.assertFalse(cart_token_valid(None, now=1050))

    def test_validate_cart_token(self):
        validate_cart_token(cart_token_doc("t1", "tok", "a@b.com", "off", now=1000))
        with self.assertRaises(DocumentValidationError):
            validate_cart_token(cart_token_doc("t1", "tok", "not-an-email", "off", now=1000))

    def test_new_cart_defaults_open(self):
        cart = new_cart("t1", "c", "o", now=1)
        self.assertEqual(cart["status"], "open")
        self.assertEqual(cart["email"], "")


if __name__ == "__main__":
    unittest.main()
