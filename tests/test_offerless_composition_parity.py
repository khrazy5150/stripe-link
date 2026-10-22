"""The Vue mirror of the offer-less composition must agree with Python (plans/PAGE_COMPOSER.md).

Both renderers read the same composition_rules.json, so the DATA cannot drift -- but the derivation code is
written twice, and the first version of the JS half did not agree with the Python half. `page_composition_key`
guards on "is there an offer", which in Python reads `if offer:` and is correct because `{}` is falsy. The
direct JS translation `if (offer)` is WRONG, because an empty object is truthy there: a storefront page would
have composed as `single` in the builder -- handed a price selector and a Buy CTA -- while the publisher
composed it correctly. A silent disagreement between preview and publish is the failure this whole module is
arranged to prevent, so it gets a test that actually runs both sides.
"""

import json
import subprocess
import unittest
from pathlib import Path

from stripe_link.domain.composition import offerless_composition, page_composition_key

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "dashboard" / "src" / "composables" / "pageComposer.js"

# (page, offer) pairs -> the composition both sides must name. The empty-offer cases are the ones that
# caught the bug; the link hub is the case that must NOT be read off the page.
CASES = [
    ("storefront", {"sections": [{"type": "brand_hero"}, {"type": "catalog_grid"}]}, {}),
    ("storefront", {"sections": [{"type": "catalog_grid"}]}, {}),
    ("storefront", {"sections": [{"type": "brand_hero"}]}, {}),
    ("store_profile", {"sections": [{"type": "brand_hero"}, {"type": "seller_profile"}]}, {}),
    # Marker order: the profile block is the more specific claim when a page carries both.
    ("store_profile", {"sections": [{"type": "catalog_grid"}, {"type": "seller_profile"}]}, {}),
    # No offer-less marker at all -> falls through to the offer-shape derivation.
    ("single", {"sections": [{"type": "hero"}]}, {}),
    # An offer present must win over whatever the page's sections look like.
    ("single", {"sections": [{"type": "brand_hero"}, {"type": "catalog_grid"}]}, {"offer_id": "o1"}),
]


def _node(script: str) -> str:
    return subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    ).stdout.strip()


class MirrorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node is not available")

    def test_both_sides_name_the_same_composition(self):
        """`deriveOfferType` lives in the Vue component, so the mirror takes it as a parameter; the stub here
        stands in for it and returns the offer-shape answer Python's composition_key gives for these fixtures
        (`single`). What is under test is the PAGE-vs-OFFER guard, which is the half that was wrong."""
        script = f"""
        import fs from 'fs';
        const src = fs.readFileSync({json.dumps(str(MIRROR))}, 'utf8');
        const stub = src.replace(
          /^import rules.*$/m,
          'const rules = ' + JSON.stringify({json.dumps(json.dumps({
              "elements": {}, "governed_sections": [], "offer_types": {}, "packs": {}, "goals": {},
          }))}) + ';');
        const m = await import('data:text/javascript,' + encodeURIComponent(stub));
        const cases = {json.dumps([[p, o] for _, p, o in CASES])};
        const derive = () => 'single';
        console.log(JSON.stringify(cases.map(([page, offer]) => m.pageCompositionKey(page, offer, derive))));
        """
        js = json.loads(_node(script) or "[]")
        self.assertEqual(len(js), len(CASES), "the mirror did not evaluate")
        for (expected, page, offer), from_js in zip(CASES, js):
            with self.subTest(page=page, offer=offer):
                from_py = page_composition_key(page, offer)
                self.assertEqual(from_py, expected, "Python disagrees with the fixture")
                self.assertEqual(from_js, expected, "the Vue mirror disagrees with Python")

    def test_an_empty_offer_is_treated_as_no_offer_on_both_sides(self):
        """The specific trap: `{}` is falsy in Python and truthy in JS, so `if (offer)` inverts the guard."""
        page = {"sections": [{"type": "brand_hero"}, {"type": "catalog_grid"}]}
        self.assertEqual(page_composition_key(page, {}), "storefront")
        script = f"""
        import fs from 'fs';
        const src = fs.readFileSync({json.dumps(str(MIRROR))}, 'utf8');
        const stub = src.replace(/^import rules.*$/m,
          'const rules = {{elements:{{}},governed_sections:[],offer_types:{{}},packs:{{}},goals:{{}}}};');
        const m = await import('data:text/javascript,' + encodeURIComponent(stub));
        console.log(m.pageCompositionKey({json.dumps(page)}, {{}}, () => 'single'));
        """
        self.assertEqual(_node(script), "storefront")

    def test_the_mirror_does_not_use_a_bare_truthiness_guard(self):
        """A source assertion as well as a behavioural one: the behavioural test above only fails if someone
        re-breaks it exactly, and this names the mistake so the fix is not re-reverted as redundant."""
        src = MIRROR.read_text(encoding="utf-8")
        body = src.split("export function pageCompositionKey", 1)[1].split("\n}", 1)[0]
        # Comment lines out first -- the comment above the guard NAMES the mistake, and matching that is how
        # this assertion failed on its first run.
        code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
        self.assertNotIn("if (offer)", code)
        self.assertIn("Object.keys(offer).length", code)

    def test_the_offerless_markers_match_python(self):
        script = f"""
        import fs from 'fs';
        const src = fs.readFileSync({json.dumps(str(MIRROR))}, 'utf8');
        const stub = src.replace(/^import rules.*$/m,
          'const rules = {{elements:{{}},governed_sections:[],offer_types:{{}},packs:{{}},goals:{{}}}};');
        const m = await import('data:text/javascript,' + encodeURIComponent(stub));
        console.log(JSON.stringify([
          m.OFFERLESS_COMPOSITIONS,
          ['brand_hero','catalog_grid','seller_profile','hero'].map(
            (t) => m.offerlessComposition({{sections: [{{type: t}}]}})),
        ]));
        """
        compositions, shapes = json.loads(_node(script))
        from stripe_link.domain.composition import OFFERLESS_COMPOSITIONS
        self.assertEqual(compositions, list(OFFERLESS_COMPOSITIONS))
        self.assertEqual(shapes, [
            offerless_composition({"sections": [{"type": t}]})
            for t in ("brand_hero", "catalog_grid", "seller_profile", "hero")
        ])


if __name__ == "__main__":
    unittest.main()
