import unittest

from stripe_link.domain.categories import (
    CURATED_CATEGORIES,
    PRODUCT_TYPES,
    PROMOTION_THRESHOLD,
    category_label,
    is_promoted,
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


if __name__ == "__main__":
    unittest.main()
