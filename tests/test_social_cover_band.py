"""The default cover on a link-in-bio page with no uploaded image.

Author, 2026-09-17: a social page created without a hero image showed no avatar either -- the avatar, name,
slogan and brand chip all live inside hero_media, which returns "" when there are no images, so they
disappeared together. The author's reading of it is the one implemented here: the avatar COMPLEMENTS a cover
image, so where there is no cover there is nothing for one to complement. The band is not a patch over the
early return -- it is the real estate an avatar needs in order to exist, granted only on the page shape whose
entire job is identity.

Why it is painted and not a file: sixteen presets would mean sixteen hosted images, a seventeenth for every
preset added, an LCP-sized download on the page type most likely to be opened on mobile data, and a photo
that is simply wrong the moment the tenant switches preset. A band built from the preset's own designed CTA
pair re-skins with the theme and cannot land off-palette -- the same rule that fixed the section tones.
"""
import unittest

from stripe_link.runtime import html as html_module

CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
SOCIAL = {"product_intent": "lead_gen", "lead_capture_action": "social_redirect", "name": "Links"}
SHOP = {"product_intent": "sell", "name": "Widget"}


def _render(offer=None, section=None, preferences=None):
    html_module._RENDER_PREFERENCES = dict(preferences if preferences is not None
                                           else {"avatar_url": "https://img.example/me.webp"})
    try:
        return html_module.render_hero_media(
            {"id": "hero-media", **(section or {})}, offer if offer is not None else SOCIAL, {})
    finally:
        html_module._RENDER_PREFERENCES = {}


class BandTests(unittest.TestCase):
    def test_a_social_page_with_no_image_gets_the_band(self):
        self.assertIn('class="sl-hero-band"', _render())

    def test_and_the_avatar_it_exists_for(self):
        markup = _render()
        self.assertIn("sl-avatar-wrap", markup)
        self.assertIn("https://img.example/me.webp", markup)

    def test_an_uploaded_cover_still_wins(self):
        # The band is the DEFAULT, not a replacement -- same contract the hero already had.
        markup = _render(section={"images": ["https://img.example/cover.webp"]})
        self.assertNotIn("sl-hero-band", markup)
        self.assertIn("cover.webp", markup)

    def test_no_avatar_means_no_band(self):
        """A band with nothing on it is a bare strip of colour -- decoration for its own sake.

        Both ways of having no avatar: never uploaded one, and hid it on this page.
        """
        self.assertEqual(_render(preferences={}), "")
        self.assertEqual(_render(section={"avatar_placement": "hidden"}), "")

    def test_no_other_page_shape_invents_one(self):
        # A product or bridge page with no image renders no hero, exactly as before. Furniture with no
        # reason to be there is worse than an empty space.
        self.assertEqual(_render(offer=SHOP), "")
        self.assertEqual(_render(offer={"product_intent": "lead_gen",
                                        "lead_capture_action": "external_url"}), "")


class PaintedNotStoredTests(unittest.TestCase):
    def test_the_band_carries_no_literal_colour(self):
        """Every colour a theme token, or the band ignores the preset it is supposed to follow."""
        rule = [line for line in CSS.splitlines() if ".sl-hero-band{" in line]
        self.assertEqual(len(rule), 1)
        self.assertNotRegex(rule[0], r"#[0-9a-fA-F]{3,6}")

    def test_it_uses_the_presets_own_designed_pair(self):
        rule = [line for line in CSS.splitlines() if ".sl-hero-band{" in line][0]
        self.assertIn("var(--sl-cta-from)", rule)
        self.assertIn("var(--sl-cta-to)", rule)

    def test_it_is_a_cover_not_a_square(self):
        # The slides are 1:1. A square of flat colour is a colour field, not a cover.
        self.assertIn("aspect-ratio:5/2", [l for l in CSS.splitlines() if ".sl-hero-band{" in l][0])

    def test_it_costs_no_request(self):
        markup = _render()
        self.assertNotIn("<img class=\"sl-hero", markup)
        self.assertNotIn("data:image", markup)

    def test_it_is_decorative_to_a_screen_reader(self):
        # It says nothing the identity block below does not already say.
        self.assertIn('role="presentation"', _render())
        self.assertNotIn('alt="\\x00', _render())

    def test_the_sentinel_can_never_be_a_real_url(self):
        # It travels through the same list as real image URLs, so it must be unmistakable for one.
        self.assertTrue(html_module.HERO_BAND.startswith("\x00"))


class AvatarSourceTests(unittest.TestCase):
    """One reader for "which avatar renders", after three callers wanted the answer."""

    def test_the_page_avatar_wins(self):
        html_module._RENDER_PREFERENCES = {"avatar_url": "store.webp"}
        try:
            self.assertEqual(html_module.avatar_source({"avatar_url": "page.webp"}), "page.webp")
            # ...and an empty one INHERITS rather than meaning "none", so changing the store picture
            # changes every page instead of leaving each frozen at upload day.
            self.assertEqual(html_module.avatar_source({}), "store.webp")
            self.assertEqual(html_module.avatar_source({"avatar_placement": "hidden"}), "")
        finally:
            html_module._RENDER_PREFERENCES = {}


if __name__ == "__main__":
    unittest.main()
