"""A return label is money out, and nothing recorded it.

`buy_return_label` has bought labels since returns shipped. It calls the same `mark_purchased`, writes
the same `cost` block, and pays the same carrier as the outbound path — and appended **no ledger entry at
all** (found 2026-10-11 while finishing P3 of `plans/MONEY_ACROSS_SILOS.md`). So a tenant who accepts
returns had their postage understated and their profit overstated by exactly their return-label spend.

It did not matter while `profit` was structurally wrong anyway: `cogs` had no supplier, so the figure was
revenue-minus-fees whatever postage did. P2 made profit a number a tenant reads, which is what turns this
from latent into wrong.

**The modelling question this slice had to answer.** A return label is recorded as `cost_adjustment`
against the `shipping_cost` component, not as a `shipping_cost` entry. The component says what KIND of
money it is — a dollar to a carrier is a dollar, and `profit` must count it. The entry type says WHY, and
`shipping_margin` answers one narrow question, *"did what I charge for postage cover what posting it
cost?"*. A return has no postage revenue beside it, so counting it there would show a tenant's outbound
pricing losing money because a buyer sent something back.
"""
import unittest

from stripe_link.domain.ledger import (return_shipping_cost_entry_from_shipment,
                                       shipping_cost_entry_from_shipment, summarize)

ORDER = {"tenant_id": "t1", "order_id": "order_x", "mode": "test", "currency": "usd"}
OUTBOUND = {"shipment_id": "shp_out", "cost": {"amount": 783, "currency": "usd"}, "purchased_at": 100}
RETURN = {"shipment_id": "shp_ret", "cost": {"amount": 650, "currency": "usd"}, "purchased_at": 200}


class TheEntryIsBuilt(unittest.TestCase):
    def test_a_return_label_produces_an_entry(self):
        entry = return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=300)
        self.assertEqual(entry["entry_type"], "cost_adjustment")
        self.assertEqual(entry["amounts"], {"shipping_cost": -650}, "an outflow, stored negative")
        self.assertEqual(entry["order_id"], "order_x")

    def test_it_is_described_so_a_tenant_can_read_the_row(self):
        """An unlabelled `cost_adjustment` in a ledger view is an unanswerable question."""
        entry = return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=300)
        self.assertEqual(entry["description"], "Return shipping label")

    def test_it_is_keyed_so_a_retry_cannot_double_count(self):
        first = return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=300)
        again = return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=999)
        self.assertEqual(first["entry_id"], again["entry_id"])
        self.assertEqual(first["idempotency_key"], again["idempotency_key"])

    def test_it_cannot_collide_with_the_outbound_label_for_the_same_order(self):
        """Under the outbound prefix the second write would REPLACE the first rather than adding to it,
        so an order with both labels would report only one of them."""
        same_id = {"shipment_id": "shp_1", "cost": {"amount": 500, "currency": "usd"}}
        outbound = shipping_cost_entry_from_shipment(same_id, ORDER, now_epoch=1)
        returned = return_shipping_cost_entry_from_shipment(same_id, ORDER, now_epoch=1)
        self.assertNotEqual(outbound["entry_id"], returned["entry_id"])
        self.assertNotEqual(outbound["idempotency_key"], returned["idempotency_key"])

    def test_a_label_with_no_cost_records_nothing(self):
        self.assertIsNone(
            return_shipping_cost_entry_from_shipment({"shipment_id": "s"}, ORDER, now_epoch=1))
        self.assertIsNone(
            return_shipping_cost_entry_from_shipment({"shipment_id": "s", "cost": {"amount": 0}},
                                                     ORDER, now_epoch=1))

    def test_the_mode_follows_the_order(self):
        live = return_shipping_cost_entry_from_shipment(RETURN, dict(ORDER, mode="live"), now_epoch=1)
        self.assertEqual(live["stripe_mode"], "live")
        self.assertEqual(
            return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=1)["stripe_mode"], "test")


class ProfitCountsItAndShippingMarginDoesNot(unittest.TestCase):
    SALE = {"entry_type": "sale", "cogs_known": True,
            "amounts": {"gross": 3291, "shipping_revenue": 900, "cogs": -650}}

    def _summary(self, *entries):
        return summarize([self.SALE, *entries])

    def test_shipping_margin_is_outbound_only(self):
        """900 charged, 783 paid to post it. The return is a different question."""
        summary = self._summary(
            shipping_cost_entry_from_shipment(OUTBOUND, ORDER, now_epoch=1),
            return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=1))
        self.assertEqual(summary["shipping_margin"], 900 - 783)

    def test_profit_counts_both_labels(self):
        summary = self._summary(
            shipping_cost_entry_from_shipment(OUTBOUND, ORDER, now_epoch=1),
            return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=1))
        self.assertEqual(summary["totals"]["shipping_cost"], -(783 + 650))
        self.assertEqual(summary["profit"], 3291 - 650 - 783 - 650)

    def test_the_return_cost_is_stated_on_its_own(self):
        """'My postage pricing is wrong' and 'returns are eating me' are different problems with
        different fixes, so the report must not blend them into one number."""
        summary = self._summary(
            shipping_cost_entry_from_shipment(OUTBOUND, ORDER, now_epoch=1),
            return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=1))
        self.assertEqual(summary["return_shipping_cost"], -650)
        self.assertEqual(summary["shipping_revenue_cost"], -783)

    def test_a_return_alone_does_not_invent_a_shipping_margin(self):
        """With no outbound label bought, there is still nothing to say about postage pricing."""
        summary = self._summary(return_shipping_cost_entry_from_shipment(RETURN, ORDER, now_epoch=1))
        self.assertIsNone(summary["shipping_margin"],
                          "a return must not make the outbound question answerable")
        self.assertEqual(summary["return_shipping_cost"], -650)

    def test_no_labels_at_all_leaves_margin_unknown(self):
        self.assertIsNone(self._summary()["shipping_margin"])
        self.assertEqual(self._summary()["return_shipping_cost"], 0)


class TheReturnPathActuallyCallsIt(unittest.TestCase):
    """The builder existing is not the fix. `shipping_cost` sat in AMOUNT_COMPONENTS with a builder and
    no writer once already, and this whole slice is the second instance of that same shape."""

    import pathlib as _pathlib
    SOURCE = (_pathlib.Path(__file__).resolve().parents[1]
              / "src/handlers/shipping.py").read_text(encoding="utf-8")

    def _function(self, name):
        start = self.SOURCE.index(f"def {name}(")
        rest = self.SOURCE[start:]
        end = rest.index("\ndef ", 1)
        return rest[:end]

    def test_buy_return_label_records_the_cost(self):
        self.assertIn("record_return_shipping_cost_entry(order, saved, now=now)",
                      self._function("buy_return_label"))

    def test_the_outbound_path_still_records_its_own(self):
        self.assertIn("record_shipping_cost_entry(order, saved, now=now)",
                      self._function("buy_label"))

    def test_the_two_writers_share_one_append(self):
        """Twenty lines of repository resolution and never-raise handling, twice, would drift on the
        LEDGER_TABLE guard or the promise not to turn a bought label into an error."""
        self.assertEqual(self.SOURCE.count("def _append_shipping_cost("), 1)
        for writer in ("record_shipping_cost_entry", "record_return_shipping_cost_entry"):
            self.assertIn("_append_shipping_cost(", self._function(writer), writer)

    def test_a_ledger_failure_cannot_fail_a_bought_label(self):
        body = self._function("_append_shipping_cost")
        self.assertIn("except Exception", body)
        self.assertIn("return False", body)


class TheWriterIsBestEffort(unittest.TestCase):
    def test_a_broken_repository_returns_false_rather_than_raising(self):
        from handlers.shipping import record_return_shipping_cost_entry

        class Broken:
            def append(self, entry):
                raise RuntimeError("DynamoDB is down")

        self.assertFalse(record_return_shipping_cost_entry(
            ORDER, RETURN, now=1, ledger_repo=Broken()))

    def test_a_real_repository_receives_the_entry(self):
        from handlers.shipping import record_return_shipping_cost_entry

        class Sink:
            def __init__(self):
                self.rows = []

            def append(self, entry):
                self.rows.append(entry)

        sink = Sink()
        self.assertTrue(record_return_shipping_cost_entry(ORDER, RETURN, now=1, ledger_repo=sink))
        self.assertEqual(sink.rows[0]["entry_type"], "cost_adjustment")
        self.assertEqual(sink.rows[0]["amounts"]["shipping_cost"], -650)

    def test_nothing_to_record_is_not_an_error(self):
        from handlers.shipping import record_return_shipping_cost_entry
        self.assertFalse(record_return_shipping_cost_entry(
            ORDER, {"shipment_id": "s"}, now=1, ledger_repo=object()))


if __name__ == "__main__":
    unittest.main()


class TheStatementSeparatesThem(unittest.TestCase):
    """Static guard, in the shape of the other dashboard guards (no JS test runner here).

    The "Shipping paid" row was `totals.shipping_cost`, which now holds BOTH labels, while being the row
    a tenant reads against "Shipping collected". Left alone it would have reported postage pricing losing
    money whenever a buyer sent something back.
    """

    import pathlib as _pathlib
    REPORTS = (_pathlib.Path(__file__).resolve().parents[1]
               / "dashboard/src/components/Reports.vue").read_text(encoding="utf-8")

    def test_shipping_paid_is_outbound_only(self):
        self.assertIn('pick: (s) => s.shipping_revenue_cost', self.REPORTS)
        self.assertNotIn('pick: (s) => (s.totals || {}).shipping_cost', self.REPORTS,
                         "the blended total must not be the row read against Shipping collected")

    def test_return_labels_have_their_own_row(self):
        self.assertIn('label: "Return labels"', self.REPORTS)
        self.assertIn("s.return_shipping_cost", self.REPORTS)

    def test_the_return_row_is_hidden_when_there_are_none(self):
        """A permanent zero row teaches a tenant to stop reading the statement."""
        self.assertIn("hide: (s) => !Number(s.return_shipping_cost", self.REPORTS)
        self.assertIn("line.hide && line.hide(now)", self.REPORTS)

    def test_the_note_says_it_is_outside_shipping_margin(self):
        self.assertIn("Not part of shipping margin", self.REPORTS)
