"""An unreadable policy is not a policy saying "no return required".

`return_requirement` skips a line whose product it cannot find, so an EMPTY product index produces
`required: False` — a confident answer derived from an absence. In September a mode bug emptied that
index and every refund skipped its return gate. The repository was made to refuse loudly so it could not
happen again… and the handler wrapped it in `except Exception: products = []`, which swallowed the
refusal and restored the old behaviour exactly.

The layered policy (a Configuration default, overridden per product) is what hides it: you never see an
error, you just get the default — and the default, derived from nothing, is the one that loses the goods.
"""
import unittest

from stripe_link.domain.returns import next_status_after_approval, policy_snapshot

LINES = [{"product_id": "p1", "quantity": 1}]
PRODUCTS = {"p1": {"product_id": "p1", "name": "Mug",
                   "fulfillment": {"requires_shipping": True},
                   "refund_policy": {"return_method": "return_required"}}}


class WhatAnEmptyIndexUsedToMeanTests(unittest.TestCase):
    def test_a_readable_catalogue_that_requires_a_return_says_so(self):
        snapshot = policy_snapshot(LINES, PRODUCTS)
        self.assertTrue(snapshot["return_required"])
        self.assertEqual(next_status_after_approval(snapshot), "return_pending")

    def test_a_genuinely_empty_catalogue_still_requires_nothing(self):
        """Unchanged, and correct: nothing here needs posting back."""
        snapshot = policy_snapshot([], {})
        self.assertFalse(snapshot["return_required"])

    def test_an_UNREADABLE_catalogue_requires_the_return(self):
        """The fix. A return wrongly required is a parcel the tenant waives with one click; a return
        wrongly skipped is goods AND money gone, with nothing to click."""
        snapshot = policy_snapshot([], {}, policy_unreadable=True)
        self.assertTrue(snapshot["return_required"])
        self.assertTrue(snapshot["policy_unreadable"])
        self.assertEqual(next_status_after_approval(snapshot), "return_pending")

    def test_it_says_what_happened_rather_than_asserting_a_policy(self):
        reason = policy_snapshot([], {}, policy_unreadable=True)["reason"]
        self.assertIn("could not be read", reason)
        self.assertIn("waive", reason)

    def test_an_unreadable_policy_never_claims_keep_it(self):
        """`keep_it` means a return was required and is being waived because the goods are worth less
        than the postage. Claiming that from an unreadable catalogue would be an invented decision."""
        snapshot = policy_snapshot([], {}, policy_unreadable=True, keep_it_below=10_000, order_total=1)
        self.assertFalse(snapshot["keep_it"])


class TheHandlerRecordsIt(unittest.TestCase):
    def test_a_raising_products_repo_marks_the_policy_unreadable(self):
        from handlers.refunds import _approve

        class Exploding:
            def list_for_tenant(self, _tenant):
                raise RuntimeError("ProvisionedThroughputExceeded")

        class Orders:
            def get(self, *_a):
                return {"order_id": "ord_1", "amount_total": 5000, "lines": []}

        class Requests:
            def put(self, doc):
                return doc

        request = {"refund_request_id": "rr_1", "tenant_id": "t1", "order_id": "ord_1", "status": "new"}
        _approve(Requests(), request, "t1", {}, 1781230000,
                 orders_repo=Orders(), products_repo=Exploding(), mode="live")
        self.assertTrue(request["policy_snapshot"]["policy_unreadable"])
        self.assertTrue(request["policy_snapshot"]["return_required"])


if __name__ == "__main__":
    unittest.main()
