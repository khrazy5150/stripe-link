"""A lead magnet's picture keeps its dimensions (plans/IMAGE_DIMENSIONS.md).

`image_dims` is captured in the browser at upload time, from the processor's reported source size, and
the renderer emits `width`/`height` from it so the browser reserves layout space (no CLS) and crawlers
learn the shape.

It was emptied for `lead_gen` products alongside the images themselves, on the same "it is never sold"
reasoning. When the images were given back -- the picture is what a squeeze page shows ABOVE the form,
and stripping them left every lead page as text on white (2026-09-15) -- their DIMENSIONS were not.

So every lead_gen picture published with no width or height: the hero of a Roundup, and every entry
whose page is a lead page. Found on a live Roundup where exactly the two lead_gen images of six were
missing them, while the four transaction ones carried theirs (2026-10-30).

The signature is worth recording, because it is how the gap was spotted rather than guessed: with no
dimensions the rendition ladder cannot be capped, so `medium` stays in it and becomes the `src`. Any
image on a page whose `src` is `medium.webp` is one with no recorded dimensions.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = (ROOT / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")


class TheDimensionsAreNotStrippedTests(unittest.TestCase):
    def test_lead_gen_no_longer_empties_them(self):
        self.assertNotIn("isLeadGen ? {} : imageDimsForUrls", STORE)

    def test_they_are_carried_for_every_intent(self):
        self.assertIn("const imageDims = imageDimsForUrls(form.image_dims, images);", STORE)

    def test_the_images_themselves_are_still_kept(self):
        """The half of this that was already fixed. If it ever regresses, a lead page goes back to being
        text on white and the dimensions would have nothing to describe."""
        self.assertNotIn("images: isLeadGen ? [] :", STORE)

    def test_they_are_still_omitted_when_empty(self):
        """An empty map must not be written as `image_dims: {}` -- absent means "nothing measured", and
        the renderer's lookup treats a missing entry and an empty one the same way only by accident."""
        self.assertIn("...(Object.keys(imageDims).length ? { image_dims: imageDims } : {}),", STORE)

    def test_only_referenced_images_are_carried(self):
        """A saved document carries the dimensions of images it actually references, not stale entries
        from uploads the tenant has since removed."""
        self.assertIn("imageDimsForUrls(form.image_dims, images)", STORE)


class TheLadderExplainsTheSymptomTests(unittest.TestCase):
    """Why a missing dimension shows up as `medium.webp` in the `src`, which is how this was found."""

    def test_no_dimensions_leaves_the_ladder_uncapped(self):
        from stripe_link.runtime.html import available_renditions, _source_long_edge
        self.assertEqual(_source_long_edge("https://img.example.com/a/small.webp", None), 0)
        self.assertIn("medium", available_renditions(0))

    def test_a_known_small_source_caps_it(self):
        from stripe_link.runtime.html import available_renditions
        self.assertEqual(available_renditions(800), ["small"])
        self.assertNotIn("medium", available_renditions(800))

    def test_the_fallback_src_follows_the_ladder(self):
        source = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        self.assertIn('fallback = "medium" if "medium" in ladder else ladder[-1]', source)
