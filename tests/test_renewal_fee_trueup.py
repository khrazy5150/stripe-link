"""A renewal whose invoice carried no PaymentIntent must still be trued up.

The bug, found 2026-10-19 by reading why a test order had been alarming since the 18th:

  * our Stripe fee is an ESTIMATE that rounds UP where Stripe rounds down, by design;
  * `fetch_actual_fees` exists to replace it with Stripe's real number;
  * but the sweep only offered an order to that fetch if it carried `payment_intent_id`;
  * and `order_record_from_invoice` OMITS that field when the cycle invoice has no payment_intent --
    it must, because the field is a GSI key and an empty string fails the whole write.

So such an order could never be corrected. Its fee stayed a cent high forever, and once Stripe settled
the charge the ledger audit reported the gap every five minutes, permanently, with nothing anyone could
do to resolve it. The audit was right; the true-up simply could not reach the charge.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain.fee_reconciliation import ESTIMATE, charge_reference, due  # noqa: E402

NOW = 1_792_000_000


def _order(**extra):
    return {"order_id": "order_in_x", "created_at": NOW - 3600,
            "fees": {"fees_source": ESTIMATE, "stripe_fee": 33, "net": 967, "gross": 1000},
            **extra}


class HowAnOrderNamesItsChargeTests(unittest.TestCase):
    def test_a_checkout_order_is_reached_by_its_payment_intent(self):
        self.assertEqual(charge_reference(_order(payment_intent_id="pi_1")),
                         ("payment_intent", "pi_1"))

    def test_a_renewal_with_no_payment_intent_is_reached_by_its_invoice(self):
        """THE regression. This order is the one that alarmed forever."""
        self.assertEqual(charge_reference(_order(invoice_id="in_1")), ("invoice", "in_1"))

    def test_the_payment_intent_wins_when_both_are_present(self):
        self.assertEqual(charge_reference(_order(payment_intent_id="pi_1", invoice_id="in_1")),
                         ("payment_intent", "pi_1"))

    def test_an_order_naming_neither_is_still_unreachable(self):
        self.assertIsNone(charge_reference(_order()))

    def test_blank_strings_do_not_count_as_naming_one(self):
        self.assertIsNone(charge_reference(_order(payment_intent_id="  ", invoice_id="")))


class WhichOrdersTheSweepOffersTests(unittest.TestCase):
    def test_a_renewal_with_only_an_invoice_is_now_due(self):
        self.assertTrue(due(_order(invoice_id="in_1"), NOW))

    def test_an_order_naming_neither_is_not_due(self):
        self.assertFalse(due(_order(), NOW))

    def test_an_already_settled_fee_is_left_alone(self):
        order = _order(invoice_id="in_1")
        order["fees"]["fees_source"] = "stripe"
        self.assertFalse(due(order, NOW), "correcting a settled fee would rewrite Stripe's own number")

    def test_still_bounded_by_age(self):
        self.assertFalse(due(_order(invoice_id="in_1", created_at=NOW), NOW), "too young to have settled")
        self.assertFalse(due(_order(invoice_id="in_1", created_at=NOW - 30 * 24 * 3600), NOW),
                         "aged out of the retry window")


class TheSweepAsksTheRightWayTests(unittest.TestCase):
    """`reconcile_order` must choose the route the order can actually answer on."""

    def _run(self, order):
        from handlers.fee_reconciliation import reconcile_order

        asked = {}

        def by_payment_intent(value, **kwargs):
            asked["payment_intent"] = value
            return {"stripe_fee": 32, "net": 968}

        def by_invoice(value, **kwargs):
            asked["invoice"] = value
            return {"stripe_fee": 32, "net": 968}

        class Repo:
            def __init__(self): self.saved = []
            def put(self, doc): self.saved.append(doc)

        orders_repo = Repo()
        moved = reconcile_order(order, api_key="sk_test_x", stripe_account="acct_1", now=NOW,
                                orders_repo=orders_repo, ledger_repo=None,
                                fetch_fees=by_payment_intent, fetch_invoice_fees=by_invoice)
        return asked, moved, orders_repo

    def test_a_renewal_is_asked_about_BY_INVOICE(self):
        asked, moved, repo = self._run(_order(invoice_id="in_1"))
        self.assertEqual(asked, {"invoice": "in_1"}, "asked the wrong way, or asked for nothing")
        # NEGATIVE by a cent: our estimate was ABOVE Stripe's actual, which is the same direction the
        # audit reported as "the ledger is ahead of Stripe on stripe_fee by 1 cents".
        self.assertEqual(moved, -1, "the one-cent estimate should have been corrected downward")
        self.assertEqual(repo.saved[0]["fees"]["stripe_fee"], 32)

    def test_a_checkout_order_is_still_asked_by_payment_intent(self):
        asked, moved, _ = self._run(_order(payment_intent_id="pi_1"))
        self.assertEqual(asked, {"payment_intent": "pi_1"})
        self.assertEqual(moved, -1)

    def test_an_order_naming_neither_asks_nothing_at_all(self):
        """It used to ask Stripe for "" and log a failure on every pass, forever."""
        asked, moved, repo = self._run(_order())
        self.assertEqual(asked, {})
        self.assertIsNone(moved)
        self.assertEqual(repo.saved, [])


if __name__ == "__main__":
    unittest.main()
