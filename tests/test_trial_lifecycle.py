import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from handlers.auth import tenant_profile_document
from stripe_link.domain.billing_status import (
    TRIAL_PERIOD_SECONDS,
    is_billing_in_good_standing,
    is_trial_expired,
)


class TrialStampTests(unittest.TestCase):
    def test_new_tenant_profile_starts_a_trial_clock(self):
        now = 1_000_000
        profile = tenant_profile_document(
            client_id="t1", email="a@b.com", first_name="A", last_name="B", status="confirmed", now=now,
        )
        self.assertEqual(profile["billing_status"], "trial")
        self.assertEqual(profile["trial_ends_at"], now + TRIAL_PERIOD_SECONDS)


class TrialExpiryTests(unittest.TestCase):
    def _trial(self, ends_at=None, **over):
        p = {"billing_status": "trial"}
        if ends_at is not None:
            p["trial_ends_at"] = ends_at
        p.update(over)
        return p

    def test_active_trial_is_in_good_standing(self):
        self.assertTrue(is_billing_in_good_standing(self._trial(ends_at=2000), now=1000))
        self.assertFalse(is_trial_expired(self._trial(ends_at=2000), now=1000))

    def test_expired_trial_downgrades_but_still_sells(self):
        # Free-forever model: expiry flips the entitlement set to the free floor, but the tenant stays in good
        # standing — pages serve and checkout charges at the free-tier fee.
        self.assertTrue(is_trial_expired(self._trial(ends_at=1000), now=2000))
        self.assertTrue(is_billing_in_good_standing(self._trial(ends_at=1000), now=2000))

    def test_trial_without_clock_is_grandfathered(self):
        # Tenants created before trial clocks (no trial_ends_at) never expire.
        self.assertFalse(is_trial_expired(self._trial(), now=9_999_999_999))
        self.assertTrue(is_billing_in_good_standing(self._trial(), now=9_999_999_999))

    def test_subscribed_trialing_does_not_expire_on_our_clock(self):
        # A Stripe 'trialing' subscriber (has subscription id) is managed by Stripe, not our platform clock.
        sub_trial = self._trial(ends_at=1000, stripe_subscription_id="sub_1")
        self.assertFalse(is_trial_expired(sub_trial, now=2000))
        self.assertTrue(is_billing_in_good_standing(sub_trial, now=2000))

    def test_exempt_never_walled(self):
        self.assertTrue(is_billing_in_good_standing(self._trial(ends_at=1000, billing_exempt=True), now=2000))

    def test_decimal_trial_ends_at_expires(self):
        # DynamoDB returns numbers as Decimal, not int — expiry detection must still work (regression). Good
        # standing is unaffected either way under the free-forever model.
        from decimal import Decimal
        profile = {"billing_status": "trial", "trial_ends_at": Decimal("1000")}
        self.assertTrue(is_trial_expired(profile, now=2000))
        self.assertTrue(is_billing_in_good_standing(profile, now=2000))


if __name__ == "__main__":
    unittest.main()
