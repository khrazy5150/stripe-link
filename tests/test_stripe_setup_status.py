"""The Payments screen must not contradict the dashboard's own nudge.

Reported 2026-10-14 from prod: a sticky "Finish setting up Stripe" toast beside a green "Stripe keys
loaded." The toast was right — only the PUBLISHABLE keys were stored, and a publishable key cannot take a
payment. The message reported that the FETCH had succeeded, and sitting under two filled key fields it read
as "you are configured".
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = (ROOT / "dashboard" / "src" / "stores" / "stripeKeys.js").read_text(encoding="utf-8")
APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
SCREEN = (ROOT / "dashboard" / "src" / "components" / "StripeKeys.vue").read_text(encoding="utf-8")
STYLES = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")


class OneRuleNotThree(unittest.TestCase):
    """The screen, the nudge and the onboarding wizard all ask "is this mode set up?". They disagreed
    because only two of them asked the same way."""

    def test_the_gap_is_computed_from_modeConfigured(self):
        gap = STORE[STORE.index("setupGap() {"):STORE.index("resetForCurrentTenant")]
        self.assertIn("this.modeConfigured(mode)", gap)

    def test_the_nudge_still_uses_the_same_expression(self):
        self.assertIn("mode.saved_secret_key || mode.connect_status === \"connected\"", APP)

    def test_a_publishable_key_does_not_count_as_configured(self):
        """It is public and cannot take a payment — which is the whole misunderstanding."""
        configured = re.search(r"modeConfigured: \(state\) => \(mode\) => \{(.|\n)*?\}", STORE).group(0)
        self.assertNotIn("publishable", configured)


class ANudgeNeedsToKNOWBeforeItWarns(unittest.TestCase):
    """`modes` starts at its empty shape, which is indistinguishable from "nothing configured". A fetch
    that failed therefore looked exactly like an unconfigured tenant — and the nudge is STICKY, so one
    dropped request left a permanent "finish setting up Stripe" beside a Payments screen that loaded fine
    and said the opposite (reported 2026-10-14)."""

    def test_the_store_records_whether_it_actually_read_them(self):
        self.assertIn("loaded: false,", STORE)
        self.assertIn("this.loaded = true;", STORE)

    def test_it_is_cleared_before_each_attempt(self):
        """Otherwise a later failure keeps answering with the previous success."""
        load = STORE[STORE.index("async load() {"):STORE.index("async loadConnectCard")]
        self.assertIn("this.loaded = false;", load)
        self.assertLess(load.index("this.loaded = false;"), load.index("this.loaded = true;"))

    def test_only_a_successful_read_sets_it(self):
        """The catch branch must not claim knowledge it does not have."""
        load = STORE[STORE.index("async load() {"):STORE.index("async loadConnectCard")]
        catch = load[load.index("} catch (error) {"):]
        self.assertNotIn("this.loaded = true", catch)

    def test_the_nudge_waits_for_it(self):
        nudge = APP[APP.index("function maybeNudgeStripeSetup()"):][:900]
        self.assertIn("if (!stripeKeys.loaded) return;", nudge)
        self.assertLess(nudge.index("stripeKeys.loaded"), nudge.index("stripeKeys.modes"))


class TheMessageSaysWhatIsMissing(unittest.TestCase):
    def test_load_no_longer_claims_success_for_a_mere_fetch(self):
        self.assertNotIn('this.message = "Stripe keys loaded."', STORE)

    def test_load_names_the_modes_that_cannot_take_payments(self):
        self.assertIn('`Publishable keys loaded, but ${gap}`', STORE)

    def test_saving_only_publishable_keys_is_not_reported_as_done(self):
        """Their change DID land, so the confirmation stays — the gap is appended."""
        self.assertIn('`Keys saved, but ${gap}`', STORE)

    def test_a_configured_tenant_still_gets_a_plain_confirmation(self):
        self.assertIn('"Stripe is set up."', STORE)
        self.assertIn('"Stripe keys saved. Secrets are encrypted before persistence."', STORE)

    def test_the_gap_is_a_clause_not_a_sentence(self):
        """Returning a finished sentence made one caller read "Keys saved, but publishable keys loaded,
        but …" — each caller owns its own prefix."""
        gap = STORE[STORE.index("setupGap() {"):STORE.index("resetForCurrentTenant")]
        self.assertNotIn("Publishable keys loaded", gap)
        self.assertNotIn("Keys saved", gap)

    def test_it_pluralises(self):
        gap = STORE[STORE.index("setupGap() {"):STORE.index("resetForCurrentTenant")]
        self.assertIn("modes cannot", gap)
        self.assertIn("mode cannot", gap)


class ItUsesTheDangerStyle(unittest.TestCase):
    def test_an_unconfigured_tenant_gets_the_error_tone(self):
        """A half-configured Stripe is not a warning: that mode cannot take a payment at all."""
        self.assertIn('this.messageTone = gap ? "error" : "success";', STORE)
        self.assertEqual(STORE.count('this.messageTone = gap ? "error" : "success";'), 2,
                         "both the load and the save paths must agree")

    def test_the_banner_renders_the_tone(self):
        self.assertIn("['keys-status-banner', store.messageTone]", SCREEN)

    def test_the_danger_style_exists(self):
        self.assertIn(".keys-status-banner.error {", STYLES)


if __name__ == "__main__":
    unittest.main()
