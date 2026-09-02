"""dashboard/src/composables/purchaseFlow.js — one stage builder for a saved offer, both document shapes.

The bug this guards: the Offers View modal read `purchase_opportunities` while the Landing Pages flow read
the legacy `items[]` + `funnel.*` pair. Both worked only because the two are dual-written; P4 of
plans/OFFER_MODEL_REDESIGN.md drops the legacy fields, and Landing Pages would then have silently lost its
bumps and upsells. The builder must produce IDENTICAL stages from either shape.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys; sys.path.insert(0, str(ROOT / "src"))
MODULE = ROOT / "dashboard" / "src" / "composables" / "purchaseFlow.js"

PRODUCTS = {
    "p1": {"name": "Creatine Gummies", "prices": [{"price_id": "pr1", "unit_amount": 3900, "currency": "usd"}]},
    "p2": {"name": "NAD Supplement", "prices": [
        {"price_id": "pr2", "unit_amount": 1445, "currency": "usd", "context": "upsell"},
        {"price_id": "pr2d", "unit_amount": 900, "currency": "usd", "context": "downsell"}]},
    "p4": {"name": "Protein Shaker Bottle", "prices": [
        {"price_id": "pr4", "unit_amount": 953, "currency": "eur", "context": "order_bump"}]},
    "p3": {"name": "Whey Protein", "prices": [
        {"price_id": "t1", "unit_amount": 2422, "currency": "usd"},
        {"price_id": "t2", "unit_amount": 4159, "currency": "usd"},
        {"price_id": "t3", "unit_amount": 5571, "currency": "usd"}]},
}

MODERN = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "p1", "price_id": "pr1", "placement": {"group": "main_offer"}},
    {"stage": "checkout", "product_id": "p4", "price_id": "pr4", "placement": {"group": "order_bump"}},
    {"stage": "post_purchase", "product_id": "p2", "price_id": "pr2", "placement": {"group": "upsell"}},
    {"stage": "post_purchase", "product_id": "p2", "price_id": "pr2d", "placement": {"group": "downsell"}},
]}

LEGACY = {
    "items": [{"product_id": "p1", "price_id": "pr1"}],
    "funnel": {
        "order_bumps": [{"product_id": "p4", "price_id": "pr4"}],
        "upsells": [{"product_id": "p2", "price_id": "pr2"}],
        "downsells": [{"product_id": "p2", "price_id": "pr2d"}],
    },
}

# Tier price_ids that RESOLVE against the product -> a low–high range.
TIERED = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "p3", "price_id": "t1", "placement": {"group": "main_offer"},
     "selectable_prices": [{"price_id": "t1"}, {"price_id": "t2"}, {"price_id": "t3"}]},
]}

# Tier price_ids that do NOT resolve (stale/removed prices) -> fall back to the single price, never a
# half-built range.
TIERS_UNRESOLVABLE = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "p1", "price_id": "pr1", "placement": {"group": "main_offer"},
     "selectable_prices": [{"price_id": "gone_a"}, {"price_id": "gone_b"}]},
]}

MISSING = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "gone_from_store", "price_id": "x", "placement": {"group": "main_offer"}},
]}


def _node(expr):
    node = shutil.which("node")
    if not node:
        return None
    proc = subprocess.run([node, "--input-type=module", "-e", expr],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def run_sig(cases):
    return _node(f"""
    import {{ funnelSignature }} from {json.dumps(str(MODULE))};
    const cases = {json.dumps(cases)};
    const out = {{}};
    for (const [k, o] of Object.entries(cases)) out[k] = funnelSignature(o);
    console.log(JSON.stringify(out));
    """)


def run_block(cases):
    return _node(f"""
    import {{ funnelSignatureFromBlock }} from {json.dumps(str(MODULE))};
    const cases = {json.dumps(cases)};
    const out = {{}};
    for (const [k, b] of Object.entries(cases)) out[k] = funnelSignatureFromBlock(b);
    console.log(JSON.stringify(out));
    """)


def run(cases):
    node = shutil.which("node")
    if not node:
        return None
    script = f"""
    import {{ stagesFromSavedOffer }} from {json.dumps(str(MODULE))};
    const P = {json.dumps(PRODUCTS)};
    const opts = {{
      resolveProduct: (id) => P[id] || null,
      formatAmount: (a, c) => (c && c !== "usd" ? c.toUpperCase() + " " : "$") + (a / 100).toFixed(2),
    }};
    const cases = {json.dumps(cases)};
    const out = {{}};
    for (const [k, offer] of Object.entries(cases)) out[k] = stagesFromSavedOffer(offer, opts);
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run([node, "--input-type=module", "-e", script],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class PurchaseFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run({"modern": MODERN, "legacy": LEGACY, "tiered": TIERED,
                       "unresolvable": TIERS_UNRESOLVABLE, "missing": MISSING})
        if cls.out is None:
            raise unittest.SkipTest("node not available")

    def test_both_document_shapes_produce_identical_stages(self):
        # The whole point: surviving the P4 migration that deletes items[]/funnel.*.
        self.assertEqual(self.out["modern"], self.out["legacy"])

    def test_stage_order_and_labels(self):
        self.assertEqual([s["key"] for s in self.out["modern"]], ["landing", "checkout", "post_purchase"])
        self.assertEqual(self.out["modern"][1]["label"], "At checkout")

    def test_downsell_nests_under_its_upsell_by_product(self):
        upsell = self.out["modern"][2]["items"][0]
        self.assertEqual(upsell["intent"], "upgrade")
        self.assertEqual(upsell["downsell"]["amount"], "$9.00")

    def test_roles_come_from_product_pricing_not_the_stored_placement(self):
        # Mirrors domain/funnels.funnel_context_items. If this read the offer's stored group instead, the
        # diagram would show a different funnel than the one that actually charges.
        out = run({"claims_nothing": {"items": [{"product_id": "p4"}], "funnel": {}}})
        stages = out["claims_nothing"]
        self.assertIn("checkout", [s["key"] for s in stages])

    def test_amount_is_currency_aware_not_a_hardcoded_dollar_sign(self):
        # The bump is priced in EUR; a hardcoded "$" would have mislabelled a real tenant's money.
        self.assertEqual(self.out["modern"][1]["items"][0]["chips"], ["EUR 9.53"])

    def test_a_tiered_landing_item_shows_its_price_RANGE(self):
        # A tiered item has no single price. The range says what the customer can actually pay, which beats
        # naming the tier count ("3 quantity tiers", the first attempt).
        self.assertEqual(self.out["tiered"][0]["items"][0]["chips"], ["$24.22 – $55.71"])

    def test_unresolvable_tier_prices_fall_back_rather_than_show_half_a_range(self):
        self.assertEqual(self.out["unresolvable"][0]["items"][0]["chips"], ["$39.00"])

    def test_funnel_signature_ignores_landing_and_sorts(self):
        # Only funnel steps matter for the drift check; landing items change for unrelated reasons.
        out = run_sig({
            "saved": MODERN,
            "reordered": {"purchase_opportunities": list(reversed(MODERN["purchase_opportunities"]))},
        })
        self.assertEqual(out["saved"], out["reordered"])
        self.assertNotIn("main_offer", out["saved"])

    def test_signature_detects_an_added_downsell(self):
        # The trap this guards: a downsell price added to a PRODUCT shows in the edit diagram immediately,
        # but the runtime reads the SAVED offer, so no buyer sees it until Update Offer is pressed.
        out = run_sig({"saved": MODERN})
        block_same = {"upsells": [{"product_id": "p2", "price_id": "pr2"}],
                      "order_bumps": [{"product_id": "p4", "price_id": "pr4"}],
                      "downsells": [{"product_id": "p2", "price_id": "pr2d"}]}
        block_added = dict(block_same, downsells=block_same["downsells"] + [{"product_id": "p1", "price_id": "x"}])
        sigs = run_block({"same": block_same, "added": block_added})
        self.assertEqual(sigs["same"], out["saved"])
        self.assertNotEqual(sigs["added"], out["saved"])

    def test_carousel_threshold_matches_the_python_constant(self):
        from stripe_link.domain.funnels import MAX_SEQUENTIAL_UPSELLS
        js = _node(f"""
        import {{ MAX_SEQUENTIAL_UPSELLS }} from {json.dumps(str(MODULE))};
        console.log(JSON.stringify(MAX_SEQUENTIAL_UPSELLS));
        """)
        self.assertEqual(js, MAX_SEQUENTIAL_UPSELLS)

    def test_a_product_missing_from_the_store_still_renders(self):
        self.assertEqual(self.out["missing"][0]["items"][0]["product"]["name"], "gone_from_store")


if __name__ == "__main__":
    unittest.main()
