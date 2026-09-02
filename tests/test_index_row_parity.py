"""An index row must render the same card as the full document it projects.

The list screen now loads GET /offers?view=index (~10% of a document) and View/Edit fetch the one full
document they need. That only works if every card-facing helper reads BOTH shapes identically — otherwise
the list and the detail view disagree, which is the drift this codebase keeps producing.

The projection is built by the real server code (domain/offer_index.py) and fed to the real client code
(composables/offerItems.js, purchaseFlow.js) through node, so this is an end-to-end shape check rather
than two hand-written fixtures that happen to agree.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stripe_link.domain.offer_index import offer_index_entry  # noqa: E402

PRODUCTS = {
    "p1": {"name": "Creatine Gummies", "prices": [{"price_id": "s1", "context": "standard", "unit_amount": 3900}],
           "images": ["https://img/creatine.jpg"]},
    "p2": {"name": "NAD Supplement", "prices": [
        {"price_id": "s2", "context": "standard", "unit_amount": 2422},
        {"price_id": "u1", "context": "upsell", "unit_amount": 1445},
        {"price_id": "d1", "context": "downsell", "unit_amount": 900}]},
    "p4": {"name": "Protein Shaker Bottle", "prices": [{"price_id": "b1", "context": "order_bump", "unit_amount": 953}]},
}

FULL_OFFER = {
    "offer_id": "offer_1", "name": "Workout Bundle", "slug": "workout-bundle", "offer_type": "bundle",
    "product_intent": "transaction", "status": "active", "created_at": "1", "updated_at": "2",
    "presentation": {"image_url": "https://img/hero.jpg"},
    "purchase_opportunities": [
        {"stage": "landing", "product_id": "p1", "price_id": "s1", "placement": {"group": "main_offer"}},
        {"stage": "landing", "product_id": "p2", "price_id": "s2", "placement": {"group": "main_offer"}},
        {"stage": "checkout", "product_id": "p4", "price_id": "b1", "placement": {"group": "order_bump"}},
        {"stage": "post_purchase", "product_id": "p2", "price_id": "u1", "placement": {"group": "upsell"}},
    ],
}

TIERED_OFFER = {
    "offer_id": "offer_2", "name": "NAD Tiers", "status": "active",
    "purchase_opportunities": [
        {"stage": "landing", "product_id": "p2", "price_id": "s2", "placement": {"group": "main_offer"},
         "selectable_prices": [{"price_id": "a"}, {"price_id": "b"}, {"price_id": "c"}]},
    ],
}


def render(offer):
    """Card-facing output for one offer, whichever shape it is."""
    node = shutil.which("node")
    if not node:
        return None
    script = f"""
    import {{ itemSummary, itemSummaryTitle, searchableItemText }} from {json.dumps(str(ROOT / "dashboard/src/composables/offerItems.js"))};
    import {{ derivedFunnelEntries, isIndexRow }} from {json.dumps(str(ROOT / "dashboard/src/composables/purchaseFlow.js"))};
    const P = {json.dumps(PRODUCTS)};
    const r = (id) => P[id] || null;
    const offer = {json.dumps(offer)};
    const d = derivedFunnelEntries(offer, r);
    console.log(JSON.stringify({{
      summary: itemSummary(offer, r),
      title: itemSummaryTitle(offer, r),
      search: searchableItemText(offer, r).split(" ").sort().join(" "),
      roles: {{bump: d.order_bump.length, upsell: d.upsell.length, downsell: d.downsell.length}},
      isIndex: isIndexRow(offer),
    }}));
    """
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class IndexRowRendersLikeTheDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node not available")

    def test_card_line_tooltip_and_roles_match(self):
        full = render(FULL_OFFER)
        row = render(offer_index_entry(FULL_OFFER))
        self.assertFalse(full["isIndex"])
        self.assertTrue(row["isIndex"], "the projection must be recognised as an index row")
        self.assertEqual(row["summary"], full["summary"])
        self.assertEqual(row["title"], full["title"])
        self.assertEqual(row["roles"], full["roles"])

    def test_the_card_line_is_the_expected_text_not_merely_equal(self):
        # Equality alone would pass if BOTH were broken.
        self.assertEqual(
            render(offer_index_entry(FULL_OFFER))["summary"],
            "Creatine Gummies, NAD Supplement · 1 bump, 1 upsell, 1 downsell",
        )

    def test_every_item_stays_searchable_through_the_projection(self):
        row = render(offer_index_entry(FULL_OFFER))
        for term in ("Protein Shaker Bottle", "p4", "Creatine Gummies"):
            with self.subTest(term=term):
                self.assertIn(term.split()[0], row["search"])

    def test_a_tiered_offer_projects_the_facts_the_type_rule_needs(self):
        entry = offer_index_entry(TIERED_OFFER)
        self.assertEqual(len(entry["landing_ids"]), 1)
        self.assertEqual(entry["landing_tier_count"], 3)

    def test_the_projection_is_much_smaller(self):
        full = len(json.dumps(FULL_OFFER))
        slim = len(json.dumps(offer_index_entry(FULL_OFFER)))
        self.assertLess(slim, full * 0.6, f"{slim}B vs {full}B")


if __name__ == "__main__":
    unittest.main()
