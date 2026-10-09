"""The parsers are checked against Stripe's ACTUAL payloads, not our memory of them.

Every hand-written Stripe fixture encodes what we believed the payload looked like. Four defects came
from that belief being stale on `2026-05-27.preview`, and all four were found by a buyer's money going
somewhere wrong rather than by a test:

| field                  | what we assumed      | what Stripe sends                      |
|------------------------|----------------------|----------------------------------------|
| `invoice.subscription` | present              | gone                                   |
| `subscription_details` | top level            | under `parent`                         |
| `line.price`           | present              | `line.pricing.price_details`           |
| `charge.refunds`       | present, expanded    | ABSENT from the webhook payload        |

The fixtures beside this file are real payloads captured from `jb-webhook-events-dev`
(`scripts/capture_webhook_fixtures.py`), scrubbed of identifying values but structurally untouched: every
key's presence and absence is Stripe's, not ours.

These tests assert what the PARSERS extract, so they fail when Stripe moves a field again. They do not
assert the payload's own shape -- pinning that would just re-encode today's assumption one layer out.
"""
import json
import pathlib
import unittest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "stripe_events"


def event(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def obj(name):
    return ((event(name).get("data") or {}).get("object")) or {}


class FixturesAreRealAndClean(unittest.TestCase):
    def test_every_money_critical_event_type_is_covered(self):
        have = {p.stem for p in FIXTURES.glob("*.json")}
        for required in ("checkout_session_completed", "charge_refunded", "invoice_paid",
                         "payment_intent_succeeded"):
            self.assertIn(required, have, f"no captured payload for {required}")

    def test_no_identifying_data_survived_capture(self):
        """The scrubber missed an account id embedded in a hosted-invoice URL the first time."""
        blob = "\n".join(p.read_text() for p in FIXTURES.glob("*.json"))
        for leak in ("khrazy5150", "keithdecosta", "Poliaxis", "Cheyenne", "1TA08M21lLbLd4Y5"):
            self.assertNotIn(leak, blob, f"{leak} leaked into a committed fixture")


class RefundsAreNotInTheChargePayload(unittest.TestCase):
    """`charge.refunds` is absent, so the ledger loop had nothing to iterate and a refunded live order
    kept its sale entry with no reversal."""

    def test_the_payload_really_omits_them(self):
        self.assertNotIn("refunds", obj("charge_refunded"))

    def test_the_fetcher_asks_stripe_instead_of_giving_up(self):
        from handlers.stripe_webhook import _refunds_for_charge
        charge = obj("charge_refunded")
        asked = []
        out = _refunds_for_charge(charge, "t_1", fetcher=lambda cid: asked.append(cid) or [{"id": "re_x"}])
        self.assertEqual(out, [{"id": "re_x"}])
        self.assertEqual(asked, [charge["id"]], "it must list the refunds for THIS charge")

    def test_the_charge_still_says_how_much_went_back(self):
        self.assertGreater(int(obj("charge_refunded").get("amount_refunded") or 0), 0)


class InvoiceFieldsMovedUnderParent(unittest.TestCase):
    """Every renewal order was stored with an empty subscription_id, and renewals never found their silo
    stamp, because both reads looked at the old top-level location."""

    def test_the_subscription_id_is_still_found(self):
        from handlers.stripe_webhook import invoice_subscription_id
        self.assertTrue(invoice_subscription_id(obj("invoice_paid")),
                        "the renewal cannot be tied back to its subscription")

    def test_the_subscription_metadata_is_still_found(self):
        from handlers.stripe_webhook import invoice_subscription_metadata
        metadata = invoice_subscription_metadata(obj("invoice_paid"))
        self.assertIsInstance(metadata, dict)
        self.assertTrue(metadata, "empty metadata means a renewal with no silo stamp and no attribution")

    def test_the_silo_stamp_resolves_from_the_real_payload(self):
        from stripe_link.domain.silo_routing import stamp_from_event
        self.assertTrue(stamp_from_event(event("invoice_paid")),
                        "an unstamped renewal falls to the legacy default instead of its own silo")


class LinePricingMoved(unittest.TestCase):
    """`line.price` became `line.pricing.price_details`, so both ids came back empty on every renewal --
    which broke the receipt lines, download links and fulfilment."""

    def test_price_and_product_ids_are_recovered_from_the_lines(self):
        lines = ((obj("invoice_paid").get("lines") or {}).get("data")) or []
        self.assertTrue(lines, "the fixture has no invoice lines to read")
        found = []
        for line in lines:
            price = line.get("price") if isinstance(line.get("price"), dict) else {}
            details = ((line.get("pricing") or {}).get("price_details")) or {}
            found.append((str(price.get("id") or details.get("price") or ""),
                          str(price.get("product") or details.get("product") or "")))
        self.assertTrue(any(p and pr for p, pr in found),
                        f"neither location yielded a price/product id: {found}")


class CheckoutSessionStillParses(unittest.TestCase):
    def test_the_silo_stamp_is_on_the_session(self):
        from stripe_link.domain.silo_routing import stamp_from_event
        self.assertTrue(stamp_from_event(event("checkout_session_completed")),
                        "an unstamped session routes by the legacy default rather than its own silo")

    def test_the_mode_is_derivable_from_livemode(self):
        from handlers.stripe_webhook import _mode_from_livemode
        self.assertIn(_mode_from_livemode(event("checkout_session_completed")), ("test", "live"))
