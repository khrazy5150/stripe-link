"""The stored crop rect and the CSS that applies it.

A crop is normalized fractions of the source, never pixels: the image service emits five renditions and
mints more on demand, so a pixel rect is correct against exactly one of them and silently wrong against
every other (plans/IMAGE_CROPPER.md).
"""

import json
import pathlib
import re
import unittest

from stripe_link.domain.image_crop import crop_style_vars, normalized_crop, surface_ratio
from stripe_link.runtime.html import render_page_ribbon

CASES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "image_crop_cases.json").read_text())["cases"]


class SharedFixtureTests(unittest.TestCase):
    """The published page and the builder's own thumbnail apply the same rect with the same formulas.

    Nothing in the languages forces those to agree, so the fixture does: if either side is edited the
    other's expectations fail. Without it the divergence surfaces as a preview that lies about the page,
    which is the most expensive kind of bug to notice.
    """

    def test_every_case_renders_as_the_fixture_says(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                self.assertEqual(crop_style_vars(case["crop"]), case["vars"])


class NormalizationTests(unittest.TestCase):
    def test_a_full_frame_crop_is_no_crop(self):
        # It changes nothing, so it must not add a wrapper, a class, or a style attribute to every page.
        self.assertIsNone(normalized_crop({"x": 0, "y": 0, "w": 1, "h": 1}))
        self.assertEqual(crop_style_vars({"x": 0, "y": 0, "w": 1, "h": 1}), "")

    def test_junk_is_ignored_rather_than_rendered(self):
        for value in (None, "", [], {"x": "a", "y": 0, "w": 1, "h": 1}, {"w": 0.5}, 42):
            with self.subTest(value=value):
                self.assertIsNone(normalized_crop(value))

    def test_a_rect_running_past_the_edge_is_pulled_back_inside(self):
        rect = normalized_crop({"x": 0.8, "y": 0.9, "w": 0.5, "h": 0.5})
        self.assertAlmostEqual(rect["x"] + rect["w"], 1.0, places=6)
        self.assertAlmostEqual(rect["y"] + rect["h"], 1.0, places=6)

    def test_no_negative_zero_reaches_the_page(self):
        # -0% is valid CSS and pure noise: it appears in every uncropped axis and churns diffs.
        self.assertNotIn("-0%", crop_style_vars({"x": 0, "y": 0, "w": 0.5, "h": 0.5}))


class RendererTests(unittest.TestCase):
    SECTION = {
        "id": "rb", "type": "page_ribbon", "presentation": "image_left", "headline": "Hi",
        "image_url": "https://images.juniorbay.net/x/large.webp",
        "cta": {"label": "Go", "action": "redirect", "target": "https://x.co"},
    }

    def _media_div(self, section):
        match = re.search(r'<div class="sl-ribbon-media[^>]*>', render_page_ribbon(section))
        return match.group(0) if match else ""

    def test_an_uncropped_ribbon_is_unchanged(self):
        # Backward compatibility: every page published before cropping existed must render byte-identically.
        self.assertEqual(self._media_div(self.SECTION), '<div class="sl-ribbon-media">')

    def test_a_cropped_ribbon_carries_the_custom_properties(self):
        section = {**self.SECTION, "image_crop": {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}}
        div = self._media_div(section)
        self.assertIn("sl-cropped", div)
        for var in ("--sl-crop-w:200%", "--sl-crop-h:200%", "--sl-crop-x:-50%", "--sl-crop-y:-50%"):
            self.assertIn(var, div)

    def test_a_junk_crop_does_not_produce_a_broken_wrapper(self):
        section = {**self.SECTION, "image_crop": {"x": 0, "y": 0, "w": 0, "h": 0}}
        self.assertEqual(self._media_div(section), '<div class="sl-ribbon-media">')

    def test_the_stylesheet_defines_what_the_markup_references(self):
        from stripe_link.runtime.html import render_template_styles
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-cropped", css)
        for var in ("--sl-crop-w", "--sl-crop-h", "--sl-crop-x", "--sl-crop-y", "--sl-crop-ar"):
            self.assertIn(var, css, "a custom property the markup sets but the CSS never reads does nothing")


class SharedRatioTests(unittest.TestCase):
    """The cropper frames what the renderer crops to, so the ratio is DATA both sides read.

    A cropper locked to a different ratio than the page renders at is worse than no cropper: the tenant
    frames a shot and the page silently discards their framing. Two constants and a comment saying "must
    match" is the failure this file exists to prevent.
    """

    def test_the_builder_reads_the_same_file_the_renderer_does(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        builder = (root / "dashboard/src/components/LandingPages.vue").read_text()
        self.assertIn("image_ratios.json", builder,
                      "the builder must import the shared ratios, not restate them")
        self.assertNotIn("RIBBON_IMAGE_RATIO", builder, "a restated constant can drift from the renderer")
        self.assertNotIn("RIBBON_IMAGE_RATIO", (root / "src/stripe_link/runtime/html.py").read_text())

    def test_every_ratio_is_a_usable_positive_number(self):
        data = json.loads((pathlib.Path(__file__).resolve().parents[1]
                           / "src/stripe_link/image_ratios.json").read_text())["ratios"]
        self.assertTrue(data, "an empty ratio table makes every surface square by accident")
        for surface, value in data.items():
            with self.subTest(surface=surface):
                self.assertIsInstance(value, (int, float))
                self.assertGreater(value, 0)

    def test_an_unknown_surface_is_square_rather_than_an_error(self):
        self.assertEqual(surface_ratio("no-such-surface"), 1.0)

    def test_the_ribbon_renders_at_the_ratio_the_table_declares(self):
        from stripe_link.domain.image_crop import surface_ratio as ratio_of
        section = {**RendererTests.SECTION, "image_crop": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}}
        div = re.search(r'<div class="sl-ribbon-media[^>]*>', render_page_ribbon(section)).group(0)
        self.assertIn(f"--sl-crop-ar:{ratio_of('page_ribbon'):g}", div)


class CssIsolationTests(unittest.TestCase):
    """Nothing outside the crop rule may size a cropped image.

    A cropped box positions its image absolutely and sizes it from the custom properties, so a stray
    width / height / object-fit / max-height corrupts that geometry. The ribbon's mobile rule
    (`.sl-page-ribbon .sl-ribbon-media img`, specificity 0,2,1) beat the crop rule (0,1,1), so the crop
    was wrong on phones -- while desktop worked only because the two tie and mine happened to come later
    in the file. Correct by source order is not correct.

    Only containers that can actually hold a `.sl-cropped` wrapper are checked. Add each surface here as
    P4 makes it croppable; a surface that never crops needs no exclusion.
    """

    CROPPABLE_CONTAINERS = [".sl-ribbon-media"]

    def _css(self):
        from stripe_link.runtime.html import render_template_styles
        return "\n".join(render_template_styles({}))

    def test_no_rule_on_a_croppable_container_can_size_the_image(self):
        css = self._css()
        for container in self.CROPPABLE_CONTAINERS:
            for rule in re.findall(r"[^{}\n]*" + re.escape(container) + r"[^{}\n]*\bimg\s*\{[^}]*\}", css):
                selector, body = rule.split("{", 1)
                if not any(p in body for p in ("max-height:", "object-fit:", "height:", "width:")):
                    continue
                with self.subTest(selector=selector.strip()[:80]):
                    self.assertIn(":not(.sl-cropped)", selector,
                                  "this rule outranks or ties the crop rule and corrupts the geometry")

    def test_the_ribbon_actually_has_such_rules_to_guard(self):
        # If the selectors are ever renamed the loop above silently matches nothing and passes forever.
        css = self._css()
        self.assertIn(".sl-ribbon-media:not(.sl-cropped) img", css)
        self.assertGreaterEqual(css.count(".sl-ribbon-media:not(.sl-cropped) img"), 2,
                                "both the desktop and the mobile rule must exclude cropped media")


class PersistenceTests(unittest.TestCase):
    def test_a_crop_survives_document_validation(self):
        """Sections pass unknown fields through today, so this works with no validator change.

        Guarded because the failure mode is silent: if a section-field allowlist is ever added, crops would
        stop persisting and every tenant's framing would quietly revert to the full frame on next save.
        """
        from stripe_link.domain.documents import validate_page_document

        crop = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
        page = {
            "page_id": "p1", "tenant_id": "t1", "offer_id": "o1", "name": "N", "status": "draft",
            "schema_version": "1", "document_type": "page", "route": {"slug": "x"},
            "sections": [{**RendererTests.SECTION, "image_crop": dict(crop)}],
        }
        validate_page_document(page)
        self.assertEqual(page["sections"][0].get("image_crop"), crop)

    def test_a_garbage_crop_degrades_to_no_crop_rather_than_breaking_the_page(self):
        # The renderer, not the validator, is the boundary: whatever reaches it must never emit broken CSS.
        for junk in ({"x": "a", "y": 0, "w": 1, "h": 1}, {"w": -1, "h": -1, "x": 0, "y": 0}, "nonsense"):
            with self.subTest(junk=junk):
                self.assertEqual(crop_style_vars(junk), "")


if __name__ == "__main__":
    unittest.main()
