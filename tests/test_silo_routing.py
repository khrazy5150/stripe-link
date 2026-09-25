"""S3: work out which silo owns a Stripe event, and say so in the logs. Refuse nothing yet.

plans/SILO_MODEL.md. S4 turns this into a refusal, and it is only safe once these logs are quiet -- a
resolver that starts dropping events on its first day drops the ones it is wrong about.

S2 (a Customer anchor) is deliberately NOT a rule here. Measured against 126 stored production events on
2026-09-25: the webhook acts on five event types, and the two that occur both carry a stamp today, while
everything the stamp cannot reach -- customer.created/updated/deleted, checkout.session.expired,
payment_intent.succeeded -- the webhook ignores entirely. An anchor resolving events nobody reads is a
mapping table to keep true for no gain.
"""
import unittest

from stripe_link.domain.silo_routing import (
    BY_DEFAULT,
    BY_HOLDING,
    BY_STAMP,
    order_id_for_event,
    resolve_event_silo,
    routing_log,
    stamp_from_event,
)


def _event(obj, **over):
    return {"id": "evt_1", "type": "checkout.session.completed", "livemode": False,
            "data": {"object": obj}, **over}


class StampReadingTests(unittest.TestCase):
    def test_a_session_carries_its_stamp_in_metadata(self):
        self.assertEqual(stamp_from_event(_event({"id": "cs_1", "metadata": {"silo": "sandbox"}})),
                         "sandbox")

    def test_an_invoice_carries_the_SUBSCRIPTIONS_stamp_under_parent(self):
        """The account is on a preview API version that moved subscription_details under `parent`. A
        resolver written against remembered field names resolves NOTHING and falls through to its default
        -- which, once S4 exists, is the difference between processing money and dropping it."""
        event = _event({"id": "in_1", "parent": {"subscription_details": {"metadata": {"silo": "sandbox"}}}},
                       type="invoice.paid")
        self.assertEqual(stamp_from_event(event), "sandbox")

    def test_the_legacy_top_level_shape_still_reads(self):
        event = _event({"id": "in_1", "subscription_details": {"metadata": {"silo": "production"}}})
        self.assertEqual(stamp_from_event(event), "production")

    def test_a_line_level_stamp_is_the_last_resort(self):
        event = _event({"id": "in_1", "lines": {"data": [{"metadata": {"silo": "sandbox"}}]}})
        self.assertEqual(stamp_from_event(event), "sandbox")

    def test_an_unknown_silo_name_is_not_a_stamp(self):
        """normalize_silo refuses to invent; a typo must not become a routing decision."""
        self.assertEqual(stamp_from_event(_event({"id": "cs_1", "metadata": {"silo": "staging-ish"}})), "")

    def test_no_metadata_is_no_stamp(self):
        self.assertEqual(stamp_from_event(_event({"id": "cs_1"})), "")
        self.assertEqual(stamp_from_event({}), "")


class ResolutionTests(unittest.TestCase):
    def test_the_stamp_wins_when_there_is_one(self):
        result = resolve_event_silo(_event({"id": "cs_1", "metadata": {"silo": "sandbox"}}),
                                    this_silo="production")
        self.assertEqual(result["silo"], "sandbox")
        self.assertEqual(result["source"], BY_STAMP)
        self.assertFalse(result["mine"])

    def test_an_order_we_already_hold_is_ours_whatever_it_forgot_to_say(self):
        result = resolve_event_silo(_event({"id": "cs_1"}), this_silo="production",
                                    holds_order=lambda order_id: True)
        self.assertEqual(result["silo"], "production")
        self.assertEqual(result["source"], BY_HOLDING)
        self.assertTrue(result["mine"])

    def test_an_unstamped_unheld_event_defaults_to_SANDBOX_never_production(self):
        """The documented read rule, applied exactly once where it is written down. Defaulting the other
        way would let an unlabelled event write into real tenants' data."""
        result = resolve_event_silo(_event({"id": "cs_1"}), this_silo="production")
        self.assertEqual(result["silo"], "sandbox")
        self.assertEqual(result["source"], BY_DEFAULT)

    def test_a_stamp_against_our_own_tables_is_an_INVARIANT_VIOLATION(self):
        """This is the one thing worth seeing before any of it starts refusing events: the sandbox stamp
        on an order production is already holding is exactly the orphan we have in the data today."""
        result = resolve_event_silo(_event({"id": "cs_1", "metadata": {"silo": "sandbox"}}),
                                    this_silo="production", holds_order=lambda order_id: True)
        self.assertFalse(result["agrees"])
        self.assertIn("sandbox", result["disagreement"])
        self.assertIn("production", result["disagreement"])

    def test_agreement_is_not_claimed_when_the_stamp_matches_us(self):
        result = resolve_event_silo(_event({"id": "cs_1", "metadata": {"silo": "production"}}),
                                    this_silo="production", holds_order=lambda order_id: True)
        self.assertTrue(result["agrees"])
        self.assertTrue(result["mine"])

    def test_a_lookup_that_RAISES_does_not_decide_a_silo(self):
        def explode(order_id):
            raise RuntimeError("AccessDenied")

        result = resolve_event_silo(_event({"id": "cs_1"}), this_silo="production", holds_order=explode)
        self.assertEqual(result["source"], BY_DEFAULT)

    def test_no_lookup_at_all_is_handled(self):
        self.assertEqual(resolve_event_silo(_event({"id": "cs_1"}), this_silo="production",
                                            holds_order=None)["source"], BY_DEFAULT)


class OrderIdTests(unittest.TestCase):
    def test_it_derives_the_id_the_WRITERS_derive(self):
        """Asking the same question a different way would make "do I hold it?" answerable by accident."""
        self.assertEqual(order_id_for_event(_event({"id": "cs_test_1"})), "order_cs_test_1")
        self.assertEqual(order_id_for_event(_event({"id": "in_1"})), "order_in_1")

    def test_an_object_with_no_id_yields_nothing(self):
        self.assertEqual(order_id_for_event(_event({})), "")


class LoggingTests(unittest.TestCase):
    """The logs ARE the deliverable of S3 -- S4 is gated on them being quiet."""

    def test_the_line_says_how_it_decided_not_only_what(self):
        event = _event({"id": "cs_1", "metadata": {"silo": "sandbox"}})
        line = routing_log(event, resolve_event_silo(event, this_silo="production"),
                           this_silo="production")["silo_routing"]
        self.assertEqual(line["source"], BY_STAMP)
        self.assertEqual(line["resolved_silo"], "sandbox")
        self.assertEqual(line["this_silo"], "production")
        self.assertEqual(line["event_type"], "checkout.session.completed")
        self.assertEqual(line["phase"], "S3")

    def test_a_run_of_defaults_is_distinguishable_from_a_run_of_disagreements(self):
        # Different problems: one means the stamp is not arriving, the other that it contradicts us.
        plain = _event({"id": "cs_1"})
        default_line = routing_log(plain, resolve_event_silo(plain, this_silo="production"),
                                   this_silo="production")["silo_routing"]
        clash = _event({"id": "cs_2", "metadata": {"silo": "sandbox"}})
        clash_line = routing_log(clash, resolve_event_silo(clash, this_silo="production",
                                                           holds_order=lambda o: True),
                                 this_silo="production")["silo_routing"]
        self.assertEqual(default_line["source"], BY_DEFAULT)
        self.assertTrue(default_line["agrees"])
        self.assertFalse(clash_line["agrees"])

    def test_it_is_json_serialisable_because_it_is_printed(self):
        import json
        event = _event({"id": "cs_1"})
        json.dumps(routing_log(event, resolve_event_silo(event, this_silo="production"),
                               this_silo="production"))


class NothingIsRefusedYetTests(unittest.TestCase):
    """S3 observes. The moment it refuses, it refuses the events it is wrong about."""

    def test_the_webhook_does_not_branch_on_the_resolution(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
        self.assertIn("resolve_event_silo(", source)
        body = source.split("silo_resolution = resolve_event_silo(", 1)[1][:900]
        for forbidden in ("if not silo_resolution", 'silo_resolution["mine"]', "if silo_resolution"):
            self.assertNotIn(forbidden, body,
                             "S3 must not act on the resolution -- that is S4, and it is gated on the logs")


if __name__ == "__main__":
    unittest.main()
