"""`charge.refunds` is not in the webhook payload, so the ledger cannot read it from there.

Taken from the stored payload of a real LIVE refund, evt_3UO4bm21lLbLd4Y513V9tcf9 on 2026-05-27.preview:
the charge carries `amount_refunded: 145`, `refunded: true`, `application_fee_amount: 10` and
`balance_transaction` — and no `refunds` key at all.

The ledger loop iterated `charge.refunds.data`, so it iterated nothing. Reconciliation reported
`ledger_written: 0`, returned 200, and the refunded order kept its sale entry with no reversal: the books
read +$1.01 where reality was -$0.44. Replaying the event could never fix it, because the payload is
identical every time — which is why this needs a fetch, not a retry.

The fourth field this API version moved, after invoice.subscription, parent.subscription_details and
line.pricing.price_details.
"""
import unittest

from handlers.stripe_webhook import _refunds_for_charge


# Exactly the shape Stripe sent, trimmed to the fields that matter.
LIVE_CHARGE = {
    "id": "ch_3UO4bm21lLbLd4Y51v07kxne",
    "amount": 145,
    "amount_refunded": 145,
    "refunded": True,
    "livemode": True,
    "payment_intent": "pi_3UO4bm21lLbLd4Y51Sp7UJX8",
    "application_fee_amount": 10,
    # NOTE: no "refunds" key. That is the whole point.
}

REFUND = {"id": "re_3UO4bm21lLbLd4Y518Il8RvT", "amount": 145, "status": "succeeded"}


class ListingTheRefundsOnACharge(unittest.TestCase):
    def test_it_fetches_when_the_payload_omits_them(self):
        seen = []

        def fetcher(charge_id):
            seen.append(charge_id)
            return [REFUND]

        out = _refunds_for_charge(LIVE_CHARGE, "t_1", fetcher=fetcher)
        self.assertEqual(out, [REFUND])
        self.assertEqual(seen, ["ch_3UO4bm21lLbLd4Y51v07kxne"])

    def test_it_prefers_the_payload_when_it_does_carry_them(self):
        """A stable API version, or an expanded charge: no call should be made."""
        charge = {**LIVE_CHARGE, "refunds": {"data": [REFUND]}}
        called = []
        out = _refunds_for_charge(charge, "t_1", fetcher=lambda c: called.append(c) or [])
        self.assertEqual(out, [REFUND])
        self.assertEqual(called, [], "the payload already had them; fetching again is a wasted call")

    def test_an_unrefunded_charge_asks_nothing(self):
        charge = {**LIVE_CHARGE, "amount_refunded": 0, "refunded": False}
        called = []
        self.assertEqual(_refunds_for_charge(charge, "t_1", fetcher=lambda c: called.append(c) or []), [])
        self.assertEqual(called, [])

    def test_a_failed_fetch_is_empty_not_an_exception(self):
        """Failing the delivery would make Stripe retry an event that can never succeed, and
        eventually disable the endpoint — the nine-day failure, repeated."""
        def boom(_):
            raise RuntimeError("Stripe is down")

        self.assertEqual(_refunds_for_charge(LIVE_CHARGE, "t_1", fetcher=boom), [])
