"""Recent Orders reads the LEDGER, like the cards above it.

Reported 2026-10-11 from a screenshot: a tenant with **8 orders** saw, directly beneath a card reading
"Orders 8", a table headed "Recent Orders" whose only row said:

    No invoices | Backend returned 0 | -- | Create invoices to populate this table

Two defects in one row.

**The source was wrong.** `recentOrders` read `state.invoices` — the INVOICES module, tenant-issued
invoices, a different thing from orders entirely. This tenant has none, so the table was correctly empty
about the wrong question. It is the same shape as the revenue card that summed gross while calling itself
net (fixed 2026-10-09): a panel reading a different source than the number it sits under. The Orders
card, the Net Revenue card and this table now share one source and cannot disagree.

**The copy was debug output.** "Backend returned 0" is a sentence about our infrastructure, shown to
somebody who wants to know about their shop — and spread across a four-column grid it landed under the
CUSTOMER heading, so the screen appeared to name a customer called "Backend returned 0".

No JS runner here, so these are static guards in the shape of the other dashboard tests.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = ROOT / "dashboard" / "src" / "stores" / "dashboard.js"
VIEW = ROOT / "dashboard" / "src" / "components" / "Dashboard.vue"


def getter(name):
    """The body of a Pinia getter, so an assertion cannot be satisfied by a comment elsewhere."""
    text = STORE.read_text(encoding="utf-8")
    start = text.index(f"{name}(state) {{")
    depth, opened = 0, text.index("{", start + len(name))
    for index in range(opened, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opened:index + 1]
    raise AssertionError(f"could not find the body of {name}")


class ItReadsTheSameSourceAsTheCardsAboveIt(unittest.TestCase):
    def test_it_reads_the_ledger(self):
        self.assertIn("state.ledger?.entries", getter("recentOrders"))

    def test_it_does_not_read_invoices(self):
        """The whole defect. `invoices` is a different module and a different question."""
        self.assertNotIn("state.invoices", getter("recentOrders"))

    def test_it_shows_sales_not_every_ledger_row(self):
        """A refund, a shipping-cost row and a cost adjustment are all ledger entries and none of them is
        an order the buyer placed."""
        self.assertIn('entry.entry_type === "sale"', getter("recentOrders"))

    def test_it_sorts_on_the_ledgers_own_timestamp(self):
        """`created_at` is when the row was written; `occurred_at` is when the money moved. Sorting on
        the wrong one puts a backfilled entry at the top."""
        body = getter("recentOrders")
        self.assertIn("occurred_at", body)

    def test_the_amount_is_what_the_buyer_paid(self):
        """Gross. The fee-netted figure belongs on the revenue card, not on a line answering 'what did
        this person spend?'."""
        self.assertIn("entry.amounts?.gross", getter("recentOrders"))

    def test_the_orders_card_and_this_table_agree_on_their_source(self):
        text = STORE.read_text(encoding="utf-8")
        self.assertIn("this.ledger?.summary?.counts?.sale", text)
        self.assertIn("state.ledger?.entries", text)


class TheEmptyStateSpeaksToTheTenant(unittest.TestCase):
    def test_no_debug_output_remains(self):
        text = VIEW.read_text(encoding="utf-8")
        for phrase in ("Backend returned 0", "Fetching invoices", "Create invoices to populate"):
            self.assertNotIn(f">{phrase}<", text, phrase)

    def test_the_empty_state_is_about_orders(self):
        self.assertIn("No orders yet", VIEW.read_text(encoding="utf-8"))

    def test_a_failed_load_is_not_shown_as_an_empty_shop(self):
        """"No orders yet" to a tenant whose request failed is the silent-zero lie again, and this panel
        has now told it once."""
        text = VIEW.read_text(encoding="utf-8")
        self.assertIn("store.error", text)
        self.assertIn("couldn", text.lower())

    def test_the_message_spans_the_row_instead_of_filling_four_cells(self):
        """Four spans in a four-column grid is why "Backend returned 0" appeared under CUSTOMER."""
        self.assertIn("dashboard-table-note", VIEW.read_text(encoding="utf-8"))
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        note = css[css.index(".dashboard-table-note"):][:200]
        self.assertIn("grid-column: 1 / -1", note)

    def test_the_placeholder_rows_are_mutually_exclusive(self):
        """Loading, error and empty are one chain, or a failed load renders two rows."""
        text = VIEW.read_text(encoding="utf-8")
        # Anchored on the table's OWN markup. `store.loading && !store.loaded` also appears in a stats
        # card further up, and anchoring there matched a block with none of this in it.
        block = text[text.index('class="dashboard-table-row muted-row"'):][:1200]
        self.assertIn('v-else-if="store.error"', block)
        self.assertIn('v-else-if="!store.recentOrders.length"', block)


if __name__ == "__main__":
    unittest.main()
