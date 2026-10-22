"""Opening an offer-less page in the builder must not rewrite it (plans/OFFERLESS_PAGES_IN_BUILDER.md P2).

Storefront, category and store-profile pages are created by the wizard and, from P2 on, edited in the
builder. That makes the load/save pair a round trip across two different code paths, and the failure mode is
quiet: the tenant opens the page to add a paragraph, and the save drops the grid, renames a section id, or
re-mints a field the wizard had written. `section_order` and per-section overrides are keyed by section id,
so a renumbered id silently discards a tenant's arrangement.

`offerlessSections` / `offerlessState` are in the shared composable precisely so this can run: they are pure
data, and the round trip through both has to be the identity.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "dashboard" / "src" / "composables" / "pageComposer.js"
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

# Exactly what the create wizard writes today (buildStorefrontPageDocument / buildCategoryPageDocument /
# buildProfilePageDocument in LandingPages.vue). If the wizard changes shape, these fixtures must too --
# which is the point: the builder has to keep reading what the wizard writes.
WIZARD_SECTIONS = {
    "storefront": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store",
         "tagline": "Good things, fairly priced", "logo_url": "https://images.example.com/logo.png"},
        {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "col_all",
         "heading": "Shop everything"},
    ],
    "storefront_minimal": [
        # No tagline, no logo, no grid heading -- the fields the wizard omits when left blank.
        {"id": "brand-hero", "type": "brand_hero", "headline": "Probe Store"},
        {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "col_all"},
    ],
    "category": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "Widgets"},
        {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "col_cat", "heading": "Widgets"},
    ],
    "profile": [
        {"id": "brand-hero", "type": "brand_hero", "headline": "About our store"},
        {"id": "seller-profile", "type": "seller_profile", "heading": "About our store"},
    ],
}


def _node(script: str) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return result.stdout.strip()


def _roundtrip(pages: dict) -> dict:
    """page name -> the sections the builder would SAVE after loading that page."""
    script = f"""
    import fs from 'fs';
    const src = fs.readFileSync({json.dumps(str(MIRROR))}, 'utf8');
    const stub = src.replace(/^import rules.*$/m,
      'const rules = {{elements:{{}},governed_sections:[],offer_types:{{}},packs:{{}},goals:{{}}}};');
    const m = await import('data:text/javascript,' + encodeURIComponent(stub));
    const pages = {json.dumps(pages)};
    const out = {{}};
    for (const [name, page] of Object.entries(pages)) {{
      const shape = page.offer_id ? '' : m.offerlessComposition(page);
      // What populateBuilderFromPage assigns, then what builderSectionCandidates emits from it.
      const state = {{ ...m.offerlessState(page), name: page.name || '' }};
      out[name] = {{ shape, sections: m.offerlessSections(shape, state) }};
    }}
    // Drop undefined-valued keys the way cleanObject does before the document is sent.
    console.log(JSON.stringify(out));
    """
    return json.loads(_node(script))


class RoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node is not available")
        pages = {
            name: {"page_id": f"pg_{name}", "name": "Internal name", "sections": sections}
            for name, sections in WIZARD_SECTIONS.items()
        }
        cls.result = _roundtrip(pages)

    def test_the_shape_is_recognised(self):
        self.assertEqual(self.result["storefront"]["shape"], "storefront")
        self.assertEqual(self.result["storefront_minimal"]["shape"], "storefront")
        self.assertEqual(self.result["category"]["shape"], "storefront")
        self.assertEqual(self.result["profile"]["shape"], "store_profile")

    def test_a_wizard_created_page_survives_the_round_trip_unchanged(self):
        for name, original in WIZARD_SECTIONS.items():
            with self.subTest(page=name):
                saved = self.result[name]["sections"]
                self.assertEqual(saved, original,
                                 f"the builder rewrote {name}'s sections")

    def test_section_ids_are_stable(self):
        """section_order and per-section overrides are keyed by id, so a renumbered id discards the
        tenant's arrangement with no error."""
        for name in WIZARD_SECTIONS:
            with self.subTest(page=name):
                ids = [s["id"] for s in self.result[name]["sections"]]
                self.assertEqual(ids, [s["id"] for s in WIZARD_SECTIONS[name]])
                for section_id in ids:
                    self.assertRegex(section_id, r"^[a-z-]+$", "an id was generated, not fixed")

    def test_a_grid_without_a_collection_is_not_persisted(self):
        """The Collection is the grid's source of truth; a grid with no collection_id resolves to an empty
        grid that renders nothing, so saving one would persist a blank section."""
        page = {"page_id": "pg_x", "name": "x", "sections": [
            {"id": "brand-hero", "type": "brand_hero", "headline": "Store"},
        ]}
        out = _roundtrip({"no_grid": page})["no_grid"]
        self.assertEqual(out["shape"], "storefront")
        self.assertEqual([s["type"] for s in out["sections"]], ["brand_hero"])

    def test_the_headline_falls_back_to_the_page_name_not_to_blank(self):
        """A brand_hero with no headline is a page with no H1 at all. The wizard always writes one, so this
        only fires for a page whose hero was emptied -- and the page name is the one thing always present."""
        page = {"page_id": "pg_y", "name": "My Shop", "sections": [
            {"id": "brand-hero", "type": "brand_hero"},
            {"id": "catalog-grid", "type": "catalog_grid", "collection_id": "c1"},
        ]}
        out = _roundtrip({"blank": page})["blank"]
        self.assertEqual(out["sections"][0]["headline"], "My Shop")

    def test_an_offer_page_gets_no_offerless_sections(self):
        page = {"page_id": "pg_o", "name": "Offer page", "offer_id": "off_1",
                "sections": [{"id": "hero", "type": "hero", "headline": "Buy"}]}
        out = _roundtrip({"offer": page})["offer"]
        self.assertEqual(out["shape"], "")
        self.assertEqual(out["sections"], [])


class BuilderWiringTests(unittest.TestCase):
    """Source assertions for the wiring the round trip cannot see, each pinned to a specific regression."""

    def test_the_offerless_guard_is_gone_from_editPage(self):
        body = BUILDER.split("function editPage(page) {", 1)[1].split("\n}", 1)[0]
        code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
        self.assertNotIn("isStorefrontPage", code,
                         "editPage still reroutes offer-less pages away from the builder")
        self.assertIn("populateBuilderFromPage", code)

    def test_grid_membership_editing_keeps_an_entry_point(self):
        """Dropping the guard orphaned editOfferlessPage, which still owns the one thing the builder
        deliberately does not edit. Losing it would be a capability regression, not a cleanup."""
        self.assertIn('@click="editOfferlessPage(page)"', BUILDER)

    def test_the_price_selector_is_gated_on_the_composition(self):
        """`offerIntent(null)` answers "transaction", so the intent check alone would have put a price
        selector bound to offer_id "" on a storefront."""
        self.assertIn('if (intent === "transaction" && sectionVisible("offer_price_selector"))', BUILDER)

    def test_an_offerless_page_is_neither_transaction_nor_lead_gen(self):
        """Every `intent === "transaction"` branch must be false for these pages -- post_checkout mints a
        thank-you page, and `sale`/`flash_sale` are priced views of an offer that does not exist."""
        body = BUILDER.split("const builderIntent = computed(", 1)[1].split("\n", 1)[0]
        self.assertIn("builder.offerless", body)
        self.assertIn('"offerless"', body)

    def test_the_three_sections_have_editors(self):
        block = BUILDER.split("const SECTION_EDITORS = {", 1)[1].split("};", 1)[0]
        for key in ("brand_hero", "catalog_grid", "seller_profile"):
            with self.subTest(section=key):
                self.assertRegex(block, rf"\b{key}:")
                self.assertIn(f"sectionEditor.row.editor === '{key}'", BUILDER)

    def test_the_builder_composition_key_puts_the_offer_first(self):
        body = BUILDER.split("const builderOfferType = computed(", 1)[1].split("\n", 1)[0]
        self.assertIn("builder.offerless ||", body)
        # And the flag may only be set for a page with no offer, which is what makes that equivalent to
        # page_composition_key's guard.
        populate = BUILDER.split("function populateBuilderFromPage(page) {", 1)[1][:4000]
        self.assertIn("page.offer_id ? \"\" : offerlessComposition(page)", populate)

    def test_the_emission_lives_in_the_composable_not_the_component(self):
        """Keep business logic out of Vue components (CLAUDE.md), and it is what makes the round trip above
        runnable at all."""
        self.assertIn("offerlessSections(builder.offerless, builder)", BUILDER)
        self.assertNotIn('id: "brand-hero",', BUILDER.split("function builderSectionCandidates", 1)[1])


if __name__ == "__main__":
    unittest.main()
