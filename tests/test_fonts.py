"""Which typeface a page uses, and who decided it.

Published pages carried NO webfont until 2026-09-07 — every one fell back to whatever the visitor's device
happened to have, so a tenant's chosen typography never reached their customers. Presets now carry
pairings, and four levels resolve which family wins.
"""

import json
import pathlib
import unittest

from stripe_link.domain.fonts import (
    DEFAULT_PRESET,
    REQUEST_WEIGHTS,
    PAIRINGS,
    PRESET_PAIRINGS,
    SERVABLE_FAMILIES,
    families_to_load,
    pairing_for_preset,
    resolve_families,
)
from stripe_link.runtime import html
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS, font_vars, render_head_seo_tags

PRESET_PAGE = {"theme": {"preset": "midnight-luxe"}}


class PrecedenceTests(unittest.TestCase):
    """system fallback ← preset ← tenant default (behind the toggle) ← page override."""

    def test_a_preset_proposes_its_pairing(self):
        self.assertEqual(resolve_families(PRESET_PAGE), {"heading": "Raleway", "body": "Lato"})

    def test_a_tenant_default_does_nothing_without_the_toggle(self):
        """The toggle is the load-bearing half. Without it, idly picking a font in preferences would
        silently re-typeset every page the tenant has ever published."""
        prefs = {"fonts": {"heading": "Oswald"}}
        self.assertEqual(resolve_families(PRESET_PAGE, prefs)["heading"], "Raleway")

    def test_a_tenant_default_applies_when_the_toggle_is_on(self):
        prefs = {"fonts": {"override_presets": True, "heading": "Oswald"}}
        self.assertEqual(resolve_families(PRESET_PAGE, prefs)["heading"], "Oswald")

    def test_a_page_override_beats_the_tenant_default(self):
        # A house style should not have to be switched off to make one page different.
        page = {"theme": {"preset": "midnight-luxe", "fonts": {"heading": {"family": "Montserrat"}}}}
        prefs = {"fonts": {"override_presets": True, "heading": "Oswald"}}
        self.assertEqual(resolve_families(page, prefs)["heading"], "Montserrat")

    def test_an_explicit_system_choice_beats_the_preset(self):
        page = {"theme": {"preset": "fire-sale", "fonts": {"body": {"family": "system"}}}}
        self.assertEqual(resolve_families(page)["body"], "system")
        self.assertNotIn("system", families_to_load(page), "system must never be requested from the CDN")


class ServabilityTests(unittest.TestCase):
    def test_only_verified_families_are_requested(self):
        """A family the service cannot serve produces CSS pointing at a 404 — worse than no webfont."""
        page = {"theme": {"preset": "clean-slate", "fonts": {"heading": {"family": "Inter Tight"}}}}
        self.assertNotIn("Inter Tight", families_to_load(page))

    def test_but_an_unservable_choice_still_reaches_the_css(self):
        """Dropping it from the STACK would silently replace the tenant's explicit choice with the
        preset's. The visitor may have the font locally; if not, the fallback applies."""
        page = {"theme": {"preset": "clean-slate", "fonts": {"heading": {"family": "Inter Tight"}}}}
        self.assertEqual(resolve_families(page)["heading"], "Inter Tight")

    def test_every_pairing_uses_only_servable_families(self):
        for name, pairing in PAIRINGS.items():
            for role, family in pairing.items():
                with self.subTest(pairing=name, role=role):
                    self.assertIn(family, SERVABLE_FAMILIES)

    def test_every_colour_preset_has_a_pairing(self):
        # A preset without one would fall back silently and look unstyled next to its siblings.
        for preset in UNIVERSAL_BUNDLE_THEME_PRESETS:
            with self.subTest(preset=preset):
                self.assertIn(preset, PRESET_PAIRINGS)

    def test_every_named_pairing_exists(self):
        for preset, pairing in PRESET_PAIRINGS.items():
            with self.subTest(preset=preset):
                self.assertIn(pairing, PAIRINGS)

    def test_no_pairing_asks_for_three_families(self):
        # Every family is a download on a page tuned for LCP.
        for name, pairing in PAIRINGS.items():
            with self.subTest(pairing=name):
                self.assertLessEqual(len(set(pairing.values())), 2)


class WeightTests(unittest.TestCase):
    """A static family serves ONE weight unless the request names more.

    This is what broke the first time it shipped: the link asked for `family=Source Code Pro` and got
    weight 400 alone, so every heading — the template renders them at 600/700/800/900 — had no matching
    face and the browser synthesised or dropped the font. A variable family hid the bug, because it
    returns its whole range in a single file whatever is asked for.
    """

    def _head(self, page):
        return "\n".join(render_head_seo_tags(page, {"name": "X"}, {}, {}, "T", "D"))

    def test_the_request_names_weights(self):
        # Only meaningful while the page asks the service at render time. Referencing links pre-generated
        # files instead, and the weights are baked into them — guarded by the generator test below.
        if not html.FONT_EMBED:
            self.skipTest("referencing mode: weights live in the generated stylesheets")
        self.assertIn(f"Pro:{','.join(REQUEST_WEIGHTS)}", self._head({"theme": {"preset": "techno-green"}}))

    def test_every_family_in_the_url_carries_them(self):
        if not html.FONT_EMBED:
            self.skipTest("referencing mode: weights live in the generated stylesheets")
        head = self._head({"theme": {"preset": "techno-green"}})
        import re
        families = re.findall(r"family=([^&\"]+)", head)
        self.assertTrue(families)
        for family in families:
            with self.subTest(family=family):
                self.assertIn(":", family, "a family without weights serves 400 only")

    def test_the_generator_bakes_in_the_same_weights_we_would_have_requested(self):
        """The invariant moved, so the guard moves with it.

        In referencing mode nothing in the URL says 400,700 — the pre-generated stylesheets carry whichever
        faces fonts-api/tools/build_family_css.py chose. If that list drifts from REQUEST_WEIGHTS, a static
        family silently ships weight 400 alone and every heading is faux-bold: exactly the bug this class
        was written for, reappearing one layer down.
        """
        generator = pathlib.Path(__file__).resolve().parents[2] / "fonts-api" / "tools" / "build_family_css.py"
        if not generator.exists():
            self.skipTest(f"sibling repo not present at {generator}")
        import re as _re
        block = _re.search(r"^WEIGHTS = \[([^\]]*)\]", generator.read_text(encoding="utf-8"), _re.M)
        self.assertIsNotNone(block, "WEIGHTS not found in the generator")
        baked = {w.strip() for w in block.group(1).split(",") if w.strip()}
        self.assertEqual(baked, set(REQUEST_WEIGHTS),
                         "the generated stylesheets and REQUEST_WEIGHTS disagree about which faces ship")

    def test_body_and_bold_are_both_covered(self):
        # Body text is 400; the template's 600-900 headings all resolve to the 700 face.
        self.assertIn("400", REQUEST_WEIGHTS)
        self.assertIn("700", REQUEST_WEIGHTS)

    def test_it_stays_lean(self):
        # Each extra weight is another file for every static family on the page.
        self.assertLessEqual(len(REQUEST_WEIGHTS), 2)


class DefaultTests(unittest.TestCase):
    def test_the_font_default_matches_the_colour_default(self):
        """A page showing techno-green colours and modern type would mean the preset does not actually
        carry the visual identity, which is the entire claim presets make."""
        self.assertIn(DEFAULT_PRESET, UNIVERSAL_BUNDLE_THEME_PRESETS)
        self.assertEqual(pairing_for_preset(None), pairing_for_preset(DEFAULT_PRESET))

    def test_an_unknown_preset_falls_back_rather_than_failing(self):
        self.assertEqual(pairing_for_preset("no-such-preset"), pairing_for_preset(DEFAULT_PRESET))


class RenderTests(unittest.TestCase):
    def _head(self, page, preferences=None):
        return "\n".join(render_head_seo_tags(page, {"name": "X"}, {}, {}, "T", "D", preferences))

    def test_the_stylesheet_matches_whichever_mode_is_configured(self):
        """FONT_EMBED decides, and each setting has its own contract.

        Embedded (`fs=true`) puts the bytes in the stylesheet the SERVICE renders: one request, one host,
        no cross-origin font fetch. Referencing links PRE-GENERATED per-family stylesheets on the same
        origin as the font files -- static and edge-cached, where asking the service meant a Lambda on the
        critical path (`x-cache: Miss` every time, ~110ms in front of first paint).
        """
        head = self._head(PRESET_PAGE)
        if html.FONT_EMBED:
            self.assertIn("fonts.juniorbay.com/?family=", head)
            self.assertIn("fs=true", head)
            self.assertNotIn("/fonts/css/", head)
        else:
            self.assertIn("/fonts/css/", head)
            self.assertNotIn("?family=", head, "referencing must not call the service at render time")

    def test_a_preconnect_warms_the_origin_the_page_will_actually_use(self):
        head = self._head(PRESET_PAGE)
        expected = html.FONT_SERVICE_ORIGIN if html.FONT_EMBED else html.FONT_CSS_ORIGIN
        self.assertIn(f'rel="preconnect" href="{expected}"', head)

    def test_only_the_families_the_page_needs(self):
        head = self._head(PRESET_PAGE)
        if html.FONT_EMBED:
            self.assertIn("family=Lato", head)
            self.assertIn("family=Raleway", head)
            self.assertNotIn("family=Oswald", head)
        else:
            # One stylesheet per family, so a page carries links for its own two and nothing else.
            self.assertIn("/fonts/css/lato.css", head)
            self.assertIn("/fonts/css/raleway.css", head)
            self.assertNotIn("/fonts/css/oswald.css", head)

    def test_the_family_list_is_sorted_so_the_url_is_a_stable_cache_key(self):
        # Two orderings of one page would be two URLs and two downloads of the same fonts.
        self.assertEqual(families_to_load(PRESET_PAGE), sorted(families_to_load(PRESET_PAGE)))

    def test_a_system_fonts_page_links_nothing(self):
        page = {"theme": {"preset": "fire-sale", "fonts": {
            "heading": {"family": "system"}, "body": {"family": "system"}}}}
        self.assertNotIn("fonts.juniorbay.com", self._head(page))

    def test_the_resolved_family_reaches_the_css_variables(self):
        """Loading the stylesheet is half the job: without the family in the token the font downloads and
        nothing on the page ever asks for it."""
        css = font_vars(PRESET_PAGE)
        self.assertIn("--sl-font-heading:Raleway,", css)
        self.assertIn("--sl-font-body:Lato,", css)

    def test_a_fallback_always_follows_the_family(self):
        # A font that fails to arrive must degrade to something readable, not the browser's default serif.
        for token in font_vars(PRESET_PAGE).split(";"):
            with self.subTest(token=token.split(":")[0]):
                self.assertIn(",", token, "every font token needs a fallback behind it")

    def test_accent_follows_the_heading_unless_named(self):
        self.assertIn("--sl-font-accent:Raleway,", font_vars(PRESET_PAGE))
        page = {"theme": {"preset": "midnight-luxe", "fonts": {"accent": {"family": "Oswald"}}}}
        self.assertIn("--sl-font-accent:Oswald,", font_vars(page))


if __name__ == "__main__":
    unittest.main()
