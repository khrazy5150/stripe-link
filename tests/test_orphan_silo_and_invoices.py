"""The orphan sweep cried wolf every five minutes, in both silos, over money it had recorded.

Found 2026-10-10 by reading what the deployed sweep was logging rather than by reasoning about it:

    [ERROR] UNRECORDED STRIPE MONEY tenant=586173f0... mode=test
            {'count': 1, 'amount': 19792, 'charges': ['ch_3UOtmw21lLbLd4Y50K7lDokj']}

in `jb-stripe-webhook-prod` AND `jb-stripe-webhook-dev`, every five minutes, for a charge that
`jb-orders-dev` held as `order_in_1UOsq521lLbLd4Y50sXIDrlB`, `status: paid`, `amount_total: 19792`.
Nothing was lost. Two independent defects stacked:

1. **A subscription charge can never be matched by PaymentIntent.** The stored order has no
   `payment_intent_id` field at all -- `order_record_from_invoice` keys on the INVOICE -- so the one
   index the sweep had returned nothing for every renewal that has ever been taken, and will take.

2. **Both silos list the same connected account's charges.** The two `stripe_keys` tables are
   per-environment, but they hold credentials for the SAME `acct_`, so production enumerated the
   sandbox tenant and asked its own orders table about a sandbox charge.

The fixture values below are the real ones, so a regression has to reproduce the actual shapes rather
than a tidied-up idea of them: metadata `{}` on the charge, the stamp only on
`invoice.parent.subscription_details.metadata.silo` (this account is on a preview API version that moved
`subscription_details` under `parent`), and `expand[]=data.invoice` as the thing that makes it reachable.
"""
import unittest

from stripe_link.domain.orphan_charges import (invoice_id_of, is_ours, order_id_for_invoice, orphans,
                                               owning_silo)

TENANT = "586173f0-40a1-7053-d421-453cf1de68d0"

# Verified against Stripe 2026-10-10. The charge's own metadata really is empty.
SUBSCRIPTION_CHARGE = {
    "id": "ch_3UOtmw21lLbLd4Y50K7lDokj",
    "paid": True,
    "status": "succeeded",
    "amount": 19792,
    "amount_captured": 19792,
    "currency": "usd",
    "created": 1791613788,
    "livemode": False,
    "refunded": False,
    "payment_intent": "pi_3UOtmw21lLbLd4Y50HtH0C7y",
    "description": "Subscription update",
    "metadata": {},
    "invoice": {
        "id": "in_1UOsq521lLbLd4Y50sXIDrlB",
        "billing_reason": "subscription_cycle",
        "metadata": {},
        "parent": {"subscription_details": {"metadata": {
            "tenant_id": TENANT, "offer_id": "offer_aA3u3qIj8vq", "silo": "sandbox"}}},
    },
}

# What `jb-orders-dev` actually holds. Note the absence of `payment_intent_id`: that absence IS defect 1.
STORED_SUBSCRIPTION_ORDER = {
    "order_id": "order_in_1UOsq521lLbLd4Y50sXIDrlB",
    "invoice_id": "in_1UOsq521lLbLd4Y50sXIDrlB",
    "status": "paid",
    "amount_total": 19792,
    "stripe_mode": "test",
    "metadata": {"silo": "sandbox"},
}


def never_found(_):
    """The PaymentIntent index, which cannot match a subscription order however healthy it is."""
    return None


def sandbox_orders(order_id):
    return STORED_SUBSCRIPTION_ORDER if order_id == "order_in_1UOsq521lLbLd4Y50sXIDrlB" else None


def empty_orders(_):
    return None


class TheExactAlarmFromProduction(unittest.TestCase):
    def test_sandbox_finds_the_order_and_says_nothing(self):
        found = orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found,
                        order_for_id=sandbox_orders, this_silo="sandbox", mode="test")
        self.assertEqual(found, [], "the order is right there, keyed by invoice")

    def test_production_does_not_report_a_sandbox_charge(self):
        """Even though production's own orders table is empty for it -- correctly, it is not production's."""
        found = orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found,
                        order_for_id=empty_orders, this_silo="production", mode="test")
        self.assertEqual(found, [], "a foreign silo's charge is not missing money")

    def test_the_old_behaviour_is_what_fired(self):
        """Without either fix -- no invoice lookup, no silo -- the alarm reproduces. If this ever stops
        failing to find the order, the test below it has stopped proving anything."""
        found = orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["charge_id"], "ch_3UOtmw21lLbLd4Y50K7lDokj")
        self.assertEqual(found[0]["amount"], 19792)


class ASubscriptionChargeIsMatchedByItsInvoice(unittest.TestCase):
    def test_a_genuinely_missing_subscription_order_is_still_reported(self):
        """The filter must not become a way to never report anything."""
        found = orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found,
                        order_for_id=empty_orders, this_silo="sandbox", mode="test")
        self.assertEqual([f["reason"] for f in found], ["no_order_for_invoice"])
        self.assertEqual(found[0]["invoice_id"], "in_1UOsq521lLbLd4Y50sXIDrlB")

    def test_the_order_id_matches_what_the_writer_writes(self):
        """`order_record_from_invoice` derives `order_{invoice_id}`. Deriving it differently here is
        exactly how a recorded order became invisible."""
        self.assertEqual(order_id_for_invoice("in_1UOsq521lLbLd4Y50sXIDrlB"),
                         STORED_SUBSCRIPTION_ORDER["order_id"])

    def test_the_payment_intent_index_is_not_consulted_for_an_invoice_charge(self):
        """An invoice charge HAS a PaymentIntent -- one we never store. Asking about it returns nothing
        and reads as a lost sale, so the invoice has to win."""
        asked = []

        def recording(pi):
            asked.append(pi)
            return None

        orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=recording,
                order_for_id=sandbox_orders, this_silo="sandbox", mode="test")
        self.assertEqual(asked, [], "the PaymentIntent index must not decide an invoice charge")

    def test_invoice_reachable_whether_expanded_or_not(self):
        self.assertEqual(invoice_id_of({"invoice": "in_abc"}), "in_abc")
        self.assertEqual(invoice_id_of({"invoice": {"id": "in_abc"}}), "in_abc")
        self.assertEqual(invoice_id_of({}), "")

    def test_without_the_invoice_lookup_nothing_changes(self):
        """`order_for_id` is optional so the other callers keep working; absent, the old path runs."""
        found = orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found,
                        this_silo="sandbox", mode="test")
        self.assertEqual([f["reason"] for f in found], ["no_order"])


class OwnershipFollowsTheWebhooksOwnRule(unittest.TestCase):
    """If the sweep and the writer disagree about who owns a charge, the sweep reports as missing
    precisely the charges the writer correctly declined."""

    def test_the_stamp_wins_when_there_is_one(self):
        self.assertEqual(owning_silo({"metadata": {"silo": "production"}}, "test"), "production")

    def test_a_subscription_charge_is_stamped_on_its_invoice_only(self):
        self.assertEqual(stamp_of_charge_only(), "", "the charge itself carries no metadata")
        self.assertEqual(owning_silo(SUBSCRIPTION_CHARGE, "test"), "sandbox")

    def test_unstamped_falls_to_the_legacy_correspondence(self):
        """The same table `event_belongs_here` uses: test was dev, live was prod, before silos existed."""
        self.assertEqual(owning_silo({}, "test"), "sandbox")
        self.assertEqual(owning_silo({}, "live"), "production")

    def test_mode_is_inferred_from_livemode_when_not_given(self):
        self.assertEqual(owning_silo({"livemode": True}), "production")
        self.assertEqual(owning_silo({"livemode": False}), "sandbox")

    def test_an_unknown_stamp_is_not_trusted_as_a_silo(self):
        self.assertEqual(owning_silo({"metadata": {"silo": "staging-ish"}, "livemode": False}), "sandbox")


def stamp_of_charge_only():
    from stripe_link.domain.silo_routing import stamp_from_object
    return stamp_from_object({k: v for k, v in SUBSCRIPTION_CHARGE.items() if k != "invoice"})


class TheFilterFailsOpen(unittest.TestCase):
    """A false alarm costs a look at the Stripe dashboard. A suppressed one costs a sale nobody records.
    Every ambiguity resolves toward reporting."""

    def test_a_deployment_that_cannot_name_its_silo_reports_everything(self):
        self.assertTrue(is_ours({"metadata": {"silo": "production"}}, this_silo="", mode="test"))

    def test_an_unknown_this_silo_value_is_treated_as_unknown(self):
        self.assertTrue(is_ours({"metadata": {"silo": "production"}}, this_silo="qa", mode="test"))

    def test_a_charge_nothing_can_attribute_is_reported(self):
        """No stamp and no mode to fall back on: report rather than drop."""
        self.assertTrue(is_ours({}, this_silo="production", mode="nonsense"))


class ThePlainCheckoutPathIsUntouched(unittest.TestCase):
    """The defect was in two paths that had never been exercised; the one that works must keep working."""

    CHECKOUT_CHARGE = {
        "id": "ch_live_1", "paid": True, "status": "succeeded", "amount_captured": 145,
        "currency": "usd", "created": 1791613788, "livemode": True, "refunded": False,
        "payment_intent": "pi_live_1", "metadata": {"silo": "sandbox"},
    }

    def test_a_held_checkout_charge_is_not_reported(self):
        found = orphans([self.CHECKOUT_CHARGE], order_for_payment_intent=lambda p: {"order_id": "order_x"},
                        order_for_id=empty_orders, this_silo="sandbox", mode="live")
        self.assertEqual(found, [])

    def test_a_missing_checkout_charge_is_still_reported(self):
        found = orphans([self.CHECKOUT_CHARGE], order_for_payment_intent=never_found,
                        order_for_id=empty_orders, this_silo="sandbox", mode="live")
        self.assertEqual([f["reason"] for f in found], ["no_order"])
        self.assertEqual(found[0]["silo"], "sandbox")

    def test_a_sandbox_stamped_live_charge_is_not_productions_problem(self):
        """The 2026-10-07 shape: a LIVE sale taken through the sandbox silo. Production must stay quiet
        about it, which the legacy mode correspondence alone would get wrong."""
        found = orphans([self.CHECKOUT_CHARGE], order_for_payment_intent=never_found,
                        order_for_id=empty_orders, this_silo="production", mode="live")
        self.assertEqual(found, [], "the stamp says sandbox; the legacy rule would have said production")

    def test_an_unreadable_table_is_never_reported_as_missing_money(self):
        def broken(_):
            raise RuntimeError("DynamoDB is down")

        self.assertEqual(orphans([self.CHECKOUT_CHARGE], order_for_payment_intent=broken,
                                 this_silo="sandbox", mode="live"), [])
        self.assertEqual(orphans([SUBSCRIPTION_CHARGE], order_for_payment_intent=never_found,
                                 order_for_id=broken, this_silo="sandbox", mode="test"), [])


if __name__ == "__main__":
    unittest.main()


class TheSweepActuallyAsksStripeForTheInvoice(unittest.TestCase):
    """The wiring, with the REAL orders repository over a fake table.

    The previous version of this test file's sibling passed while the deployed sweep raised
    `AttributeError` every five minutes, because its fake invented a method the real class lacked.
    `orders_repo.get` is a real method of `TenantRangeRepository`; proving it by calling the real class
    is the only kind of proof that has held up in this codebase.
    """

    def setUp(self):
        import unittest.mock

        from handlers import fee_reconciliation as module
        from stripe_link.repositories.documents import (StripeKeysRepository, TenantRangeRepository,
                                                        tenant_mode_pk)
        self.module = module
        self.mock = unittest.mock
        self.sent_params = []
        self.notifications = []

        stored_pk = tenant_mode_pk(TENANT, "test")

        class FakeOrdersTable:
            def get_item(self, Key):  # noqa: N803 - boto3's own casing
                if (Key["PK"], Key["SK"]) == (stored_pk, "order_in_1UOsq521lLbLd4Y50sXIDrlB"):
                    return {"Item": dict(STORED_SUBSCRIPTION_ORDER, PK=Key["PK"], SK=Key["SK"])}
                return {}

            def query(self, **kwargs):
                return {"Items": []}

        class FakeKeysTable:
            def scan(self, **kwargs):
                return {"Items": [{"tenant_id": TENANT, "mode": "test", "connect_account_id": "acct_1"}]}

        class Keys(StripeKeysRepository):
            def __init__(self):
                super().__init__("jb-stripe-keys-test", key_field="tenant_id", table=FakeKeysTable())

        class Notifications:
            def __init__(self, sink):
                self.sink = sink

            def put(self, document):
                self.sink.append(document)

        self.orders_repo = TenantRangeRepository(
            "jb-orders-test", id_field="order_id", mode="test", table=FakeOrdersTable())
        self.keys_repo = Keys()
        self.notifications_repo = Notifications(self.notifications)

    def _run(self, silo, charges=(SUBSCRIPTION_CHARGE,)):
        def lister(**kwargs):
            self.sent_params.append(kwargs.get("params") or {})
            return {"data": list(charges)}

        with self.mock.patch.object(self.module, "checkout_credentials",
                                    lambda *a, **k: ("sk_test_x", "acct_1")):
            return self.module._report_orphan_charges(
                "test", 1_791_700_000, orders_repo=self.orders_repo, stripe_repo=self.keys_repo,
                secret_cipher=None, list_charges=lister,
                notifications_repo=self.notifications_repo, this_silo=silo)

    def test_it_expands_the_invoice_so_the_stamp_is_reachable(self):
        """Without this the charge carries no silo at all and the filter has nothing to read."""
        self._run("sandbox")
        self.assertEqual(self.sent_params[0].get("expand[]"), "data.invoice")

    def test_sandbox_finds_the_order_through_the_real_repository(self):
        out = self._run("sandbox")
        self.assertEqual((out["orphans"], out["amount"]), (0, 0))
        self.assertEqual(self.notifications, [], "this is the alarm that was firing every five minutes")

    def test_production_does_not_alarm_about_it(self):
        out = self._run("production")
        self.assertEqual(out["orphans"], 0)
        self.assertEqual(self.notifications, [])

    def test_the_tally_records_which_silo_decided(self):
        self.assertEqual(self._run("production")["silo"], "production")

    def test_a_real_gap_still_notifies_and_says_why(self):
        missing = dict(SUBSCRIPTION_CHARGE, id="ch_gone",
                       invoice=dict(SUBSCRIPTION_CHARGE["invoice"], id="in_gone"))
        out = self._run("sandbox", charges=(missing,))
        self.assertEqual(out["orphans"], 1)
        note = self.notifications[0]
        self.assertEqual(note["notification_id"], "orphan_charge_ch_gone")
        self.assertEqual(note["silo"], "sandbox")
        self.assertEqual(note["orphan_reason"], "no_order_for_invoice")
        self.assertEqual(note["invoice_id"], "in_gone",
                         "an operator needs the invoice to open it, not just the charge")

    def test_a_deployment_with_no_silo_still_reports(self):
        """Fails open: `this_silo=''` is how a stack deployed before `SILO` existed behaves."""
        out = self._run("", charges=(dict(SUBSCRIPTION_CHARGE, id="ch_x", invoice={"id": "in_x"}),))
        self.assertEqual(out["orphans"], 1)


class TheAlarmIsActuallyWired(unittest.TestCase):
    """**The detection built to end the silence was itself silent** (found 2026-10-10).

    `handler` defaults `notifications_repo` to None so tests can inject one. `_notify_overdue` resolves
    it lazily from `NOTIFICATIONS_TABLE` when it is None; `_report_orphan_charges` did not. So on every
    scheduled run `_notify_orphans` took its `if notifications_repo is None: return` and the only record
    of unrecorded money was an ERROR log with no reader. Both notification tables held zero
    `orphan_charge_*` rows while the log had been screaming every five minutes.

    This is the sibling of the `refundError`-set-but-never-rendered defect and of the fake that
    implemented a method the real repository lacked: the end of the path was never exercised.
    """

    def setUp(self):
        import unittest.mock

        from handlers import fee_reconciliation as module
        self.module = module
        self.mock = unittest.mock

        class Keys:
            def connected(self, mode):
                return [{"tenant_id": TENANT, "mode": mode, "connect_account_id": "acct_1"}]

        class Orders:
            def find_by_payment_intent(self, payment_intent):
                return None

            def get(self, tenant_id, order_id):
                return None

        self.keys_repo = Keys()
        self.orders_repo = Orders()

    def _run(self, env):
        lost = dict(SUBSCRIPTION_CHARGE, id="ch_lost", invoice={"id": "in_lost"})
        with self.mock.patch.object(self.module, "checkout_credentials",
                                    lambda *a, **k: ("sk_test_x", "acct_1")), \
             self.mock.patch.dict("os.environ", env, clear=False), \
             self.mock.patch.object(self.module, "notifications_repository") as factory:
            factory.return_value = _Sink()
            out = self.module._report_orphan_charges(
                "test", 1_791_700_000, orders_repo=self.orders_repo, stripe_repo=self.keys_repo,
                secret_cipher=None, list_charges=lambda **k: {"data": [lost]},
                notifications_repo=None, this_silo="sandbox")
            return out, factory

    def test_it_builds_a_notifications_repository_when_none_is_injected(self):
        out, factory = self._run({"NOTIFICATIONS_TABLE": "jb-notifications-test"})
        factory.assert_called_once_with(mode="test")
        self.assertEqual(out["orphans"], 1)
        self.assertEqual(out["notified"], 1,
                         "finding money and telling nobody is the defect this pins")
        self.assertEqual(factory.return_value.sink[0]["notification_id"], "orphan_charge_ch_lost")

    def test_the_tally_reports_a_find_that_notified_nobody(self):
        """Without the table there is genuinely nowhere to write, and the tally must say so rather than
        letting `orphans: 1` imply someone was told."""
        out, _ = self._run({})
        self.assertEqual((out["orphans"], out["notified"]), (1, 0))


class _Sink:
    def __init__(self):
        self.sink = []

    def put(self, document):
        self.sink.append(document)
