"""The Site cap (plans/SITE_AS_BUSINESS_IDENTITY.md §P5).

Each test pins one of the plan's LOCKED decisions, because every one of them is a rule someone could
reasonably implement the other way round -- and two of them take a tenant's storefront off the internet
if they are got wrong.
"""
import unittest

from stripe_link.domain.platform_billing import plan_sites
from stripe_link.domain.site_quota import (DEFAULT_FREE_SITES, DEFAULT_PLAN_SITES, UNLIMITED,
                                           countable_sites, locked_site_ids, over_cap_message,
                                           site_allowance, site_is_locked)


def _site(site_id, created_at=0, status="active"):
    return {"site_id": site_id, "created_at": created_at, "status": status}


class TheAllowanceTests(unittest.TestCase):
    def test_the_free_floor_is_one_site_not_none(self):
        """Free-forever means a WORKING store. A floor of zero would soft-lock the only Site a free
        tenant has, which is the free tier taking the shop down rather than capping it."""
        self.assertEqual(site_allowance({})["allowance"], 1)
        self.assertEqual(DEFAULT_FREE_SITES, 1)

    def test_a_subscriber_gets_the_number_denormalized_onto_the_profile(self):
        got = site_allowance({"billing_status": "active", "sites": 10})
        self.assertEqual(got, {"allowance": 10, "source": "plan"})

    def test_a_paying_tenant_whose_webhook_has_not_run_gets_the_lowest_PAID_rung(self):
        """They bought something, so a missing number must not read as the free floor."""
        got = site_allowance({"billing_status": "active"})
        self.assertEqual(got["allowance"], DEFAULT_PLAN_SITES)
        self.assertGreater(DEFAULT_PLAN_SITES, DEFAULT_FREE_SITES)

    def test_a_CANCELED_subscriber_falls_to_the_free_floor_not_to_zero(self):
        """THE ONE THAT TAKES A SHOP DOWN. `stripe_subscription_id` survives a cancellation, so reading
        "has an id" as "is paying" would keep a stale allowance forever -- and zeroing `sites` the way the
        AI allowances are zeroed would leave a lapsed tenant with no Sites at all. The pricing pivot's
        rule is that a lapsed subscription sells on at the free-tier fee."""
        lapsed = {"billing_status": "canceled", "stripe_subscription_id": "sub_1", "sites": 0}
        self.assertEqual(site_allowance(lapsed), {"allowance": 1, "source": "free"})

    def test_billing_exempt_is_unlimited(self):
        self.assertEqual(site_allowance({"billing_exempt": True})["allowance"], UNLIMITED)

    def test_the_free_floor_is_overridable_from_config(self):
        self.assertEqual(site_allowance({}, free_allowance=3)["allowance"], 3)


class ThePlanRowTests(unittest.TestCase):
    def test_sites_can_be_priced_from_the_generic_limits_map(self):
        """A new allowance has to be a ROW EDIT on the Pricing screen, not a deploy."""
        self.assertEqual(plan_sites({"limits": {"sites": 10}}), 10)

    def test_a_top_level_field_still_works(self):
        self.assertEqual(plan_sites({"sites": 3}), 3)

    def test_a_plan_row_predating_the_field_gets_the_lowest_paid_rung(self):
        self.assertEqual(plan_sites({}), DEFAULT_PLAN_SITES)


class WhichSitesAreLockedTests(unittest.TestCase):
    def test_archived_sites_do_not_count(self):
        """Archiving IS the tenant's "pick which stay active": it is already a reversible close that keeps
        every address reserved, so it must free a slot or it is no lever at all."""
        sites = [_site("a", 1), _site("b", 2, status="archived"), _site("c", 3)]
        self.assertEqual([s["site_id"] for s in countable_sites(sites)], ["a", "c"])

    def test_the_OLDEST_stay_active(self):
        sites = [_site("new", 300), _site("old", 100), _site("mid", 200)]
        self.assertEqual(locked_site_ids(sites, 1), {"mid", "new"})

    def test_the_answer_does_not_depend_on_row_order(self):
        """DynamoDB does not promise an order. If which Site is locked moved between page loads, a tenant
        would watch a different storefront go read-only on each refresh."""
        a, b, c = _site("a", 1), _site("b", 2), _site("c", 3)
        self.assertEqual(locked_site_ids([a, b, c], 2), locked_site_ids([c, a, b], 2))

    def test_equal_timestamps_still_resolve_deterministically(self):
        """Two Sites created in the same second -- a copy-to-mode does exactly this."""
        same = [_site("b", 7), _site("a", 7)]
        self.assertEqual(locked_site_ids(same, 1), {"b"})

    def test_nothing_is_locked_under_the_cap(self):
        self.assertEqual(locked_site_ids([_site("a", 1)], 3), set())

    def test_unlimited_locks_nothing(self):
        self.assertEqual(locked_site_ids([_site(str(i), i) for i in range(50)], UNLIMITED), set())

    def test_an_unidentifiable_site_is_never_locked(self):
        """The fail-open direction: refusing to publish because a document was odd is the worse error."""
        self.assertFalse(site_is_locked({}, [_site("a", 1)], 0))
        self.assertFalse(site_is_locked(None, [_site("a", 1)], 0))


class TheMessageTests(unittest.TestCase):
    def test_it_names_the_number_and_the_way_out(self):
        """A cap a tenant cannot see is one they experience as a broken button."""
        message = over_cap_message(3)
        self.assertIn("3 Sites", message)
        self.assertIn("Archive", message)

    def test_one_site_reads_as_singular(self):
        self.assertIn("1 Site per mode", over_cap_message(1))
