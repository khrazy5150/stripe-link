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
        text = source()
        self.assertIn("After Stripe and platform fees, less refunds", text)
        self.assertNotIn("From paid invoices", text)

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
