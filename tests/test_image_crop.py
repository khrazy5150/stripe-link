"""The stored crop rect and the CSS that applies it.

A crop is normalized fractions of the source, never pixels: the image service emits five renditions and
mints more on demand, so a pixel rect is correct against exactly one of them and silently wrong against
every other (plans/IMAGE_CROPPER.md).
"""

import json
import pathlib
import re
import unittest

from stripe_link.domain.image_crop import CROP_KEYS, crop_aspect, crop_style_vars, normalized_crop, surface_ratio, surface_ratios
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

    def test_every_entry_is_one_of_the_three_legal_shapes(self):
        """A number locks, a list offers choices, null accepts any shape. Nothing else is meaningful."""
        from stripe_link.domain.image_crop import FREEFORM

        table = json.loads((pathlib.Path(__file__).resolve().parents[1]
                            / "src/stripe_link/image_ratios.json").read_text())
        data = {**table["placement"], **table["asset"]}
        self.assertTrue(data, "an empty table makes every surface square by accident")
        for surface, value in data.items():
            with self.subTest(surface=surface):
                if value is None:
                    continue
                entries = value if isinstance(value, list) else [value]
                self.assertTrue(entries, "an empty list offers the tenant nothing")
                for entry in entries:
                    if entry == FREEFORM:
                        continue
                    self.assertIsInstance(entry, (int, float))
                    self.assertGreater(entry, 0)

    def test_a_locked_surface_reports_its_one_ratio(self):
        # author_bio renders in a 14rem circle, so its shape is not the tenant's to choose.
        self.assertEqual(surface_ratio("author_bio"), 1.0)

    def test_a_surface_offering_choices_has_no_single_ratio(self):
        # page_ribbon renders height:auto, so it never had one shape. The crop carries what it was made at.
        from stripe_link.domain.image_crop import FREEFORM
        options = surface_ratios("page_ribbon")
        self.assertGreater(len(options), 1)
        self.assertIn(FREEFORM, options, "a shape-agnostic surface must offer the source's own ratio")

    def test_an_unknown_surface_is_freeform_rather_than_an_error(self):
        from stripe_link.domain.image_crop import FREEFORM
        self.assertEqual(surface_ratios("no-such-surface"), [FREEFORM])

    def test_the_crop_carries_the_shape_it_was_made_at(self):
        """A preset or freeform crop's shape cannot be recovered from the rect alone.

        The rect is fractions of the SOURCE, so without the source's dimensions 0.5x0.5 could be any shape.
        Depending on the image_dims sidecar would make the page wrong whenever it is missing, so the cropper
        records the ratio it framed at.
        """
        wide = {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "ar": 16 / 9}
        self.assertIn("--sl-crop-ar:1.77778", crop_style_vars(wide, "page_ribbon"))
        self.assertAlmostEqual(crop_aspect(wide, "page_ribbon"), 16 / 9, places=5)

    def test_a_locked_surface_still_answers_for_crops_made_before_it_recorded_one(self):
        # Backward compatibility for any crop stored without `ar`.
        self.assertEqual(crop_aspect({"x": 0, "y": 0, "w": 0.5, "h": 0.5}, "author_bio"), 1.0)


class CropperContractTests(unittest.TestCase):
    """What the Vue cropper writes is what the Python renderer reads. Nothing in either language forces it.

    The rect alone cannot reveal the output shape -- it is fractions of the SOURCE, so 0.5 x 0.5 is any
    shape until you know the source's dimensions. For a locked surface the table answers, but for a preset
    or "original" crop only the cropper knows, so it records `ar`. Drop that and every ribbon crop silently
    renders square.
    """

    def _cropper(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "dashboard/src/components/shared/ImageCropper.vue").read_text()

    def test_the_cropper_records_the_shape_it_framed_at(self):
        source = self._cropper()
        start = source.find('emit("apply"')
        self.assertGreater(start, -1, "the cropper must emit an applied crop")
        payload = source[start:source.find("\n}", start)]
        self.assertIn("ar:", payload,
                      "the applied crop must carry `ar` or the renderer cannot know its shape")

    def test_the_cropper_emits_every_key_the_renderer_reads(self):
        source = self._cropper()
        for key in CROP_KEYS:
            with self.subTest(key=key):
                self.assertRegex(source, rf"\b{key}:\s*round\(",
                                 f"the renderer requires {key}; a crop missing it is discarded entirely")

    def test_the_surface_declares_the_shape_and_the_cropper_obeys(self):
        # A cropper that picked its own ratio would silently discard the tenant's framing on save.
        self.assertIn("ratios", self._cropper())
        field = (pathlib.Path(__file__).resolve().parents[1]
                 / "dashboard/src/components/shared/ImageUploadField.vue").read_text()
        self.assertIn(':ratios="ratios"', field, "the field must pass the surface's allowance straight through")


class CssIsolationTests(unittest.TestCase):
    """Nothing outside the crop rule may size a cropped image.

    A cropped box positions its image absolutely and sizes it from the custom properties, so a stray
    width / height / object-fit / max-height corrupts that geometry. The ribbon's mobile rule
    (`.sl-page-ribbon .sl-ribbon-media img`, specificity 0,2,1) beat the crop rule (0,1,1), so the crop was
    wrong on phones -- while desktop was right only because the two tie and the crop rule happened to sit
    later in the file. Correct by source order is not correct.
    """

    CROPPABLE_CONTAINERS = [".sl-ribbon-media", ".sl-author-photo", ".sl-content-media"]

    def _css(self):
        from stripe_link.runtime.html import render_template_styles
        return "\n".join(render_template_styles({}))

    def test_no_rule_on_a_croppable_container_can_size_the_image(self):
        css = self._css()
        for container in self.CROPPABLE_CONTAINERS:
            for rule in re.findall(r"[^{}\n]*" + re.escape(container) + r"[^{}\n]*\bimg\s*\{[^}]*\}", css):
                selector, body = rule.split("{", 1)
                if not any(prop in body for prop in ("max-height:", "object-fit:", "height:", "width:")):
                    continue
                with self.subTest(selector=selector.strip()[:80]):
                    self.assertIn(":not(.sl-cropped)", selector,
                                  "this rule outranks or ties the crop rule and corrupts the geometry")

    def test_each_croppable_container_actually_has_such_a_rule(self):
        # If a selector is renamed the loop above silently matches nothing and passes forever.
        css = self._css()
        for container in self.CROPPABLE_CONTAINERS:
            with self.subTest(container=container):
                self.assertIn(f"{container}:not(.sl-cropped) img", css)

    def test_the_shared_rule_imposes_no_appearance_of_its_own(self):
        # It briefly set border-radius:1rem -- the ribbon's -- which would have squared off the author
        # photo's circle. The crop box clips; the surface keeps its own look.
        rule = re.search(r"\.sl-cropped\{[^}]*\}", self._css()).group(0)
        self.assertNotIn("border-radius", rule)

    def test_every_placement_surface_actually_renders_its_crop(self):
        """Every PLACEMENT surface must crop end to end. Asset surfaces deliberately render nothing --
        their stored URL is already the cropped derivative, so applying a rect again would double-crop.

        A surface listed but not wired is a lie the cropper cannot detect: the tenant is offered a shape
        picker, frames a photo, and the page ignores it.
        """
        from stripe_link.runtime.html import render_author_bio, render_content_blocks

        root = pathlib.Path(__file__).resolve().parents[1]
        declared = set(json.loads((root / "src/stripe_link/image_ratios.json").read_text())["placement"])
        crop = {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "ar": 1}
        rendered = {
            "page_ribbon": render_page_ribbon({**RendererTests.SECTION, "image_crop": dict(crop)}),
            "author_bio": render_author_bio({
                "id": "ab", "type": "author_bio", "name": "Jo",
                "photo_url": "https://i/x/large.webp", "image_crop": dict(crop)}),
            "content_block": render_content_blocks({
                "id": "cb", "type": "content_block",
                "blocks": [{"title": "T", "body": "B", "image_url": "https://i/x/large.webp",
                            "image_crop": dict(crop)}]}),
        }
        self.assertEqual(declared, set(rendered),
                         "a declared surface with no coverage here is one nobody has proven crops")
        for surface, html in rendered.items():
            with self.subTest(surface=surface):
                self.assertIn("sl-cropped", html, f"{surface} is declared croppable but ignores its crop")


class MechanismTests(unittest.TestCase):
    """A surface is cropped one way or the other, never both and never neither.

    PLACEMENT crops are clipped in CSS at render time, so the stored URL is the original. ASSET crops are
    baked into a derivative, so the stored URL is ALREADY cropped. Wire a surface the wrong way and you get
    one of two silent failures: an asset image clipped again on top of a baked crop, or a placement image
    whose crop is stored and never applied.
    """

    def _table(self):
        return json.loads((pathlib.Path(__file__).resolve().parents[1]
                           / "src/stripe_link/image_ratios.json").read_text())

    def test_no_surface_is_declared_under_both_mechanisms(self):
        table = self._table()
        overlap = set(table["placement"]) & set(table["asset"])
        self.assertEqual(overlap, set(), "a surface cropped twice is cropped wrong")

    def test_asset_surfaces_bake_and_placement_surfaces_do_not(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        table = self._table()
        sources = {
            "dashboard/src/components/Services.vue": set(table["asset"]),
            "dashboard/src/components/LandingPages.vue": set(table["placement"]),
        }
        for path, surfaces in sources.items():
            text = (root / path).read_text()
            for surface in surfaces:
                with self.subTest(surface=surface):
                    self.assertIn(surface, text, f"{surface} is declared but nothing in {path} uses it")
        # Matches the `bake` PROP on a component, not the word "baked" in prose.
        bake_prop = re.compile(r"^\s+:?bake(=|\s*$)", re.M)
        builder = (root / "dashboard/src/components/LandingPages.vue").read_text()
        self.assertIsNone(bake_prop.search(builder),
                          "a placement surface that bakes would store a cropped URL and clip it again")
        services = (root / "dashboard/src/components/Services.vue").read_text()
        self.assertIsNotNone(bake_prop.search(services),
                             "an asset surface must bake or its crop never reaches og:image")

    def test_the_renderer_only_knows_about_placement_surfaces(self):
        from stripe_link.domain.image_crop import ASSET_SURFACES, PLACEMENT_SURFACES

        renderer = (pathlib.Path(__file__).resolve().parents[1]
                    / "src/stripe_link/runtime/html.py").read_text()
        for surface in PLACEMENT_SURFACES:
            with self.subTest(placement=surface):
                self.assertIn(f'"{surface}"', renderer, "a placement crop is applied by the renderer")
        for surface in ASSET_SURFACES:
            with self.subTest(asset=surface):
                self.assertNotIn(f'cropped_media(\n', "")  # readability no-op
                self.assertNotIn(f'"{surface}", "sl-', renderer,
                                 "an asset crop is already in the file; clipping it again double-crops")


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
