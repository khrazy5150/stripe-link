"""The Photo element: images as the content, not as decoration on something else.

Every other image-bearing element attaches the picture to something — a content block's prose, an author's
name, a before/after comparison. There was no way to put an image on a page AS the content, which is what a
stack of screenshotted customer reviews is: the picture is the argument.

A list with one shared heading rather than one image per element, because the screenshots that prompted
this arrive as a set under a single claim. NOT repeatable: `test_composition_placement` already settled
that question for link_cards on observed behaviour — a second click of the palette button means "another
photo", not "another photo block".
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import UNIVERSAL_BUNDLE_TEMPLATE_STYLES, render_photo

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
RATIOS = json.loads((ROOT / "src" / "stripe_link" / "image_ratios.json").read_text(encoding="utf-8"))
FIXTURE = ROOT / "schemas" / "examples" / "page-creatine-standard.json"
IMG = "https://i/x/large.webp"


def page(section):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["sections"] = [{"type": "photo", "id": "ph", **section}]
    return doc


class ItRendersTheImages(unittest.TestCase):
    def test_each_image_appears(self):
        html = render_photo({"images": [{"url": IMG}, {"url": "https://i/y/large.webp"}]})
        self.assertEqual(len(re.findall(r"<img ", html)), 2)

    def test_an_entry_with_no_url_is_dropped(self):
        """The builder starts with one blank row, so a half-filled block must not emit an empty frame."""
        html = render_photo({"images": [{"url": IMG}, {"url": "   ", "caption": "orphan"}]})
        self.assertEqual(len(re.findall(r"<img ", html)), 1)
        self.assertNotIn("orphan", html)

    def test_no_images_renders_nothing(self):
        for images in ([], [{"url": ""}], None):
            with self.subTest(images=images):
                self.assertEqual(render_photo({"images": images}), "")

    def test_the_heading_is_an_h2_so_it_joins_the_outline(self):
        html = render_photo({"heading": "Real members", "images": [{"url": IMG}]})
        self.assertIn('<h2 class="sl-photo-heading">', html)

    def test_no_heading_means_no_empty_h2(self):
        self.assertNotIn("<h2", render_photo({"images": [{"url": IMG}]}))


class CaptionsPairWithTheirImage(unittest.TestCase):
    def test_a_caption_makes_it_a_figure(self):
        html = render_photo({"images": [{"url": IMG, "caption": "Liza Simpson"}]})
        self.assertIn("<figure", html)
        self.assertIn("<figcaption>Liza Simpson</figcaption>", html)

    def test_no_caption_means_no_figure(self):
        """A <figure> with no caption adds a landmark that says nothing."""
        html = render_photo({"images": [{"url": IMG}]})
        self.assertNotIn("<figure", html)
        self.assertNotIn("<figcaption", html)

    def test_a_caption_is_escaped(self):
        self.assertIn("&lt;script&gt;", render_photo({"images": [{"url": IMG, "caption": "<script>"}]}))


class AltTextFallsBackHonestly(unittest.TestCase):
    def test_explicit_alt_wins(self):
        html = render_photo({"images": [{"url": IMG, "alt": "A dashboard", "caption": "Wayne"}]})
        self.assertIn('alt="A dashboard"', html)

    def test_the_caption_is_the_fallback(self):
        """It describes the picture to everyone, so it is honest alt text; inventing one is not."""
        self.assertIn('alt="Wayne"', render_photo({"images": [{"url": IMG, "caption": "Wayne"}]}))

    def test_the_heading_is_never_borrowed_as_alt(self):
        """It describes the SET; repeating it would announce the same words on every image."""
        html = render_photo({"heading": "Real members", "images": [{"url": IMG}, {"url": IMG}]})
        self.assertNotIn('alt="Real members"', html)


class TheLayoutIsStackedUntilAskedOtherwise(unittest.TestCase):
    """A review screenshot is only proof while its text is readable, and a grid shrinks it until it is not."""

    def test_stacked_by_default(self):
        self.assertNotIn("is-side-by-side", render_photo({"images": [{"url": IMG}]}))

    def test_the_flag_turns_the_grid_on(self):
        self.assertIn("is-side-by-side", render_photo({"side_by_side": True, "images": [{"url": IMG}]}))

    def test_the_grid_only_applies_where_there_is_room(self):
        """Two half-width images on a phone are two unreadable images."""
        css = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        rule = next(r for r in UNIVERSAL_BUNDLE_TEMPLATE_STYLES
                    if isinstance(r, str) and "is-side-by-side" in r)
        self.assertIn("@media (min-width:", rule)
        self.assertIn("grid-template-columns:repeat(2", rule)


class TheCropIsClippedByTheContainer(unittest.TestCase):
    """Re-asserted per element: rounding the <img> rounds the part that is already overflowing, which
    showed as a straight-cornered photo with a curved ghost (fixed once already, 2026-10-12)."""

    def test_the_radius_is_on_the_media_box_not_the_image(self):
        css = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-photo-media{border-radius:", css)
        self.assertNotIn(".sl-photo img{", css)

    def test_the_uncropped_sizing_rule_yields_to_a_crop(self):
        css = "".join(UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-photo-media:not(.sl-cropped) img{", css)

    def test_a_crop_emits_the_shared_vars(self):
        html = render_photo({"images": [{"url": IMG, "crop": {"x": .1, "y": .1, "w": .5, "h": .5, "ar": 1}}]})
        self.assertIn("sl-cropped", html)
        self.assertIn("--sl-crop-ar:1", html)

    def test_the_cropper_offers_original_first(self):
        """A screenshot has no sensible fixed ratio; cropping one to 4:3 removes its content."""
        self.assertEqual(RATIOS["placement"]["photo"][0], "original")


class ItIsRegisteredLikeEveryOtherElement(unittest.TestCase):
    def test_it_is_addable_and_not_repeatable(self):
        spec = RULES["elements"]["photo"]
        self.assertEqual(spec["ui"], "add")
        self.assertFalse(spec["repeatable"])

    def test_the_builder_starts_it_with_one_row(self):
        """An editor that opens empty reads as broken."""
        self.assertIn('if (type === "photo") return', BUILDER)
        self.assertRegex(BUILDER, r'type === "photo"\) return \{ \.\.\.base, heading: "", images: \[\{')

    def test_an_all_blank_block_is_not_saved(self):
        self.assertIn("if (!images.length) return null;", BUILDER)


class TheDocumentValidatesIt(unittest.TestCase):
    def test_a_minimal_block_is_accepted(self):
        validate_page_document(page({"images": [{"url": IMG}]}))

    def test_everything_optional_is_optional(self):
        validate_page_document(page({"heading": "H", "side_by_side": True,
                                     "images": [{"url": IMG, "alt": "a", "caption": "c"}]}))

    def test_an_image_without_a_url_is_rejected(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"images": [{"caption": "no picture"}]}))

    def test_side_by_side_must_be_a_boolean(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page({"side_by_side": "yes", "images": [{"url": IMG}]}))


if __name__ == "__main__":
    unittest.main()
