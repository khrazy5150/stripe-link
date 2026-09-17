"""The "Go to URL" page — a bridge, given the same furniture as the click-to-call page.

Author, 2026-09-16: "equip that page with the same elements as the Click to Call page". They are the same
shape of page — no price, no form, one outbound action — so they had no business looking like two products.
What differs is the one line that identifies the destination: a phone number there, a hostname here.
"""
import json
import pathlib
import unittest

from stripe_link.domain.composition import default_visible, excluded_sections
from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)


def _render(target="https://www.opentable.com/r/lemon-thyme", kicker="", tone=None, label="Book a table",
            show_destination=True):
    section = {"id": "c", "type": "checkout_cta", "show_destination": show_destination}
    if kicker:
        section["kicker"] = kicker
    if tone:
        section["tone"] = tone
    return html_module.render_external_cta(
        {"type": "external", "label": label, "target": target}, section)


class DestinationTests(unittest.TestCase):
    """A bridge page asks someone to LEAVE. The question that earns the click is "leave for where?"."""

    def test_the_host_is_the_identifying_line(self):
        # A bare button never answered it; the full URL answers it in a form nobody reads.
        self.assertIn(">opentable.com<", _render())

    def test_www_is_dropped_from_the_LABEL_only(self):
        # Never from the href: the URL has to stay the URL. Only what the visitor reads is tidied.
        self.assertEqual(html_module.destination_label("https://www.opentable.com/r/x"), "opentable.com")
        self.assertIn('href="https://www.opentable.com/r/lemon-thyme"', _render())

    def test_a_file_path_is_still_just_a_host(self):
        """The label is ALWAYS the host now (author, 2026-09-17: a bridge button redirects, period).

        It briefly returned a filename when the path looked like one, which put "index.html" on a live
        advertorial in 4.4rem type.
        """
        self.assertEqual(html_module.destination_label("https://miniguardcam.com/index.html"),
                         "miniguardcam.com")
        self.assertEqual(html_module.destination_label("https://cdn.x.com/f/2026-price-list.pdf"), "cdn.x.com")

    def test_query_strings_and_fragments_do_not_leak_in(self):
        # An affiliate tag is not part of where you are going, and is not something to show a visitor.
        self.assertEqual(html_module.destination_label("https://shop.example.com/x?ref=aff123#top"),
                         "shop.example.com")

    def test_a_bare_host_survives(self):
        self.assertEqual(html_module.destination_label("opentable.com"), "opentable.com")

    def test_nothing_in_nothing_out(self):
        self.assertEqual(html_module.destination_label(""), "")
        self.assertNotIn("sl-cta-lead", _render(target=""))

    def test_the_line_is_suppressible_and_off_by_default_here(self):
        """The author, on seeing "index.html": "Either pick a better choice or remove it altogether."

        Both. The choice is fixed above; and a destination host answers "leave for where?" only when the host
        means something to the visitor -- a CDN hostname or an artifact URL is noise, and we cannot tell
        which from here. So the tenant decides, and the quiet default wins the tie.
        """
        self.assertNotIn("sl-cta-lead", _render(show_destination=None))
        self.assertNotIn("sl-cta-lead", _render(show_destination=False))
        self.assertIn("sl-cta-lead", _render(show_destination=True))

    def test_a_phone_number_still_shows_by_default(self):
        # It IS the call page; hiding it would leave a button with nothing to say.
        markup = html_module.render_call_cta(
            {"type": "call", "label": "Call Now", "target": "+12065654418"}, {})
        self.assertIn("sl-cta-lead", markup)

    def test_the_destination_is_itself_a_link(self):
        # On a page with one job the identifying detail should be clickable, not decorative.
        markup = _render()
        self.assertIn('class="sl-cta-lead" href="https://www.opentable.com/r/lemon-thyme"', markup)

    def test_it_opens_in_a_new_tab_safely(self):
        markup = _render()
        self.assertEqual(markup.count('rel="noopener noreferrer"'), 3)  # lead + panel button + sticky
        self.assertIn('target="_blank"', markup)


class SharedFurnitureTests(unittest.TestCase):
    """Same panel, same sticky bar, same tone, same kicker — one implementation."""

    def test_it_wears_the_shared_panel(self):
        self.assertIn("sl-cta-panel", _render())

    def test_it_has_the_sticky_bar(self):
        self.assertIn('data-cta-sticky="external"', _render())

    def test_it_takes_a_kicker(self):
        self.assertIn("No account needed", _render(kicker="No account needed"))

    def test_it_takes_the_shared_tone(self):
        self.assertIn("sl-cta-panel sl-tone-accent", _render(tone="accent"))
        self.assertIn("sl-cta-panel sl-tone-contrast", _render())

    def test_one_panel_implementation_serves_both(self):
        runtime = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        self.assertEqual(runtime.count("def render_cta_panel("), 1)
        for fn in ("render_call_cta", "render_external_cta"):
            body = runtime.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
            self.assertIn("render_cta_panel(", body, fn)
        # ...and the third caller is gone with the type it served.
        self.assertNotIn("def render_download_cta(", runtime)

    def test_the_offer_never_produces_a_download_cta_again(self):
        offers = (ROOT / "dashboard" / "src" / "components" / "Offers.vue").read_text(encoding="utf-8")
        contract = offers.split("function primaryCtaContract", 1)[1].split("\n}", 1)[0]
        self.assertNotIn('type: "download"', contract)
        self.assertIn('return { type: "external", label: "Learn More", target };', contract)

    def test_the_builder_offers_the_controls_for_every_panelled_cta(self):
        self.assertIn('const PANEL_CTA_TYPES = ["call", "external"];', BUILDER)
        self.assertIn("PANEL_CTA_TYPES.includes(builderCta.type)", BUILDER)


class BridgeCompositionTests(unittest.TestCase):
    def test_trust_badges_are_on_by_default(self):
        self.assertTrue(default_visible("lead_bridge", "trust_badges"))

    def test_a_hero_image_is_ON_by_default(self):
        """Reversed 2026-09-16 after the author saw a real advertorial.

        The old rule was "a bridge page that loads a hero image is a slower bridge" -- a sound argument that
        lost to a stronger one: a page that looks unfinished does not get the click it was optimised to
        deliver quickly. The reversal is recorded in the rules file rather than the old reason being deleted,
        so the trade-off is still legible.
        """
        self.assertTrue(default_visible("lead_bridge", "hero_media"))
        rules = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
        comment = rules["offer_types"]["lead_bridge"]["_comment"]
        self.assertIn("REVERSING", comment)
        self.assertIn("slower bridge", comment)

    def test_nothing_that_takes_money_is_allowed(self):
        for key in ("offer_price_selector", "price_highlight", "refund_policy", "tip_jar"):
            self.assertIn(key, excluded_sections("lead_bridge"), key)


if __name__ == "__main__":
    unittest.main()
