"""Carrier tracking, received rather than guessed.

`fulfilment.delivery_status` has read `shipment["tracking_status"]` since the shipping work and nothing
ever wrote it: one reader, zero writers. These tests pin the two things that make the feed trustworthy
enough for `buyer_guarantees.no_delivery_refund` to be built on later -- that a late event cannot
un-deliver a parcel, and that "no delivery known" is never confused with "did not arrive".
"""

import json
import os
import pathlib
import unittest

from stripe_link.domain.fulfilment import delivery_status
from stripe_link.domain.shipping_providers import MockProvider, ShippingProvider
from stripe_link.domain.tracking import (
    DELIVERED,
    FAILURE,
    PRE_TRANSIT,
    RETURNED,
    TRANSIT,
    accepts,
    fields_to_write,
    has_arrived,
    normalize_status,
    parse_status_date,
    reading,
    register,
    shipment_id_from,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def webhook(status, *, date="2026-07-24T15:02:00Z", metadata="shp_abc", details=""):
    """A `track_updated` body in the shape Shippo documents: the Tracking object wrapped in `data`."""
    return {"event": "track_updated", "data": {
        "carrier": "usps", "tracking_number": "9400111", "metadata": metadata,
        "tracking_status": {"status": status, "status_date": date, "status_details": details},
    }}


class ReadingThePayload(unittest.TestCase):
    def test_the_documented_shape_is_read(self):
        out = reading(webhook(DELIVERED, details="Left with resident."))
        self.assertEqual(out["tracking_status"], DELIVERED)
        self.assertEqual(out["tracking_detail"], "Left with resident.")
        self.assertEqual(out["tracking_status_at"], 1784905320)

    def test_a_bare_tracking_object_is_read_too(self):
        """`POST /tracks` returns the object bare and the webhook wraps it in `data`. Both arrive at this
        module, so both are read rather than only the one a test happened to use."""
        bare = webhook(TRANSIT)["data"]
        self.assertEqual(reading(bare)["tracking_status"], TRANSIT)
        self.assertEqual(shipment_id_from(bare), "shp_abc")

    def test_our_own_id_is_the_only_identifier_resolved(self):
        """Carried in Shippo's `metadata` because we put it there. `tracking_number` is not ours and would
        need a new index; `transaction` is the provider's."""
        self.assertEqual(shipment_id_from(webhook(TRANSIT, metadata="shp_xyz")), "shp_xyz")
        self.assertEqual(shipment_id_from(webhook(TRANSIT, metadata="")), "")

    def test_an_unknown_status_is_dropped_not_stored(self):
        """`delivery_status` would fall through it to our own gate view anyway, and storing a word nothing
        can translate puts a value on the document that looks like a delivery fact and is not one."""
        self.assertEqual(normalize_status("ON_A_VAN_SOMEWHERE"), "")
        self.assertEqual(reading(webhook("ON_A_VAN_SOMEWHERE")), {})

    def test_never_raises_on_rubbish(self):
        for junk in (None, "", [], {}, {"data": "nope"}, {"data": {"tracking_status": 7}}):
            with self.subTest(junk=junk):
                self.assertEqual(reading(junk), {})
                self.assertEqual(shipment_id_from(junk), "")

    def test_an_undated_event_reads_as_zero_rather_than_now(self):
        """0 means "undated", and the ordering rules below never let an undated event displace a dated
        one. Substituting our own clock would make every undated event look like the newest."""
        self.assertEqual(parse_status_date(""), 0)
        self.assertEqual(parse_status_date("not a date"), 0)
        self.assertEqual(reading(webhook(TRANSIT, date=""))["tracking_status_at"], 0)

    def test_an_offset_timestamp_is_normalised_to_utc(self):
        self.assertEqual(parse_status_date("2026-07-24T11:02:00-04:00"), 1784905320)

    def test_a_naive_timestamp_is_read_as_utc(self):
        self.assertEqual(parse_status_date("2026-07-24T15:02:00"), 1784905320)


class WhatMayOverwriteWhat(unittest.TestCase):
    """Shippo retries twice on a non-2XX and events for one parcel can arrive out of order, so "latest
    received" is not "latest happened"."""

    def test_a_first_reading_is_always_accepted(self):
        self.assertTrue(accepts({}, reading(webhook(TRANSIT))))

    def test_a_newer_event_wins(self):
        stored = {"tracking_status": TRANSIT, "tracking_status_at": 1000}
        self.assertTrue(accepts(stored, {"tracking_status": DELIVERED, "tracking_status_at": 2000}))

    def test_an_older_event_is_refused(self):
        stored = {"tracking_status": TRANSIT, "tracking_status_at": 2000}
        self.assertFalse(accepts(stored, {"tracking_status": PRE_TRANSIT, "tracking_status_at": 1000}))

    def test_a_retry_of_the_same_event_is_idempotent_rather_than_refused(self):
        stored = {"tracking_status": TRANSIT, "tracking_status_at": 2000}
        self.assertTrue(accepts(stored, {"tracking_status": TRANSIT, "tracking_status_at": 2000}))

    def test_a_late_scan_cannot_un_deliver_a_parcel(self):
        """THE ONE THAT MATTERS. This is the transition that would make a delivery guarantee pay out on an
        order the buyer already has, and a carrier posting a stale in-transit scan after the box was on
        the doorstep is an ordinary thing for a carrier to do."""
        stored = {"tracking_status": DELIVERED, "tracking_status_at": 1000}
        for status in (TRANSIT, PRE_TRANSIT):
            with self.subTest(status=status):
                self.assertFalse(accepts(stored, {"tracking_status": status,
                                                  "tracking_status_at": 9999}))

    def test_a_delivered_parcel_may_still_be_returned(self):
        """A refused delivery or a return to sender is a real journey, so these two may follow
        DELIVERED -- the sticky rule is about going backwards, not about never moving again."""
        stored = {"tracking_status": DELIVERED, "tracking_status_at": 1000}
        for status in (RETURNED, FAILURE):
            with self.subTest(status=status):
                self.assertTrue(accepts(stored, {"tracking_status": status,
                                                 "tracking_status_at": 2000}))

    def test_an_unusable_reading_changes_nothing(self):
        self.assertFalse(accepts({"tracking_status": TRANSIT}, {}))
        self.assertEqual(fields_to_write({"tracking_status": TRANSIT}, {}, now=5), {})


class DeliveredAt(unittest.TestCase):
    def test_it_is_set_from_the_carriers_clock(self):
        fields = fields_to_write({}, reading(webhook(DELIVERED)), now=9_000_000)
        self.assertEqual(fields["delivered_at"], 1784905320)
        self.assertEqual(fields["tracking_updated_at"], 9_000_000)

    def test_it_falls_back_to_our_clock_only_when_the_carrier_dated_nothing(self):
        """A delivery with no date is still a delivery, and leaving it unset would leave the guarantee
        measuring against nothing."""
        fields = fields_to_write({}, reading(webhook(DELIVERED, date="")), now=9_000_000)
        self.assertEqual(fields["delivered_at"], 9_000_000)

    def test_it_is_written_once_and_never_moved(self):
        """A parcel delivered, returned and redelivered did still arrive on the first date. Moving it
        would silently re-open a promise that had been kept."""
        stored = {"tracking_status": DELIVERED, "tracking_status_at": 1000, "delivered_at": 1000}
        fields = fields_to_write(stored, {"tracking_status": RETURNED, "tracking_status_at": 2000},
                                 now=9_000_000)
        self.assertEqual(fields["tracking_status"], RETURNED)
        self.assertNotIn("delivered_at", fields)

    def test_nothing_sets_it_on_a_parcel_in_transit(self):
        fields = fields_to_write({}, reading(webhook(TRANSIT)), now=9_000_000)
        self.assertNotIn("delivered_at", fields)

    def test_absence_is_not_a_claim_that_it_did_not_arrive(self):
        """The distinction the whole guarantee rests on. Every shipment predating this feed, and every
        carrier that never scans, answers False here -- and so does a parcel genuinely lost."""
        self.assertFalse(has_arrived({}))
        self.assertFalse(has_arrived({"tracking_status": TRANSIT}))
        self.assertTrue(has_arrived({"delivered_at": 1000}))


class Registering(unittest.TestCase):
    class Boom:
        def register_tracking(self, **_kwargs):
            raise RuntimeError("Shippo is down")

    SHIPMENT = {"shipment_id": "shp_abc", "carrier": "usps", "tracking_number": "9400111"}

    def test_the_mock_provider_registers_a_parcel_just_handed_over(self):
        fields = register(MockProvider(), self.SHIPMENT, now=5_000)
        self.assertEqual(fields["tracking_status"], PRE_TRANSIT)
        self.assertEqual(fields["tracking_registered_at"], 5_000)
        self.assertNotIn("delivered_at", fields)

    def test_the_mock_never_reports_a_delivery_at_registration(self):
        """The whole flow is walked with no provider account, and a mock that delivered every parcel the
        moment it shipped would make a delivery guarantee untestable in the state that matters."""
        self.assertEqual(MockProvider().register_tracking(
            carrier="usps", tracking_number="1")["tracking_status"]["status"], PRE_TRANSIT)

    def test_a_provider_with_no_tracking_feed_is_not_a_crash(self):
        """`{}` by default on the interface, for `parcel_templates`' reason: a provider that tells us
        nothing is a true answer."""
        self.assertEqual(ShippingProvider().register_tracking(carrier="usps", tracking_number="1"), {})
        self.assertEqual(register(ShippingProvider(), self.SHIPMENT, now=5_000),
                         {"tracking_registered_at": 5_000})

    def test_a_failing_provider_never_fails_the_shipment(self):
        """By the time this runs the postage is paid and the parcel is going. A tracking registration that
        failed must not turn a successful shipment into an error the tenant thinks they should retry."""
        self.assertEqual(register(self.Boom(), self.SHIPMENT, now=5_000), {})

    def test_nothing_is_registered_without_a_number(self):
        """USPS First-Class carries no tracking number at all, and `mark_shipped` says so explicitly."""
        for missing in ("carrier", "tracking_number", "shipment_id"):
            with self.subTest(missing=missing):
                shipment = {k: v for k, v in self.SHIPMENT.items() if k != missing}
                self.assertEqual(register(MockProvider(), shipment, now=5_000), {})


class TheScreenFinallyReadsIt(unittest.TestCase):
    """`fulfilment._TRACKING` was written against Shippo's exact vocabulary and had nothing to translate.
    The point of the feed is that these stop being theoretical."""

    def test_a_delivered_parcel_now_reads_as_delivered(self):
        fields = fields_to_write({}, reading(webhook(DELIVERED)), now=1)
        self.assertEqual(delivery_status({}, {"shipment": fields})["key"], "delivered")

    def test_the_carriers_own_sentence_reaches_the_status_cell(self):
        """Every field this feed stores must have a reader, or it repeats the fault it exists to fix: the
        Orders screen passes `delivery.note` straight through, and this is the one line a tenant chasing
        a parcel actually wants."""
        fields = fields_to_write({}, reading(webhook(DELIVERED, details="Left with resident.")), now=1)
        self.assertEqual(delivery_status({}, {"shipment": fields})["note"], "Left with resident.")

    def test_a_scan_with_no_sentence_leaves_the_note_empty(self):
        fields = fields_to_write({}, reading(webhook(TRANSIT)), now=1)
        self.assertEqual(delivery_status({}, {"shipment": fields})["note"], "")

    def test_every_status_this_module_stores_is_one_the_screen_understands(self):
        """A status stored here that `delivery_status` cannot translate would silently fall through to our
        own gate view -- the Status cell would ignore a real carrier scan and show a stale guess."""
        for status in (PRE_TRANSIT, TRANSIT, DELIVERED, RETURNED, FAILURE):
            with self.subTest(status=status):
                resolved = delivery_status({}, {"shipment": {"tracking_status": status}})
                self.assertNotEqual(resolved["key"], "not_shippable")


class TheSchemaAgrees(unittest.TestCase):
    def schema(self):
        return json.loads((ROOT / "schemas" / "Shipment.schema.json").read_text())["properties"]

    def test_every_field_written_is_declared(self):
        """`Shipment.schema.json` is `additionalProperties: false`, so a field written and not declared is
        a document the schema rejects."""
        written = set(fields_to_write({}, reading(webhook(DELIVERED)), now=1))
        written.add("tracking_registered_at")
        written.add("tracking_substatus")
        self.assertTrue(written <= set(self.schema()), written - set(self.schema()))

    def test_the_status_enum_matches_the_module(self):
        self.assertEqual(sorted(self.schema()["tracking_status"]["enum"]),
                         sorted({PRE_TRANSIT, TRANSIT, DELIVERED, RETURNED, FAILURE, "UNKNOWN"}))



class ThePlatformKey(unittest.TestCase):
    """Shipping is BYOK per tenant; tracking is the one Shippo call this platform makes with its own
    credentials. A tracker registered with a TENANT's key reports to a webhook on their account -- which is
    not ours -- and it would still register, so `guarantee_due.observable` would count the parcel as
    visible while no delivery ever arrived."""

    def setUp(self):
        from stripe_link import shippo_tracking
        shippo_tracking._KEY_CACHE.clear()
        self._prev = os.environ.get("SHIPPO_TRACKING_SECRET_NAME")
        os.environ["SHIPPO_TRACKING_SECRET_NAME"] = "jb/shippo-tracking/test"

    def tearDown(self):
        from stripe_link import shippo_tracking
        shippo_tracking._KEY_CACHE.clear()
        if self._prev is None:
            os.environ.pop("SHIPPO_TRACKING_SECRET_NAME", None)
        else:
            os.environ["SHIPPO_TRACKING_SECRET_NAME"] = self._prev

    def secrets(self, payload, *, raises=False):
        class Fake:
            def get_secret_value(self, SecretId=None):  # noqa: N803 - boto3's own parameter name
                if raises:
                    raise RuntimeError("AccessDenied")
                return {"SecretString": json.dumps(payload)}
        return Fake()

    def test_the_mode_picks_the_key(self):
        """A test-mode order must never burn a PAID track on a parcel that does not exist, and Shippo's
        test key only accepts their mock numbers."""
        from stripe_link.shippo_tracking import load_key
        both = {"live_key": "shippo_live_1", "test_key": "shippo_test_1"}
        self.assertEqual(load_key("live", client=self.secrets(both)), "shippo_live_1")
        self.assertEqual(load_key("test", client=self.secrets(both)), "shippo_test_1")

    def test_an_unknown_mode_is_treated_as_test(self):
        """Fail-safe in the same direction as `resolve_stripe_mode`: a caller that forgets the mode gets
        the key that cannot spend money."""
        from stripe_link.shippo_tracking import load_key
        both = {"live_key": "shippo_live_1", "test_key": "shippo_test_1"}
        for mode in ("", None, "nonsense"):
            with self.subTest(mode=mode):
                self.assertEqual(load_key(mode, client=self.secrets(both)), "shippo_test_1")

    def test_no_secret_means_tracking_is_simply_off(self):
        from stripe_link.shippo_tracking import platform_tracker
        self.assertIsNone(platform_tracker("live", secrets_client=self.secrets({})))

    def test_a_denied_secret_is_off_rather_than_an_error(self):
        """The parcel is already gone and the buyer already told. No feed is where every parcel started."""
        from stripe_link.shippo_tracking import platform_tracker
        self.assertIsNone(platform_tracker("live", secrets_client=self.secrets({}, raises=True)))

    def test_a_configured_key_builds_a_shippo_client(self):
        from stripe_link.shippo_tracking import platform_tracker
        tracker = platform_tracker("live", secrets_client=self.secrets({"live_key": "shippo_live_1"}))
        self.assertEqual(tracker.name, "shippo")
        self.assertTrue(hasattr(tracker, "register_tracking"))

    def test_tracking_off_registers_nothing_rather_than_failing(self):
        """`register` already treats a falsy provider as nothing to do, so the whole chain degrades to
        "this parcel has no feed" -- and the sweep stays silent on it by the gate's own rule."""
        self.assertEqual(register(None, {"shipment_id": "s", "carrier": "usps",
                                         "tracking_number": "1"}, now=5), {})

if __name__ == "__main__":
    unittest.main()
