"""The headline-highlight colours and saved themes, both missed in the migration.

The author, comparing stripe-cart's colour panel with stripe-link's: *"Stripe Link is missing the
emphasized text (anything within the double asteriks **) highlighted text (anything within the double
chevrons ^^) ... The legacy app also had the ability to save a custom preset."*

Both were half-migrated, in opposite directions:

* The highlight TOKENS existed and were rendered -- `.sl-mark-text` and `.sl-mark-bg` have read
  `--sl-highlight-*` since the markup shipped -- but no entry in `composition_rules.json`'s
  `token_catalog`, which is what the Appearance panel is generated from. A tenant could not reach them.
* Saved themes were the reverse: `user_preferences.landing_pages.custom_color_themes` is in the schema
  AND validated server-side with the legacy's own 10-theme cap, and NOTHING in the dashboard ever read
  or wrote it. A data model with no UI.

An audit while fixing this found 45 of 64 emitted tokens absent from the catalog. These are the ones
asked for; the rest are recorded in plans/ADVANCED_COLOR_SETTINGS.md.
"""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text())
CATALOG = RULES["token_catalog"]
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text()
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text()


class TheHighlightColoursAreReachable(unittest.TestCase):
    def test_all_three_are_in_the_catalog(self):
        for token in ("highlight_text", "highlight_bg", "highlight_bg_text"):
            with self.subTest(token=token):
                self.assertIn(token, CATALOG)

    def test_they_are_grouped_with_the_headline_they_modify(self):
        """`**text**` and `^^text^^` are markup INSIDE the headline, so that is where a tenant looks."""
        for token in ("highlight_text", "highlight_bg", "highlight_bg_text"):
            self.assertEqual(CATALOG[token]["group"], "Headline highlights")

    def test_the_labels_name_the_markup_not_the_token(self):
        """A tenant types `**bold**`, they do not type `highlight_text`."""
        self.assertIn("**", CATALOG["highlight_text"]["label"])
        self.assertIn("^^", CATALOG["highlight_bg"]["label"])
        self.assertIn("^^", CATALOG["highlight_bg_text"]["label"])

    def test_the_renderer_actually_reads_them(self):
        """A catalog entry for a token nothing renders would be a control that does nothing."""
        self.assertIn("--sl-highlight-text", HTML)
        self.assertIn("--sl-highlight-bg", HTML)
        self.assertIn("--sl-highlight-bg-text", HTML)

    def test_the_other_gradient_surface_is_reachable_too(self):
        """The countdown is the page's only other gradient, and was equally unreachable."""
        for token in ("countdown_bg", "countdown_end_bg", "countdown_text"):
            with self.subTest(token=token):
                self.assertEqual(CATALOG[token]["group"], "Countdown bar")


class EveryCatalogTokenIsReal(unittest.TestCase):
    """A catalog entry the renderer never emits is a control with no effect -- worse than a missing one,
    because the tenant watches it do nothing."""

    def test_each_catalog_token_is_emitted(self):
        from stripe_link.runtime.html import theme_tokens
        emitted = set(theme_tokens({"theme": {"preset": "techno-green"}}))
        for token in CATALOG:
            with self.subTest(token=token):
                self.assertIn(token, emitted)

    def test_the_catalog_is_still_short_of_the_full_set(self):
        """Recorded rather than asserted away: 45 of 64 tokens had no control when this was written, and
        this is the number to watch as the catalog is completed."""
        from stripe_link.runtime.html import theme_tokens
        emitted = set(theme_tokens({"theme": {"preset": "techno-green"}}))
        self.assertLess(len(CATALOG), len(emitted), "if the catalog is complete, delete this test")


class SavedThemesHaveTheirMissingHalf(unittest.TestCase):
    """The document shape was migrated and left unused. These guard the UI that now fills it."""

    def test_the_builder_reads_the_migrated_field(self):
        self.assertIn("custom_color_themes", BUILDER)

    def test_it_saves_and_deletes_through_preferences(self):
        self.assertIn('apiRequest("/preferences"', BUILDER)
        self.assertIn("writeSavedThemes", BUILDER)

    def test_it_respects_the_servers_own_cap(self):
        """The server refuses an 11th; saying so beats surfacing a 400."""
        self.assertIn("MAX_SAVED_THEMES = 10", BUILDER)

    def test_only_hex_is_saved(self):
        """Saved-theme tokens are validated as HEX specifically, stricter than a page, which accepts any
        CSS colour. Filtering means one `rgba()` does not refuse the whole save."""
        self.assertIn("hexTokensOnly", BUILDER)

    def test_applying_replaces_rather_than_merges(self):
        """A merge would leave the previous theme's colours behind, so "apply" would mean different
        things depending on what was already set."""
        self.assertIn("builder.theme_tokens = { ...(theme.tokens || {}) }", BUILDER)

    def test_the_server_cap_is_what_the_ui_claims(self):
        documents = (ROOT / "src" / "stripe_link" / "domain" / "documents.py").read_text()
        self.assertIn("at most 10 custom color themes", documents)


if __name__ == "__main__":
    unittest.main()
