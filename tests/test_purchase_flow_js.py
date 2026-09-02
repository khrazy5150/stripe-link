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
MODULE = ROOT / "dashboard" / "src" / "composables" / "purchaseFlow.js"

PRODUCTS = {
    "p1": {"name": "Creatine Gummies", "prices": [{"price_id": "pr1", "unit_amount": 3900, "currency": "usd"}]},
    "p2": {"name": "NAD Supplement", "prices": [
        {"price_id": "pr2", "unit_amount": 1445, "currency": "usd"},
        {"price_id": "pr2d", "unit_amount": 900, "currency": "usd"}]},
    "p4": {"name": "Protein Shaker Bottle", "prices": [{"price_id": "pr4", "unit_amount": 953, "currency": "eur"}]},
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

TIERED = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "p1", "price_id": "pr1", "placement": {"group": "main_offer"},
     "selectable_prices": [{"price_id": "a"}, {"price_id": "b"}, {"price_id": "c"}]},
]}

MISSING = {"purchase_opportunities": [
    {"stage": "landing", "product_id": "gone_from_store", "price_id": "x", "placement": {"group": "main_offer"}},
]}


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
        cls.out = run({"modern": MODERN, "legacy": LEGACY, "tiered": TIERED, "missing": MISSING})
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

    def test_amount_is_currency_aware_not_a_hardcoded_dollar_sign(self):
        # The bump is priced in EUR; a hardcoded "$" would have mislabelled a real tenant's money.
        self.assertEqual(self.out["modern"][1]["items"][0]["chips"], ["EUR 9.53"])

    def test_a_tiered_landing_item_names_the_choice_instead_of_one_price(self):
        self.assertEqual(self.out["tiered"][0]["items"][0]["chips"], ["3 quantity tiers"])

    def test_a_product_missing_from_the_store_still_renders(self):
        self.assertEqual(self.out["missing"][0]["items"][0]["product"]["name"], "gone_from_store")


if __name__ == "__main__":
    unittest.main()
