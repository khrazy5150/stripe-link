"""The connected-account allowance (plans/ATTENTION_PRIMITIVE.md §6.2c).

This number is a COST dial before it is a product one: the publishing vendor charges $19/mo up to 100
connected accounts and $129 at 101, a hard step. Accounts-per-tenant decides when that step lands, so
each rule below is pinned against the reasoning that chose it rather than against a number.
"""
import unittest

from stripe_link.domain.account_quota import (DEFAULT_FREE_CONNECTED_ACCOUNTS,
                                              DEFAULT_PLAN_CONNECTED_ACCOUNTS, UNLIMITED,
                                              account_allowance, may_connect, over_cap_message)
from stripe_link.domain.platform_billing import plan_connected_accounts


class TheAllowanceTests(unittest.TestCase):
    def test_the_free_floor_is_ZERO_unlike_the_Site_cap(self):
        """The asymmetry is deliberate. A Site is the tenant's own storefront and free-forever means a
        working one; a connected social account spends OUR vendor allowance on every post, and
        `attention` is not a free-tier capability at all."""
        self.assertEqual(DEFAULT_FREE_CONNECTED_ACCOUNTS, 0)
        self.assertEqual(account_allowance({}), {"allowance": 0, "source": "free"})

    def test_a_subscriber_gets_the_denormalized_number(self):
        got = account_allowance({"billing_status": "active", "connected_accounts": 6})
        self.assertEqual(got, {"allowance": 6, "source": "plan"})

    def test_a_paying_tenant_whose_webhook_has_not_run_gets_the_default(self):
        got = account_allowance({"billing_status": "active"})
        self.assertEqual(got["allowance"], DEFAULT_PLAN_CONNECTED_ACCOUNTS)

    def test_the_default_is_one_per_supported_CHANNEL(self):
        """Three channels ship (instagram, tiktok, youtube_shorts). Fewer than one each would sell
        multi-channel publishing and then ration it; more brings the vendor's cost cliff forward."""
        self.assertEqual(DEFAULT_PLAN_CONNECTED_ACCOUNTS, 3)

    def test_a_canceled_subscriber_drops_to_the_free_floor(self):
        lapsed = {"billing_status": "canceled", "stripe_subscription_id": "sub_1",
                  "connected_accounts": 10}
        self.assertEqual(account_allowance(lapsed), {"allowance": 0, "source": "free"})

    def test_billing_exempt_is_unlimited(self):
        self.assertEqual(account_allowance({"billing_exempt": True})["allowance"], UNLIMITED)


class ThePlanRowTests(unittest.TestCase):
    def test_it_is_priced_from_the_generic_limits_map(self):
        """A cost dial that needs a deploy is one nobody turns."""
        self.assertEqual(plan_connected_accounts({"limits": {"connected_accounts": 10}}), 10)

    def test_a_top_level_field_works_too(self):
        self.assertEqual(plan_connected_accounts({"connected_accounts": 1}), 1)

    def test_a_row_predating_the_field_gets_the_default(self):
        self.assertEqual(plan_connected_accounts({}), DEFAULT_PLAN_CONNECTED_ACCOUNTS)


class MayConnectTests(unittest.TestCase):
    def _tenant(self, n):
        return {"billing_status": "active", "connected_accounts": n}

    def test_room_left_allows_it(self):
        got = may_connect(self._tenant(3), 1)
        self.assertTrue(got["allowed"])
        self.assertEqual(got["remaining"], 2)

    def test_at_the_cap_it_refuses(self):
        got = may_connect(self._tenant(3), 3)
        self.assertFalse(got["allowed"])
        self.assertEqual(got["remaining"], 0)

    def test_over_the_cap_never_reports_NEGATIVE_room(self):
        """A downgrade can leave a tenant above their new allowance. "-2 left" is not a sentence any
        screen should print."""
        got = may_connect(self._tenant(3), 5)
        self.assertFalse(got["allowed"])
        self.assertEqual(got["remaining"], 0)

    def test_a_free_tenant_may_connect_nothing(self):
        self.assertFalse(may_connect({}, 0)["allowed"])

    def test_exempt_is_unbounded_and_says_so_with_None(self):
        got = may_connect({"billing_exempt": True}, 99)
        self.assertTrue(got["allowed"])
        self.assertIsNone(got["allowance"])
        self.assertIsNone(got["remaining"])


class TheMessageTests(unittest.TestCase):
    def test_it_names_the_number_and_the_way_out(self):
        message = over_cap_message(3)
        self.assertIn("3 connected social accounts", message)
        self.assertIn("Disconnect", message)

    def test_one_reads_as_singular(self):
        self.assertIn("1 connected social account.", over_cap_message(1))

    def test_zero_sells_the_upgrade_rather_than_a_disconnect(self):
        """Telling a tenant with none to disconnect one would be nonsense."""
        self.assertIn("does not include", over_cap_message(0))
        self.assertNotIn("Disconnect", over_cap_message(0))
