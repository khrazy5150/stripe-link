import unittest

from stripe_link.domain.categories import (
    CURATED_CATEGORIES,
    PRODUCT_TYPES,
    PROMOTION_THRESHOLD,
    category_label,
    is_promoted,
    SYSTEM_CATEGORIES,
    normalize_category,
    search_suggestions,
)


class NormalizeCategoryTests(unittest.TestCase):
    def test_folds_near_duplicates_to_one_key(self):
        for text in ("Dietary Supplement", "dietary supplement", "  Dietary   Supplement  ", "DIETARY-SUPPLEMENT"):
            self.assertEqual(normalize_category(text), "dietary_supplement")

    def test_folds_accents(self):
        self.assertEqual(normalize_category("Café Crème"), "cafe_creme")

    def test_punctuation_only_is_empty(self):
        self.assertEqual(normalize_category("!!!"), "")
        self.assertEqual(normalize_category(""), "")

    def test_every_curated_label_round_trips_to_its_key(self):
        # The invariant that keeps the taxonomy from fragmenting: typing a curated label must land on that
        # curated key, not mint a duplicate. Guaranteed because the key IS normalize(label).
        for key, meta in CURATED_CATEGORIES.items():
            self.assertEqual(normalize_category(meta["label"]), key)

    def test_live_product_keys_are_preserved(self):
        # The 5 categories real products already store must still exist, or those products lose their category.
        for key in ("apparel", "dietary_supplement", "course", "professional_services", "other"):
            self.assertIn(key, CURATED_CATEGORIES)


class TypeScopingTests(unittest.TestCase):
    def test_categories_are_scoped_by_product_type(self):
        physical = {r["key"] for r in search_suggestions("", [], product_type="physical", limit=100)}
        service = {r["key"] for r in search_suggestions("", [], product_type="service", limit=100)}
        self.assertIn("apparel", physical)
        self.assertNotIn("apparel", service)
        self.assertIn("plumbing", service)
        self.assertNotIn("plumbing", physical)

    def test_other_is_valid_for_every_type(self):
        for ptype in PRODUCT_TYPES:
            keys = {r["key"] for r in search_suggestions("", [], product_type=ptype, limit=100)}
            self.assertIn("other", keys)

    def test_no_product_type_lists_everything(self):
        self.assertEqual(
            {r["key"] for r in search_suggestions("", [], limit=100)},
            set(CURATED_CATEGORIES),
        )


class PromotionTests(unittest.TestCase):
    def test_promoted_at_the_threshold(self):
        self.assertFalse(is_promoted({"tenant_ids": {"a", "b"}}))
        self.assertTrue(is_promoted({"tenant_ids": set("abc")}))
        self.assertEqual(PROMOTION_THRESHOLD, 3)

    def test_empty_or_missing_is_not_promoted(self):
        self.assertFalse(is_promoted({}))
        self.assertFalse(is_promoted({"tenant_ids": set()}))


class SearchTests(unittest.TestCase):
    def test_curated_matches_by_substring(self):
        self.assertIn("dietary_supplement", [r["key"] for r in search_suggestions("supp", [])])

    def test_promoted_contributed_appears_to_everyone(self):
        contributed = [{"category_key": "artisan_candles", "label": "Artisan Candles",
                        "types": {"physical"}, "tenant_ids": {"a", "b", "c"}}]
        keys = [r["key"] for r in search_suggestions("candle", contributed, product_type="physical")]
        self.assertIn("artisan_candles", keys)

    def test_below_threshold_hidden_from_others_shown_to_owner(self):
        contributed = [{"category_key": "artisan_candles", "label": "Artisan Candles",
                        "types": {"physical"}, "tenant_ids": {"a"}}]
        self.assertNotIn("artisan_candles",
                         [r["key"] for r in search_suggestions("candle", contributed, tenant_id="other")])
        yours = search_suggestions("candle", contributed, tenant_id="a")
        self.assertEqual([r["key"] for r in yours], ["artisan_candles"])
        self.assertEqual(yours[0]["source"], "yours")

    def test_label_prefers_curated_then_provided_then_humanized(self):
        self.assertEqual(category_label("dietary_supplement"), "Dietary Supplement")
        self.assertEqual(category_label("artisan_candles", "Artisan Candles"), "Artisan Candles")
        self.assertEqual(category_label("artisan_candles"), "Artisan Candles")


class SystemCategoryTests(unittest.TestCase):
    """A category the SYSTEM assigns is not one the tenant may pick (author, 2026-09-15).

    "tip" is filed automatically by the Receive-tips purpose so tips group together in the product list. That
    made it a category the tenant had USED, so the picker offered it back to them on every other product —
    and, once three tenants owned a tip jar, it was on course to be promoted to a suggestion for everybody.
    "Tip" is meaningless on a T-shirt, and picking it there files the T-shirt wrongly.
    """

    def _contributed(self, key, label, tenants=("t1",), types=("digital",)):
        return {"category_key": key, "label": label,
                "tenant_ids": set(tenants), "product_types": set(types)}

    def test_the_tenants_own_tip_category_is_not_offered_back(self):
        contributed = [self._contributed("tip", "Tip")]
        keys = [row["key"] for row in search_suggestions("", contributed, tenant_id="t1")]
        self.assertNotIn("tip", keys)

    def test_it_cannot_be_promoted_to_everybody(self):
        # The promotion threshold counts DISTINCT tenants, and every tenant with a tip jar contributes one.
        contributed = [self._contributed("tip", "Tip", tenants=("t1", "t2", "t3", "t4"))]
        keys = [row["key"] for row in search_suggestions("", contributed, tenant_id="t9")]
        self.assertNotIn("tip", keys)

    def test_searching_for_it_by_name_finds_nothing(self):
        contributed = [self._contributed("tip", "Tip")]
        self.assertEqual(search_suggestions("tip", contributed, tenant_id="t1"), [])

    def test_other_contributed_categories_are_untouched(self):
        # The filter is a named set, not a heuristic — nothing else should have gone with it.
        contributed = [self._contributed("tip", "Tip"), self._contributed("hiking_gear", "Hiking Gear")]
        # Past the default page of 20, which the curated list fills on its own.
        keys = [row["key"] for row in search_suggestions("", contributed, tenant_id="t1", limit=500)]
        self.assertIn("hiking_gear", keys)
        self.assertNotIn("tip", keys)

    def test_the_excluded_set_is_named_where_it_can_be_found(self):
        self.assertIn("tip", SYSTEM_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
