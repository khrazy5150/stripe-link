"""A lead belongs to the books it was captured in.

The same asymmetry as refunds, one layer down: `_emit_lead_notification` already scoped the NOTIFICATION
about a lead to the capture's mode, while the lead itself appeared in both lists. One of those was wrong.

What makes leads different from refunds: nothing in a lead reveals its mode after the fact. A refund
request carries `order_cs_live_...`; a lead carries page_id and offer_id, which are IDENTICAL across
modes because the cross-mode copy preserves ids. So the mode must be recorded at capture or it is lost —
and older records can only be shown in both modes.
"""
import json
import unittest

from handlers.leads import lead_mode, list_leads


def lead(lid="lead_1", **extra):
    return {"lead_id": lid, "tenant_id": "t1", "offer_id": "offer_same_in_both_modes",
            "page_id": "page_same_in_both_modes", "created_at": 1, **extra}


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows

    def list_for_tenant(self, tenant_id):
        return [dict(r) for r in self.rows]


def listed(rows, mode):
    event = {"httpMethod": "GET", "queryStringParameters": {"mode": mode},
             "headers": {"X-Tenant-Id": "t1"}, "body": None, "requestContext": {}}
    return [r["lead_id"] for r in json.loads(list_leads(event, FakeRepo(rows))["body"])["leads"]]


class TheModeOfALeadTests(unittest.TestCase):
    def test_it_comes_from_the_stored_field(self):
        self.assertEqual(lead_mode(lead(stripe_mode="test")), "test")
        self.assertEqual(lead_mode(lead(stripe_mode="live")), "live")

    def test_a_lead_without_one_cannot_be_placed(self):
        """And cannot be derived: page_id and offer_id are the same in both modes by design."""
        self.assertEqual(lead_mode(lead()), "")

    def test_rubbish_is_not_a_mode(self):
        self.assertEqual(lead_mode(lead(stripe_mode="sandbox")), "")


class TheListIsScopedTests(unittest.TestCase):
    ROWS = [lead("live_1", stripe_mode="live"), lead("test_1", stripe_mode="test")]

    def test_live_does_not_show_test_leads(self):
        self.assertEqual(listed(self.ROWS, "live"), ["live_1"])

    def test_test_does_not_show_live_leads(self):
        self.assertEqual(listed(self.ROWS, "test"), ["test_1"])

    def test_a_lead_captured_before_this_is_shown_in_BOTH(self):
        """A lead is a person who asked to be contacted. Losing one is worse than showing it twice."""
        rows = [lead("legacy")]
        self.assertEqual(listed(rows, "live"), ["legacy"])
        self.assertEqual(listed(rows, "test"), ["legacy"])

    def test_the_existing_filters_still_work_alongside_it(self):
        rows = [lead("a", stripe_mode="live", status="new"),
                lead("b", stripe_mode="live", status="archived")]
        event = {"httpMethod": "GET", "queryStringParameters": {"mode": "live", "status": "new"},
                 "headers": {"X-Tenant-Id": "t1"}, "body": None, "requestContext": {}}
        out = json.loads(list_leads(event, FakeRepo(rows))["body"])["leads"]
        self.assertEqual([r["lead_id"] for r in out], ["a"])


if __name__ == "__main__":
    unittest.main()
