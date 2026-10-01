"""The tenant's accounting: what they sold, what they charged to post it, and what each of those cost.

plans/LIVE_SHIPPING_RATES.md. Three faults made every report built on this ledger wrong, and all three
failed as ZEROS -- legitimate-looking values nobody could question by reading them:

1. `sale_entry_from_order` read `order["stripe_fee"]`; both webhook paths write `order["fees"]["stripe_fee"]`.
   So EVERY entry ever written recorded no fees, and `net` and `profit` both equalled `gross`.
2. Tax was never captured on the order at all, so `tax_liability` was structurally zero.
3. `shipping_cost` was in AMOUNT_COMPONENTS with no builder and no writer, so `shipping_margin` could only
   ever be None.

Pinned to the first real shipped dev order: $56.79 merchandise + $5.98 postage, Stripe fee $2.13 (estimate),
platform fee $2.84 on merchandise only.
"""
import unittest

from stripe_link.domain.ledger import (
    AMOUNT_COMPONENTS,
    BREAKDOWN_COMPONENTS,
    sale_entry_from_order,
    shipping_cost_entry_from_shipment,
    summarize,
)

ORDER = {"tenant_id": "t1", "order_id": "o1", "payment_intent_id": "pi_1", "amount_total": 6277,
         "currency": "usd", "mode": "test", "shipping_amount": 598,
         "fees": {"stripe_fee": 213, "platform_fee": 284, "net_payout": 5780}}
SHIPMENT = {"shipment_id": "shp_1", "order_id": "o1", "purchased_at": 2,
            "cost": {"amount": 910, "currency": "usd"}}


def sale(**over):
    return sale_entry_from_order({**ORDER, **over}, now_epoch=1)


class FeesReachTheLedgerTests(unittest.TestCase):
    def test_fees_are_read_from_where_the_webhook_writes_them(self):
        amounts = sale()["amounts"]
        self.assertEqual(amounts["stripe_fee"], -213)
        self.assertEqual(amounts["platform_fee"], -284)

    def test_the_flat_shape_still_works_for_older_documents(self):
        legacy = {k: v for k, v in ORDER.items() if k != "fees"}
        amounts = sale_entry_from_order({**legacy, "stripe_fee": 213, "platform_fee": 284},
                                        now_epoch=1)["amounts"]
        self.assertEqual(amounts["platform_fee"], -284)

    def test_net_is_no_longer_just_gross(self):
        # The symptom: a report telling the tenant their costs were nothing.
        self.assertEqual(summarize([sale()])["net"], 6277 - 213 - 284)

    def test_a_missing_fee_block_is_still_zero_not_a_crash(self):
        bare = {k: v for k, v in ORDER.items() if k != "fees"}
        self.assertEqual(summarize([sale_entry_from_order(bare, now_epoch=1)])["net"], 6277)


class TaxIsALiabilityTests(unittest.TestCase):
    def test_collected_tax_is_recorded_as_a_liability_not_income(self):
        entry = sale(tax_amount=450)
        self.assertEqual(entry["amounts"]["tax"], 450)
        summary = summarize([entry])
        self.assertEqual(summary["tax_liability"], 450)
        # Held, not earned: it comes straight back out of profit.
        self.assertEqual(summary["profit"], summary["net"] - 450)

    def test_no_tax_is_still_zero(self):
        self.assertEqual(summarize([sale()])["tax_liability"], 0)

    def test_the_webhook_captures_it_from_both_paths(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src/handlers/stripe_webhook.py").read_text(encoding="utf-8")
        self.assertIn('"tax_amount": int((session.get("total_details") or {}).get("amount_tax") or 0)',
                      source)
        self.assertIn('"tax_amount": int(invoice.get("tax") or 0)', source)


class ShippingMarginTests(unittest.TestCase):
    def test_the_carrier_cost_is_its_own_append_only_entry(self):
        # The label is bought AFTER the sale -- sometimes days after. Editing the sale would mean a
        # financial row that changes after the fact.
        entry = shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2)
        self.assertEqual(entry["entry_type"], "shipping_cost")
        self.assertEqual(entry["amounts"]["shipping_cost"], -910)
        self.assertEqual(entry["order_id"], "o1")

    def test_it_is_keyed_on_the_shipment_so_a_retry_cannot_double_count(self):
        a = shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2)
        b = shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=9)
        self.assertEqual(a["entry_id"], b["entry_id"])
        self.assertEqual(a["idempotency_key"], b["idempotency_key"])

    def test_an_unbought_label_records_nothing(self):
        self.assertIsNone(shipping_cost_entry_from_shipment({"shipment_id": "s"}, ORDER, now_epoch=2))

    def test_margin_is_real_once_both_halves_exist(self):
        # Charged $5.98, label cost $9.10: this tenant is losing $3.12 a parcel, which is exactly the
        # thing they could not previously find out.
        summary = summarize([sale(), shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2)])
        self.assertEqual(summary["shipping_revenue"], 598)
        self.assertEqual(summary["shipping_cost"], -910)
        self.assertEqual(summary["shipping_margin"], -312)

    def test_margin_stays_None_while_the_cost_is_unknowable(self):
        # Never revenue + 0, which would publish a margin implying postage was free.
        self.assertIsNone(summarize([sale()])["shipping_margin"])

    def test_the_carrier_cost_comes_out_of_profit_but_not_out_of_net(self):
        # `net` is what Stripe pays out; postage is bought separately from the carrier.
        both = summarize([sale(), shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2)])
        self.assertEqual(both["net"], summarize([sale()])["net"])
        self.assertEqual(both["profit"], both["net"] - 910)


class SegregationTests(unittest.TestCase):
    def test_merchandise_and_shipping_are_reported_apart(self):
        summary = summarize([sale()])
        self.assertEqual(summary["merchandise_revenue"], 5679)
        self.assertEqual(summary["shipping_revenue"], 598)
        self.assertEqual(summary["merchandise_revenue"] + summary["shipping_revenue"],
                         summary["totals"]["gross"])

    def test_postage_is_never_counted_twice(self):
        # `shipping_revenue` is a PARTITION of gross, not an addition to it.
        self.assertNotIn("shipping_revenue", AMOUNT_COMPONENTS)
        self.assertIn("shipping_revenue", BREAKDOWN_COMPONENTS)
        with_ship = summarize([sale()])
        without = summarize([sale(shipping_amount=0)])
        self.assertEqual(with_ship["net"], without["net"])

    def test_a_digital_sale_reports_no_shipping_lines(self):
        summary = summarize([sale(shipping_amount=0)])
        self.assertEqual(summary["shipping_revenue"], 0)
        self.assertEqual(summary["merchandise_revenue"], 6277)
        self.assertIsNone(summary["shipping_margin"])

    def test_the_full_picture_for_one_shipped_order(self):
        summary = summarize([sale(tax_amount=0),
                             shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2)])
        self.assertEqual(
            {k: summary[k] for k in ("merchandise_revenue", "shipping_revenue", "shipping_cost",
                                     "shipping_margin", "net", "profit", "tax_liability")},
            {"merchandise_revenue": 5679, "shipping_revenue": 598, "shipping_cost": -910,
             "shipping_margin": -312, "net": 5780, "profit": 4870, "tax_liability": 0})


class TheLabelFlowWritesItTests(unittest.TestCase):
    def test_buying_a_label_appends_the_cost(self):
        from handlers.shipping import record_shipping_cost_entry

        class Repo:
            def __init__(self):
                self.rows = []

            def append(self, entry):
                self.rows.append(entry)

        repo = Repo()
        self.assertTrue(record_shipping_cost_entry(ORDER, SHIPMENT, now=2, ledger_repo=repo))
        self.assertEqual(repo.rows[0]["amounts"]["shipping_cost"], -910)

    def test_a_ledger_outage_never_fails_the_label(self):
        from handlers.shipping import record_shipping_cost_entry

        class Broken:
            def append(self, entry):
                raise RuntimeError("dynamo down")

        self.assertFalse(record_shipping_cost_entry(ORDER, SHIPMENT, now=2, ledger_repo=Broken()))

    def test_the_function_is_granted_the_table_it_writes(self):
        import pathlib

        template = (pathlib.Path(__file__).resolve().parents[1]
                    / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  ShippingFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("!Ref LedgerTable", block)


class RefundsSegregateTooTests(unittest.TestCase):
    """A refund that reverses `gross` but not `shipping_revenue` leaves the postage standing, and shipping
    margin overstated for every refunded order that had any."""

    def _refund_entry(self, refund_amount):
        import handlers.stripe_webhook as webhook

        captured = {}

        class Repo:
            def append(self, entry):
                captured["entry"] = entry

        webhook.record_refund_ledger_entry(
            Repo(), tenant_id="t1", order=ORDER, refund={"id": "re_1", "amount": refund_amount},
            payment_intent="pi_1", charge_id="ch_1", now=5)
        return captured.get("entry")

    def test_a_full_refund_takes_the_postage_back_with_it(self):
        entry = self._refund_entry(6277)
        self.assertEqual(entry["amounts"]["gross"], -6277)
        self.assertEqual(entry["amounts"]["shipping_revenue"], -598)

    def test_a_fully_refunded_order_leaves_no_shipping_revenue_standing(self):
        summary = summarize([sale(), self._refund_entry(6277)])
        self.assertEqual(summary["shipping_revenue"], 0)
        self.assertEqual(summary["merchandise_revenue"], 0)
        self.assertEqual(summary["totals"]["gross"], 0)

    def test_a_partial_refund_reverses_no_postage(self):
        # It cannot be attributed between goods and postage from the amount alone. Visibly incomplete
        # beats quietly wrong.
        entry = self._refund_entry(1000)
        self.assertEqual(entry["amounts"]["gross"], -1000)
        self.assertNotIn("shipping_revenue", entry["amounts"])

    def test_the_carrier_cost_is_not_reversed_by_a_refund(self):
        # The label was bought and the postage is spent, whatever the buyer got back.
        summary = summarize([sale(),
                             shipping_cost_entry_from_shipment(SHIPMENT, ORDER, now_epoch=2),
                             self._refund_entry(6277)])
        self.assertEqual(summary["shipping_cost"], -910)
