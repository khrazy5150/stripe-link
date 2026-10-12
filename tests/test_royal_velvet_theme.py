"""Royal Velvet: white cards on a near-black violet page, with a violet-to-fuchsia CTA.

Restyled 2026-10-12 to the author's reference. The interesting part is not the palette but that the
preset has **two surfaces of opposite polarity** — the page is light-on-dark and every card is
dark-on-light. The token set could not express that: thirteen elements are painted with `--sl-card` and
ten carried no ink of their own, so they inherited the page's light `--sl-text`. Setting `card: #ffffff`
alone would have rendered them white on white.

`card_text` / `card_muted` / `card_heading` exist for that, and default to the page values so no other
preset moved.
"""
import unittest

from stripe_link.domain.section_theme import contrast_ratio
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_THEME_PRESETS, render_template_styles, theme_tokens

AA = 4.5


def tokens(preset="royal-velvet"):
    return theme_tokens({"theme": {"preset": preset}})


class TheCardTokensChangeNothingElse(unittest.TestCase):
    """The whole reason they are defaults rather than required fields."""

    def test_every_other_preset_still_inks_cards_from_the_page(self):
        for name, preset in UNIVERSAL_BUNDLE_THEME_PRESETS.items():
            if name == "royal-velvet":
                continue
            with self.subTest(preset=name):
                resolved = tokens(name)
                self.assertEqual(resolved["card_text"], preset["text"])
                self.assertEqual(resolved["card_muted"], preset["muted"])

    def test_royal_velvet_is_the_one_that_differs(self):
        resolved = tokens()
        self.assertNotEqual(resolved["card_text"], resolved["text"],
                            "this preset exists to have opposite surfaces")


class BothSurfacesAreReadable(unittest.TestCase):
    """A two-polarity theme is exactly where an unreadable pair hides, so every pair is measured."""

    def pairs(self):
        t = tokens()
        return {
            "headline on page": (t["headline"], t["background"]),
            "body on page": (t["text"], t["background"]),
            "content on page": (t["content_text"], t["background"]),
            "legal on page": (t["legal_text"], t["background"]),
            "hero text": (t["text"], t["hero_bg"]),
            "countdown": (t["countdown_text"], t["countdown_bg"]),
            "text on card": (t["card_text"], t["card"]),
            "muted on card": (t["card_muted"], t["card"]),
            "heading on card": (t["card_heading"], t["card"]),
            "price title": (t["price_title"], t["price_card_bg"]),
            "price description": (t["price_description"], t["price_card_bg"]),
            "price amount": (t["price_amount"], t["price_card_bg"]),
            "price regular": (t["price_regular"], t["price_card_bg"]),
            "faq summary": (t["faq_summary"], t["faq_bg"]),
            "faq text": (t["faq_text"], t["faq_bg"]),
            "refund text": (t["refund_text"], t["refund_bg"]),
            "cta on gradient start": (t["cta_text"], t["cta_from"]),
            "cta on gradient end": (t["cta_text"], t["cta_to"]),
            "chip": (t["chip_text"], t["chip_bg"]),
            "featured badge": (t["featured_badge_text"], t["featured_badge_bg"]),
            "numbered badge": (t["accent_text"], t["accent"]),
        }

    def test_every_pair_passes_wcag_aa(self):
        for label, (ink, surface) in self.pairs().items():
            with self.subTest(pair=label):
                ratio = contrast_ratio(ink, surface)
                self.assertIsNotNone(ratio, f"{label}: {ink} on {surface} is unreadable by the checker")
                self.assertGreaterEqual(ratio, AA, f"{label}: {ink} on {surface} is {ratio:.2f}")

    def test_the_check_covers_both_polarities(self):
        """A guard that only measured one surface would have passed the bug this preset introduced."""
        t = tokens()
        self.assertLess(contrast_ratio(t["text"], t["card"]), AA,
                        "page ink on a card is exactly what must NOT be used -- proving the two differ")


class TheReferenceDesignIsActuallyPresent(unittest.TestCase):
    def test_cards_are_white(self):
        self.assertEqual(tokens()["card"], "#ffffff")
        self.assertEqual(tokens()["price_card_bg"], "#ffffff")

    def test_the_page_is_near_black_violet(self):
        self.assertEqual(tokens()["background"], "#0a0512")

    def test_the_cta_is_a_violet_to_fuchsia_gradient(self):
        t = tokens()
        self.assertEqual((t["cta_from"], t["cta_to"]), ("#7c3aed", "#c026d3"))
        self.assertNotEqual(t["cta_from"], t["cta_to"], "a gradient needs two stops")

    def test_the_headline_is_white_not_the_accent(self):
        """The reference carries its purple in the highlighted words and the CTA, which is what stops
        the page reading as uniformly violet."""
        self.assertEqual(tokens()["headline"], "#ffffff")


class CardContainersStateTheirOwnInk(unittest.TestCase):
    """Ten of them inherited `--sl-text` from `body`. On a white card that is invisible."""

    def css(self):
        return "\n".join(render_template_styles({"theme": {"preset": "royal-velvet"},
                                                 "template": "universal_bundle"}))

    def test_the_card_painted_containers_set_card_text(self):
        css = self.css()
        for selector in (".sl-next-step{", ".sl-testimonial{", ".sl-numbered-item{",
                         ".sl-ba-frame{", ".sl-minicart{", ".sl-notice-card{"):
            with self.subTest(selector=selector):
                rule = next(line for line in css.splitlines() if selector in line)
                self.assertIn("--sl-card-text", rule,
                              f"{selector} is painted with the card and would inherit the page ink")

    def test_children_inside_a_card_use_card_inks(self):
        css = self.css()
        for selector, token in ((".sl-numbered-text{", "--sl-card-muted"),
                                (".sl-testimonial blockquote{", "--sl-card-text"),
                                (".sl-next-step p{", "--sl-card-muted")):
            with self.subTest(selector=selector):
                rule = next(line for line in css.splitlines() if selector in line)
                self.assertIn(token, rule)

    def test_the_section_heading_stays_on_the_page(self):
        """`.sl-numbered-heading` sits ABOVE the cards, not inside one -- it keeps the page ink."""
        rule = next(line for line in self.css().splitlines() if ".sl-numbered-heading{" in line)
        self.assertIn("--sl-content-heading", rule)
        self.assertNotIn("--sl-card", rule)

    def test_the_variable_is_emitted(self):
        self.assertIn("--sl-card-text:#14101f", self.css())


if __name__ == "__main__":
    unittest.main()
