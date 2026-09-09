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

from stripe_link.runtime.html import IMAGE_RENDITION_WIDTHS

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
