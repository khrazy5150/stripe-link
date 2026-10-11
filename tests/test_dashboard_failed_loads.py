"""A request that did not come back is not the answer zero.

Every fetch in the dashboard store is best-effort, so one dead endpoint cannot blank the whole screen.
That is right. It was implemented as `.catch(() => ({ products: [] }))`, which is not: a failed request
rendered as a confident **0**, in the same typeface as the truth, under a label reading "Lifetime".

A tenant with a thousand products was one network blip from being told they had none. And after the
authorizer landed, an expired session made *every* private call fail at once — which is precisely the
shape that produced "No Stripe keys saved yet. Re-enter keys for this tenant." on a tenant whose keys
were fine (2026-10-11). Telling somebody to re-enter credentials they still have is worse than saying
nothing.

This is the third instance of the same rule in three days, which is why it is a test and not a note:

* revenue — `revenueKnown`, after the card summed gross while calling itself net;
* profit — `profit_known`, after it was revenue-minus-fees wearing the word profit;
* and now every remaining card.

No JS runner here, so these are static guards in the shape of the other dashboard tests.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = ROOT / "dashboard" / "src" / "stores" / "dashboard.js"
VIEW = ROOT / "dashboard" / "src" / "components" / "Dashboard.vue"


def source():
    return STORE.read_text(encoding="utf-8")


class AFailureIsRemembered(unittest.TestCase):
    def test_the_store_tracks_which_loads_failed(self):
        self.assertIn("failed: {}", source())
        self.assertIn("this.failed = failed", source())

    def test_no_fetch_still_swallows_into_an_empty_collection(self):
        """The exact shape of the bug. `catch(() => ({ products: [] }))` is indistinguishable, to every
        reader downstream, from a tenant who genuinely has none."""
        text = source()
        for forbidden in ("catch(() => ({ products: [] }))",
                          "catch(() => ({ customers: [] }))",
                          "catch(() => ({ invoices: [] }))",
                          "catch(() => ({ notifications: [] }))"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_failure_is_recorded_per_endpoint(self):
        """One shared flag would blank four cards because one of them failed."""
        self.assertIn('attempt("products"', source())
        self.assertIn('attempt("customers"', source())
        self.assertIn('attempt("ledger"', source())

    def test_a_failed_ledger_is_null_rather_than_empty(self):
        """`attempt` resolves to {} on failure, and `revenueKnown` keys on null -- so without this an
        unreachable ledger would read as a ledger reporting $0.00."""
        self.assertIn("failed.ledger ? null :", source())


class TheCardsSayTheyDoNotKnow(unittest.TestCase):
    def test_customers_and_products_show_a_dash_not_a_zero(self):
        text = source()
        self.assertIn('state.failed.customers ? "—" :', text)
        self.assertIn('state.failed.products ? "—" :', text)

    def test_each_dash_carries_its_reason(self):
        """A dash alone reads as "nothing here", which is the same lie as the zero, only quieter."""
        text = source()
        self.assertIn("Could not load customers", text)
        self.assertIn("Could not load products", text)

    def test_the_reason_reaches_the_screen(self):
        view = VIEW.read_text(encoding="utf-8")
        self.assertIn("store.stats.customersMeta", view)
        self.assertIn("store.stats.productsMeta", view)

    def test_the_lifetime_label_survives_when_nothing_failed(self):
        """The normal case must keep its subtitle; a card that loses it on every healthy render has
        traded one wrong message for another."""
        view = VIEW.read_text(encoding="utf-8")
        self.assertIn("<template v-else>Lifetime &bull; {{ environmentLabel }}</template>", view)

    def test_the_orders_card_cannot_assert_zero_when_both_sources_failed(self):
        """Half the screen admitting it does not know, beside the other half asserting none, is the
        worst of the available answers."""
        self.assertIn('state.failed.invoices ? "—" : state.invoices.length', source())


class TheRuleIsAppliedEverywhere(unittest.TestCase):
    """Three cards learned this separately. The fourth should not have to."""

    def test_every_stats_value_has_an_unknown_state(self):
        text = source()
        start = text.index("stats(state) {")
        body = text[start:text.index("\n    },", start)]
        for measure in ("orders", "revenue", "customers", "products"):
            self.assertIn(f"{measure}:", body, measure)
        # Each of the four resolves to a dash on some path.
        self.assertGreaterEqual(body.count('"—"'), 4,
                                "every headline figure must be able to say it does not know")


if __name__ == "__main__":
    unittest.main()
