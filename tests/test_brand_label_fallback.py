"""The brand mark the builder NAMES must be the brand mark the page renders.

Reported 2026-10-13: the "Hide brand name" note read "Removes the ● Poliaxis Nutrition mark" on a page
whose mark actually says "Quill". Not a wording slip -- two different resolutions:

  * the RENDERER (`resolve_business_name`) goes Site organisation name -> tenant business name -> owner
    display name;
  * the BUILDER was calling `offerBrandDefault`, the OFFER brand chain used for SEO titles
    (offer.presentation.brand -> business name -> product name -> ...), which has no idea a Site exists.

The note now names no value at all -- the real mark is visible in the preview beside it, and naming a
value is what produced the wrong one. The PLACEHOLDER on the brand-label field is the one that has to be
right: it promises what publishing will show when the field is left empty.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")


class TheNoteNamesNoValue(unittest.TestCase):
    def test_it_says_brand_name(self):
        self.assertIn("● brand name</strong> mark above the hero", BUILDER)

    def test_it_no_longer_interpolates_a_resolved_brand(self):
        note = re.search(r"Removes the <strong>[^<]*</strong> mark above the hero", BUILDER)
        self.assertIsNotNone(note)
        self.assertNotIn("{{", note.group(0), "an interpolated value here is what was wrong")


class ThePlaceholderTellsTheTruth(unittest.TestCase):
    """A placeholder that names the wrong business is a promise the publish will break."""

    def test_it_reads_the_rendered_mark(self):
        self.assertIn("renderedBrandLabel", BUILDER)
        self.assertIn("""querySelector('[data-section-type="brand_label"]')""", BUILDER)

    def test_the_renderer_emits_that_hook(self):
        """The selector is only as good as the attribute it matches."""
        self.assertIn('data-section-type=\\"brand_label\\"', HTML)

    def test_it_refreshes_when_the_frame_reloads(self):
        self.assertIn("void previewTokenEpoch.value", BUILDER)

    def test_the_offer_chain_survives_only_as_a_fallback(self):
        fallback = re.search(r"const brandLabelFallback = computed\((.|\n)*?\);", BUILDER).group(0)
        self.assertIn("renderedBrandLabel.value ||", fallback)
        self.assertLess(fallback.index("renderedBrandLabel.value"), fallback.index("offerBrandDefault"),
                        "the rendered mark must win; the offer chain is the pre-load guess")

    def test_the_two_chains_really_are_different(self):
        """If they ever converge this test is noise -- but today the renderer starts from the Site and the
        builder's offer chain has no concept of one."""
        server = re.search(r"def resolve_business_name\(\)(.|\n)*?\n\n\n", HTML).group(0)
        self.assertIn("_RENDER_ORG", server)
        builder = re.search(r"function offerBrandDefault\(offer\)(.|\n)*?\n}", BUILDER).group(0)
        self.assertNotIn("site", builder.lower())


if __name__ == "__main__":
    unittest.main()
