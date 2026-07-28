"""Smart, SEO-descriptive offer slug generation (plans/TODO.md — the software ships good slugs by default)."""
import unittest

from handlers.offers import smart_offer_slug


def _prod(pid, name, category):
    return {"product_id": pid, "name": name, "product_category": category}


def _offer(product_ids, brand=""):
    return {"items": [{"product_id": p, "quantity": 1} for p in product_ids], "presentation": {"brand": brand}}


class SmartOfferSlugTests(unittest.TestCase):
    def test_single_product_uses_brand_and_product_name(self):
        products = {"p1": _prod("p1", "Whey Protein", "dietary_supplement")}
        self.assertEqual(smart_offer_slug(_offer(["p1"], brand="Axel Mart"), products), "axel-mart-whey-protein")

    def test_brand_repeating_a_product_word_is_not_stuttered(self):
        products = {"p1": _prod("p1", "VYHTHV Whey Protein", "dietary_supplement")}
        self.assertEqual(smart_offer_slug(_offer(["p1"], brand="VYHTHV"), products), "vyhthv-whey-protein")

    def test_bundle_with_a_shared_category_names_the_category(self):
        products = {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                    "p2": _prod("p2", "Creatine Gummies", "dietary_supplement")}
        self.assertEqual(
            smart_offer_slug(_offer(["p1", "p2"], brand="Axel Mart"), products),
            "axel-mart-dietary-supplement-bundle",
        )

    def test_bundle_with_mixed_categories_names_the_top_two_products(self):
        products = {"p1": _prod("p1", "Whey Protein", "dietary_supplement"),
                    "p2": _prod("p2", "Yoga Mat", "fitness_gear")}
        self.assertEqual(smart_offer_slug(_offer(["p1", "p2"]), products), "whey-protein-yoga-mat-bundle")

    def test_length_is_capped_but_keeps_the_bundle_descriptor(self):
        products = {"p1": _prod("p1", "Extra Strength Whey Protein Isolate", "dietary_supplement"),
                    "p2": _prod("p2", "Advanced Creatine Monohydrate Powder", "fitness_gear")}
        slug = smart_offer_slug(_offer(["p1", "p2"], brand="Axel Mart"), products)
        self.assertTrue(slug.endswith("-bundle"))
        self.assertLessEqual(len(slug.split("-")), 6)

    def test_stop_words_are_dropped(self):
        products = {"p1": _prod("p1", "The Best Protein for You", "dietary_supplement")}
        self.assertEqual(smart_offer_slug(_offer(["p1"]), products), "best-protein")

    def test_no_products_falls_back_to_offer_name(self):
        self.assertEqual(smart_offer_slug({"name": "Holiday Combo", "items": []}, {}), "holiday-combo")


if __name__ == "__main__":
    unittest.main()
