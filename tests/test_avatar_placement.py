"""The hero avatar can sit in three places, and the default is exactly what shipped before.

The avatar element already existed: render_hero_media reads section.avatar_url and emits
.sl-avatar-wrap, pinned bottom-left over the hero. What it lacked was a CHOICE -- the references put it
overlapping a cover image (linkcloud) or inline under the name with no cover at all (eddieabbew), and an
overlay avatar hanging off nothing reads as a mistake.
"""
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import avatar_placement, render_hero_media


def _section(**overrides):
    # render_hero_media returns nothing without media -- the avatar rides ON the hero, so there has to
    # be a hero for it to ride on.
    section = {"type": "hero_media", "avatar_url": "https://img.example/a.jpg",
               "images": ["https://img.example/hero.jpg"]}
    section.update(overrides)
    return section


class PlacementResolutionTests(unittest.TestCase):
    def test_the_default_is_the_behaviour_that_already_shipped(self):
        # A page saved before this existed must render identically.
        self.assertEqual(avatar_placement({"avatar_url": "x"}), "overlay")

    def test_the_three_placements_resolve(self):
        for value in ("overlay", "inline", "centered"):
            self.assertEqual(avatar_placement({"avatar_placement": value}), value)

    def test_an_unknown_value_degrades_rather_than_breaking(self):
        # A hand-edited document should fall back to the old behaviour, not render an unstyled div.
        self.assertEqual(avatar_placement({"avatar_placement": "diagonal"}), "overlay")


class ReservedSpaceTests(unittest.TestCase):
    """`has-avatar` reserves the gap the overlay OVERHANGS into. Only the overlay overhangs."""

    def _media_class(self, section):
        markup = render_hero_media(section, {}, {})
        found = re.search(r'class="(sl-hero-media[^"]*)"', markup)
        return found.group(1) if found else ""

    def test_the_overlay_reserves_space_beneath_the_hero(self):
        self.assertIn("has-avatar", self._media_class(_section(avatar_placement="overlay")))

    def test_an_inline_avatar_does_not_leave_a_hole(self):
        # It sits in normal flow, so the reserved gap would be empty space under the hero.
        for placement in ("inline", "centered"):
            self.assertNotIn("has-avatar", self._media_class(_section(avatar_placement=placement)), placement)

    def test_no_avatar_reserves_nothing(self):
        self.assertNotIn("has-avatar", self._media_class(_section(avatar_url="")))


class ValidationTests(unittest.TestCase):
    def test_a_new_document_cannot_store_an_unknown_placement(self):
        """Degrading at RENDER is for documents that already exist. A new save should be refused, or the
        bad value silently becomes 'overlay' forever and the tenant never learns their choice was lost."""
        import json
        import pathlib
        fixture = (pathlib.Path(__file__).resolve().parents[1]
                   / "schemas" / "examples" / "page-creatine-standard.json")
        page = json.loads(fixture.read_text(encoding="utf-8"))
        hero = {"type": "hero_media", "id": "hero-media",
                "images": ["https://img.example/hero.jpg"],
                "avatar_url": "https://img.example/a.jpg", "avatar_placement": "overlay"}
        page["sections"] = [hero] + page["sections"]
        validate_page_document(page)              # a known value passes
        hero["avatar_placement"] = "sideways"
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page)


if __name__ == "__main__":
    unittest.main()


class HiddenPlacementTests(unittest.TestCase):
    """"hidden" exists because the avatar became a REFERENCE.

    An empty page-level avatar_url now means "inherit the store's", not "no avatar" -- so without an
    explicit hide, a tenant who uploads a store avatar has no way to keep it off one particular page.
    Reported 2026-09-10.
    """

    def setUp(self):
        from stripe_link.runtime import html as html_module
        self.html = html_module
        html_module._RENDER_PREFERENCES["avatar_url"] = "https://img.example/store.jpg"

    def tearDown(self):
        self.html._RENDER_PREFERENCES.clear()

    def _render(self, placement):
        return self.html.render_hero_media(
            {"type": "hero_media", "images": ["https://img.example/h.jpg"],
             "avatar_placement": placement}, {}, {})

    def test_hidden_removes_an_inherited_avatar(self):
        self.assertNotIn("sl-avatar", self._render("hidden"))

    def test_hidden_removes_a_page_specific_avatar_too(self):
        markup = self.html.render_hero_media(
            {"type": "hero_media", "images": ["https://img.example/h.jpg"],
             "avatar_url": "https://img.example/page.jpg", "avatar_placement": "hidden"}, {}, {})
        self.assertNotIn("sl-avatar", markup)

    def test_hidden_reserves_no_overhang(self):
        # has-avatar would leave a gap under the hero for an avatar that is not there.
        self.assertNotIn("has-avatar", self._render("hidden"))

    def test_the_other_placements_still_show_it(self):
        for placement in ("overlay", "inline", "centered"):
            self.assertIn("sl-avatar", self._render(placement), placement)


class PlacementPersistenceTests(unittest.TestCase):
    def test_the_builder_saves_the_placement_even_when_the_avatar_is_INHERITED(self):
        """Reported 2026-09-10: every placement rendered as an overlay.

        The serializer gated avatar_placement on builder.avatar_url. Once the avatar became a reference,
        a page inheriting the store image has an EMPTY avatar_url -- so the placement was discarded on
        exactly the pages most likely to use it.
        """
        import pathlib
        builder = (pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertIn("avatar_placement: builder.avatar_placement || undefined", builder)
        self.assertNotIn("avatar_placement: builder.avatar_url ?", builder)


class HeroStructureTests(unittest.TestCase):
    """Where each overlay lives in the DOM, because that is what decides how it positions.

    All three reported 2026-09-10 on a real page.
    """

    def setUp(self):
        from stripe_link.runtime import html as html_module
        self.html = html_module
        html_module._RENDER_PREFERENCES["avatar_url"] = "https://img.example/store.jpg"

    def tearDown(self):
        self.html._RENDER_PREFERENCES.clear()

    def _markup(self, images, **overrides):
        section = {"type": "hero_media", "images": images, "brand_overlay": True,
                   "brand_text": "ACME", "brand_position": "bottom-left"}
        section.update(overrides)
        return self.html.render_hero_media(section, {}, {})

    def test_the_brand_sits_inside_the_figure_so_it_anchors_to_the_artwork(self):
        # Outside it, the containing block is .sl-hero-media, which GROWS when an inline avatar appears --
        # so a bottom-left brand slid down level with the avatar and overlapped it on a phone.
        for images in (["https://i/a.jpg"], ["https://i/a.jpg", "https://i/b.jpg"]):
            markup = self._markup(images, avatar_placement="centered")
            self.assertLess(markup.index("sl-hero-brand"), markup.index("</figure>"), images)

    def test_the_avatar_stays_outside_the_figure(self):
        # An inline or centred avatar is in normal flow BELOW the image, not painted on it.
        markup = self._markup(["https://i/a.jpg"], avatar_placement="centered")
        self.assertGreater(markup.index("sl-avatar-wrap"), markup.index("</figure>"))

    def test_the_carousel_counter_sits_with_the_dots_not_over_the_image(self):
        # Overlaid top-right it collided with a top-right brand chip: two translucent pills stacked on the
        # artwork read as a bug rather than a design.
        markup = self._markup(["https://i/a.jpg", "https://i/b.jpg"], brand_position="top-right")
        dots = markup.index("sl-hero-dots")
        counter = markup.index("sl-hero-counter")
        self.assertLess(dots, counter)
        self.assertLess(counter, markup.index("</figure>"))


class TopCentreAndPulseTests(unittest.TestCase):
    """A second overlay position, and an opt-in pulse on the brand dot."""

    def setUp(self):
        from stripe_link.runtime import html as html_module
        self.html = html_module
        html_module._RENDER_PREFERENCES["avatar_url"] = "https://img.example/store.jpg"

    def tearDown(self):
        self.html._RENDER_PREFERENCES.clear()

    def _hero(self, placement):
        return self.html.render_hero_media(
            {"type": "hero_media", "images": ["https://img.example/h.jpg"],
             "avatar_placement": placement}, {}, {})

    def test_top_centre_renders_the_avatar(self):
        self.assertIn("sl-avatar--overlay_top", self._hero("overlay_top"))

    def test_each_overlay_reserves_room_on_the_side_it_overhangs(self):
        """Both overlays hang half off the artwork -- one below, one above.

        Changed 2026-09-10: top-centre first sat INSIDE the image, which read as pasted on rather than
        overhanging. It now mirrors the bottom-left overlay, so the section has to reserve the room ABOVE
        the hero or the avatar collides with the brand label sitting there.
        """
        self.assertIn("has-avatar", self._hero("overlay"))
        self.assertNotIn("has-avatar-top", self._hero("overlay"))
        self.assertIn("has-avatar-top", self._hero("overlay_top"))
        for placement in ("inline", "centered", "hidden"):
            # In normal flow, or absent: nothing overhangs, so nothing is reserved.
            self.assertNotIn("has-avatar", self._hero(placement), placement)

    def test_the_brand_label_dot_pulses_too(self):
        """The setting is about "the brand dot", and the brand appears EITHER on the hero chip OR above the
        hero -- never both. Gating the option on the hero overlay left the pulse unreachable in the case it
        suits best, which is the brand sitting above the image."""
        from stripe_link.runtime.html import render_brand_label
        self.assertIn("is-pulsing", render_brand_label({"label": "ACME", "brand_dot_pulse": True}, {}))
        self.assertNotIn("is-pulsing", render_brand_label({"label": "ACME"}, {}))

    def test_the_brand_dot_pulses_only_when_asked(self):
        from stripe_link.runtime.html import render_hero_brand
        section = {"brand_overlay": True, "brand_text": "ACME"}
        self.assertNotIn("is-pulsing", "".join(render_hero_brand(section, {})))
        self.assertIn("is-pulsing", "".join(render_hero_brand({**section, "brand_dot_pulse": True}, {})))

    def test_the_pulse_stops_for_reduced_motion(self):
        """A blinking element is exactly what that preference is for, and the marquee already honours it."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        reduced = [line for line in source.split("\n") if "prefers-reduced-motion" in line]
        self.assertTrue(reduced)
        self.assertIn(".sl-hero-brand-dot.is-pulsing{animation:none}", reduced[0])
