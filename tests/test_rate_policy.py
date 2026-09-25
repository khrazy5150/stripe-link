"""Which rate gets bought, decided once instead of per order.

plans/ORDER_FULFILMENT.md F3. The author's question was "where do tenants find the best shipping charge?"
The answer is that they should not hunt per order, because hunting is what makes a bulk flow impossible:
a saved policy picks one rate per row and shows its justification, and the dropdown handles the exceptions.
"""
import unittest

from stripe_link.domain.rate_policy import (
    common_services,
    normalize_policy,
    select_rate,
    sort_rates,
)

USPS = {"carrier": "USPS", "service": "Ground Advantage", "service_token": "usps_ground_advantage",
        "rate_id": "r1", "amount": 387, "estimated_days": 5, "attributes": ["CHEAPEST"]}
UPS = {"carrier": "UPS", "service": "Ground", "service_token": "ups_ground",
       "rate_id": "r2", "amount": 520, "estimated_days": 3, "attributes": ["BESTVALUE"]}
FEDEX = {"carrier": "FedEx", "service": "Standard Overnight", "service_token": "fedex_overnight",
         "rate_id": "r3", "amount": 4120, "estimated_days": 1, "attributes": ["FASTEST"]}
RATES = [UPS, FEDEX, USPS]  # deliberately unsorted


class PolicyDefaultTests(unittest.TestCase):
    def test_an_absent_policy_is_cheapest(self):
        self.assertEqual(normalize_policy(None)["prefer"], "cheapest")

    def test_a_malformed_policy_degrades_rather_than_raising(self):
        """A bad policy must not be able to stop a tenant seeing their rates; it falls back to the
        behaviour they had before a policy existed."""
        policy = normalize_policy({"prefer": "whatever", "max_transit_days": "soon",
                                   "max_auto_amount": -5})
        self.assertEqual(policy["prefer"], "cheapest")
        self.assertIsNone(policy["max_transit_days"])
        self.assertIsNone(policy["max_auto_amount"])


class SelectionTests(unittest.TestCase):
    def test_cheapest_by_default_and_it_says_so(self):
        result = select_rate(RATES, {})
        self.assertEqual(result["rate"]["rate_id"], "r1")
        self.assertEqual(result["reason"], "cheapest of 3")

    def test_fastest_picks_the_overnight(self):
        result = select_rate(RATES, {"prefer": "fastest"})
        self.assertEqual(result["rate"]["rate_id"], "r3")
        self.assertIn("1 day", result["reason"])
        self.assertNotIn("1 days", result["reason"])

    def test_best_value_honours_the_providers_own_tag(self):
        result = select_rate(RATES, {"prefer": "best_value"})
        self.assertEqual(result["rate"]["rate_id"], "r2")

    def test_a_delivery_promise_narrows_BEFORE_price_is_considered(self):
        """This is how a tenant who promised two-day delivery stops ground being chosen silently."""
        result = select_rate(RATES, {"max_transit_days": 3})
        self.assertEqual(result["rate"]["rate_id"], "r2")
        self.assertIn("within 3 days", result["reason"])
        self.assertIn("2 of 3", result["reason"])

    def test_an_impossible_promise_shows_everything_rather_than_nothing(self):
        """The tenant needs to SEE that their promise cannot be met, not an empty cell."""
        result = select_rate(RATES, {"max_transit_days": 0 or None})
        self.assertIsNotNone(result["rate"])
        result = select_rate([USPS], {"max_transit_days": 1})
        self.assertEqual(result["rate"]["rate_id"], "r1")

    def test_a_preferred_carrier_wins_when_it_is_close_on_price(self):
        result = select_rate(RATES, {"preferred_carrier": "UPS"})
        self.assertEqual(result["rate"]["rate_id"], "r2")
        self.assertIn("UPS preferred", result["reason"])
        self.assertIn("$1.33 more", result["reason"])

    def test_a_preferred_carrier_does_NOT_win_at_any_price(self):
        result = select_rate(RATES, {"preferred_carrier": "FedEx"})
        self.assertEqual(result["rate"]["rate_id"], "r1")

    def test_the_tolerance_is_configurable(self):
        result = select_rate(RATES, {"preferred_carrier": "FedEx", "preferred_carrier_tolerance": 100000})
        self.assertEqual(result["rate"]["rate_id"], "r3")

    def test_the_ceiling_WITHHOLDS_rather_than_hiding(self):
        """One click in a bulk flow spends money on twenty parcels. The rate is still shown -- the tenant
        just has to choose it themselves."""
        result = select_rate(RATES, {"prefer": "fastest", "max_auto_amount": 2500})
        self.assertTrue(result["withheld"])
        self.assertIsNotNone(result["rate"])
        self.assertIn("above your $25.00 limit", result["reason"])

    def test_the_ceiling_is_checked_against_what_was_actually_chosen(self):
        # Cheapest is under the ceiling, so nothing is withheld even though dearer rates exist.
        result = select_rate(RATES, {"max_auto_amount": 500})
        self.assertFalse(result["withheld"])
        self.assertEqual(result["rate"]["rate_id"], "r1")

    def test_no_rates_is_not_a_crash(self):
        result = select_rate([], {})
        self.assertIsNone(result["rate"])
        self.assertEqual(result["candidates"], [])

    def test_every_rate_comes_back_for_the_dropdown_in_policy_order(self):
        result = select_rate(RATES, {"prefer": "fastest"})
        self.assertEqual([r["rate_id"] for r in result["candidates"]], ["r3", "r2", "r1"])


class UnknownTransitTests(unittest.TestCase):
    """A rate with no transit estimate must not win a speed race: unknown is not fast."""

    def test_an_unknown_estimate_does_not_beat_a_known_one_on_fastest(self):
        mystery = {"carrier": "X", "service": "?", "rate_id": "rX", "amount": 100, "estimated_days": None}
        result = select_rate([mystery, FEDEX], {"prefer": "fastest"})
        self.assertEqual(result["rate"]["rate_id"], "r3")

    def test_but_it_still_wins_on_price(self):
        mystery = {"carrier": "X", "service": "?", "rate_id": "rX", "amount": 100, "estimated_days": None}
        result = select_rate([mystery, FEDEX], {})
        self.assertEqual(result["rate"]["rate_id"], "rX")


class CommonServiceTests(unittest.TestCase):
    """"Apply overnight to these twelve" is a trap when the service exists for eleven of them."""

    def test_only_services_every_order_shares(self):
        shared = common_services([[USPS, UPS], [USPS, FEDEX]])
        self.assertEqual([s["service_token"] for s in shared], ["usps_ground_advantage"])

    def test_nothing_in_common_is_an_empty_list_not_an_error(self):
        self.assertEqual(common_services([[USPS], [FEDEX]]), [])

    def test_no_selection_is_empty(self):
        self.assertEqual(common_services([]), [])


class SortStabilityTests(unittest.TestCase):
    def test_sorting_does_not_mutate_the_input(self):
        before = [r["rate_id"] for r in RATES]
        sort_rates(RATES, {"prefer": "fastest"})
        self.assertEqual([r["rate_id"] for r in RATES], before)


if __name__ == "__main__":
    unittest.main()
