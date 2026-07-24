"""Abandoned-cart recovery — sweep, email, unsubscribe, token rehydration (LISTICLE_AND_CART.md L2 D2)."""
import json
import unittest

from handlers.cart import handler as cart_handler
from handlers.cart_recovery import handler as sweep_handler
from stripe_link.domain.cart import (
    cart_token_doc,
    mark_recovery_sent,
    new_cart,
    normalize_page_url,
    recoverable,
)
from stripe_link.domain.cart_recovery import recovery_email
from tests.fakes import FakeDocumentRepository

PAGE = "https://shop.example.com/deals"


def _open_cart(cart_id="cart1", *, email="buyer@example.com", updated_at=0, attempts=0, page_url=PAGE, opted_out=False, items=1):
    cart = new_cart("t1", cart_id, "off_1", now=0)
    cart["email"] = email
    cart["email_opted_out"] = opted_out
    cart["page_url"] = page_url
    cart["updated_at"] = updated_at
    cart["item_count"] = items
    cart["total_amount"] = 1999 * items
    cart["currency"] = "usd"
    cart["line_items"] = [{"line_id": "l1", "product_id": "p", "price_id": "pr", "qty": items, "unit_amount": 1999, "currency": "usd", "name": "Widget"}]
    if attempts:
        cart["recovery"] = {"attempts": attempts, "last_sent_at": 10}
    return cart


class RecoverableTests(unittest.TestCase):
    def _r(self, cart, now=10000):
        return recoverable(cart, now, min_age_seconds=3600, max_attempts=1)

    def test_eligible_stale_cart(self):
        self.assertTrue(self._r(_open_cart(updated_at=0)))

    def test_fresh_cart_not_eligible(self):
        self.assertFalse(self._r(_open_cart(updated_at=9000)))   # <1h ago

    def test_no_email_not_eligible(self):
        self.assertFalse(self._r(_open_cart(email="")))

    def test_opted_out_not_eligible(self):
        self.assertFalse(self._r(_open_cart(opted_out=True)))

    def test_already_sent_not_eligible(self):
        self.assertFalse(self._r(_open_cart(attempts=1)))

    def test_no_page_url_not_eligible(self):
        self.assertFalse(self._r(_open_cart(page_url="")))

    def test_converted_not_eligible(self):
        cart = _open_cart()
        cart["status"] = "converted"
        self.assertFalse(self._r(cart))

    def test_normalize_page_url_requires_https(self):
        self.assertEqual(normalize_page_url("http://x.com"), "")
        self.assertEqual(normalize_page_url("https://x.com/p"), "https://x.com/p")


class RecoveryEmailTests(unittest.TestCase):
    def test_email_has_links_and_items(self):
        content = recovery_email(_open_cart(items=2), recovery_url="https://r/return?ct=tok",
                                 unsubscribe_url="https://r/unsub", organization={"name": "Luxe"})
        self.assertIn("2 items", content["subject"])
        self.assertIn("https://r/return?ct=tok", content["html"])
        self.assertIn("https://r/unsub", content["html"])
        self.assertIn("Luxe", content["html"])
        self.assertIn("Widget", content["text"])


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.carts = FakeDocumentRepository("cart_id")
        self.tokens = FakeDocumentRepository("token")
        self.sent = []

    def _mailer(self, **kwargs):
        self.sent.append(kwargs)
        return {"ok": True}

    def _run(self, now=10000):
        return sweep_handler(
            {}, None, carts_repo=self.carts, cart_tokens_repo=self.tokens, sites_repo=None,
            mailer_send=self._mailer, now_fn=lambda: now, token_factory=lambda: "tok_fixed",
        )

    def test_sweep_sends_and_marks(self):
        self.carts.put(_open_cart("c1", updated_at=0))
        result = self._run()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.sent[0]["to"], "buyer@example.com")
        # A recovery token was minted pointing back to the cart, and the cart is marked sent (won't re-send).
        self.assertEqual(self.tokens.get("t1", "tok_fixed")["cart_id"], "c1")
        self.assertEqual(self.carts.get("t1", "c1")["recovery"]["attempts"], 1)
        self.assertEqual(self._run()["sent"], 0)   # second sweep: cap reached

    def test_sweep_skips_fresh_and_converted(self):
        self.carts.put(_open_cart("fresh", updated_at=9999))
        converted = _open_cart("done", updated_at=0)
        converted["status"] = "converted"
        self.carts.put(converted)
        self.assertEqual(self._run()["sent"], 0)


class UnsubscribeAndRehydrateTests(unittest.TestCase):
    def setUp(self):
        self.carts = FakeDocumentRepository("cart_id")
        self.tokens = FakeDocumentRepository("token")
        self.carts.put(_open_cart("c1", updated_at=0))
        self.tokens.put(cart_token_doc("t1", "rtok", "buyer@example.com", "off_1", now=100, cart_id="c1"))

    def test_get_by_token_rehydrates_cart(self):
        resp = cart_handler(
            {"httpMethod": "GET", "resource": "/cart", "queryStringParameters": {"tenant_id": "t1", "ct": "rtok"}},
            None, carts_repo=self.carts, cart_tokens_repo=self.tokens, now_fn=lambda: 200,
        )
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["cart"]["cart_id"], "c1")

    def test_unsubscribe_opts_out_cart(self):
        resp = cart_handler(
            {"httpMethod": "GET", "resource": "/cart/unsubscribe", "queryStringParameters": {"tenant_id": "t1", "token": "rtok"}},
            None, carts_repo=self.carts, cart_tokens_repo=self.tokens, now_fn=lambda: 300,
        )
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("unsubscribed", resp["body"].lower())
        self.assertTrue(self.carts.get("t1", "c1")["email_opted_out"])

    def test_unsubscribe_unknown_token_still_confirms(self):
        resp = cart_handler(
            {"httpMethod": "GET", "resource": "/cart/unsubscribe", "queryStringParameters": {"tenant_id": "t1", "token": "nope"}},
            None, carts_repo=self.carts, cart_tokens_repo=self.tokens, now_fn=lambda: 300,
        )
        self.assertEqual(resp["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
