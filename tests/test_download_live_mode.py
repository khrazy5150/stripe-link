"""A live purchase could not download the thing it paid for.

Reported 2026-10-14, from the first real live sale on prod. The buyer's receipt link answered:

    {"error": "not_purchased", "message": "No paid order found for this download."}

The order was there and it was paid. Money tables are keyed per MODE (`TENANT#<id>#live`), the mode comes
from the REQUEST, and the link the receipt builds carries no `mode` at all -- so it resolved to the
fail-safe "test" and looked for a live order in the test books. Appending `&mode=live` by hand returned 302
against production, which is what proved it.

The fix is not to remember the parameter in one more place. The Checkout Session id ALREADY says which
books it belongs to -- `cs_live_` is not a test session -- and it is the one thing every link about an order
is guaranteed to carry. Deriving it there also heals every link already sitting in an inbox.

The thank-you page had the same hole from the same cause: its fetch sends no `mode` either, so a live
order was looked up with test credentials and the page showed the buyer nothing at all.
"""
import json
import os
import unittest
from unittest.mock import patch

from handlers.downloads import serve_handler
from stripe_link.common import stripe_mode_from_session_id
from tests.fakes import FakeDocumentRepository

LIVE_SESSION = "cs_live_a1wG8J9XsNr4vq5DFCDIXgRcRmuARZzSEAm3f5eY9zJt7znmr2GyYcaH5A"


class FakeS3:
    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        return f"https://s3.example/{operation}/{Params['Key']}?sig=abc"


class SessionIdTests(unittest.TestCase):
    def test_it_reads_the_mode_the_id_declares(self):
        self.assertEqual(stripe_mode_from_session_id(LIVE_SESSION), "live")
        self.assertEqual(stripe_mode_from_session_id("cs_test_abc"), "test")

    def test_anything_else_declares_nothing(self):
        """Empty, not "test". "I cannot tell" and "it is a test session" are different answers, and the
        caller decides what to do with the first -- here, fall back to the request."""
        for value in ("", None, "cs_abc", "order_cs_live_x", "CS_LIVE_X"):
            self.assertEqual(stripe_mode_from_session_id(value), "")


class ServeModeTests(unittest.TestCase):
    """The repositories the handler BUILDS, which is where the mode actually lands."""

    def setUp(self):
        self.built = []

    def serve(self, query):
        orders = FakeDocumentRepository("order_id")
        products = FakeDocumentRepository("product_id")
        orders.put({"tenant_id": "t1", "order_id": f"order_{query['session_id']}", "status": "paid",
                    "product": {"product_id": "prod_1"}})
        products.put({"tenant_id": "t1", "product_id": "prod_1",
                      "digital_asset": {"bucket_key": "downloads/t1/prod_1/a/guide.pdf", "filename": "guide.pdf"}})

        def record(name, repo):
            def build(*, mode=None, **_):
                self.built.append((name, mode))
                return repo
            return build

        with patch.dict(os.environ, {"MEDIA_BUCKET": "jb-media-dev"}, clear=False), \
                patch("handlers.downloads.orders_repository", record("orders", orders)), \
                patch("handlers.downloads.products_repository", record("products", products)):
            return serve_handler({"httpMethod": "GET", "queryStringParameters": query}, None, s3_client=FakeS3())

    def test_a_live_session_reads_the_live_books_without_being_told(self):
        """The exact shape of the emailed link: no `mode` anywhere in it."""
        response = self.serve({"tenant_id": "t1", "session_id": LIVE_SESSION, "product_id": "prod_1"})
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(self.built, [("orders", "live"), ("products", "live")])

    def test_both_repositories_agree(self):
        """Orders and products are keyed per mode separately. Reading the order live and the product test
        would find the order and then report the product has no file -- a different wrong answer."""
        self.serve({"tenant_id": "t1", "session_id": LIVE_SESSION, "product_id": "prod_1"})
        self.assertEqual({mode for _, mode in self.built}, {"live"})

    def test_a_test_session_still_reads_the_test_books(self):
        response = self.serve({"tenant_id": "t1", "session_id": "cs_test_abc", "product_id": "prod_1"})
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(self.built, [("orders", "test"), ("products", "test")])

    def test_the_id_outranks_the_query_string(self):
        """A `cs_live_` session is not a test session whatever the URL says. The param is the thing that
        can be stale or forgotten; the id travels with the order."""
        self.serve({"tenant_id": "t1", "session_id": LIVE_SESSION, "product_id": "prod_1", "mode": "test"})
        self.assertEqual(self.built, [("orders", "live"), ("products", "live")])

    def test_an_id_that_declares_nothing_falls_back_to_the_request(self):
        self.serve({"tenant_id": "t1", "session_id": "cs_1", "product_id": "prod_1", "mode": "live"})
        self.assertEqual(self.built, [("orders", "live"), ("products", "live")])
        self.built.clear()
        self.serve({"tenant_id": "t1", "session_id": "cs_1", "product_id": "prod_1"})
        self.assertEqual(self.built, [("orders", "test"), ("products", "test")])


class UpsellSessionModeTests(unittest.TestCase):
    """The thank-you page's own fetch had the same hole, from the same cause."""

    def ask(self, query):
        from handlers.upsell import get_upsell_session

        asked = []

        class FakeStripeKeys:
            def get(self, tenant_id, mode=None):
                asked.append(mode)
                return {}

        response = get_upsell_session(
            {"httpMethod": "GET", "queryStringParameters": query},
            stripe_repo=FakeStripeKeys(), secret_cipher=None, opener=None,
        )
        return asked, json.loads(response["body"])

    def test_a_live_session_asks_for_live_credentials(self):
        """`get_upsell_session` defaulted to "test" whenever no `mode` was sent -- and the island sends
        none -- so a live order was fetched with TEST Stripe credentials and the page got an error."""
        asked, body = self.ask({"clientID": "t1", "session_id": LIVE_SESSION})
        self.assertEqual(asked, ["live"])
        # Proven by the message naming the mode it went looking for.
        self.assertIn("live Stripe keys", body["message"])

    def test_a_test_session_still_asks_for_test_credentials(self):
        asked, _ = self.ask({"clientID": "t1", "session_id": "cs_test_abc"})
        self.assertEqual(asked, ["test"])

    def test_the_id_outranks_the_query_string_here_too(self):
        asked, _ = self.ask({"clientID": "t1", "session_id": LIVE_SESSION, "mode": "test"})
        self.assertEqual(asked, ["live"])


if __name__ == "__main__":
    unittest.main()
