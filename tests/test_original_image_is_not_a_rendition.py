"""The upload must not store an `original.*` URL whose renditions do not exist.

Found 2026-10-12: an Author Bio photo rendered as alt text inside an empty circle on a live page.

    .../offers/<id>/original.jpg  -> HTTP 200
    .../offers/<id>/{thumb,small,medium,large}.webp -> HTTP 403   (none were ever made)

The processor copies the original FIRST and makes the variants afterwards, so the original is servable
within milliseconds. The dashboard's poll probed at 400ms, `original` was in its candidate list, it won
the race, and the upload reported success -- while processing went on to produce nothing. The page then
stored `.../original.jpg` and `responsive_img` asked for `.../medium.webp`.

**The renderer is NOT the place to fix this**, and that was the first attempt. `responsive_img` rewrites
an original into its rendition ladder on purpose: `tests/test_page_performance.py` records a page that
shipped a 2000px 250KB PNG because that rewrite was missing, while a 12KB small.webp existed for the same
asset. From the URL alone, "renditions exist" and "processing failed" are indistinguishable -- so fixing
it there trades one real defect for another.

It is fixed at the source instead: `original` is only accepted once the processor reports `complete`.
After that, a stored original means processing finished, which is exactly when the ladder exists.
"""
import unittest


class TheUploadPollNoLongerRacesTheProcessor(unittest.TestCase):
    """Static guards -- there is no JS test runner in this repo."""

    def source(self, name):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / name).read_text()

    def test_original_is_gated_on_completion(self):
        js = self.source("api/uploads.js")
        self.assertIn('const settled = body.status === "complete"', js)
        self.assertIn("allowOriginal: settled", js)

    def test_the_candidate_list_can_exclude_it(self):
        js = self.source("api/uploads.js")
        self.assertIn("allowOriginal ? urls.original : null", js)

    def test_renditions_are_still_accepted_immediately(self):
        """A rendition cannot load before it has been made, so it needs no gate -- and gating it would
        add a poll cycle to every upload for nothing."""
        js = self.source("api/uploads.js")
        # Sliced to the NEXT function, not to the first "}" -- the signature destructures
        # `{ allowOriginal = true } = {}`, so the first brace closes the parameter, not the body.
        candidates = js[js.index("function imageUrlCandidates"):]
        candidates = candidates[:candidates.index("function cdnImageUrl")]
        for rung in ("urls.small?.webp", "urls.medium?.webp", "urls.large?.webp"):
            self.assertIn(rung, candidates)
            self.assertNotIn(f"allowOriginal ? {rung}", candidates)

    def test_a_completed_upload_with_only_an_original_still_resolves(self):
        """`complete` with no variants is a real answer -- a PNG/TIFF kept as-is, or a non-image. The gate
        must not turn those into a 180-second timeout."""
        js = self.source("api/uploads.js")
        self.assertIn("allowOriginal: settled", js)
        self.assertNotIn("allowOriginal: false", js)


class OneUploadFlow(unittest.TestCase):
    """Products carried its own presign-upload-poll, with its own candidate list and its own timings. The
    ONLY thing protecting it was a larger opening delay (1200ms vs 400ms) -- it had the same bug and lost
    the race less often. Two copies of one flow means a fix lands in one of them."""

    def source(self, name):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / name).read_text()

    def test_products_uses_the_shared_uploader(self):
        vue = self.source("components/Products.vue")
        self.assertIn('uploadImage(file, { basePrefix: "products" })', vue)

    def test_the_duplicate_is_gone_entirely(self):
        """Leaving it would imply there are still two answers to "is this image ready?"."""
        vue = self.source("components/Products.vue")
        for dead in ("pollProductImageUrl", "productImageUrlCandidates", "function imageUrlLoads"):
            self.assertNotIn(dead, vue)

    def test_the_landing_builder_shares_it(self):
        self.assertIn("await uploadImage(file)", self.source("components/LandingPages.vue"))


class TheRendererKeepsItsPerformanceFix(unittest.TestCase):
    """Pinned here as well as in test_page_performance, because this file is where someone will come
    looking after the next broken image and the temptation is to 'fix' it one layer too late."""

    def test_an_original_url_still_gets_its_rendition_ladder(self):
        from stripe_link.runtime.html import responsive_img
        tag = responsive_img("https://images.juniorbay.com/offers/abc/original.png", "x", sizes="100vw")
        self.assertIn("srcset", tag)
        self.assertIn("medium.webp", tag)


if __name__ == "__main__":
    unittest.main()
