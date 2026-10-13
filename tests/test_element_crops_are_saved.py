"""A crop the tenant made must survive the save.

The author, after the circular guide landed: *"the final image ignores the crop."*

The cropper was never broken. `ImageUploadField` emits the rect and the builder writes it to
`element.image_crop`, which is why the LIVE PREVIEW showed the crop correctly -- it posts the in-memory
document straight to `/pages/render`. The loss was in the serializer: `author_bio`, `content_block` and
`page_ribbon` each build their section field-by-field and simply never listed `image_crop`. The crop
lived until the page was saved and then vanished, so the published page rendered the uncropped image.

`before_after` persisted `before_crop`/`after_crop` correctly all along, which is what made the omission
look like a renderer bug rather than three missing fields.

These are source guards: there is no JS test runner here, and the round trip they protect is
save -> document -> render.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text()
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text()


class TheRendererReadsACrop(unittest.TestCase):
    """What the document must carry. If a renderer stops reading one, its save guard below is pointless
    and should go with it."""

    def test_author_bio(self):
        self.assertIn('section.get("image_crop"), "author_bio"', HTML)

    def test_page_ribbon(self):
        self.assertIn('section.get("image_crop"), "page_ribbon"', HTML)

    def test_content_block_reads_it_off_the_BLOCK(self):
        """Not off the section -- a content_block section holds a list of blocks, each with its own
        image, so a section-level crop would apply one framing to all of them."""
        self.assertIn('block.get("image_crop"), "content_block"', HTML)

    def test_before_after_reads_two(self):
        self.assertIn('section.get("before_crop")', HTML)
        self.assertIn('section.get("after_crop")', HTML)


class TheBuilderSavesIt(unittest.TestCase):
    def serializer(self, element_type):
        """The element -> section mapping, which is what runs on save."""
        start = BUILDER.index(f'if (element.type === "{element_type}")')
        return BUILDER[start:start + 1400]

    def loader(self, element_type):
        """The section -> element mapping, which is what runs when the page is reopened."""
        marker = f'type: "{element_type}"'
        idx = [m.start() for m in re.finditer(re.escape(marker), BUILDER)]
        hits = [BUILDER[i - 200:i + 700] for i in idx if "elements.push" in BUILDER[i - 200:i + 60]]
        self.assertTrue(hits, f"no loader found for {element_type}")
        return "\n".join(hits)

    def test_author_bio_saves_and_reloads_the_crop(self):
        self.assertIn("image_crop: element.image_crop", self.serializer("author_bio"))
        self.assertIn("image_crop: section.image_crop", self.loader("author_bio"))

    def test_page_ribbon_saves_and_reloads_the_crop(self):
        # Asserted on the VALUE, not an exact spelling: the ribbon writes it conditionally, because
        # `centered` has no image slot. Pinning the literal would fail a correct implementation.
        self.assertIn("element.image_crop", self.serializer("page_ribbon"))
        self.assertIn("image_crop: section.image_crop", self.loader("page_ribbon"))

    def test_content_block_saves_the_crop_on_the_block(self):
        saved = self.serializer("content_block")
        self.assertIn("image_crop: element.image_crop", saved)
        self.assertIn("blocks: [{", saved)
        self.assertIn("image_crop: block.image_crop", BUILDER)

    def test_before_after_still_saves_both(self):
        """It was already right; this stops a refactor taking it with the others."""
        saved = self.serializer("before_after")
        self.assertIn("before_crop: element.before_crop", saved)
        self.assertIn("after_crop: element.after_crop", saved)

    def test_the_ribbon_crop_goes_when_its_image_goes(self):
        """`centered` has no image slot, so carrying a crop into a document that ignores the image would
        leave a framing decision attached to nothing."""
        saved = self.serializer("page_ribbon")
        self.assertIn('image_crop: element.presentation === "centered" ? undefined', saved)


class EveryCropBoundInTheUiIsPersisted(unittest.TestCase):
    """Derived, so a NEW element that binds a cropper cannot quietly drop it the way these three did."""

    def bound_fields(self):
        return set(re.findall(r':crop="element\.([a-z_]+)"', BUILDER))

    def test_the_derivation_finds_the_known_ones(self):
        found = self.bound_fields()
        self.assertIn("image_crop", found)
        self.assertIn("before_crop", found)
        self.assertIn("after_crop", found)

    def test_each_bound_crop_field_appears_in_a_serializer(self):
        """Checks the VALUE is read, not how it is spelled -- one element writes it conditionally."""
        serializers = BUILDER[BUILDER.index("function elementToSection") if "function elementToSection" in BUILDER
                              else 0:]
        for field in sorted(self.bound_fields()):
            with self.subTest(field=field):
                self.assertIn(f"element.{field}", serializers,
                              f"{field} is bound to a cropper but no serializer reads it -- the crop "
                              f"will work in the Live Preview and vanish on save")


if __name__ == "__main__":
    unittest.main()
