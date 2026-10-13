"""A surface that renders a circle must crop against a circle.

The author, 2026-10-12: *"the Author Bio cropper uses a rectangular cropper but the resulting image will
be a circle."*

The ratio was never the problem -- `image_ratios.json` locks `author_bio` to 1, and the frame really is
square. What was missing is that a SQUARE frame over an image destined for `border-radius:50%` hides
which corners vanish, so a photo framed to the edges comes out with its head clipped.

Nothing about the stored value changes: a circle IS a square plus CSS, and the normalized rect is
identical either way. This is a guide, and it is deliberately only drawn when the frame is square --
over any other ratio it would promise a circle the surface cannot produce.
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RATIOS = json.loads((ROOT / "src" / "stripe_link" / "image_ratios.json").read_text())
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text()


def dash(name):
    return (ROOT / "dashboard" / "src" / "components" / name).read_text()


class TheCropperCanDrawACircle(unittest.TestCase):
    def test_it_accepts_a_shape(self):
        cropper = dash("shared/ImageCropper.vue")
        self.assertIn('shape: { type: String, default: "rect" }', cropper)

    def test_the_guide_is_square_only(self):
        """Drawn over a non-square frame it would promise a circle the surface cannot produce."""
        cropper = dash("shared/ImageCropper.vue")
        self.assertIn("Math.abs(activeRatio.value - 1) < 0.001", cropper)

    def test_the_frame_is_actually_clipped(self):
        """Clipping the frame (not overlaying a ring) is what makes the lost corners visible."""
        cropper = dash("shared/ImageCropper.vue")
        self.assertIn(".cropper-frame.is-circle { border-radius: 50%; }", cropper)

    def test_the_field_passes_it_through(self):
        field = dash("shared/ImageUploadField.vue")
        self.assertIn('shape: { type: String, default: "rect" }', field)
        self.assertIn(':shape="shape"', field)

    def test_the_default_stays_rectangular(self):
        """Every other surface must be untouched -- this is additive or it is a regression."""
        for name in ("shared/ImageCropper.vue", "shared/ImageUploadField.vue"):
            with self.subTest(component=name):
                self.assertIn('default: "rect"', dash(name))


class TheCircularSurfacesAskForIt(unittest.TestCase):
    def test_author_bio_does(self):
        self.assertIn('shape="circle"', dash("LandingPages.vue"))

    def test_the_store_avatar_does(self):
        """Its own docstring already said "a circular avatar is not negotiable"; now the cropper agrees."""
        self.assertIn('shape="circle"', dash("shared/StoreAvatarField.vue"))

    def test_author_bio_is_locked_square_so_the_guide_is_honest(self):
        self.assertEqual(RATIOS["placement"]["author_bio"], 1)

    def test_the_renderer_really_draws_those_two_as_circles(self):
        """The guide must follow the renderer, not a guess. If this stops being a circle the guide is a
        lie and this test is where that surfaces."""
        rule = next(line for line in HTML.splitlines() if ".sl-author-photo{" in line)
        self.assertIn("border-radius:50%", rule)


class SurfacesStillRenderingCirclesWithoutACropper(unittest.TestCase):
    """Recorded rather than fixed. `.sl-testimonial img` and `.sl-quote-photo img` are circles too, but
    those elements upload through a bare file input with no cropper at all -- so there is no guide to
    add yet. Pinned so the gap is visible instead of being rediscovered from a clipped head."""

    def test_they_are_still_circular_in_the_renderer(self):
        for selector in (".sl-testimonial img{", ".sl-quote-minimal .sl-quote-photo img{"):
            with self.subTest(selector=selector):
                rule = next(line for line in HTML.splitlines() if selector in line)
                self.assertIn("border-radius:50%", rule)

    def test_those_elements_have_no_cropper_today(self):
        builder = dash("LandingPages.vue")
        quote = builder[builder.index("element.type === 'quote'"):]
        quote = quote[:4000]
        self.assertNotIn("<ImageUploadField", quote,
                         "quote gained a cropper -- give it shape=\"circle\" and delete this test")


if __name__ == "__main__":
    unittest.main()
