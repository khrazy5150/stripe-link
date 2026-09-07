"""The Before/After element: two photographs of the same thing, wiped between by a draggable divider.

The single most persuasive element for a visual-outcome trade -- dentistry, landscaping, renovation,
detailing -- because it is evidence rather than assertion.
"""

import re
import unittest

from stripe_link.runtime.html import (
    render_before_after,
    render_page_interactions_script,
    render_template_styles,
)

PAIR = {
    "id": "ba", "type": "before_after",
    "before_url": "https://i/b/large.webp",
    "after_url": "https://i/a/large.webp",
}


class RenderTests(unittest.TestCase):
    def test_a_pair_renders_a_frame(self):
        html = render_before_after(PAIR)
        self.assertIn('data-section-type="before_after"', html)
        self.assertIn("data-sl-before-after", html)

    def test_one_image_is_not_a_comparison(self):
        # Half a wipe is worse than none: it looks broken rather than incomplete.
        for section in ({**PAIR, "after_url": ""}, {**PAIR, "before_url": ""}, {"id": "ba"}):
            with self.subTest(section=sorted(section)):
                self.assertEqual(render_before_after(section), "")

    def test_after_sits_under_before(self):
        # Dragging left reveals the OUTCOME, which is what the tenant is selling and what people expect.
        html = render_before_after(PAIR)
        self.assertLess(html.index("is-after"), html.index("is-before"),
                        "the after layer must be painted first so before can be clipped over it")

    def test_the_before_image_loads_eagerly(self):
        # It is what the visitor sees at rest, so it is the LCP candidate of the two.
        html = render_before_after(PAIR)
        before = html[html.index("is-before"):]
        self.assertIn('loading="eager"', before)

    def test_the_shape_and_start_reach_the_css(self):
        html = render_before_after({**PAIR, "ratio": 16 / 9, "start": 30})
        self.assertIn("--sl-ba-ar:1.77778", html)
        self.assertIn("--sl-ba-pos:30%", html)

    def test_a_nonsense_shape_falls_back_rather_than_breaking_the_frame(self):
        for ratio in (0, -2, "wide", None):
            with self.subTest(ratio=ratio):
                self.assertIn("--sl-ba-ar:1.33333", render_before_after({**PAIR, "ratio": ratio}))

    def test_the_start_position_is_clamped(self):
        for value, expected in ((-40, "0%"), (250, "100%"), ("nonsense", "50%")):
            with self.subTest(value=value):
                self.assertIn(f"--sl-ba-pos:{expected}", render_before_after({**PAIR, "start": value}))

    def test_labels_are_authored_and_escaped(self):
        html = render_before_after({**PAIR, "before_label": 'A<script>"', "after_label": ""})
        self.assertNotIn("<script>", html)
        self.assertIn("After", html, "an empty label falls back rather than rendering a blank chip")


class AccessibilityTests(unittest.TestCase):
    """The divider is a real control, not a div listening for pointer events.

    Hand-rolled dragging works for exactly one input device. A range input brings keyboard, touch,
    click-to-jump and assistive technology for free, and shrinks the script to one assignment.
    """

    def test_the_divider_is_a_range_input(self):
        html = render_before_after(PAIR)
        self.assertIn('type="range"', html)
        self.assertIn('min="0"', html)
        self.assertIn('max="100"', html)

    def test_it_is_labelled(self):
        html = render_before_after({**PAIR, "before_label": "Day 1", "after_label": "Day 30"})
        match = re.search(r'aria-label="([^"]+)"[^>]*>|<input[^>]*aria-label="([^"]+)"', html)
        self.assertIn("aria-label", html)
        self.assertIn("Day 1", html)
        self.assertIn("Day 30", html)

    def test_the_frame_shows_focus(self):
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-ba-frame:focus-within", css,
                      "a keyboard user must be able to see which control they are on")

    def test_the_decorative_handle_is_hidden_from_assistive_tech(self):
        # The range already announces the value; the bar would be a second, meaningless stop.
        self.assertIn('class="sl-ba-handle" aria-hidden="true"', render_before_after(PAIR))


class NoScriptTests(unittest.TestCase):
    """Published pages are static artifacts, so the no-JS state is a real state a visitor will see."""

    def test_the_divider_rests_where_it_was_authored(self):
        # The clip-path reads the custom property straight from the markup, so no script is needed for a
        # legible side-by-side -- only for moving it.
        html = render_before_after({**PAIR, "start": 65})
        self.assertIn("--sl-ba-pos:65%", html)

    def test_the_clip_is_css_not_script(self):
        css = "\n".join(render_template_styles({}))
        self.assertIn("clip-path:inset(0 calc(100% - var(--sl-ba-pos,50%)) 0 0)", css)


class ScriptTests(unittest.TestCase):
    def test_a_page_with_a_pair_gets_the_handler(self):
        page = {"page_id": "p", "sections": [PAIR]}
        self.assertIn("data-sl-before-after", render_page_interactions_script(page))

    def test_an_incomplete_pair_does_not_summon_a_script(self):
        # It renders nothing, so a handler for it would be dead weight on every visitor's page.
        page = {"page_id": "p", "sections": [{**PAIR, "after_url": ""}]}
        self.assertEqual(render_page_interactions_script(page), "")


class LayoutTests(unittest.TestCase):
    def test_both_layers_are_the_same_box(self):
        """Clipping rather than resizing is what guarantees the halves stay in register.

        Sizing the top layer to the divider would make its image narrower than the one beneath, so the two
        halves would show different parts of the frame and the seam would visibly jump.
        """
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-before-after .sl-ba-img{position:absolute;inset:0", css)

    def test_the_layers_do_not_fight_a_crop(self):
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-before-after .sl-ba-img:not(.sl-cropped) img", css,
                      "an unscoped img rule here would outrank the crop rule and corrupt the geometry")

    def test_a_cropped_pair_carries_its_crop(self):
        crop = {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "ar": 1.3333333333}
        html = render_before_after({**PAIR, "before_crop": crop, "after_crop": crop})
        self.assertEqual(html.count("sl-cropped"), 2, "both sides carry their own crop")


if __name__ == "__main__":
    unittest.main()
