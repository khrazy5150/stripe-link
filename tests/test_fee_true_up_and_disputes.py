"""Two accounting-accuracy requirements from PRD/AI_AND_COMMERCE_PRD.md, checked against the code.

- Phase 1 hygiene / Phase 5: *"reconcile the estimated `stripe_fee`/`net_payout` to the actual value from
  the charge's balance transaction (`platform_fee` is already exact)"*. Nothing read a balance transaction;
  our fee rounds UP where Stripe rounds down, so every stored payout was a cent or two light.
- Phase 5: *"Every financial event (sale, refund, dispute, shipping/cost) appends an immutable, idempotent
  ledger entry"*. `charge.dispute.created` flagged the ORDER and told the ledger nothing, so a disputed
  order kept counting as revenue.
"""
import json
import unittest

from handlers.stripe_webhook import (
    fetch_actual_fees,
    record_dispute_ledger_entry,
    true_up_fees,
)
from stripe_link.domain.ledger import dispute_entry_from_event, sale_entry_from_order, summarize

ESTIMATE = {"tenant_keyed_amount": 6277, "stripe_fee": 213, "platform_fee": 284, "net_payout": 5780}
ORDER = {"tenant_id": "t1", "order_id": "o1", "payment_intent_id": "pi_1", "amount_total": 6277,
         "currency": "usd", "mode": "test", "shipping_amount": 598,
         "fees": {"stripe_fee": 213, "platform_fee": 284}}
DISPUTE = {"id": "dp_1", "amount": 6277, "currency": "usd", "created": 9, "payment_intent": "pi_1",
           "balance_transactions": [{"fee": 1500}]}


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(payload):
    def _open(request, timeout=0):
        return Response(payload)
    return _open


SETTLED = {"latest_charge": {"balance_transaction": {
    "net": 5781, "fee": 496,
    "fee_details": [{"type": "stripe_fee", "amount": 212},
                    {"type": "application_fee", "amount": 284}]}}}


class TrueUpTests(unittest.TestCase):
    def test_the_real_stripe_fee_replaces_the_estimate(self):
        trued = true_up_fees(ESTIMATE, {"stripe_fee": 212, "net": 5781})
        self.assertEqual(trued["stripe_fee"], 212)
        self.assertEqual(trued["net_payout"], 5781)
        self.assertEqual(trued["fees_source"], "balance_transaction")

    def test_the_platform_fee_is_never_touched(self):
        # It was exact already: checkout chose the number and Stripe applied it.
        self.assertEqual(true_up_fees(ESTIMATE, {"stripe_fee": 212})["platform_fee"], 284)

    def test_no_actual_leaves_the_estimate_alone(self):
        self.assertEqual(true_up_fees(ESTIMATE, {}), ESTIMATE)
        self.assertEqual(true_up_fees(ESTIMATE, None), ESTIMATE)

    def test_an_unsettled_charge_is_not_an_error(self):
        # Some payment methods settle later. Not a reason to overwrite a usable estimate with nothing.
        unsettled = {"latest_charge": {"balance_transaction": None}}
        self.assertEqual(fetch_actual_fees("pi_1", api_key="sk_test_x", opener=opener_for(unsettled)), {})

    def test_only_stripes_own_fee_is_read_from_the_breakdown(self):
        # `fee` on the transaction also contains the application fee; counting that as a Stripe fee would
        # double-count the platform's cut against the tenant.
        actual = fetch_actual_fees("pi_1", api_key="sk_test_x", opener=opener_for(SETTLED))
        self.assertEqual(actual["stripe_fee"], 212)
        self.assertNotEqual(actual["stripe_fee"], 496)

    def test_a_stripe_outage_leaves_the_order_recordable(self):
        def boom(request, timeout=0):
            raise RuntimeError("stripe unreachable")

        self.assertEqual(fetch_actual_fees("pi_1", api_key="sk_test_x", opener=boom), {})

    def test_no_key_means_no_call(self):
        self.assertEqual(fetch_actual_fees("pi_1", api_key="", opener=opener_for(SETTLED)), {})

    def test_the_trued_up_fee_is_what_reaches_the_ledger(self):
        order = {**ORDER, "fees": true_up_fees(ESTIMATE, {"stripe_fee": 212})}
        self.assertEqual(summarize([sale_entry_from_order(order, now_epoch=1)])["net"], 5781)

    def test_the_webhook_applies_it_on_the_completed_session_path(self):
        import inspect

        import handlers.stripe_webhook as webhook

        source = inspect.getsource(webhook.persist_checkout_session_completed)
        self.assertIn("true_up_fees(fee_breakdown_from_session(", source)


class DisputeLedgerTests(unittest.TestCase):
    def test_a_chargeback_reverses_the_sale(self):
        entry = dispute_entry_from_event(DISPUTE, ORDER, now_epoch=9)
        self.assertEqual(entry["entry_type"], "dispute")
        self.assertEqual(entry["amounts"]["gross"], -6277)

    def test_the_network_fee_is_recorded_as_a_cost(self):
        self.assertEqual(dispute_entry_from_event(DISPUTE, ORDER, now_epoch=9)["amounts"]["stripe_fee"],
                         -1500)

    def test_a_full_chargeback_takes_the_postage_too(self):
        self.assertEqual(
            dispute_entry_from_event(DISPUTE, ORDER, now_epoch=9)["amounts"]["shipping_revenue"], -598)

    def test_it_is_idempotent_on_stripes_dispute_id(self):
        a = dispute_entry_from_event(DISPUTE, ORDER, now_epoch=9)
        b = dispute_entry_from_event(DISPUTE, ORDER, now_epoch=99)
        self.assertEqual(a["entry_id"], b["entry_id"])
        self.assertEqual(a["idempotency_key"], b["idempotency_key"])

    def test_a_disputed_order_stops_counting_as_revenue(self):
        # The whole point: before this, it kept counting.
        summary = summarize([sale_entry_from_order(ORDER, now_epoch=1),
                             dispute_entry_from_event(DISPUTE, ORDER, now_epoch=9)])
        self.assertEqual(summary["totals"]["gross"], 0)
        self.assertEqual(summary["merchandise_revenue"], 0)
        self.assertEqual(summary["net"], -(213 + 284 + 1500))

    def test_an_empty_dispute_records_nothing(self):
        self.assertIsNone(dispute_entry_from_event({}, ORDER, now_epoch=9))
        self.assertIsNone(dispute_entry_from_event({"id": "dp_2", "amount": 0}, ORDER, now_epoch=9))

    def test_reconciliation_appends_it(self):
        class Repo:
            def __init__(self):
                self.rows = []

            def append(self, entry):
                self.rows.append(entry)

        repo = Repo()
        self.assertTrue(record_dispute_ledger_entry(DISPUTE, ORDER, repo, 9))
        self.assertEqual(repo.rows[0]["amounts"]["gross"], -6277)

    def test_a_ledger_outage_never_fails_the_dispute_reconciliation(self):
        class Broken:
            def append(self, entry):
                raise RuntimeError("dynamo down")

        self.assertFalse(record_dispute_ledger_entry(DISPUTE, ORDER, Broken(), 9))

    def test_the_handler_can_be_given_a_ledger_repo(self):
        # It referenced `ledger_repo` in the dispute branch without it being a parameter -- a NameError
        # that would have fired only on a real chargeback.
        import inspect

        import handlers.stripe_webhook as webhook

        self.assertIn("ledger_repo", inspect.signature(webhook.handler).parameters)
