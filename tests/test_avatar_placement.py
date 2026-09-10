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
