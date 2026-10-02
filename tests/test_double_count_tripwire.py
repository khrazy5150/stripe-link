"""The forbidden combination, and a tripwire so the rule gets a caller the day it can have one.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P3. `shipping_charges.smart_pricing_conflict` implements the
invariant from plans/SHIPPING_CHARGES.md:

    free    + cost line      = baked        (recovered in the price)
    free    + no cost line   = absorbed     (a loss leader, deliberately)
    charged + no cost line   = the buyer pays it
    charged + cost line      = DOUBLE-COUNTED   <- forbidden

It has tests and **no production caller**, which this session has now seen three times: `fees.fee_base`
let the platform charge a fee on postage in the books for weeks, `ledger` `cogs` still reports profit
without goods, and this one would let a buyer be charged twice for the same postage.

It cannot be wired yet: `cost_profile` does not exist on the Price (plans/SMART_PRICING.md build order
step 1 is unbuilt), so a caller today would read a field nothing can populate -- dead code pretending to
be a guard. **So the guard is this test.** The moment `cost_profile` becomes a real field, this fails
until the validator is actually called, which is the failure mode it exists to prevent.
"""
import pathlib
import unittest

from stripe_link.domain.shipping_charges import smart_pricing_conflict

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SHIPPING_LINE = {"lines": [{"label": "Shipping to customer", "kind": "fixed", "amount": 400}]}


def offer(options):
    return {"shipping": {"eligible": True, "options": options}}


class TheInvariantItselfTests(unittest.TestCase):
    def test_a_paid_baseline_beside_a_shipping_cost_line_is_refused(self):
        conflict = smart_pricing_conflict(offer([{"label": "Ground", "amount": 800}]), SHIPPING_LINE)
        self.assertTrue(conflict)

    def test_a_free_baseline_may_be_recovered_in_the_price(self):
        # "baked" -- the whole mechanism behind free shipping over a threshold.
        self.assertEqual(smart_pricing_conflict(offer([{"label": "Ground", "amount": 0}]), SHIPPING_LINE),
                         "")

    def test_a_paid_UPGRADE_above_a_free_baseline_is_fine(self):
        # "free ground, paid overnight" is an ordinary offer: the tenant absorbs the baseline and may
        # price it in, while the upgrade is pure buyer-paid revenue.
        clean = offer([{"label": "Ground", "amount": 0}, {"label": "Overnight", "amount": 2500}])
        self.assertEqual(smart_pricing_conflict(clean, SHIPPING_LINE), "")

    def test_no_cost_line_is_always_fine(self):
        self.assertEqual(smart_pricing_conflict(offer([{"label": "Ground", "amount": 800}]), {"lines": []}),
                         "")


class TheTripwireTests(unittest.TestCase):
    """Fails the day `cost_profile` becomes real and nothing calls the validator."""

    @staticmethod
    def _cost_profile_exists():
        for path in list(SRC.rglob("*.py")) + list((ROOT / "schemas").glob("*.json")):
            if path.name in ("shipping_charges.py",):
                continue  # the function's own parameter name, not a stored field
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "cost_profile" in text:
                return True, path
        return False, None

    @staticmethod
    def _has_caller():
        for path in SRC.rglob("*.py"):
            if path.name == "shipping_charges.py":
                continue
            if "smart_pricing_conflict" in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        return False

    def test_the_rule_is_enforced_as_soon_as_it_CAN_be(self):
        exists, where = self._cost_profile_exists()
        if not exists:
            self.skipTest("cost_profile is not a stored field yet (SMART_PRICING.md step 1 unbuilt); "
                          "a caller today would read a field nothing can populate")
        self.assertTrue(
            self._has_caller(),
            f"`cost_profile` is now stored ({where}), so `smart_pricing_conflict` must be CALLED "
            "somewhere in src/ -- a buyer charged twice for the same postage is the failure it prevents, "
            "and neither the price nor the shipping line looks wrong on its own.")

    def test_the_tripwire_can_actually_detect_a_caller(self):
        # Guards the guard: a detector that can never return True would skip forever and prove nothing.
        self.assertTrue(any("buyer_paid_shipping" in p.read_text(encoding="utf-8", errors="ignore")
                            for p in SRC.rglob("*.py") if p.name != "shipping_charges.py"),
                        "the search method itself is broken if it cannot find a known cross-module use")
