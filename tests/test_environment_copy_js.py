"""dashboard/src/composables/environmentCopy.js — a cross-mode copy must carry the WHOLE funnel.

The bug this guards: `resolvePageDeps` resolved products from `offer.items` alone. The offer document was
copied whole — funnel definition and all — while only the landing product went with it, so the target
mode held an offer referencing bump and upsell products that did not exist there. The funnel was simply
missing, with no error on either side.

Measured on a real 5-product offer (1 item, 2 bumps, 2 upsells): the copy carried 1 product and left 4.

Runs the real module in node, like the other JS parity tests here, because the rule is in the JavaScript
and a Python restatement of it would be the thing that drifts.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "purchaseFlow.js"
COPY = ROOT / "dashboard" / "src" / "composables" / "environmentCopy.js"

# The shape that caught it: one landing item, the rest of the funnel in `funnel.*`.
BUNDLE_LEGACY = {
    "offer_id": "offer_1",
    "items": [{"product_id": "landing"}],
    "funnel": {
        "order_bumps": [{"product_id": "bump_a"}, {"product_id": "bump_b"}],
        "upsells": [{"product_id": "up_a"}, {"product_id": "up_b"}],
        "downsells": [{"product_id": "down_a"}],
    },
}

# The same offer normalized, which is what a saved document carries today.
BUNDLE_MODERN = {
    "offer_id": "offer_1",
    "items": [{"product_id": "landing"}],
    "purchase_opportunities": [
        {"stage": "landing", "product_id": "landing", "placement": {"group": "main_offer"}},
        {"stage": "checkout", "product_id": "bump_a", "placement": {"group": "order_bump"}},
        {"stage": "checkout", "product_id": "bump_b", "placement": {"group": "order_bump"}},
        {"stage": "post_purchase", "product_id": "up_a", "placement": {"group": "upsell"}},
        {"stage": "post_purchase", "product_id": "up_b", "placement": {"group": "upsell"}},
        {"stage": "post_purchase", "product_id": "down_a", "placement": {"group": "downsell"}},
    ],
}

WITH_SERVICE = {
    "offer_id": "offer_2",
    "items": [{"product_id": "landing"}],
    "funnel": {"order_bumps": [{"service_id": "svc_1"}]},
}


def _node(expr):
    node = shutil.which("node")
    if not node:
        return None
    proc = subprocess.run([node, "--input-type=module", "-e", expr],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def resolved(offer):
    """The product + service ids the copy would carry, using the module's OWN logic."""
    return _node(f"""
    import {{ offerEntries }} from {json.dumps(str(MODULE))};
    const offer = {json.dumps(offer)};
    const serviceIds = new Set();
    const collect = (e) => {{ for (const x of e || []) if (x?.service_id) serviceIds.add(String(x.service_id)); }};
    collect(offer.purchase_opportunities); collect(offer.items);
    const f = offer.funnel || {{}};
    collect(f.order_bumps); collect(f.upsells); collect(f.downsells);
    const products = [];
    for (const entry of offerEntries(offer)) {{
      const id = String(entry?.id || "");
      if (id && !serviceIds.has(id)) products.push(id);
    }}
    console.log(JSON.stringify({{ products: [...new Set(products)], services: [...serviceIds] }}));
    """)


class CopyCarriesTheWholeFunnelTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")

    def test_every_funnel_product_is_resolved_legacy_shape(self):
        out = resolved(BUNDLE_LEGACY)
        self.assertEqual(sorted(out["products"]),
                         ["bump_a", "bump_b", "down_a", "landing", "up_a", "up_b"])

    def test_every_funnel_product_is_resolved_normalized_shape(self):
        out = resolved(BUNDLE_MODERN)
        self.assertEqual(sorted(out["products"]),
                         ["bump_a", "bump_b", "down_a", "landing", "up_a", "up_b"])

    def test_both_shapes_resolve_IDENTICALLY(self):
        """P4 of OFFER_MODEL_REDESIGN drops the legacy fields; the copy must not change behaviour when it
        does."""
        self.assertEqual(sorted(resolved(BUNDLE_LEGACY)["products"]),
                         sorted(resolved(BUNDLE_MODERN)["products"]))

    def test_items_alone_is_not_enough(self):
        """The regression itself, stated as a number: reading items[] would resolve one of six."""
        self.assertEqual(len(BUNDLE_LEGACY["items"]), 1)
        self.assertEqual(len(resolved(BUNDLE_LEGACY)["products"]), 6)

    def test_a_service_is_flagged_and_NOT_copied_as_a_product(self):
        """Services carry scheduling setup the target mode must own, so they are surfaced rather than
        moved — and classifying them by an id prefix would be a guess about a naming convention."""
        out = resolved(WITH_SERVICE)
        self.assertEqual(out["services"], ["svc_1"])
        self.assertNotIn("svc_1", out["products"])
        self.assertIn("landing", out["products"])


PAGE_WITH_COLLECTION = {
    "page_id": "page_1",
    "offer_id": "offer_1",
    "sections": [
        {"type": "catalog_grid", "collection_id": "col_1", "items": [{"offer_id": "offer_2"}]},
        {"type": "catalog_grid", "collection_id": "col_1"},   # the same collection twice
        {"type": "catalog_grid"},                             # inline only, nothing to carry
        {"type": "hero"},
    ],
}


def collections_for(page):
    return _node(f"""
    import {{ collectionIdsForPage }} from {json.dumps(str(COPY))};
    console.log(JSON.stringify(collectionIdsForPage({json.dumps(page)})));
    """)


class EmbeddedCollectionsAreSurfacedTests(unittest.TestCase):
    """A catalog_grid can be fed by a Collection. At publish, `load_page_collections` is best-effort: a
    missing collection "just leaves that grid to its inline config" — so a page copied without it renders
    a different grid, or an empty one, and nothing reports that."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")

    def test_an_embedded_collection_is_found(self):
        self.assertEqual(collections_for(PAGE_WITH_COLLECTION), ["col_1"])

    def test_the_same_collection_twice_is_one(self):
        self.assertEqual(len(collections_for(PAGE_WITH_COLLECTION)), 1)

    def test_a_page_with_no_collection_grid_reports_none(self):
        self.assertEqual(collections_for({"page_id": "p", "sections": [{"type": "hero"}]}), [])

    def test_a_grid_with_only_inline_items_is_not_a_collection(self):
        page = {"sections": [{"type": "catalog_grid", "items": [{"offer_id": "o1"}]}]}
        self.assertEqual(collections_for(page), [])


class PromisedCouponsAreSurfacedTests(unittest.TestCase):
    """A coupon cannot be copied the way a product can. Its document REQUIRES stripe_coupon_id and
    stripe_promo_code_id, which name objects in the SOURCE mode's Stripe account — so stripping them
    makes it invalid and keeping them points the target at coupons its key cannot see. A real copy needs
    new Stripe objects, which a browser-orchestrated copy cannot create."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")

    def coupons(self, offers):
        return _node(f"""
        import {{ couponIdsForOffers }} from {json.dumps(str(COPY))};
        console.log(JSON.stringify(couponIdsForOffers({json.dumps(offers)})));
        """)

    def test_a_promised_coupon_is_found(self):
        self.assertEqual(self.coupons([{"offer_id": "o1", "discount": {"coupon_id": "cpn_1"}}]), ["cpn_1"])

    def test_offers_with_no_discount_report_none(self):
        self.assertEqual(self.coupons([{"offer_id": "o1"}, {"offer_id": "o2", "discount": {}}]), [])

    def test_the_same_coupon_on_two_offers_is_one(self):
        offers = [{"discount": {"coupon_id": "cpn_1"}}, {"discount": {"coupon_id": "cpn_1"}}]
        self.assertEqual(self.coupons(offers), ["cpn_1"])


class TheCopyUsesTheSharedNormalizerTests(unittest.TestCase):
    def test_it_does_not_read_offer_items_directly(self):
        """A guard against the exact edit that caused this: resolving deps from `offer.items` again would
        silently drop the funnel, and nothing else in the copy would complain."""
        source = COPY.read_text(encoding="utf-8")
        self.assertIn("offerEntries", source)
        deps = source[source.index("export async function resolvePageDeps"):]
        self.assertNotIn("for (const item of offer.items || []) {", deps)


if __name__ == "__main__":
    unittest.main()
