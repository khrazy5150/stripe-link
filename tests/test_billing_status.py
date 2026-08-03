import unittest

from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing


class AssertBillingInGoodStandingTests(unittest.TestCase):
    def test_allows_trial_active_and_missing_status(self):
        assert_billing_in_good_standing({"billing_status": "trial"})
        assert_billing_in_good_standing({"billing_status": "active"})
        assert_billing_in_good_standing({})
        assert_billing_in_good_standing(None)

    def test_allows_past_due_as_grace_window(self):
        # past_due is the Stripe dunning/grace window — still allowed (plans/SAAS_BILLING_PAYWALL.md).
        assert_billing_in_good_standing({"billing_status": "past_due"})

    def test_allows_exempt_even_when_suspended(self):
        assert_billing_in_good_standing({"billing_status": "suspended", "billing_exempt": True})

    def test_blocks_suspended(self):
        with self.assertRaises(BillingStatusError):
            assert_billing_in_good_standing({"billing_status": "suspended"})

    def test_blocks_canceled(self):
        with self.assertRaises(BillingStatusError):
            assert_billing_in_good_standing({"billing_status": "canceled"})

    def test_error_carries_the_status(self):
        try:
            assert_billing_in_good_standing({"billing_status": "suspended"})
            self.fail("expected BillingStatusError")
        except BillingStatusError as exc:
            self.assertEqual(exc.status, "suspended")


if __name__ == "__main__":
    unittest.main()
