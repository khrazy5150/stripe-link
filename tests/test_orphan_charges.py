"""Money Stripe took that we never recorded has to be noticed by the software, not by eye.

On 2026-10-07 two live sales were charged and neither produced an order, a ledger entry or a customer
row. Nothing flagged it. The operator found both by reading the Stripe dashboard a day later, and the
second only because they were looking for the first.

Every other guard is a prevention and each was correct until the day it wasn't. This is the detection
behind them, and it is deliberately ignorant of cause: it asks Stripe what it charged and the orders
table what it holds, and reports the difference.
"""
import unittest
import unittest.mock

from stripe_link.domain.orphan_charges import (MIN_AGE_SECONDS, charge_window, is_recordable,
                                               orphans, summarize)


def charge(**over):
    base = {"id": "ch_1", "payment_intent": "pi_1", "amount": 145, "amount_captured": 145,
            "currency": "usd", "paid": True, "status": "succeeded", "created": 1000,
            "livemode": True, "refunded": False}
    base.update(over)
    return base


class WhichChargesShouldHaveAnOrder(unittest.TestCase):
    def test_a_succeeded_captured_charge_should(self):
        self.assertTrue(is_recordable(charge()))

    def test_a_refunded_one_still_should(self):
        """The money moved twice. Both movements belong in the books -- this is exactly the pair that
        went missing, and a refund is not an excuse to forget the sale."""
        self.assertTrue(is_recordable(charge(refunded=True)))

    def test_a_failed_or_uncaptured_charge_should_not(self):
        self.assertFalse(is_recordable(charge(paid=False, status="failed")))
        self.assertFalse(is_recordable(charge(amount_captured=0)))
        self.assertFalse(is_recordable(charge(status="pending")))


class TheWindowAvoidsCryingWolf(unittest.TestCase):
    def test_a_charge_still_in_flight_is_out_of_scope(self):
        """Webhook delivery is asynchronous and a retry takes minutes. Flagging a ten-second-old charge
        would fire on every healthy sale and the alarm would be ignored within a day."""
        gte, lte = charge_window(10_000)
        self.assertEqual(lte, 10_000 - MIN_AGE_SECONDS)
        self.assertLess(gte, lte)
        self.assertGreaterEqual(MIN_AGE_SECONDS, 600, "shorter than the retry backoff would be noise")


class FindingTheGap(unittest.TestCase):
    def _lookup(self, known):
        return lambda pi: {"order_id": "ord"} if pi in known else None

    def test_a_charge_with_no_order_is_reported(self):
        found = orphans([charge()], order_for_payment_intent=self._lookup(set()))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["charge_id"], "ch_1")
        self.assertEqual(found[0]["amount"], 145)
        self.assertEqual(found[0]["reason"], "no_order")

    def test_a_charge_we_hold_is_not_reported(self):
        self.assertEqual(orphans([charge()], order_for_payment_intent=self._lookup({"pi_1"})), [])

    def test_a_charge_with_no_payment_intent_is_reported_not_skipped(self):
        """Unmatchable is not the same as absent, and silence is what this module exists to end."""
        found = orphans([charge(payment_intent=None)], order_for_payment_intent=self._lookup(set()))
        self.assertEqual([f["reason"] for f in found], ["no_payment_intent"])

    def test_an_unreadable_orders_table_is_not_reported_as_missing_money(self):
        """The most alarming possible way to say "DynamoDB is down" would be to claim every sale
        vanished. A failing lookup yields nothing rather than a false alarm."""
        def boom(_):
            raise RuntimeError("table unavailable")

        self.assertEqual(orphans([charge()], order_for_payment_intent=boom), [])

    def test_the_real_incident_is_what_this_catches(self):
        """Both 2026-10-07 charges: succeeded, later refunded, and no order on either side."""
        live = [charge(id="ch_3UO29m", payment_intent="pi_3UO29m", refunded=True),
                charge(id="ch_3UO4bm", payment_intent="pi_3UO4bm", refunded=True)]
        found = orphans(live, order_for_payment_intent=self._lookup(set()))
        self.assertEqual(summarize(found),
                         {"count": 2, "amount": 290, "charges": ["ch_3UO29m", "ch_3UO4bm"]})


class TheReportIsOneStory(unittest.TestCase):
    def test_the_log_line_and_the_notification_cannot_disagree(self):
        """Both read `summarize`, so there is one set of numbers rather than two that drift."""
        found = orphans([charge(), charge(id="ch_2", payment_intent="pi_2", amount_captured=500)],
                        order_for_payment_intent=lambda pi: None)
        self.assertEqual(summarize(found)["amount"], 645)
        self.assertEqual(summarize(found)["count"], 2)

    def test_the_charge_ids_are_carried_so_an_operator_can_open_them(self):
        found = orphans([charge()], order_for_payment_intent=lambda pi: None)
        self.assertIn("ch_1", summarize(found)["charges"])


class TheSweepPassReportsAndNotifies(unittest.TestCase):
    """The wiring: the pass rides the sweep that already runs every 5 minutes, so it adds no Lambda and
    no API route -- the stack is at CloudFormation's transform limit and cannot take either."""

    def setUp(self):
        from handlers import fee_reconciliation as module
        self.module = module
        self.notifications = []

        class Notifications:
            def __init__(self, sink):
                self.sink = sink

            def put(self, document):
                self.sink.append(document)

        class Orders:
            def find_by_payment_intent(self, payment_intent):
                return {"order_id": "ord"} if payment_intent == "pi_known" else None

        # The REAL repository over a fake table, not a fake repository. The first version of this test
        # invented a `scan_type()` the real class does not have, so it passed while the deployed sweep
        # logged `AttributeError` every five minutes -- the exact fake-that-cannot-fail mistake this
        # codebase keeps paying for. A fake must stand in for the real interface, not describe one.
        from stripe_link.repositories.documents import StripeKeysRepository

        class FakeKeysTable:
            ROWS = [
                {"tenant_id": "t_1", "mode": "live", "connect_account_id": "acct_1"},
                {"tenant_id": "t_2", "mode": "test", "connect_account_id": "acct_2"},
                {"tenant_id": "t_3", "mode": "live"},  # connected to nothing; must be skipped
            ]

            def scan(self, **kwargs):
                condition = kwargs.get("FilterExpression")
                return {"Items": [r for r in self.ROWS if condition and _matches(condition, r)]}

        def _matches(condition, row):
            """Good enough for the two attributes `connected()` filters on."""
            text = str(condition.get_expression() if hasattr(condition, "get_expression") else condition)
            wanted_live = "live" in text
            if row.get("mode") != ("live" if wanted_live else "test"):
                return False
            return bool(row.get("connect_account_id"))

        class Keys(StripeKeysRepository):
            def __init__(self):
                super().__init__("jb-stripe-keys-test", key_field="tenant_id", table=FakeKeysTable())

        self.notifications_repo = Notifications(self.notifications)
        self.orders_repo = Orders()
        self.keys_repo = Keys()

    def _run(self, charges, mode="live"):
        with unittest.mock.patch.object(
            self.module, "checkout_credentials", lambda *a, **k: ("sk_test_x", "acct_1")
        ):
            return self.module._report_orphan_charges(
                mode, 100_000,
                orders_repo=self.orders_repo, stripe_repo=self.keys_repo, secret_cipher=None,
                list_charges=lambda **kwargs: {"data": charges},
                notifications_repo=self.notifications_repo,
            )

    def test_it_only_asks_about_tenants_in_this_mode(self):
        out = self._run([], mode="live")
        self.assertEqual(out["tenants"], 1, "t_2 is a test-mode row and must not be swept as live")

    def test_an_unrecorded_charge_is_counted_and_notified(self):
        out = self._run([charge(id="ch_lost", payment_intent="pi_lost")])
        self.assertEqual((out["orphans"], out["amount"]), (1, 145))
        self.assertEqual(len(self.notifications), 1)
        note = self.notifications[0]
        self.assertEqual(note["kind"], "unrecorded_charge")
        self.assertEqual(note["severity"], "critical")
        self.assertEqual(note["notification_id"], "orphan_charge_ch_lost",
                         "keyed by charge so a repeating sweep does not repeat the alarm")

    def test_a_recorded_charge_raises_nothing(self):
        out = self._run([charge(id="ch_ok", payment_intent="pi_known")])
        self.assertEqual(out["orphans"], 0)
        self.assertEqual(self.notifications, [])

    def test_a_stripe_failure_does_not_stop_the_sweep(self):
        """Fee reconciliation has real work to do; a reporting pass must never take it down."""
        def boom(**kwargs):
            raise RuntimeError("Stripe unavailable")

        with unittest.mock.patch.object(
            self.module, "checkout_credentials", lambda *a, **k: ("sk_test_x", "acct_1")
        ):
            out = self.module._report_orphan_charges(
                "live", 100_000, orders_repo=self.orders_repo, stripe_repo=self.keys_repo,
                secret_cipher=None, list_charges=boom, notifications_repo=self.notifications_repo)
        self.assertEqual(out["failed"], 1)
        self.assertEqual(out["orphans"], 0)
