"""The per-asset alt sidecar (page/offer/product `image_alts`).

Alt text was never actually MISSING before this: all fourteen responsive_img call sites already passed a
fallback derived from surrounding data. The problem was that many of those fallbacks are generic --
"Content image", "Product", "Offer", "Quote" -- which passes the accessibility check while telling a
screen-reader user and a crawler nothing. The sidecar lets a tenant describe the asset once, keyed by
rendition base so the description follows the image everywhere it is reused.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime import html as H

BASE = "https://images.juniorbay.com/offers/abc123"


class DescribedAltTests(unittest.TestCase):
    def tearDown(self):
        H._RENDER_ALTS_INDEX.clear()

    def test_a_tenant_description_beats_the_derived_fallback(self):
        H._RENDER_ALTS_INDEX.update(H.collect_image_alts({"image_alts": {BASE: "Bottle of NAD+ capsules"}}))
        tag = H.responsive_img(f"{BASE}/medium.webp", "Product", sizes="100vw")
        self.assertIn('alt="Bottle of NAD+ capsules"', tag)
        self.assertNotIn('alt="Product"', tag)

    def test_without_a_description_every_call_site_keeps_the_alt_it_always_passed(self):
        tag = H.responsive_img(f"{BASE}/medium.webp", "Product", sizes="100vw")
        self.assertIn('alt="Product"', tag)

    def test_a_blank_description_falls_back_rather_than_blanking_the_alt(self):
        # An empty alt on a content image is the very thing accessibility_warnings flags, so a tenant
        # clearing the field must not be able to create the warning they were trying to silence.
        H._RENDER_ALTS_INDEX.update(H.collect_image_alts({"image_alts": {BASE: "   "}}))
        self.assertIn('alt="Product"', H.responsive_img(f"{BASE}/medium.webp", "Product", sizes="100vw"))

    def test_one_description_covers_every_rendition_and_placement_of_the_asset(self):
        H._RENDER_ALTS_INDEX.update(H.collect_image_alts({"image_alts": {f"{BASE}/large.webp": "A rose garden"}}))
        for size in ("thumb", "small", "medium", "large", "full"):
            with self.subTest(size=size):
                self.assertIn('alt="A rose garden"', H.responsive_img(f"{BASE}/{size}.webp", "x", sizes="100vw"))

    def test_a_non_rendition_url_can_still_carry_a_description(self):
        ext = "https://cdn.example.com/logo.png"
        H._RENDER_ALTS_INDEX.update(H.collect_image_alts({"image_alts": {ext: "Acme logo"}}))
        self.assertIn('alt="Acme logo"', H.responsive_img(ext, "Client", sizes="100vw"))

    def test_descriptions_merge_across_documents_without_conflict(self):
        merged = H.collect_image_alts(
            {"image_alts": {f"{BASE}/medium.webp": "from the page"}},
            {"image_alts": {"https://images.juniorbay.com/offers/zzz/medium.webp": "from the product"}},
            None,
            {"image_alts": "not a dict"},
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[BASE], "from the page")

    def test_alt_text_is_escaped(self):
        H._RENDER_ALTS_INDEX.update(H.collect_image_alts({"image_alts": {BASE: 'a "quoted" <b>thing</b>'}}))
        tag = H.responsive_img(f"{BASE}/medium.webp", "x", sizes="100vw")
        self.assertNotIn("<b>", tag)
        self.assertIn("&quot;quoted&quot;", tag)


class ImageAltsValidationTests(unittest.TestCase):
    FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples" / "page-creatine-standard.json"

    def _page(self, alts):
        page = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        page["image_alts"] = alts
        return page

    def test_a_well_formed_sidecar_validates(self):
        validate_page_document(self._page({BASE: "A description"}))
        validate_page_document(self._page({}))

    def test_malformed_sidecars_are_refused(self):
        for bad in ([], {"": "x"}, {BASE: 123}, {BASE: None}, {BASE: "x" * 251}):
            with self.subTest(bad=bad), self.assertRaises(DocumentValidationError):
                validate_page_document(self._page(bad))

    def test_a_blank_description_is_allowed_because_it_means_no_override(self):
        validate_page_document(self._page({BASE: ""}))


if __name__ == "__main__":
    unittest.main()
