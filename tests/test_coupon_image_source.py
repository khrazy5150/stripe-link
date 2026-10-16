"""The coupon's picture is CHOSEN, not inherited from a fallback chain.

Author, 2026-10-15: *"there is no way to get rid of the default image. Worse still, there is no way to
upload an image to replace it."* Both were true, and the second was worse than it looked: the editor showed
a Picture field and the coupon's serializer never carried `image_url`, so anything typed there was
discarded on save.

The renderer used to walk `image_url` -> the offer's product photo -> the platform favicon, so a coupon
always had an image and "none" was unsayable. It now reads one declared source.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.documents import DocumentValidationError, validate_page_document  # noqa: E402
from stripe_link.runtime.html import render_coupon  # noqa: E402

BASE = {"id": "c", "code": "LAUNCH20", "value_text": "20% off", "headline": "Launch week"}
OFFER = {"offer_type": "single", "items": [{"product_id": "p1"}]}
PRODUCTS = {"p1": {"product_id": "p1", "images": ["https://img.example/product.jpg"]}}
PAGE = {"sections": [{"type": "hero_media", "images": ["https://img.example/hero.jpg"]}]}
BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def coupon(**extra):
    return render_coupon({**BASE, **extra}, OFFER, PRODUCTS, "", None, PAGE)


class TheThreeSourcesTests(unittest.TestCase):
    def test_none_renders_no_picture(self):
        self.assertNotIn("sl-coupon-media", coupon(image_source="none"))

    def test_absent_means_none(self):
        """The complaint was an image nobody asked for, so a coupon that never chose one stops having one."""
        self.assertNotIn("sl-coupon-media", coupon())

    def test_hero_uses_the_page_hero(self):
        markup = coupon(image_source="hero")
        self.assertIn("https://img.example/hero.jpg", markup)
        self.assertIn("sl-coupon-media", markup)

    def test_upload_uses_the_uploaded_file(self):
        markup = coupon(image_source="upload", image_url="https://img.example/up.jpg")
        self.assertIn("https://img.example/up.jpg", markup)

    def test_upload_with_nothing_uploaded_renders_no_picture(self):
        self.assertNotIn("sl-coupon-media", coupon(image_source="upload"))


class TheOldFallbacksAreGoneTests(unittest.TestCase):
    def test_the_product_photo_is_never_borrowed(self):
        for source in ("none", "hero", "upload"):
            with self.subTest(source=source):
                self.assertNotIn("product.jpg", coupon(image_source=source, image_url=""))

    def test_the_platform_favicon_is_never_borrowed(self):
        """It was the LAST resort and is the reason an image appeared with nothing configured at all."""
        self.assertNotIn("sl-coupon-media-logo", coupon())


class TheCropTests(unittest.TestCase):
    def test_an_uploaded_image_can_be_cropped(self):
        markup = coupon(image_source="upload", image_url="https://img.example/up.jpg",
                        # Fractions of the source, the shape normalized_crop expects — not pixels.
                        image_crop={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
        self.assertIn("sl-coupon-media", markup)
        self.assertIn("sl-cropped", markup)
        self.assertIn("--sl-crop-ar", markup)

    def test_no_crop_adds_no_markup(self):
        markup = coupon(image_source="upload", image_url="https://img.example/up.jpg")
        self.assertNotIn("sl-cropped", markup)

    def test_the_surface_has_declared_ratios(self):
        import json

        ratios = json.loads((pathlib.Path(__file__).resolve().parents[1]
                             / "src" / "stripe_link" / "image_ratios.json").read_text())
        self.assertIn("coupon", ratios["placement"])


class TheStoredSectionTests(unittest.TestCase):
    def page(self, **coupon_section):
        return {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
                "page_id": "p1", "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                "sections": [{"type": "coupon", "id": "c", "code": "X", **coupon_section}]}

    def test_each_source_validates(self):
        for source in ("none", "hero", "upload"):
            with self.subTest(source=source):
                validate_page_document(self.page(image_source=source))

    def test_a_typo_is_refused(self):
        """Silently meaning "none" would leave a tenant who uploaded an image staring at an empty panel."""
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self.page(image_source="heroic"))


class TheBuilderSavesItTests(unittest.TestCase):
    def serializer(self):
        body = BUILDER.split('if (element.type === "coupon") {', 1)[1]
        return body[:body.index("\n  }")]

    def test_the_picture_now_survives_a_save(self):
        """`image_url` was absent from this serializer entirely, so the Picture field the editor already
        showed was discarded on every save. That is the whole of "no way to upload an image"."""
        body = self.serializer()
        self.assertIn("image_source:", body)
        self.assertIn("image_url: element.image_url", body)
        self.assertIn("image_crop: element.image_crop", body)

    def test_the_file_is_stored_only_when_it_is_the_source(self):
        """A leftover URL from an abandoned upload must not travel with a coupon set to `hero` or `none`."""
        self.assertIn('element.image_source === "upload"', self.serializer())

    def test_a_new_coupon_starts_with_no_image(self):
        new_element = BUILDER.split('if (type === "coupon") return', 1)[1].split(";", 1)[0]
        self.assertIn('image_source: "none"', new_element)

    def test_the_editor_offers_all_three(self):
        self.assertIn('<option value="none">No image</option>', BUILDER)
        self.assertIn('<option value="hero">Same as the hero image</option>', BUILDER)
        self.assertIn('<option value="upload">Upload an image</option>', BUILDER)

    def test_the_uploader_appears_only_for_upload(self):
        self.assertIn("""v-if="element.image_source === 'upload'\"""", BUILDER)


if __name__ == "__main__":
    unittest.main()
