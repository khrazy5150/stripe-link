"""Product-scoped coupons — Option A (plans/COUPONS_COMPLETION.md).

Stripe's `applies_to.products` DOES scope a discount, and **never echoes back**: `applies_to` reads `null`
on create and on retrieve whether or not a scope was set. Verified against the live API in test mode on
2026-09-23 — 50% off scoped to one product of a $100 + $50 cart discounted 5000, not 7500.

So these tests assert the payload we SEND. Asserting a response field would assert nothing, and asserting
the echo is exactly the mistake that made this look broken for a day.
"""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from handlers.coupons import CouponScopeError, coupon_edit_conflict, handler, stripe_product_ids_for
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_document
from stripe_link.stripe_coupons import coupon_payload
from tests.fakes import FakeDocumentRepository

ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeStripeKeys:
    def get(self, tenant_id, mode="test"):
        return {"connect_account_id": "acct_test"}


def recording_opener():
    """Captures the form body sent to Stripe, so a test can assert the scope actually travelled."""
    import io
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout=None):
        calls.append((request.full_url, (request.data or b"").decode()))
        body = {"id": "promo_1"} if "promotion_codes" in request.full_url else {"id": "co_1"}
        return _Response(json.dumps(body).encode())

    opener.calls = calls
    return opener


class PayloadTests(unittest.TestCase):
    def test_scope_becomes_indexed_applies_to_products(self):
        payload = coupon_payload({"type": "percent", "value": 50, "duration": "once"}, {}, "X",
                                 ["prod_a", "prod_b"])

        self.assertEqual(payload["applies_to[products][0]"], "prod_a")
        self.assertEqual(payload["applies_to[products][1]"], "prod_b")

    def test_no_scope_sends_no_applies_to_at_all(self):
        payload = coupon_payload({"type": "percent", "value": 50, "duration": "once"}, {}, "X")

        self.assertEqual([key for key in payload if "applies_to" in key], [])


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.products = FakeDocumentRepository("product_id")
        self.products.put({"tenant_id": "t1", "product_id": "p_synced",
                           "name": "Synced", "stripe_product_id": "prod_stripe_1"})
        self.products.put({"tenant_id": "t1", "product_id": "p_unsynced", "name": "Never Synced"})

    def test_our_ids_become_stripe_ids(self):
        self.assertEqual(
            stripe_product_ids_for(["p_synced"], "t1", "test", self.products), ["prod_stripe_1"])

    def test_no_scope_resolves_to_nothing(self):
        self.assertEqual(stripe_product_ids_for([], "t1", "test", self.products), [])
        self.assertEqual(stripe_product_ids_for(None, "t1", "test", self.products), [])

    def test_an_unsynced_product_is_REFUSED_not_dropped(self):
        # Dropping it would send a shorter scope and discount the wrong set; dropping every one would send
        # no scope and discount the entire cart. Both are silent over-discounts nothing could detect,
        # because Stripe does not echo applies_to back.
        with self.assertRaises(CouponScopeError) as caught:
            stripe_product_ids_for(["p_synced", "p_unsynced"], "t1", "test", self.products)

        self.assertIn("Never Synced", str(caught.exception))

    def test_a_product_that_does_not_exist_is_refused_too(self):
        with self.assertRaises(CouponScopeError):
            stripe_product_ids_for(["p_ghost"], "t1", "test", self.products)


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("coupon_id")
        self.products = FakeDocumentRepository("product_id")
        self.products.put({"tenant_id": "tenant_demo", "product_id": "p1",
                           "name": "Creatine", "stripe_product_id": "prod_creatine"})
        self.coupon = load_fixture("coupon-demo.json")

    def _create(self, coupon, opener):
        with patch("handlers.coupons.checkout_credentials", return_value=("sk_test_x", "acct_test")):
            return handler({"httpMethod": "POST", "body": json.dumps(coupon)}, None,
                           repository=self.repository, stripe_repo=FakeStripeKeys(),
                           secret_cipher=object(), opener=opener, products_repo=self.products)

    def test_the_scope_reaches_stripe(self):
        scoped = deepcopy(self.coupon)
        scoped["applies_to_product_ids"] = ["p1"]
        opener = recording_opener()

        response = self._create(scoped, opener)

        self.assertEqual(response["statusCode"], 201)
        coupon_body = [body for url, body in opener.calls if url.endswith("/coupons")][0]
        self.assertIn("applies_to%5Bproducts%5D%5B0%5D=prod_creatine", coupon_body)

    def test_the_stored_document_keeps_OUR_ids_not_stripes(self):
        scoped = deepcopy(self.coupon)
        scoped["applies_to_product_ids"] = ["p1"]

        body = json.loads(self._create(scoped, recording_opener())["body"])

        self.assertEqual(body["coupon"]["applies_to_product_ids"], ["p1"])

    def test_an_unsynced_scope_creates_NOTHING_at_stripe(self):
        self.products.put({"tenant_id": "tenant_demo", "product_id": "p_raw", "name": "Unsynced"})
        scoped = deepcopy(self.coupon)
        scoped["applies_to_product_ids"] = ["p_raw"]
        opener = recording_opener()

        response = self._create(scoped, opener)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "coupon_scope_unresolved")
        self.assertEqual(opener.calls, [], "nothing may be created at Stripe for a coupon we refuse")
        self.assertEqual(self.repository.documents, {})

    def test_an_unscoped_coupon_still_works_exactly_as_before(self):
        opener = recording_opener()

        self.assertEqual(self._create(deepcopy(self.coupon), opener)["statusCode"], 201)
        coupon_body = [body for url, body in opener.calls if url.endswith("/coupons")][0]
        self.assertNotIn("applies_to", coupon_body)


class ImmutabilityTests(unittest.TestCase):
    """`applies_to` is frozen on the Stripe Coupon, so changing it is the same broken promise as
    changing the value."""

    def test_changing_the_scope_is_a_conflict(self):
        existing = {"code": "SAVE10", "discount": {}, "applies_to_product_ids": ["p1"]}
        incoming = {"code": "SAVE10", "discount": {}, "applies_to_product_ids": ["p1", "p2"]}

        self.assertEqual(coupon_edit_conflict(existing, incoming), "applies_to_product_ids")

    def test_an_unchanged_scope_is_not(self):
        existing = {"code": "SAVE10", "discount": {}, "applies_to_product_ids": ["p1"]}

        self.assertEqual(coupon_edit_conflict(existing, dict(existing)), "")

    def test_absent_on_both_sides_is_not_a_change(self):
        self.assertEqual(coupon_edit_conflict({"code": "A", "discount": {}},
                                              {"code": "A", "discount": {}}), "")


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.coupon = load_fixture("coupon-demo.json")

    def test_the_field_is_optional(self):
        validate_coupon_document(self.coupon)

    def test_a_list_of_strings_is_accepted(self):
        validate_coupon_document({**self.coupon, "applies_to_product_ids": ["p1", "p2"]})

    def test_anything_else_is_refused(self):
        for bad in ("p1", [""], [None], [{"product_id": "p1"}]):
            with self.assertRaises(DocumentValidationError):
                validate_coupon_document({**self.coupon, "applies_to_product_ids": bad})


if __name__ == "__main__":
    unittest.main()
