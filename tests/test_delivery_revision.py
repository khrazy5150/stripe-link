"""The shipment notice corrects the date the buyer is holding.

plans/THANK_YOU_PAGE.md P4. The thank-you page promises an arrival computed from a GUESS about when the
parcel will ship. The moment it actually ships, that guess becomes a fact — and a tenant who was three
days out of stock has a buyer holding a date that was never going to happen.

The author, 2026-10-04: *"It may be possible that a tenant who has run out of inventory had their shipment
delivered delayed. So a revised date with a possible tenant explanation should work."*
"""
import unittest

from stripe_link.domain.delivery_estimate import from_ship_date
from stripe_link.domain.shipping_promise import revised_promise, revised_sentence

QUOTE = {"options": [
    {"service_token": "usps_ground_advantage", "carrier": "USPS", "label": "Ground Advantage",
     "transit_days_min": 5, "transit_days_max": 5},
    {"service_token": "ups_next_day_air", "carrier": "UPS", "label": "Next Day Air",
     "transit_days_min": 1, "transit_days_max": 1},
]}
ORDER = {"order_id": "order_1",
         "shipping_quote": {"service_token": "usps_ground_advantage"},
         "delivery_estimate": {"arrives_on": "2026-10-12", "service": "USPS Ground Advantage"}}


def revise(shipped_on, shipment=None, order=None):
    return revised_promise(order or ORDER, QUOTE, shipment or {"service": "Ground Advantage"},
                           shipped_on=shipped_on)


class ItRecomputesFromTheDayItReallyLeftTests(unittest.TestCase):
    def test_a_known_ship_date_needs_no_cutoff_or_timezone(self):
        """The parcel is already gone; there is nothing left to decide about which working day it left."""
        out = from_ship_date("2026-10-05", transit_days_min=5)
        self.assertEqual(out["arrives_on"], "2026-10-12")

    def test_shipping_on_time_keeps_the_promised_date(self):
        out = revise("2026-10-05")
        self.assertEqual(out["arrives_on"], "2026-10-12")
        self.assertFalse(out["changed"])

    def test_shipping_late_moves_it(self):
        out = revise("2026-10-08")
        self.assertEqual(out["arrives_on"], "2026-10-15")
        self.assertTrue(out["changed"])
        self.assertTrue(out["later"])
        self.assertEqual(out["was"], "2026-10-12")

    def test_shipping_early_moves_it_too(self):
        out = revise("2026-10-01")
        self.assertTrue(out["changed"])
        self.assertFalse(out["later"])


class TheWordingTurnsOnWhetherItMovedTests(unittest.TestCase):
    """An apology for nothing teaches buyers to expect one and devalues the next real apology."""

    def test_an_unchanged_date_is_simply_stated(self):
        self.assertEqual(revised_sentence(revise("2026-10-05")),
                         "It should reach you on Monday, October 12.")

    def test_a_later_date_NAMES_the_change(self):
        """The buyer is holding a date. Finding out by noticing the parcel is late is worse than being
        told."""
        line = revised_sentence(revise("2026-10-08"))
        self.assertIn("later than the Monday, October 12 we first estimated", line)
        self.assertIn("Thursday, October 15", line)

    def test_an_earlier_date_is_good_news_worth_sending(self):
        line = revised_sentence(revise("2026-10-01"))
        self.assertIn("sooner", line)

    def test_nothing_to_say_says_nothing(self):
        self.assertEqual(revised_sentence({}), "")
        self.assertEqual(revised_sentence(None), "")


class TransitDaysComeFromWhatACTUALLYShippedTests(unittest.TestCase):
    """The tenant picks a carrier and service when they mark an order shipped, and it need not be the one
    the buyer paid for — upgrading to get a late parcel there on time is exactly what a tenant does."""

    def test_the_shipments_own_days_win(self):
        # The label-buying path has these from the rate it bought.
        out = revise("2026-10-08", shipment={"service": "Whatever", "transit_days_min": 1,
                                             "transit_days_max": 1})
        self.assertEqual(out["arrives_on"], "2026-10-09")

    def test_otherwise_the_quoted_option_for_that_service(self):
        # Shipped by Next Day Air instead of the Ground Advantage the buyer paid for.
        out = revise("2026-10-08", shipment={"service": "Next Day Air"})
        self.assertEqual(out["arrives_on"], "2026-10-09")

    def test_otherwise_what_the_buyer_was_quoted(self):
        # An unrecognised service name: still right about the SHIP DATE, which is the part that moved.
        out = revise("2026-10-08", shipment={"service": "Some Courier"})
        self.assertEqual(out["arrives_on"], "2026-10-15")

    def test_the_carrier_registry_is_not_a_source(self):
        """It knows which services carry tracking, not how fast they are. Inventing a duration for
        "Priority Mail" would be the typed-in guess this whole thread replaced."""
        from stripe_link.domain.carriers import carrier_registry

        usps = carrier_registry().get("usps") or {}
        for service in usps.get("services") or []:
            self.assertNotIn("transit_days_min", service)

    def test_an_order_that_was_never_rated_revises_nothing(self):
        self.assertEqual(revised_promise({"order_id": "o"}, None, {"service": "x"},
                                         shipped_on="2026-10-08"), {})


class NothingWasPromisedSoNothingWasBrokenTests(unittest.TestCase):
    def test_an_order_with_no_original_estimate_just_gets_a_date(self):
        order = {"shipping_quote": {"service_token": "usps_ground_advantage"}}
        out = revise("2026-10-08", order=order)
        self.assertFalse(out["changed"])
        self.assertIsNone(out["was"])
        self.assertEqual(revised_sentence(out), "It should reach you on Thursday, October 15.")


class TheEmailCarriesBothTests(unittest.TestCase):
    def _content(self, **kw):
        from stripe_link.domain.receipts import shipment_tracking_content

        return shipment_tracking_content(business_name="Poliaxis", order_id="order_1",
                                         items="Workout Bundle", carrier_label="USPS",
                                         service_label="Ground Advantage", tracking_number="94001",
                                         tracking_url="https://x", has_tracking=True, **kw)

    def test_the_arrival_line_appears(self):
        out = self._content(arrival_line="It should reach you on Monday, October 12.")
        self.assertIn("It should reach you on Monday, October 12.", out["text"])
        self.assertIn("It should reach you on Monday, October 12.", out["html"])

    def test_the_tenants_note_appears(self):
        note = "We ran out of stock and restocked Tuesday. Sorry for the wait."
        self.assertIn(note, self._content(tenant_note=note)["text"])

    def test_the_note_is_escaped(self):
        out = self._content(tenant_note='<script>alert("x")</script>')
        self.assertNotIn("<script>", out["html"])

    def test_the_date_comes_BEFORE_the_tracking_table(self):
        """It is what the buyer opened the email to find out.

        Measured against the BODY, not the whole document: the first "94001" in the HTML is the hidden
        preheader, which is inbox preview text rather than anything the reader scrolls past."""
        out = self._content(arrival_line="It should reach you on Monday, October 12.")
        body = out["html"].split("Tracking number", 1)
        self.assertEqual(len(body), 2, "no tracking row to compare against")
        self.assertIn("October 12", body[0])

    def test_an_email_without_either_is_unchanged(self):
        plain = self._content()
        self.assertIn("Workout Bundle is on its way.", plain["text"])


class TheHandlerStoresTheCorrectionBesideThePromiseTests(unittest.TestCase):
    """`delivery_estimate` holds what the buyer was ORIGINALLY told. Support answering "but you said the
    12th" needs both the promise and the correction, and a field that quietly becomes the new truth loses
    the thing that was actually promised."""

    SOURCE = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "src" / "handlers" / "orders.py").read_text()

    def test_the_revision_lands_on_the_shipment(self):
        self.assertIn('shipment["delivery_revision"] = revised', self.SOURCE)

    def test_it_never_overwrites_the_order(self):
        self.assertNotIn('order["delivery_estimate"] =', self.SOURCE)

    def test_the_note_is_length_capped(self):
        # Tenant free text that travels to a buyer.
        self.assertIn('str(body.get("note") or "").strip()[:400]', self.SOURCE)

    def test_a_failed_revision_never_stops_a_parcel_shipping(self):
        block = self.SOURCE.split("def _revised_arrival", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("except Exception", block)
        self.assertIn("return {}", block)
