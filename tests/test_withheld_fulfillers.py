"""A delegate whose calendar has broken must not keep being sold.

`tenant_busy_intervals` returns [] on any failure -- deliberately, so a Google outage cannot close the
shop -- and the slot engine cannot tell [] from "free". So a delegate who revokes the app, or quits and
removes it, silently contributes no busy time and the platform keeps booking customers onto someone
nobody can reach (2026-11-10).

The half that must not be got backwards: a delegate with NO calendar at all is a SUPPORTED setup, fully
bookable, their hours taken from the tenant's availability. Only a BROKEN LINK is withheld.
"""
import unittest

from stripe_link.domain.scheduling import available_slots
# The real fixtures, rather than a second set invented here: weekly_hours wants
# {day: "mon", enabled: True, start_time, end_time}, and a hand-rolled shape silently produces NO slots
# -- which makes every "we withheld them" assertion pass for the wrong reason.
from tests.test_scheduling import SERVICE, WED_END, WED_START, tenant_avail


def _slots(service, fulfillers, withheld=()):
    return available_slots(
        {**SERVICE, **service}, tenant_avail(), fulfillers, [], [],
        now_epoch=WED_START - 3600, range_start_epoch=WED_START, range_end_epoch=WED_END,
        withheld_fulfiller_ids=withheld,
    )


class WithholdingEmptiesTheServiceRatherThanFallingThroughTests(unittest.TestCase):
    SERVICE = {"service_id": "svc_1", "allowed_fulfillers": [{"fulfiller_id": "f1", "enabled": True}]}
    PEOPLE = [{"fulfiller_id": "f1"}]

    def test_the_baseline_offers_slots(self):
        """Without this the rest of the class could pass by offering nothing for unrelated reasons."""
        self.assertTrue(_slots(self.SERVICE, self.PEOPLE))

    def test_withholding_the_only_fulfiller_yields_NO_slots(self):
        self.assertEqual(_slots(self.SERVICE, self.PEOPLE, withheld={"f1"}), [])

    def test_it_does_NOT_fall_through_to_the_tenants_own_hours(self):
        """The trap: candidates come from the SERVICE, so an emptied list used to reach `[None]` and
        sell the tenant's time for work only a delegate does."""
        slots = _slots(self.SERVICE, self.PEOPLE, withheld={"f1"})
        self.assertEqual(slots, [], "an emptied candidate list must not become a tenant-level booking")

    def test_another_fulfiller_still_takes_the_work(self):
        service = {"service_id": "svc_1",
                   "allowed_fulfillers": [{"fulfiller_id": "f1", "enabled": True},
                                          {"fulfiller_id": "f2", "enabled": True}]}
        people = [{"fulfiller_id": "f1"}, {"fulfiller_id": "f2"}]
        slots = _slots(service, people, withheld={"f1"})
        self.assertTrue(slots)
        self.assertTrue(all(s.get("fulfiller_id") != "f1" for s in slots))

    def test_a_service_with_no_fulfillers_is_untouched(self):
        """A single-operator tenant has no fulfillers at all; withholding must not reach them."""
        self.assertTrue(_slots({"service_id": "svc_1"}, [], withheld={"f1"}))

    def test_withholding_nobody_changes_nothing(self):
        self.assertEqual(_slots(self.SERVICE, self.PEOPLE),
                         _slots(self.SERVICE, self.PEOPLE, withheld=()))


class WhoGetsWithheldTests(unittest.TestCase):
    CONNS = [{"connection_id": "c_ok", "status": "connected"},
             {"connection_id": "c_dead", "status": "revoked"}]

    def _withheld(self, fulfillers):
        from handlers.booking import _withheld_fulfiller_ids

        class Repo:
            def list_for_tenant(self, _t):
                return WhoGetsWithheldTests.CONNS

        return _withheld_fulfiller_ids("t1", fulfillers, Repo())

    def test_a_delegate_with_no_google_account_is_never_withheld(self):
        self.assertEqual(self._withheld([{"fulfiller_id": "f1"}]), [])

    def test_a_working_link_is_never_withheld(self):
        self.assertEqual(self._withheld([{"fulfiller_id": "f2", "calendar_connection_id": "c_ok"}]), [])

    def test_a_broken_link_is_withheld(self):
        self.assertEqual(self._withheld([{"fulfiller_id": "f3", "calendar_connection_id": "c_dead"}]),
                         ["f3"])

    def test_an_unreadable_connections_table_withholds_NOBODY(self):
        """A hiccup reading DynamoDB must not close the shop -- the opposite failure, and a worse one."""
        from handlers.booking import _withheld_fulfiller_ids

        class Boom:
            def list_for_tenant(self, _t):
                raise RuntimeError("DynamoDB is down")

        self.assertEqual(
            _withheld_fulfiller_ids("t1", [{"fulfiller_id": "f3", "calendar_connection_id": "c_dead"}],
                                    Boom()), [])


if __name__ == "__main__":
    unittest.main()


class ThePublicResponseLeaksNothingTests(unittest.TestCase):
    """The slots route is `Authorizer: NONE` -- customers browse it. The first draft of this feature
    returned the withheld fulfiller ids and "reconnect it, or assign someone else": staff identity and
    an internal instruction, handed to a buyer."""

    def test_the_reason_is_neutral_and_carries_no_staff_detail(self):
        import inspect

        from handlers import booking

        src = inspect.getsource(booking)
        self.assertIn('"reason": "no_available_fulfiller"', src)
        self.assertNotIn('"fulfiller_ids": sorted(withheld_ids),\n            "message"', src)

    def test_the_detail_goes_to_the_LOG_not_the_customer(self):
        import inspect

        from handlers import booking

        src = inspect.getsource(booking)
        self.assertIn('"slots_withheld"', src, "the operator still needs to see which people and why")
