"""The Dashboard's revenue card reads the LEDGER, not the orders table.

It used to sum `amounts.amount_paid` across orders, which made it **gross** and blind to **refunds**
while the card was titled "Net Revenue". Measured 2026-10-09 on real live data: four $1.45 sales, two of
them fully refunded, displayed as **$5.80**. The ledger said **$1.14** and agreed with Stripe's own Net
volume to the penny.

The ledger already nets Stripe's fee and the platform fee and carries refunds as negative entries, and
`Reports.vue` has always read it. The Dashboard was deriving a second, worse answer from a different
source — the kind of divergence that makes a tenant distrust both numbers.

There is no JS test runner in this repo, so this guards the source the way the rendered-island tests do.
A real unit test would be better; a static guard is better than nothing and costs no toolchain.
"""
import pathlib
import re
import unittest

STORE = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "stores" / "dashboard.js"


def source():
    return STORE.read_text()


class RevenueComesFromTheLedger(unittest.TestCase):
    def test_the_store_requests_the_ledger(self):
        self.assertIn('apiRequest("/ledger")', source(),
                      "the only source that nets fees and reverses refunds")

    def test_revenue_reads_the_ledger_summary(self):
        body = _getter("revenueCents")
        self.assertIn("ledger", body)
        self.assertIn("net", body)

    def test_revenue_does_not_sum_orders(self):
        """The exact shape of the bug: a reduce over invoices adding up amount_paid."""
        body = _getter("revenueCents")
        for forbidden in ("amount_paid", "paidInvoices", "invoices", "reduce"):
            self.assertNotIn(forbidden, body,
                             f"revenue must not be derived from orders ({forbidden!r})")

    def test_the_orders_based_getter_is_gone_entirely(self):
        """Leaving it would imply orders are still a revenue source for someone to reach for."""
        self.assertNotIn("paidInvoices", source())


class TheCardSaysWhichFigureItIs(unittest.TestCase):
    """Gross, net-of-fees, and net-of-fees-and-refunds are three different numbers a tenant cares about.
    The old subtitle named a SOURCE ("From paid invoices") while the title claimed a measure it was not."""

    def test_the_subtitle_names_the_measure(self):
        """Two branches, because naming the refunded amount is only honest when there is one."""
        text = source()
        self.assertIn("After Stripe and platform fees", text)   # nothing refunded
        self.assertIn("refunded", text)                          # something was
        self.assertNotIn("From paid invoices", text,
                         "the old subtitle named a SOURCE while the title claimed a measure")

    def test_a_failed_ledger_load_is_not_shown_as_zero(self):
        """Every load here is best-effort. A silent 0 reads as "you have made no money" rather than
        "we could not ask", which is a worse lie than the one being fixed."""
        text = source()
        self.assertIn("revenueKnown", text)
        self.assertIn("Could not load the ledger", text)


def _getter(name):
    """The body of a Pinia getter, so an assertion cannot be satisfied by a comment elsewhere."""
    text = source()
    start = text.index(f"{name}()")
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError(f"could not find the body of {name}")


class TheGuardCanFail(unittest.TestCase):
    def test_extracting_a_getter_body_really_works(self):
        body = _getter("revenueCents")
        self.assertTrue(body.startswith("{") and body.endswith("}"), body[:60])
        self.assertLess(len(body), 400, "this should be the getter, not half the file")


class TheOrdersCardIsOnTheSameBasisAsRevenue(unittest.TestCase):
    """Four orders producing $1.14 read as a bug, because revenue was net of refunds and the order
    count was not. Nothing on screen reconciled them.

    Subtracting alone does not fix it: two standing orders out of four would imply 2 × $1.01 = $2.02,
    and the real figure is $1.14 — short by the 88¢ of fees the two refunds destroyed and never
    returned. No order count divides cleanly into net revenue once a refund exists. The only honest
    display names both numbers.
    """

    def test_the_count_comes_from_the_same_ledger_as_revenue(self):
        body = _getter("saleCount") + _getter("refundCount")
        self.assertIn("ledger", body)
        self.assertNotIn("invoices", body, "the two cards must not be computed on different bases")

    def test_the_headline_is_orders_that_stand(self):
        self.assertIn("this.saleCount - this.refundCount", source())

    def test_the_refund_count_is_named_underneath(self):
        self.assertIn("refunded", source())
        self.assertIn("placed", source(), "the gross count is kept, not hidden")

    def test_the_refunded_amount_explains_the_revenue(self):
        """`net` is already net of refunds, so a reader cannot recover what went back by subtraction."""
        self.assertIn("refundedCents", source())
        self.assertIn("refunded", _getter("refundedCents"))


class TheLedgerStatesWhatWentBack(unittest.TestCase):
    def test_summarize_reports_a_refunded_total(self):
        from stripe_link.domain.ledger import summarize
        entries = [
            {"entry_type": "sale", "amounts": {"gross": 145, "stripe_fee": -34, "platform_fee": -10}},
            {"entry_type": "sale", "amounts": {"gross": 145, "stripe_fee": -34, "platform_fee": -10}},
            {"entry_type": "refund", "amounts": {"gross": -145}},
        ]
        summary = summarize(entries)
        self.assertEqual(summary["refunded"], 145, "the absolute amount that went back")
        self.assertEqual(summary["counts"], {"sale": 2, "refund": 1})
        self.assertEqual(summary["net"], 57, "202 earned, 145 returned")

    def test_it_is_zero_when_nothing_was_refunded(self):
        from stripe_link.domain.ledger import summarize
        self.assertEqual(summarize([{"entry_type": "sale", "amounts": {"gross": 145}}])["refunded"], 0)

    def test_the_real_numbers_from_2026_10_09(self):
        """Four $1.45 sales, two refunded. The card said $5.80; the truth is $1.14."""
        from stripe_link.domain.ledger import summarize
        sale = {"entry_type": "sale", "amounts": {"gross": 145, "stripe_fee": -34, "platform_fee": -10}}
        refund = {"entry_type": "refund", "amounts": {"gross": -145}}
        summary = summarize([sale] * 4 + [refund] * 2)
        self.assertEqual(summary["net"], 114)
        self.assertEqual(summary["refunded"], 290)
        self.assertEqual(summary["counts"]["sale"] - summary["counts"]["refund"], 2)
