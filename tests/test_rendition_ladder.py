"""stripe-link's srcset widths must match the ladder image-processing actually generates.

`IMAGE_RENDITION_WIDTHS` becomes the `w` descriptor on every srcset entry -- a promise to the browser about
how wide each file is. The files come from a DIFFERENT repository, and nothing connects the two but this
test. Drift means the browser chooses with wrong widths: downloading the 1080 file believing it is 800, or
upscaling an 800 file into a slot that needed 1080.

The ladder now has exactly ONE home: the `SIZES` constant in `imageProcessorApp.js`. It briefly also lived in
a `SizesJson` CloudFormation parameter, which failed twice on 2026-09-08 -- a template `Default` is ignored
once a stack holds a stored value, and SAM's `parameter_overrides` cannot carry JSON in either form (it
mangled the value to `[{`, and the ladder then worked only because parsing threw and the code fell back to
the constant). Removing the parameter is what makes this test meaningful: it reads the value that runs.

Skipped when the sibling repo is not checked out, so it never fails for the wrong reason.
"""
import pathlib
import re
import unittest

from stripe_link.runtime import html as html_module
from stripe_link.runtime.html import IMAGE_RENDITION_WIDTHS, available_renditions

REPO = pathlib.Path(__file__).resolve().parents[2] / "image-processing"
PROCESSOR = REPO / "src" / "imageProcessorApp.js"


@unittest.skipUnless(PROCESSOR.exists(), f"sibling repo not present at {PROCESSOR}")
class RenditionLadderTests(unittest.TestCase):
    def processor_ladder(self) -> dict[str, int]:
        source = PROCESSOR.read_text(encoding="utf-8")
        block = re.search(r"const SIZES\s*=\s*\[(.*?)\n\];", source, re.S)
        self.assertIsNotNone(block, "SIZES not found — has the processor been restructured?")
        return {
            name: int(width)
            for name, width in re.findall(r'name:\s*"(\w+)",\s*width:\s*(\d+)', block.group(1))
        }

    def test_every_width_we_advertise_matches_what_the_processor_produces(self):
        self.assertEqual(
            IMAGE_RENDITION_WIDTHS, self.processor_ladder(),
            "the srcset widths and the processor's ladder have drifted — the browser would be told a file "
            "is a width it is not",
        )

    def test_the_ladder_has_no_second_home(self):
        # The whole point of the 2026-09-08 cleanup. If an env override comes back, this test is reading a
        # value that may not be the one deployed, and it should fail loudly rather than pass misleadingly.
        for path in (PROCESSOR, REPO / "template.yaml", REPO / "samconfig.toml"):
            with self.subTest(file=path.name):
                live = [
                    line for line in path.read_text(encoding="utf-8").splitlines()
                    if "SIZES_JSON" in line and not line.strip().startswith(("#", "//"))
                ]
                self.assertEqual(live, [], f"{path.name} reintroduces a size-ladder override")


class SmallSourceRenditionTests(unittest.TestCase):
    """A srcset must never name a rendition the processor did not emit.

    Reported 2026-09-09: a link-card image rendered broken while its own URL loaded perfectly in the
    address bar. The srcset named medium/large/full for a 225px upload, all of which 403, and
    responsive_img additionally hardcoded `medium.webp` as the plain src -- so the BROWSER's chosen file
    did not exist even though the file we were handed was fine.

    The processor clamps each target to the source and drops a size that collapses onto the previous one,
    so a small upload simply has no large renditions. Rather than reimplement that (it depends on upscale
    settings this repo cannot see, and guessing wrong reintroduces the 403), the rule is: never name a
    rendition wider than the SOURCE. Those can only be upscales -- bytes without detail -- so excluding
    them is right even where the file happens to exist.
    """

    def test_a_small_source_names_only_renditions_that_can_exist(self):
        self.assertEqual(available_renditions(225), ["thumb", "small"])

    def test_a_large_source_is_unchanged(self):
        self.assertEqual(available_renditions(3000), list(IMAGE_RENDITION_WIDTHS))

    def test_upscales_are_excluded_even_when_the_file_exists(self):
        # The 800x420 case from the same page: medium/large/full DO exist, and are upscales of an 800px
        # source. Serving them costs bytes for no detail.
        self.assertEqual(available_renditions(800), ["thumb", "small"])

    def test_unknown_dimensions_change_nothing(self):
        # Legacy images predate the image_dims sidecar and mostly come from large sources. Breaking those
        # to fix a case we cannot detect would trade a known-good for a guess.
        self.assertEqual(available_renditions(0), list(IMAGE_RENDITION_WIDTHS))

    def test_the_src_is_never_a_rendition_the_ladder_excluded(self):
        base = "https://images.example/offers/ABC"
        html_module._RENDER_DIMS_INDEX.clear()
        html_module._RENDER_DIMS_INDEX[base] = (225, 225)
        markup = html_module.responsive_img(f"{base}/small.webp", "Card", sizes="100vw")
        self.assertIn(f'src="{base}/small.webp"', markup)
        for absent in ("medium.webp", "large.webp", "full.webp"):
            self.assertNotIn(absent, markup)
        html_module._RENDER_DIMS_INDEX.clear()

    def test_a_large_source_still_gets_medium_as_its_src(self):
        base = "https://images.example/offers/BIG"
        html_module._RENDER_DIMS_INDEX.clear()
        html_module._RENDER_DIMS_INDEX[base] = (4000, 3000)
        markup = html_module.responsive_img(f"{base}/small.webp", "Card", sizes="100vw")
        self.assertIn(f'src="{base}/medium.webp"', markup)
        html_module._RENDER_DIMS_INDEX.clear()
