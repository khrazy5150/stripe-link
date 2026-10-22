"""Minting a Stripe Price for a plan, from the Admin Site.

CREATE ONLY. A Stripe Price is immutable -- its amount cannot be edited -- so "change the price" is
always "make a new Price and decide what happens to everyone on the old one". This does the first half
and refuses to pretend it did the second.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from handlers import platform_subscription as subs  # noqa: E402


class FakePlans:
    def __init__(self, plan=None):
        self.plan = plan

    def list_plans(self, mode):
        return [self.plan] if self.plan else []

    def get_config(self, mode):
        return {}


class Recorder:
    """Stands in for the Stripe transport, recording what we would have sent."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, method, path, *, api_key, opener=None, data=None, idempotency_key=None, **kw):
        if self.fail:
            raise subs.StripeApiError(402, "Your card was declined.", "card_declined")
        self.calls.append({"path": path, "data": data, "idem": idempotency_key})
        return {"id": f"{'prod' if path == '/products' else 'price'}_new"}


def run(event, plans=None, recorder=None):
    # The plan lookup goes through a 5-minute module cache keyed by mode. Left alone, one test's
    # FakePlans answers the next test's lookup -- which is also why the Admin Site PASSES product_id
    # explicitly rather than trusting this read: a plan row written seconds ago may not be in the
    # cache yet, and a missed product_id would mint a second Stripe product.
    from stripe_link.domain import platform_billing
    platform_billing._CACHE.clear()
    recorder = recorder or Recorder()
    original = subs.stripe_request
    subs.stripe_request = recorder
    try:
        return subs.handler({"internal_create_price": True, **event}, None,
                            plans_repository=plans or FakePlans(), secret_key="sk_test"), recorder
    finally:
        subs.stripe_request = original


class CreatingAPriceTests(unittest.TestCase):
    def test_it_creates_a_product_then_a_recurring_price(self):
        result, rec = run({"plan_key": "pro", "label": "Pro", "monthly_amount": 2900})
        self.assertTrue(result["ok"])
        self.assertEqual([c["path"] for c in rec.calls], ["/products", "/prices"])
        price = rec.calls[1]["data"]
        self.assertEqual(price["unit_amount"], 2900)
        self.assertEqual(price["currency"], "usd")
        self.assertEqual(price["recurring"], {"interval": "month"})
        self.assertEqual(result["price_id"], "price_new")

    def test_an_existing_product_is_reused(self):
        # A ladder of price changes should stay ONE product with a history, not a pile of
        # near-identical products.
        plans = FakePlans({"plan_key": "pro", "product_id": "prod_existing", "label": "Pro"})
        result, rec = run({"plan_key": "pro", "monthly_amount": 4900}, plans=plans)
        self.assertEqual([c["path"] for c in rec.calls], ["/prices"])
        self.assertEqual(rec.calls[0]["data"]["product"], "prod_existing")
        self.assertEqual(result["product_id"], "prod_existing")

    def test_the_same_amount_twice_is_idempotent(self):
        # A double-click must not mint two prices. The key covers plan AND amount, so a genuinely new
        # amount still gets its own Price.
        _, rec_a = run({"plan_key": "pro", "monthly_amount": 2900})
        _, rec_b = run({"plan_key": "pro", "monthly_amount": 4900})
        same = [c for c in rec_a.calls if c["path"] == "/prices"][0]["idem"]
        other = [c for c in rec_b.calls if c["path"] == "/prices"][0]["idem"]
        self.assertIn("2900", same)
        self.assertNotEqual(same, other)

    def test_it_never_modifies_or_archives_anything(self):
        # The whole safety property in one assertion: every call is a POST that CREATES.
        _, rec = run({"plan_key": "pro", "monthly_amount": 2900})
        for call in rec.calls:
            self.assertIn(call["path"], ("/products", "/prices"))
            self.assertNotIn("active", call["data"] or {})

    def test_a_missing_amount_is_refused_before_stripe(self):
        result, rec = run({"plan_key": "pro"})
        self.assertFalse(result["ok"])
        self.assertEqual(rec.calls, [])

    def test_a_missing_plan_key_is_refused_before_stripe(self):
        result, rec = run({"monthly_amount": 2900})
        self.assertFalse(result["ok"])
        self.assertEqual(rec.calls, [])

    def test_a_stripe_refusal_is_reported_not_raised(self):
        # The admin needs to read what Stripe said, not a stack trace.
        result, _ = run({"plan_key": "pro", "monthly_amount": 2900}, recorder=Recorder(fail=True))
        self.assertFalse(result["ok"])
        self.assertIn("Stripe refused", result["error"])

    def test_the_http_routes_are_untouched_by_the_internal_path(self):
        # The internal event has no httpMethod; the HTTP dispatch must not see it.
        response = subs.handler({"httpMethod": "OPTIONS"}, None, plans_repository=FakePlans())
        self.assertEqual(response["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
