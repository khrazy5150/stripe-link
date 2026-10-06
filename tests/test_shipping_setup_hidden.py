"""A buyer never sees a shipping section the TENANT has not finished setting up.

The author, 2026-10-06: *"I don't want the buyer to see the shipping element unless everything is set up
to collect shipping. The landing page must still work but assume free shipping in those cases."*

The distinction that makes this safe is between a failure the tenant must fix and one the carrier is
having. Both arrived as `needs: "carrier"`, which is why they could not be treated differently:

  - **setup** (no carrier connected, no ship-from address, an unreadable key) -- the buyer can do nothing
    about it, so the section stays hidden and the order posts free. The BUILDER is told instead.
  - **transient** (a carrier having a bad minute) -- still shown. Hiding it would silently ship a real
    order for nothing on the strength of a timeout.
"""
import unittest
from pathlib import Path

from handlers.shipping import is_setup_error


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
CHECKOUT = (ROOT / "src" / "handlers" / "checkout.py").read_text(encoding="utf-8")
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class WhoseProblemIsItTests(unittest.TestCase):
    def test_the_tenant_has_not_finished_setting_up(self):
        for error in ("no_provider", "no_ship_from", "key_unreadable: ClientError"):
            with self.subTest(error=error):
                self.assertTrue(is_setup_error(error))

    def test_a_carrier_having_a_bad_minute_is_not(self):
        """Hiding this would ship a real order for nothing on the strength of a timeout."""
        for error in ("ProviderError: carrier down", "timeout", "Hard: Invalid Destination Postal Code"):
            with self.subTest(error=error):
                self.assertFalse(is_setup_error(error))

    def test_an_absent_error_is_not_a_setup_problem(self):
        self.assertFalse(is_setup_error(""))
        self.assertFalse(is_setup_error(None))

    def test_a_prefix_match_does_not_swallow_an_unrelated_reason(self):
        """`no_provider` must not match `no_provider_support_in_region` or similar."""
        self.assertFalse(is_setup_error("no_provider_for_this_country"))


class TheQuoteSaysWhichTests(unittest.TestCase):
    def test_it_emits_setup_for_a_tenant_problem_and_carrier_otherwise(self):
        # The RATE-ERROR branch specifically. Splitting on the first `payload["needs"] =` finds the
        # unrelated no-zones assignment earlier in the function.
        branch = CHECKOUT.split('rated["error"]:', 1)[1].split("return json_response(payload)", 1)[0]
        self.assertIn("is_setup_error", branch)
        self.assertIn('"setup"', branch)
        self.assertIn('"carrier"', branch)

    def test_the_reason_still_travels_for_the_builder(self):
        """The buyer is told nothing, so the tenant has to be told precisely."""
        self.assertIn('payload["rate_error"] = rated["error"]', CHECKOUT)


class ThePageStaysQuietTests(unittest.TestCase):
    def test_the_island_hides_on_setup_as_it_does_on_zones(self):
        self.assertIn("data.needs === 'zones' || data.needs === 'setup'", HTML)

    def test_a_transient_carrier_failure_is_still_spoken(self):
        """The error message must survive -- this is the case that must NOT be hidden."""
        self.assertIn("We could not get shipping rates for this address right now.", HTML)

    def test_no_reason_string_is_ever_undefined(self):
        """`reasons[data.needs]` is painted at a buyer; a missing key would render as nothing useful."""
        reasons = HTML.split("var reasons = {", 1)[1].split("};", 1)[0]
        for key in ("country", "postal_code", "carrier", "services", "box_price", "zones", "setup"):
            with self.subTest(needs=key):
                self.assertIn(f"{key}:", reasons)


class TheBuilderIsToldInsteadTests(unittest.TestCase):
    def test_it_warns_on_setup_and_names_the_missing_piece(self):
        self.assertIn('quote.needs === "setup"', BUILDER)
        for reason in ("no_provider", "no_ship_from", "key_unreadable"):
            with self.subTest(reason=reason):
                self.assertIn(reason, BUILDER)

    def test_the_warning_states_the_cost_not_just_the_cause(self):
        """"Buyers will not see it" understates it: nothing is collected for postage on any order."""
        self.assertIn("ship with no postage collected", BUILDER)


if __name__ == "__main__":
    unittest.main()
