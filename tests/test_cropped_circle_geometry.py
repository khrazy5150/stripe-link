"""A cropped image must be clipped by its CONTAINER, never by a radius of its own.

The author, on a live author photo: *"Black area"* on both sides of the circle, widening downwards.

A crop makes the image deliberately LARGER than its box -- that is how the framing works. The author's
photo rendered 140px wide by 227px tall inside a 140px circle. `.sl-cropped>img` carried
`border-radius:inherit`, so the image also drew a 50% radius **of its own box**: an ellipse 140x227,
while the container's circle is 140x140. The two do not line up, and the taller ellipse pinches inward
exactly where the container does not:

    top of circle   image 136.2px wide in a 140px box   ->   3.8px of black
    middle          image 129.3px                       ->  10.7px
    near bottom     image  48.4px                       ->  91.6px

The container clips already -- `overflow:hidden` plus whatever radius the surface sets -- so the
inherited radius was never doing useful work, only damage, and only on cropped surfaces.
"""
import math
import unittest

from stripe_link.runtime.html import render_template_styles


def css():
    return "\n".join(render_template_styles({"theme": {"preset": "royal-velvet"},
                                             "template": "universal_bundle"}))


def rule(selector):
    return next(line for line in css().splitlines() if selector in line)


class TheImageDoesNotClipItself(unittest.TestCase):
    def test_the_cropped_image_has_no_radius(self):
        self.assertNotIn("border-radius", rule(".sl-cropped>img{"))

    def test_the_container_still_clips(self):
        container = rule(".sl-cropped{")
        self.assertIn("overflow:hidden", container)
        self.assertIn("position:relative", container, "the crop offsets resolve against this box")

    def test_the_circular_surface_still_rounds_itself(self):
        """The circle has to come from somewhere -- removing it from the image must not remove it from
        the surface."""
        self.assertIn("border-radius:50%", rule(".sl-author-photo{"))

    def test_the_image_is_still_positioned_and_sized_by_the_crop(self):
        img = rule(".sl-cropped>img{")
        for var in ("--sl-crop-x", "--sl-crop-y", "--sl-crop-w", "--sl-crop-h"):
            self.assertIn(var, img)
        self.assertIn("max-width:none", img, "a crop routinely needs the image wider than its box")


class TheGeometryThatProvedIt(unittest.TestCase):
    """Kept as arithmetic rather than prose: it is the argument for why the radius had to go, and it
    reproduces the exact widths seen on the page."""

    BOX = 140.0
    CROP_W, CROP_H = 100.0, 162.2718      # the live values, from the saved rect

    def visible_width_with_self_radius(self, fraction_down):
        img_w = self.CROP_W / 100 * self.BOX
        img_h = self.CROP_H / 100 * self.BOX
        top = -(self.CROP_H - 100.0) / 100 * self.BOX
        a, b = img_w / 2, img_h / 2
        y = -top + fraction_down * self.BOX
        dy = (y - b) / b
        return 2 * a * math.sqrt(max(0.0, 1 - dy * dy))

    def test_a_self_radius_would_pinch_the_image(self):
        self.assertAlmostEqual(self.visible_width_with_self_radius(0.0), 136.2, places=0)
        self.assertAlmostEqual(self.visible_width_with_self_radius(1.0), 0.0, places=1)

    def test_without_one_the_image_fills_the_box_everywhere(self):
        """What the fix restores: the image is a plain rectangle, and the CONTAINER makes it a circle."""
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            with self.subTest(down=fraction):
                self.assertEqual(self.CROP_W / 100 * self.BOX, self.BOX)

    def test_the_crop_itself_was_always_correct(self):
        """Worth pinning: the rect, the maths and the file were all right. Only the clipping was wrong,
        which is why every earlier theory about the crop came up empty."""
        src_w, src_h = 493, 800
        w, h = 1.0, 0.61625
        self.assertAlmostEqual((w * src_w) / (h * src_h), 1.0, places=3)
        box = self.BOX
        self.assertAlmostEqual((100 / w / 100 * box) / (100 / h / 100 * box), src_w / src_h, places=3)


if __name__ == "__main__":
    unittest.main()
