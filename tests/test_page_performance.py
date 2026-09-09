"""Two rendering invariants that cost real page-speed score when they broke.

Both were found measuring a published artifact against PageSpeed, not by reading code, and neither shows up
as a bug in the output -- the page looks correct in every case. That is exactly why they need pinning.
"""
import json
import pathlib
import re
import unittest

from stripe_link.runtime.html import rendition_base, render_page, responsive_img

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSET = "https://images.juniorbay.com/offers/abc123"


def _fixture(name):
    return json.loads((ROOT / "schemas" / "examples" / name).read_text(encoding="utf-8"))


class NoRenderBlockingScriptTests(unittest.TestCase):
    """The interactions script must stay OUT of <head>.

    It is ~50KB of INLINE script, and `defer` is specified to do nothing without a `src` -- so there is no
    attribute that makes it non-blocking where it used to sit. In <head> it stopped the parser before any
    content painted, which PageSpeed charges twice: once to LCP, once to Total Blocking Time.
    """

    def setUp(self):
        page, offer = _fixture("page-creatine-standard.json"), _fixture("offer-creatine-standard.json")
        product = _fixture("product-creatine-gummies.json")
        self.html = render_page(page, offer, {product.get("product_id"): product})
        self.head = self.html.split("</head>", 1)[0]
        self.body = self.html.split("</head>", 1)[1]

    # The analytics adapter stays in <head> deliberately: Google documents its snippet as "as high in the
    # head as possible" so a pageview survives a fast bounce, and that is worth a ~2.5KB parser pause. This
    # cap is the line between that deliberate trade and the 50KB one that was not.
    MAX_HEAD_INLINE_SCRIPT = 8_000

    def test_nothing_large_blocks_the_head(self):
        for body in re.findall(r'<script(?![^>]*\bsrc=)(?![^>]*type="application/)[^>]*>(.*?)</script>',
                               self.head, re.S):
            with self.subTest(bytes=len(body)):
                self.assertLessEqual(
                    len(body), self.MAX_HEAD_INLINE_SCRIPT,
                    "an inline script this size in <head> stalls first paint, and an inline script cannot "
                    "be deferred -- move it to the end of <body>",
                )

    def test_the_interactions_script_is_not_in_the_head(self):
        # A marker unique to that script: the analytics adapter also hooks DOMContentLoaded, legitimately.
        self.assertNotIn("data-sl-current-year", self.head)

    def test_the_interactions_script_still_ships_just_later(self):
        # Moving it must not silently drop it -- the page's behaviour depends on it.
        self.assertIn("data-sl-current-year", self.body)


class OriginalUrlRenditionTests(unittest.TestCase):
    """An image stored as its ORIGINAL url must still get the webp srcset.

    A page shipped a 2000px 250KB PNG because the url ended `/original.png`, the rendition regex missed, and
    responsive_img fell through to its plain-tag branch -- while a 12KB small.webp existed for that very
    asset. The image looked fine, which is why it survived so long.
    """

    def test_an_original_image_url_resolves_to_its_rendition_base(self):
        for ext in ("png", "jpg", "jpeg", "webp"):
            with self.subTest(ext=ext):
                self.assertEqual(rendition_base(f"{ASSET}/original.{ext}"), ASSET)

    def test_an_original_image_url_gets_a_srcset_and_a_sized_src(self):
        tag = responsive_img(f"{ASSET}/original.png", "ESPN", sizes="100vw")
        self.assertIn("srcset=", tag)
        self.assertIn(f"{ASSET}/medium.webp", tag)
        self.assertNotIn("original.png", tag)

    def test_original_is_never_offered_inside_the_srcset(self):
        # It is only a key for recovering the base; serving it would reintroduce the very problem.
        srcset = re.search(r'srcset="([^"]*)"', responsive_img(f"{ASSET}/original.png", "x", sizes="100vw"))
        self.assertNotIn("original", srcset.group(1))

    def test_a_video_original_is_left_alone(self):
        # There are no webp renditions of an mp4; rewriting one would break the video.
        self.assertIsNone(rendition_base(f"{ASSET}/original.mp4"))
        self.assertIn("original.mp4", responsive_img(f"{ASSET}/original.mp4", "clip", sizes="100vw"))


if __name__ == "__main__":
    unittest.main()
