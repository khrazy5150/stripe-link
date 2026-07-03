import unittest

from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing


class AssertBillingInGoodStandingTests(unittest.TestCase):
    def test_allows_trial_active_and_missing_status(self):
        assert_billing_in_good_standing({"billing_status": "trial"})
        assert_billing_in_good_standing({"billing_status": "active"})
        assert_billing_in_good_standing({})
        assert_billing_in_good_standing(None)

    def test_blocks_past_due(self):
        with self.assertRaises(BillingStatusError):
            assert_billing_in_good_standing({"billing_status": "past_due"})

    def test_blocks_suspended(self):
        with self.assertRaises(BillingStatusError):
            assert_billing_in_good_standing({"billing_status": "suspended"})

    def test_error_carries_the_status(self):
        try:
            assert_billing_in_good_standing({"billing_status": "suspended"})
            self.fail("expected BillingStatusError")
        except BillingStatusError as exc:
            self.assertEqual(exc.status, "suspended")


if __name__ == "__main__":
    unittest.main()
