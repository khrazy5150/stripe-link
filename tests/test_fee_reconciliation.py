"""Phase 1: the sweep that replaces an estimated Stripe fee with the real one.

Every sale records an estimate when it is written. Most are corrected seconds later by the webhook, which
reads the charge's balance transaction. Upsells are not -- they are PaymentIntents we create ourselves, so
nothing fires afterwards, and the transaction is not attached yet when the handler asks. Proven rather
than assumed, on a real funnel (2026-10-04): `stripe returned []` on the create expansion and again on an
immediate retry.

What it costs, measured on that same funnel, paid with a Canadian Visa (Stripe adds 1.5% on a
foreign-issued card):

    order       amount   recorded   actual   drift
    main         18564        847      847      +0   <- the webhook trued it up
    upsell_1       900         57       70     +13
    upsell_2      1786         82      109     +27

Every earlier run matched exactly, because the cards were US-issued and the estimate is right for those.
That is why it went unnoticed, and why `fees_source` had to exist before this sweep could.
"""
import unittest

from handlers.fee_reconciliation import handler
from stripe_link.domain.fee_reconciliation import due

ESTIMATED = {"tenant_keyed_amount": 1786, "stripe_fee": 82, "platform_fee": 89,
             "net_payout": 1615, "fees_source": "estimate"}


def order(order_id="order_up_1", *, pi="pi_up_1", created=1_000_000, fees=None, tenant="t1"):
    return {"tenant_id": tenant, "order_id": order_id, "payment_intent_id": pi,
            "amount_total": 1786, "currency": "usd", "stripe_mode": "test", "mode": "test",
            "line_item_type": "upsell", "created_at": created,
            "fees": dict(ESTIMATED if fees is None else fees)}


class OrdersRepo:
    def __init__(self, rows):
        self.rows = {r["order_id"]: dict(r) for r in rows}

    def scan_type(self):
        return [dict(r) for r in self.rows.values()]

    def get(self, tenant_id, order_id):
        # The webhook reaches one order by key; the sweep walks them all. Both are on the real
        # TenantRangeRepository, and a double missing one makes negative tests pass for the wrong reason.
        row = self.rows.get(order_id)
        return dict(row) if row and row.get("tenant_id") == tenant_id else None

    def put(self, document):
        self.rows[document["order_id"]] = dict(document)
        return document


class LedgerRepo:
    def __init__(self, rows=None):
        self.rows = {(r["tenant_id"], r["entry_id"]): dict(r) for r in (rows or [])}

    def get(self, tenant_id, entry_id):
        row = self.rows.get((tenant_id, entry_id))
        return dict(row) if row else None

    def append(self, document):
        self.rows[(document["tenant_id"], document["entry_id"])] = dict(document)
        return document


class StripeRepo:
    def __init__(self, keys=None):
        self.keys = keys if keys is not None else {"secret_key_ref": "ref_1"}

    def get(self, tenant_id, **_kwargs):
        return dict(self.keys)


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "sk_test_x"


def run(orders, ledger=None, *, actual=None, now=1_000_600, stripe_repo=None, fetch=None):
    calls = []

    def fetch_fees(pi, **kwargs):
        calls.append(pi)
        return dict(actual or {})

    tally = handler({}, None, orders_repo=orders, ledger_repo=ledger or LedgerRepo(),
                    stripe_repo=stripe_repo or StripeRepo(), secret_cipher=Cipher(),
                    fetch_fees=fetch or fetch_fees, now_fn=lambda: now, modes=("test",))
    return tally["test"], calls


class ItCorrectsTheOrderAndTheLedgerTogetherTests(unittest.TestCase):
    """Correcting one without the other is worse than correcting neither: the two then disagree, and the
    report a tenant reads is built from the ledger."""

    def test_the_order_takes_stripes_number(self):
        repo = OrdersRepo([order()])
        tally, _ = run(repo, actual={"stripe_fee": 109, "net": 1588})
        fees = repo.rows["order_up_1"]["fees"]
        self.assertEqual(fees["stripe_fee"], 109)
        self.assertEqual(fees["fees_source"], "balance_transaction")
        # The platform's cut is exact already; only the payout moves with the corrected Stripe fee.
        self.assertEqual(fees["platform_fee"], 89)
        self.assertEqual(fees["net_payout"], 1786 - 109 - 89)
        self.assertEqual(tally["corrected"], 1)
        self.assertEqual(tally["drift_cents"], 27)

    def test_the_ledger_row_is_restated_in_place(self):
        ledger = LedgerRepo()
        run(OrdersRepo([order()]), ledger, actual={"stripe_fee": 109})
        self.assertEqual(len(ledger.rows), 1, "the sale must not be counted twice")
        entry = ledger.rows[("t1", "le_sale_pi_up_1")]
        self.assertEqual(entry["amounts"]["stripe_fee"], -109)

    def test_it_keeps_the_rows_own_provenance_and_timing(self):
        """Rebuilding would default `source` to `webhook`, which is the one thing an upsell is not -- and
        would date the sale to the moment it was corrected."""
        ledger = LedgerRepo([{"tenant_id": "t1", "entry_id": "le_sale_pi_up_1", "source": "upsell",
                              "occurred_at": 1_000_000, "created_at": 1_000_000, "amounts": {}}])
        run(OrdersRepo([order()]), ledger, actual={"stripe_fee": 109}, now=1_000_600)
        entry = ledger.rows[("t1", "le_sale_pi_up_1")]
        self.assertEqual(entry["source"], "upsell")
        self.assertEqual(entry["occurred_at"], 1_000_000)
        self.assertEqual(entry["created_at"], 1_000_000)


class ItOnlyTouchesWhatAnnouncedItselfTests(unittest.TestCase):
    def test_an_order_without_the_marker_predates_this_and_is_left_alone(self):
        # Not a cutoff anyone has to maintain -- just the consequence of only correcting what said it was
        # uncorrected. The author has twice asked for existing data to stay as it is.
        legacy = order(fees={"stripe_fee": 82, "platform_fee": 89})
        repo = OrdersRepo([legacy])
        tally, calls = run(repo, actual={"stripe_fee": 109})
        self.assertEqual(calls, [], "Stripe must not even be asked about it")
        self.assertEqual(repo.rows["order_up_1"]["fees"], legacy["fees"])
        self.assertEqual(tally["examined"], 0)

    def test_an_already_settled_order_is_left_alone(self):
        repo = OrdersRepo([order(fees=dict(ESTIMATED, fees_source="balance_transaction"))])
        _, calls = run(repo, actual={"stripe_fee": 999})
        self.assertEqual(calls, [])

    def test_an_order_with_no_charge_to_look_up_is_skipped(self):
        # True of every upsell ever written before payment_intent_id was recorded.
        repo = OrdersRepo([order(pi="")])
        _, calls = run(repo, actual={"stripe_fee": 109})
        self.assertEqual(calls, [])

    def test_a_charge_too_young_to_have_settled_is_not_asked_yet(self):
        _, calls = run(OrdersRepo([order(created=1_000_000)]), actual={"stripe_fee": 109},
                       now=1_000_060)
        self.assertEqual(calls, [], "asking early only wastes a Stripe call; the next pass gets it")

    def test_a_charge_older_than_the_window_is_abandoned(self):
        # Still estimated after a week is a thing to look at, not to retry forever.
        _, calls = run(OrdersRepo([order(created=1_000_000)]), actual={"stripe_fee": 109},
                       now=1_000_000 + 8 * 24 * 3600)
        self.assertEqual(calls, [])


class OneBadOrderNeverStopsThePassTests(unittest.TestCase):
    def test_an_unsettled_charge_is_counted_and_retried_later(self):
        repo = OrdersRepo([order()])
        tally, _ = run(repo, actual={})
        self.assertEqual((tally["unsettled"], tally["corrected"]), (1, 0))
        # Left marked an estimate ON PURPOSE: that is what makes the next pass pick it up again.
        self.assertEqual(repo.rows["order_up_1"]["fees"]["fees_source"], "estimate")

    def test_a_partial_answer_is_not_mistaken_for_a_correction(self):
        # A balance transaction arrives `pending` with no fee_details; `{"net": ...}` is truthy and means
        # nothing. Testing the dict rather than the fee is the bug this whole thread was chasing.
        repo = OrdersRepo([order()])
        tally, _ = run(repo, actual={"net": 1615})
        self.assertEqual(tally["corrected"], 0)
        self.assertEqual(repo.rows["order_up_1"]["fees"]["stripe_fee"], 82)

    def test_one_tenants_broken_credentials_do_not_stop_another(self):
        class Broken(StripeRepo):
            def get(self, tenant_id, **_kwargs):
                if tenant_id == "t1":
                    raise RuntimeError("kms denied")
                return {"secret_key_ref": "ref_2"}

        repo = OrdersRepo([order("a", tenant="t1"), order("b", tenant="t2")])
        tally, _ = run(repo, actual={"stripe_fee": 109}, stripe_repo=Broken())
        self.assertEqual((tally["failed"], tally["corrected"]), (1, 1))
        self.assertEqual(repo.rows["b"]["fees"]["fees_source"], "balance_transaction")

    def test_a_tenant_with_no_usable_key_is_a_failure_not_a_crash(self):
        repo = OrdersRepo([order()])
        tally, _ = run(repo, actual={"stripe_fee": 109}, stripe_repo=StripeRepo(keys={}))
        self.assertEqual(tally["failed"], 1)

    def test_a_stripe_outage_leaves_the_order_alone(self):
        def boom(pi, **kwargs):
            raise RuntimeError("stripe 503")

        repo = OrdersRepo([order()])
        tally, _ = run(repo, fetch=boom)
        self.assertEqual(tally["failed"], 1)
        self.assertEqual(repo.rows["order_up_1"]["fees"], ESTIMATED)

    def test_credentials_are_resolved_once_per_tenant(self):
        class Counting(StripeRepo):
            def __init__(self):
                super().__init__()
                self.reads = 0

            def get(self, tenant_id, **_kwargs):
                self.reads += 1
                return super().get(tenant_id)

        repo = OrdersRepo([order("a", pi="pi_a"), order("b", pi="pi_b"), order("c", pi="pi_c")])
        counting = Counting()
        run(repo, actual={"stripe_fee": 109}, stripe_repo=counting)
        self.assertEqual(counting.reads, 1, "a Secrets Manager read + KMS decrypt per order is waste")


class TheRealFunnelTests(unittest.TestCase):
    """The numbers that prompted this, replayed through the sweep."""

    def test_the_canadian_visa_drift_is_recovered(self):
        rows = [order("upsell_1", pi="pi_1",
                      fees={"tenant_keyed_amount": 900, "stripe_fee": 57, "platform_fee": 45,
                            "net_payout": 798, "fees_source": "estimate"}),
                order("upsell_2", pi="pi_2",
                      fees={"tenant_keyed_amount": 1786, "stripe_fee": 82, "platform_fee": 89,
                            "net_payout": 1615, "fees_source": "estimate"})]
        actual = {"pi_1": {"stripe_fee": 70}, "pi_2": {"stripe_fee": 109}}
        repo = OrdersRepo(rows)
        tally, _ = run(repo, fetch=lambda pi, **kw: dict(actual[pi]))
        self.assertEqual(tally["corrected"], 2)
        self.assertEqual(tally["drift_cents"], 13 + 27)


class TheDecisionIsPureTests(unittest.TestCase):
    """`due` is the whole selection rule, testable without a repository or a Stripe key."""

    def test_it_reads_like_the_four_conditions_it_is(self):
        row = order()
        self.assertTrue(due(row, 1_000_600))
        self.assertFalse(due(dict(row, fees={"stripe_fee": 1}), 1_000_600))
        self.assertFalse(due(dict(row, payment_intent_id=""), 1_000_600))
        self.assertFalse(due(row, 1_000_010))
        self.assertFalse(due(None, 1_000_600))


class TheSweepDrivesTheGENUINERepositoryTests(unittest.TestCase):
    """The doubles above implement the signature the sweep assumes, which is exactly how a repository
    mismatch hid once before in this codebase: 5381 tests passed while `put(tenant_id, record)` was being
    called on a repository whose `put` takes one argument. So this drives the real
    `TenantRangeRepository` over a stub boto3 table.

    `scan_type` is new on that class, and a sweep that cannot read the table does nothing and says
    nothing -- the most expensive kind of silence.
    """

    class StubTable:
        """Just enough boto3 Table to be scanned, including one page break."""

        def __init__(self, items):
            self.items = items
            self.scans = []

        def scan(self, **kwargs):
            self.scans.append(kwargs)
            start = kwargs.get("ExclusiveStartKey") or 0
            page = self.items[start:start + 1]
            out = {"Items": page}
            if start + 1 < len(self.items):
                out["LastEvaluatedKey"] = start + 1
            return out

        def put_item(self, Item=None, **_kwargs):
            self.items = [i for i in self.items if i.get("order_id") != Item.get("order_id")] + [Item]

    def _repo(self, items, mode="test"):
        from stripe_link.repositories.documents import TenantRangeRepository

        table = self.StubTable(items)
        return TenantRangeRepository("jb-orders-dev", id_field="order_id", table=table, mode=mode), table

    def test_scan_type_reads_every_page(self):
        repo, table = self._repo([order("a", pi="pi_a"), order("b", pi="pi_b"), order("c", pi="pi_c")])
        self.assertEqual(sorted(o["order_id"] for o in repo.scan_type()), ["a", "b", "c"])
        self.assertEqual(len(table.scans), 3, "it must follow LastEvaluatedKey, not read one page")

    def test_it_filters_by_mode_on_the_server(self):
        # Not in Python afterwards: an unfiltered scan returns test money alongside real money, and this
        # sweep WRITES.
        repo, table = self._repo([order()])
        repo.scan_type()
        self.assertIn("FilterExpression", table.scans[0])

    def test_the_sweep_runs_end_to_end_against_it(self):
        repo, table = self._repo([order()])
        ledger = LedgerRepo()
        tally, _ = run(repo, ledger, actual={"stripe_fee": 109})
        self.assertEqual(tally["corrected"], 1)
        stored = [i for i in table.items if i["order_id"] == "order_up_1"][0]
        self.assertEqual(stored["fees"]["stripe_fee"], 109)
        self.assertEqual(stored["fees"]["fees_source"], "balance_transaction")

    def test_the_real_put_takes_one_argument(self):
        # The exact shape of the earlier mismatch, asserted rather than assumed.
        import inspect

        from stripe_link.repositories.documents import TenantRangeRepository

        params = list(inspect.signature(TenantRangeRepository.put).parameters)
        self.assertEqual(params, ["self", "document"])


class TheScheduleReachesTheSweepTests(unittest.TestCase):
    """The sweep shares the webhook's Lambda rather than owning one, for two reasons: the stack is at
    CloudFormation's 1MB SAM-transform limit and a new function does not fit, and this is the right home
    anyway -- the sweep does exactly what that handler does to every other sale, for the one sale path no
    webhook follows. It also means the webhook already holds every permission the sweep needs.

    The cost of sharing is a dispatch, and a dispatch is a thing that can silently stop working: an
    EventBridge event has no `httpMethod`, so a webhook handler that reads one first answers 405 to the
    schedule and the sweep simply never runs. Nothing would fail; it would just stop reconciling.
    """

    SOURCE = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "src" / "handlers" / "stripe_webhook.py").read_text()
    TEMPLATE = (__import__("pathlib").Path(__file__).resolve().parents[1] / "template.yaml").read_text()

    def test_a_scheduled_event_is_answered_before_any_http_check(self):
        body = self.SOURCE.split("\ndef handler(", 1)[1]
        self.assertLess(body.index('"aws.events"'), body.index('event.get("httpMethod"'),
                        "an EventBridge event has no httpMethod; reading one first answers it 405")

    def test_it_dispatches_to_the_sweep(self):
        block = self.SOURCE.split('"aws.events"', 1)[1][:400]
        self.assertIn("from handlers.fee_reconciliation import handler as reconcile_fees", block)
        self.assertIn("return reconcile_fees(event, context)", block)

    def test_a_scheduled_event_really_routes_through(self):
        import handlers.stripe_webhook as webhook_module

        called = {}

        import handlers.fee_reconciliation as sweep_module

        def fake(event, context, **_kwargs):
            called["event"] = event
            return {"ok": 1}

        real = sweep_module.handler
        sweep_module.handler = fake
        try:
            out = webhook_module.handler({"source": "aws.events", "detail-type": "Scheduled Event"}, None)
        finally:
            sweep_module.handler = real
        self.assertEqual(called["event"]["detail-type"], "Scheduled Event")
        self.assertEqual(out, {"ok": 1})

    def test_the_schedule_is_declared_on_that_function(self):
        block = self.TEMPLATE.split("StripeWebhookFunction:", 1)[1].split("\n  PlatformBillingWebhook", 1)[0]
        self.assertIn("FeeReconciliationSweep:", block)
        self.assertIn("rate(5 minutes)", block)

    def test_the_sweep_has_no_function_of_its_own(self):
        # If one is ever added back, this test is the reminder that the transform limit is why.
        self.assertNotIn("FeeReconciliationFunction", self.TEMPLATE)


class ThereIsNoEventAtTheRightMomentTests(unittest.TestCase):
    """Phase 2 was built and then deleted. This records why, so nobody rebuilds it.

    The plan called for an accelerator: correct the fee the instant Stripe says the charge succeeded,
    instead of waiting for the sweep. It was built on `payment_intent.succeeded` -- already subscribed on
    the Connect endpoint in both modes, and firing for both sale paths, so it looked ideal.

    **It never once succeeded.** The event arrives about a second after the charge; the balance
    transaction is not readable for 76-101s. Four invocations over four hours, every one logging
    `still unsettled at payment_intent.succeeded; leaving it to the sweep`, each having spent a Stripe
    call to learn nothing. That is the same race, and the same waste, as the three synchronous attempts
    inside the upsell handler deleted an hour earlier.

    There is no Stripe event at the right moment. `charge.updated` is no better -- it fires on metadata
    edits and other noise, not on settlement. The sweep is the whole answer, and that is not a gap in the
    design; it is what the measurement forces.

    Kept from the attempt, because both are right regardless:

    - `reconcile_order`, the shared primitive the sweep calls. Phase 2 is why it was extracted.
    - `metadata[order_id]` on the upsell's PaymentIntent -- free, and it makes a charge traceable to an
      order in the Stripe dashboard for refunds, disputes and support.
    """

    WEBHOOK = (__import__("pathlib").Path(__file__).resolve().parents[1]
               / "src" / "handlers" / "stripe_webhook.py").read_text()
    UPSELL = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "src" / "handlers" / "upsell.py").read_text()
    SWEEP = (__import__("pathlib").Path(__file__).resolve().parents[1]
             / "src" / "handlers" / "fee_reconciliation.py").read_text()

    def test_the_webhook_does_not_try_to_true_a_fee_on_payment_intent_succeeded(self):
        self.assertNotIn("payment_intent.succeeded", self.WEBHOOK)
        self.assertNotIn("reconcile_payment_intent_fees", self.WEBHOOK)

    def test_no_sale_path_asks_stripe_for_a_fee_it_cannot_have_yet(self):
        # The upsell handler, then the webhook. Both learned the same thing the expensive way.
        self.assertNotIn("fetch_actual_fees", self.UPSELL)
        self.assertNotIn("latest_charge.balance_transaction", self.UPSELL)

    def test_the_checkout_true_up_IS_still_there(self):
        """The one synchronous true-up that works, and the reason "delete them all" was not the right
        instruction: 8 of the last 9 main orders were trued at write time by this, at no extra call."""
        self.assertIn("true_up_fees(fee_breakdown_from_session", self.WEBHOOK)

    def test_the_shared_primitive_survives(self):
        self.assertIn("def reconcile_order(", self.SWEEP)
        self.assertIn("moved = reconcile_order(order", self.SWEEP)

    def test_the_order_id_on_the_paymentintent_survives(self):
        self.assertIn('pi_params["metadata[order_id]"] = order_id', self.UPSELL)


class TheGateIsSetByMeasurementTests(unittest.TestCase):
    """Two real upsell charges were polled until their balance transaction became readable: **92s and
    101s**, both on the same ten-second tick, so the true delay sits between roughly 82s and 101s
    (2026-10-04). That single number closed every open timing question in this work:

    - why no synchronous true-up could ever succeed — three attempts, all racing something ~90s away;
    - why `payment_intent.succeeded` is useless here, arriving about a second after the charge;
    - and why a fifteen-minute sweep was leaving an order wrong for up to fourteen minutes to fix
      something that had been ready in under two.

    The gate is 180s: the measurement plus room for a slower day. Tightening to 120 is the author's
    stated next step **once production measurements support it** — these were two test-mode charges, and
    the conservative direction is the cheap one. Asking early costs a wasted Stripe call; the next pass
    gets it anyway five minutes later.
    """

    def test_the_gate_clears_the_measured_delay_with_room(self):
        from stripe_link.domain.fee_reconciliation import MIN_AGE_SECONDS

        self.assertGreaterEqual(MIN_AGE_SECONDS, 101, "below the slowest charge actually measured")
        self.assertLessEqual(MIN_AGE_SECONDS, 300, "more caution than the evidence asks for")

    def test_a_charge_at_the_measured_delay_is_not_yet_asked_about(self):
        # 101s was readable, but only just, and on a test-mode charge. The gate deliberately sits past it.
        self.assertFalse(due(order(created=1_000_000), 1_000_101))

    def test_a_charge_past_the_gate_is(self):
        self.assertTrue(due(order(created=1_000_000), 1_000_181))

    def test_the_sweep_runs_often_enough_to_make_the_gate_the_limit(self):
        """A 5-minute cadence with a 180s gate corrects within ~3-8 minutes. A 15-minute cadence made the
        schedule the bottleneck rather than settlement, which is the wrong thing to be waiting on."""
        template = (__import__("pathlib").Path(__file__).resolve().parents[1] / "template.yaml").read_text()
        block = template.split("FeeReconciliationSweep:", 1)[1][:900]
        self.assertIn("rate(5 minutes)", block)


class TheSweepRecordsHowLongSettlementTookTests(unittest.TestCase):
    """Evidence for tightening the 180s gate to 120, which the author wants argued from production rather
    than from two test-mode charges.

    **The data is censored, and we are the ones censoring it.** The sweep only looks at orders older than
    `MIN_AGE_SECONDS`, so a charge that settled at 95s is first observed at 180s and recorded as 180.
    These lines prove "settled by N" and never "settled at N" -- they can justify LOOSENING the gate and
    cannot, on their own, justify tightening it.

    Which is why the unsettled case is logged too. An order still unreadable at N seconds is the only
    direct evidence of a FLOOR the sweep ever produces, and it is the opposite of the instinct to log
    successes.
    """

    def _logs(self, rows, actual, now):
        import logging

        from handlers import fee_reconciliation as module

        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler_ = Capture()
        module.logger.addHandler(handler_)
        try:
            tally = module.handler({}, None, orders_repo=OrdersRepo(rows), ledger_repo=LedgerRepo(),
                                   stripe_repo=StripeRepo(), secret_cipher=Cipher(),
                                   fetch_fees=lambda pi, **kw: dict(actual.get(pi) or {}),
                                   now_fn=lambda: now, modes=("test",))
        finally:
            module.logger.removeHandler(handler_)
        return tally["test"], records

    def test_a_correction_records_the_age_at_which_it_proved_readable(self):
        tally, logs = self._logs([order("a", pi="pi_a", created=1_000_000)],
                                 {"pi_a": {"stripe_fee": 109}}, 1_000_400)
        self.assertIn("fee settle: order=a age=400s readable drift=+27c", logs)
        self.assertEqual((tally["settled_age_min"], tally["settled_age_max"]), (400, 400))

    def test_an_unsettled_charge_records_a_FLOOR(self):
        # The only direct evidence the sweep produces about how long settlement really takes.
        _, logs = self._logs([order("b", pi="pi_b", created=1_000_000)], {}, 1_000_400)
        self.assertIn("fee settle: order=b age=400s NOT YET readable", logs)

    def test_the_tally_spans_the_ages_it_saw(self):
        rows = [order("a", pi="pi_a", created=1_000_000), order("c", pi="pi_c", created=1_000_200)]
        tally, _ = self._logs(rows, {"pi_a": {"stripe_fee": 109}, "pi_c": {"stripe_fee": 95}}, 1_000_400)
        self.assertEqual((tally["settled_age_min"], tally["settled_age_max"]), (200, 400))

    def test_a_pass_that_corrected_nothing_claims_no_ages(self):
        tally, _ = self._logs([order("b", pi="pi_b", created=1_000_000)], {}, 1_000_400)
        self.assertNotIn("settled_age_min", tally)

    def test_the_censoring_is_written_down_where_a_reader_lands(self):
        # A number that cannot mean what it looks like needs its caveat in the module, not in a plan.
        from handlers.fee_reconciliation import _settle_evidence

        self.assertIn("censored", _settle_evidence.__doc__)
        self.assertIn("MIN_AGE_SECONDS", _settle_evidence.__doc__)
