"""`/upsell/session` answers "what file did this order buy?".

Folded onto the endpoint the thank-you page ALREADY calls with this `session_id`, exactly as `delivery` was
and for the same reason: the stack is at CloudFormation's transform limit, so a new route is spent only on
a question that cannot be answered anywhere else (plans/MONEY_ACROSS_SILOS.md notes the budget).

The answer is the purchase-verified `/download` LINK, never the file and never a presigned S3 URL: clicking
it re-checks the order server-side, so a link scraped off a thank-you page is worth no more than the order
behind it.
"""
import os
import unittest
from unittest.mock import patch

from handlers.upsell import _download_delivery
from tests.fakes import FakeDocumentRepository

ENV = {"ORDERS_TABLE": "jb-orders-test", "PUBLIC_API_BASE_URL": "https://api.example"}
ASSET = {"bucket_key": "downloads/t1/prod_1/a/guide.pdf", "filename": "guide.pdf"}


def repos(order_status="paid", asset=ASSET, product_id="prod_1"):
    orders = FakeDocumentRepository("order_id")
    products = FakeDocumentRepository("product_id")
    orders.put({"tenant_id": "t1", "order_id": "order_cs_live_1", "payment_status": order_status,
                "session_id": "cs_live_1", "product": {"product_id": product_id}})
    product = {"tenant_id": "t1", "product_id": "prod_1"}
    if asset:
        product["digital_asset"] = asset
    products.put(product)
    return orders, products


def ask(**kwargs):
    orders, products = repos(**kwargs)
    with patch.dict(os.environ, ENV, clear=False):
        return _download_delivery("t1", "cs_live_1", mode="live", orders_repo=orders, products_repo=products)


class DeliveryTests(unittest.TestCase):
    def test_a_paid_digital_order_gets_its_link(self):
        answer = ask()
        self.assertEqual(answer["filename"], "guide.pdf")
        self.assertIn("https://api.example/download?", answer["url"])
        self.assertIn("session_id=cs_live_1", answer["url"])
        self.assertIn("product_id=prod_1", answer["url"])
        self.assertIn("tenant_id=t1", answer["url"])

    def test_it_hands_out_a_verified_link_not_the_file(self):
        """The S3 object is never named here. The page gets the endpoint that checks the order, so the
        link is worth exactly as much as the purchase behind it."""
        self.assertNotIn("downloads/t1", ask()["url"])
        self.assertNotIn("s3", ask()["url"].lower())

    def test_an_unpaid_order_is_offered_nothing(self):
        """Not even a link that would refuse: a download button that then says "no paid order found" is
        worse than no button."""
        self.assertEqual(ask(order_status="open"), {})

    def test_a_partial_refund_keeps_the_file(self):
        """Refunding part of an order has not undone the purchase, and taking the file back would punish
        the buyer for the tenant's bookkeeping."""
        self.assertTrue(ask(order_status="partially_refunded"))

    def test_a_product_with_no_file_answers_nothing(self):
        self.assertEqual(ask(asset=None), {})
        self.assertEqual(ask(asset={"filename": "guide.pdf"}), {})

    def test_an_order_with_no_product_answers_nothing(self):
        self.assertEqual(ask(product_id=""), {})

    def test_a_missing_order_answers_nothing(self):
        with patch.dict(os.environ, ENV, clear=False):
            orders, products = repos()
            self.assertEqual(
                _download_delivery("t1", "cs_live_absent", mode="live", orders_repo=orders, products_repo=products),
                {})

    def test_a_broken_repository_answers_nothing(self):
        """Best-effort, like `_delivery_promise`: a thank-you page renders whatever happened here. The
        receipt email carries the same link, so the buyer is not stranded by an empty answer."""
        class Broken:
            def get(self, *a, **k):
                raise RuntimeError("dynamo is having a day")

        with patch.dict(os.environ, ENV, clear=False):
            self.assertEqual(_download_delivery("t1", "cs_live_1", mode="live",
                                                orders_repo=Broken(), products_repo=Broken()), {})

    def test_it_asks_for_nothing_without_an_orders_table(self):
        with patch.dict(os.environ, {"ORDERS_TABLE": ""}, clear=False):
            self.assertEqual(_download_delivery("t1", "cs_live_1", mode="live"), {})


class ResponseTests(unittest.TestCase):
    def test_the_endpoint_reports_it_beside_delivery(self):
        """Same response, same session_id, one fetch. The thank-you page's two islands read different keys
        off it rather than making two requests that could disagree about the same order."""
        import handlers.upsell as upsell

        body = open(upsell.__file__).read().split("def get_upsell_session", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"delivery": _delivery_promise(tenant_id, session_id, mode=mode)', body)
        self.assertIn('"download": _download_delivery(tenant_id, session_id, mode=mode)', body)

    def test_both_read_the_same_mode(self):
        """`delivery` used to resolve its own mode from the request while the credentials came from
        elsewhere -- two answers about one order out of two different sets of books."""
        import handlers.upsell as upsell

        body = open(upsell.__file__).read().split("def get_upsell_session", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("mode=resolve_stripe_mode(event)", body)


if __name__ == "__main__":
    unittest.main()
