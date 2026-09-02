"""Behaviour of dashboard/src/composables/offerItems.js, exercised through node.

This logic is JS-only (no Python counterpart), so there is nothing to hold in parity — but it encodes
rules that were wrong in production and would be easy to regress:

  * items[] is LANDING-ONLY, so "everything in this offer" must read purchase_opportunities
  * funnel counts are PLACEMENTS, not distinct products — an upsell reselling a landing product is still
    a real step, and deduping it hid a configured upsell entirely
  * an order-bump product must be findable by search

Skipped if node is unavailable.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "offerItems.js"

# Roles are DERIVED from these pricing contexts, not from the offer's stored placement — so the fixtures
# have to carry real prices now.
def _p(name, *contexts):
    return {"name": name, "prices": [{"price_id": f"pr_{c}", "context": c, "unit_amount": 1000}
                                     for c in (contexts or ("standard",))]}

PRODUCTS = {
    "p1": _p("Creatine Gummies"), "p2": _p("NAD Supplement", "upsell"), "p3": _p("Whey Protein"),
    "p4": _p("Protein Shaker Bottle", "order_bump"), "p5": _p("Resistance Bands"),
    "svc1": _p("60-Minute Mobile Massage"),
    # For the ordering case: one product per funnel role.
    "b1": _p("Shaker", "order_bump"), "u1": _p("Upgrade A", "upsell"),
    "u2": _p("Upgrade B", "upsell"), "d1": _p("Rescue", "downsell"),
}

WORKOUT_BUNDLE = {
    "items": [{"product_id": "p1"}, {"product_id": "p2"}, {"product_id": "p3"}],
    "purchase_opportunities": [
        {"stage": "landing", "product_id": "p1", "placement": {"group": "main_offer"}},
        {"stage": "landing", "product_id": "p2", "placement": {"group": "main_offer"}},
        {"stage": "landing", "product_id": "p3", "placement": {"group": "main_offer"}},
        {"stage": "checkout", "product_id": "p4", "placement": {"group": "order_bump"}},
        {"stage": "post_purchase", "product_id": "p2", "placement": {"group": "upsell"}},
    ],
}

# Saved before purchase_opportunities existed: items[] IS the landing set, so it must still work.
LEGACY = {"items": [{"product_id": "p1"}, {"service_id": "svc1"}]}

# Document order deliberately scrambled: downsell first, bump last. The rendered line must still read in
# FUNNEL order.
ORDERING = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "p1", "placement": {"group": "main_offer"}},
    {"stage": "post_purchase", "product_id": "d1", "placement": {"group": "downsell"}},
    {"stage": "post_purchase", "product_id": "u1", "placement": {"group": "upsell"}},
    {"stage": "post_purchase", "product_id": "u2", "placement": {"group": "upsell"}},
    {"stage": "checkout", "product_id": "b1", "placement": {"group": "order_bump"}},
]}

# p4 carries an order_bump price, so the derived role is "bump" regardless of what the document stored.
MANY = {"purchase_opportunities": (
    [{"stage": "landing", "product_id": f"p{i}", "placement": {"group": "main_offer"}} for i in (1, 2, 3, 5)]
    + [{"stage": "post_purchase", "product_id": "p4", "placement": {"group": "downsell"}}]
)}


def run_js(expr_map):
    node = shutil.which("node")
    if not node:
        return None
    script = f"""
    import * as m from {json.dumps(str(MODULE))};
    const P = {json.dumps(PRODUCTS)};
    const r = (id) => P[id] || null;
    const offers = {json.dumps(expr_map)};
    const out = {{}};
    for (const [k, offer] of Object.entries(offers)) {{
      out[k] = {{
        summary: m.itemSummary(offer, r),
        title: m.itemSummaryTitle(offer, r),
        search: m.searchableItemText(offer, r),
      }};
    }}
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class OfferItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_js({"bundle": WORKOUT_BUNDLE, "legacy": LEGACY, "many": MANY, "ordering": ORDERING})
        if cls.out is None:
            raise unittest.SkipTest("node not available")

    def test_landing_names_then_role_counts(self):
        self.assertEqual(
            self.out["bundle"]["summary"],
            "Creatine Gummies, NAD Supplement, Whey Protein · 1 bump, 1 upsell",
        )

    def test_an_upsell_reselling_a_landing_product_is_still_counted(self):
        # p2 is BOTH a landing item and the upsell. These words name funnel STEPS, not products, so the
        # step is real and must show. Deduping it (the original rule) hid a configured upsell completely.
        self.assertIn("1 upsell", self.out["bundle"]["summary"])

    def test_counts_come_from_product_pricing_not_the_stored_placement(self):
        # The drift this closes: the card read placement.group while the diagram beside it derived from
        # pricing, so adding a funnel price to a product made them disagree.
        out = run_js({"stale": {"purchase_opportunities": [
            {"stage": "landing", "product_id": "p1", "placement": {"group": "main_offer"}},
            # document says upsell; p4's PRICE says order_bump. Pricing wins, because pricing charges.
            {"stage": "post_purchase", "product_id": "p4", "placement": {"group": "upsell"}},
        ]}})
        self.assertIn("1 bump", out["stale"]["summary"])
        self.assertNotIn("upsell", out["stale"]["summary"])

    def test_roles_read_in_funnel_order_not_document_order(self):
        self.assertEqual(
            self.out["ordering"]["summary"],
            "Creatine Gummies · 1 bump, 2 upsells, 1 downsell",
        )

    def test_order_bump_product_is_searchable(self):
        # The whole point: "where is that Protein Shaker I added?"
        self.assertIn("Protein Shaker Bottle", self.out["bundle"]["search"])
        self.assertIn("p4", self.out["bundle"]["search"])

    def test_title_names_each_funnel_entry_with_its_role(self):
        # The counts are only unambiguous because hovering says which product plays which part.
        title = self.out["bundle"]["title"]
        self.assertIn("Landing: Creatine Gummies, NAD Supplement, Whey Protein", title)
        self.assertIn("Funnel: Protein Shaker Bottle (bump), NAD Supplement (upsell)", title)

    def test_legacy_offer_without_opportunities_still_reads(self):
        self.assertEqual(self.out["legacy"]["summary"], "Creatine Gummies, 60-Minute Mobile Massage")

    def test_more_than_three_landing_items_collapse_and_keep_role_counts(self):
        self.assertEqual(
            self.out["many"]["summary"],
            "Creatine Gummies, NAD Supplement, Whey Protein +1 more · 1 bump, 1 upsell",
        )


if __name__ == "__main__":
    unittest.main()
