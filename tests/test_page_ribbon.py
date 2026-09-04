"""Page Ribbon — the first presentation of the Attention Block (plans/ATTENTION_PRIMITIVE.md §4a).

A mid-scroll interruption that ASKS for something. Not a content_block: a content block informs, a ribbon
acts — the same reason checkout_cta is its own element rather than a styled paragraph.

Static only, and deliberately so. Ten of the plan's twelve uses need no per-visitor state, and pages are
rendered ONCE at publish time and served as bytes from S3, so anything that varies by visitor needs
client-side hydration — a separate project (A-P3), not something to half-build here.
"""

import unittest

from stripe_link.domain.section_theme import DARK_INK, LIGHT_INK
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_page_ribbon, safe_href

CSS = "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
RIBBON = {
    "id": "rb",
    "eyebrow": "Limited time",
    "headline": "Get your benefits back",
    "body": "Return to ad-free videos and downloads.",
    "image_url": "https://img/p.png",
    "cta": {"label": "Reactivate now", "action": "redirect", "target": "https://example.com/x"},
}


class SafeHrefTests(unittest.TestCase):
    """The link is typed by a tenant, so the scheme is an injection surface."""

    def test_script_schemes_are_refused(self):
        for bad in ("javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<script>x</script>",
                    "vbscript:x", " javascript:alert(1)"):
            with self.subTest(bad=bad):
                self.assertEqual(safe_href(bad), "")

    def test_protocol_relative_is_refused(self):
        # //evil.com inherits the page's scheme and reads like a path at a glance.
        self.assertEqual(safe_href("//evil.com/x"), "")

    def test_navigable_schemes_and_same_origin_paths_pass(self):
        for good in ("https://example.com", "http://example.com", "mailto:a@b.co", "tel:+15550101234", "/another-page"):
            with self.subTest(good=good):
                self.assertEqual(safe_href(good), good)

    def test_a_refused_link_drops_the_button_rather_than_rendering_a_dead_one(self):
        html = render_page_ribbon({**RIBBON, "cta": {"label": "Click", "action": "redirect", "target": "javascript:x"}})
        self.assertNotIn("sl-ribbon-cta", html)
        self.assertIn("Get Your Benefits Back", html, "the ribbon still renders; only the button goes")


class RenderTests(unittest.TestCase):
    def test_renders_the_full_formula(self):
        html = render_page_ribbon(RIBBON)
        for expected in ("sl-ribbon-eyebrow", "sl-ribbon-headline", "sl-ribbon-body",
                         "sl-ribbon-media", "sl-ribbon-cta"):
            self.assertIn(expected, html)

    def test_nothing_to_say_renders_nothing(self):
        self.assertEqual(render_page_ribbon({"id": "rb", "eyebrow": "Only an eyebrow"}), "")

    def test_eyebrow_image_and_cta_are_each_optional(self):
        html = render_page_ribbon({"id": "rb", "headline": "Just a headline"})
        for absent in ("sl-ribbon-eyebrow", "sl-ribbon-media", "sl-ribbon-cta"):
            self.assertNotIn(absent, html)

    def test_a_button_needs_both_a_label_and_a_target(self):
        for cta in ({"label": "Go", "action": "redirect", "target": ""},
                    {"label": "", "action": "redirect", "target": "https://x.co"}):
            with self.subTest(cta=cta):
                self.assertNotIn("sl-ribbon-cta", render_page_ribbon({**RIBBON, "cta": cta}))

    def test_phone_and_email_actions_build_their_own_schemes(self):
        tel = render_page_ribbon({**RIBBON, "cta": {"label": "Call", "action": "call_phone", "target": "+15550101234"}})
        self.assertIn('href="tel:+15550101234"', tel)
        mail = render_page_ribbon({**RIBBON, "cta": {"label": "Email", "action": "email", "target": "a@b.co"}})
        self.assertIn('href="mailto:a@b.co"', mail)

    def test_external_links_open_away_and_internal_ones_do_not(self):
        self.assertIn('target="_blank"', render_page_ribbon(RIBBON))
        internal = render_page_ribbon({**RIBBON, "cta": {"label": "See", "action": "redirect", "target": "/offer"}})
        self.assertNotIn('target="_blank"', internal)
        self.assertIn('rel="noopener"', internal)

    def test_copy_is_escaped(self):
        html = render_page_ribbon({"id": "rb", "headline": "safe", "body": "<script>x</script> & more"})
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)


class PresentationTests(unittest.TestCase):
    def test_image_left_is_the_default(self):
        for section in (RIBBON, {**RIBBON, "presentation": ""}, {**RIBBON, "presentation": "diagonal"}):
            with self.subTest(p=section.get("presentation")):
                self.assertIn("is-image_left", render_page_ribbon(section))

    def test_centered_drops_the_image_rather_than_changing_the_chosen_layout(self):
        html = render_page_ribbon({**RIBBON, "presentation": "centered"})
        self.assertIn("is-centered", html)
        self.assertNotIn("sl-ribbon-media", html)

    def test_compact_keeps_its_image(self):
        self.assertIn("sl-ribbon-media", render_page_ribbon({**RIBBON, "presentation": "compact"}))

    def test_every_presentation_bounds_its_columns(self):
        # A ribbon is full-width furniture; an unbounded track would widen the page on a phone.
        for cls in ("is-image_left", "is-centered", "is-compact"):
            with self.subTest(cls=cls):
                self.assertIn(f".sl-page-ribbon.{cls}{{grid-template-columns:minmax(0,", CSS)


class SectionOverrideTests(unittest.TestCase):
    """Fourth consumer of the step-0 override — and the one that most wants it, since an interruption
    that matches the page is not an interruption."""

    def test_default_follows_the_preset(self):
        self.assertNotIn("sl-section-themed", render_page_ribbon(RIBBON))

    def test_a_dark_background_derives_light_ink(self):
        self.assertIn(f"--sl-section-ink:{LIGHT_INK}", render_page_ribbon({**RIBBON, "theme": {"bg": "#0f0f0f"}}))

    def test_the_button_gets_its_own_derived_ink(self):
        # Text sits ON the button, so a pale button must flip to dark text by itself.
        pale = render_page_ribbon({**RIBBON, "theme": {"bg": "#0f0f0f", "accent": "#f1f1f1"}})
        self.assertIn(f"--sl-section-accent-ink:{DARK_INK}", pale)
        self.assertIn("color:var(--sl-section-accent-ink,var(--sl-cta-text,#fff))", CSS)


if __name__ == "__main__":
    unittest.main()
