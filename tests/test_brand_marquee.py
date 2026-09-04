"""Brand Marquee — text-or-logo social proof with scroll and speed control (plans/BRAND_MARQUEE.md).

An ENHANCEMENT of client_marquee, not a new element. Three things it fixes or adds, in order of how much
they mattered:

  1. Text entries were SILENTLY DROPPED. Entries were filtered on `image_url`, so a tenant who typed
     "YouTube" and uploaded nothing got no logo, no text and no warning — while the builder labelled the
     name field as being for search engines only. The legacy marquee this replaced was text-only, so the
     element could not reproduce what it succeeded.
  2. Scrolling becomes a three-state choice. `auto` keeps the >= 5 rule exactly, so no existing page moves.
  3. Speed control, with the marquee's OWN duration property — the countdown banner has a separate
     marquee, and the two sharing a name is how one of them silently stopped animating once before.
"""

import unittest

from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_client_marquee

CSS = "\n".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
FIVE = [{"name": f"Client {n}", "image_url": f"https://img/{n}.png"} for n in range(5)]


class TextEntriesTests(unittest.TestCase):
    """The bug this enhancement exists to fix."""

    def test_a_name_with_no_logo_renders(self):
        html = render_client_marquee({"id": "m", "logos": [{"name": "YouTube"}]})
        self.assertIn("YouTube", html)
        self.assertIn("sl-marquee-word", html)

    def test_a_logo_renders_instead_of_the_name(self):
        html = render_client_marquee({"id": "m", "logos": [{"name": "YouTube", "image_url": "https://i/y.png"}]})
        self.assertIn("sl-marquee-logo", html)
        self.assertNotIn("sl-marquee-word", html)
        self.assertIn('alt="YouTube"', html, "the name becomes the alt text once it is not the content")

    def test_only_an_entry_with_neither_is_dropped(self):
        html = render_client_marquee({"id": "m", "logos": [{"name": "Real"}, {"name": "", "image_url": ""}]})
        self.assertEqual(html.count("sl-marquee-word") + html.count("sl-marquee-logo"), 1)

    def test_no_entries_at_all_renders_nothing(self):
        self.assertEqual(render_client_marquee({"id": "m", "logos": []}), "")

    def test_a_wordmark_is_typography_not_a_white_card(self):
        # Text in a logo-shaped white card reads as a logo that failed to load.
        self.assertIn(".sl-marquee-word{", CSS)
        self.assertIn("color:var(--sl-muted)", CSS)
        self.assertNotIn(".sl-marquee-word{display:inline-flex;align-items:center;background:#ffffff", CSS)

    def test_names_are_escaped(self):
        html = render_client_marquee({"id": "m", "logos": [{"name": "<script>x</script>"}]})
        self.assertNotIn("<script>", html)


class ScrollModeTests(unittest.TestCase):
    def test_auto_preserves_the_existing_threshold_exactly(self):
        # The whole reason `auto` is the default: no page that exists today changes behaviour.
        self.assertIn("sl-marquee-track", render_client_marquee({"id": "m", "logos": FIVE}))
        self.assertIn("sl-marquee-static", render_client_marquee({"id": "m", "logos": FIVE[:4]}))

    def test_always_scrolls_below_the_threshold(self):
        html = render_client_marquee({"id": "m", "scroll": "always", "logos": FIVE[:2]})
        self.assertIn("sl-marquee-track", html)

    def test_never_stays_static_above_it(self):
        html = render_client_marquee({"id": "m", "scroll": "never", "logos": FIVE})
        self.assertIn("sl-marquee-static", html)
        self.assertNotIn("sl-marquee-track", html)

    def test_an_unknown_mode_falls_back_to_auto(self):
        html = render_client_marquee({"id": "m", "scroll": "sideways", "logos": FIVE})
        self.assertIn("sl-marquee-track", html)

    def test_the_scrolling_row_is_announced_once(self):
        html = render_client_marquee({"id": "m", "logos": FIVE})
        self.assertEqual(html.count('aria-hidden="true"'), 1, "the duplicate row must be hidden")


class SpeedTests(unittest.TestCase):
    def test_speed_is_emitted_only_when_scrolling(self):
        self.assertIn("--sl-brand-marquee-duration:8s",
                      render_client_marquee({"id": "m", "scroll": "always", "scroll_seconds": 8, "logos": FIVE[:1]}))
        self.assertNotIn("--sl-brand-marquee-duration",
                         render_client_marquee({"id": "m", "scroll": "never", "logos": FIVE}))

    def test_out_of_range_and_junk_are_clamped(self):
        for given, expected in ((1, "3s"), (999, "60s"), ("fast", "30s"), (None, "30s")):
            with self.subTest(given=given):
                html = render_client_marquee({"id": "m", "scroll": "always", "scroll_seconds": given, "logos": FIVE[:1]})
                self.assertIn(f"--sl-brand-marquee-duration:{expected}", html)

    def test_it_does_not_share_a_property_with_the_countdown_marquee(self):
        # Two marquees sharing a name is how one of them silently stopped animating before.
        self.assertIn("var(--sl-brand-marquee-duration,30s)", CSS)
        self.assertIn("--sl-countdown-marquee-duration", CSS)


class LogoBackingTests(unittest.TestCase):
    def test_the_card_is_the_default(self):
        # A dark logo on a dark preset is invisible without it, so this must not change silently.
        html = render_client_marquee({"id": "m", "logos": [{"name": "A", "image_url": "https://i/a.png"}]})
        self.assertIn('class="sl-marquee-logo"', html)

    def test_none_drops_the_card(self):
        html = render_client_marquee({"id": "m", "logo_backing": "none",
                                      "logos": [{"name": "A", "image_url": "https://i/a.png"}]})
        self.assertIn("sl-marquee-logo is-bare", html)
        self.assertIn(".sl-marquee-logo.is-bare{background:none", CSS)


if __name__ == "__main__":
    unittest.main()
