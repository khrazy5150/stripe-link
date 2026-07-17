import json
import unittest

from handlers.product_categories import handler as categories_handler
from handlers.products import record_category_usage


class FakeCategoriesRepo:
    def __init__(self, contributed=None):
        self._contributed = contributed or []
        self.recorded = []

    def list_all(self):
        return self._contributed

    def record_usage(self, key, label, product_type, tenant_id, now):
        self.recorded.append((key, label, product_type, tenant_id))


def event(method="GET", params=None):
    return {"httpMethod": method, "queryStringParameters": params or {}}


class SearchEndpointTests(unittest.TestCase):
    def test_returns_curated_scoped_by_type(self):
        resp = categories_handler(event(params={"product_type": "service", "q": "plumb"}), None,
                                  repository=FakeCategoriesRepo())
        body = json.loads(resp["body"])
        keys = [c["key"] for c in body["categories"]]
        self.assertIn("plumbing", keys)
        self.assertNotIn("apparel", keys)

    def test_promoted_contributed_shown_to_all(self):
        repo = FakeCategoriesRepo([
            {"category_key": "artisan_candles", "label": "Artisan Candles",
             "types": {"physical"}, "tenant_ids": {"a", "b", "c"}},
        ])
        resp = categories_handler(event(params={"product_type": "physical", "q": "candle"}), None, repository=repo)
        self.assertIn("artisan_candles", [c["key"] for c in json.loads(resp["body"])["categories"]])

    def test_below_threshold_private_to_owner(self):
        repo = FakeCategoriesRepo([
            {"category_key": "artisan_candles", "label": "Artisan Candles",
             "types": {"physical"}, "tenant_ids": {"tenant_a"}},
        ])
        seen_by_other = categories_handler(
            event(params={"q": "candle", "tenant_id": "tenant_b"}), None, repository=repo)
        self.assertNotIn("artisan_candles", [c["key"] for c in json.loads(seen_by_other["body"])["categories"]])
        seen_by_owner = categories_handler(
            event(params={"q": "candle", "tenant_id": "tenant_a"}), None, repository=repo)
        self.assertIn("artisan_candles", [c["key"] for c in json.loads(seen_by_owner["body"])["categories"]])

    def test_options_preflight(self):
        self.assertEqual(categories_handler(event(method="OPTIONS"), None, repository=FakeCategoriesRepo())["statusCode"], 200)


class RecordUsageHookTests(unittest.TestCase):
    def test_records_a_contributed_category(self):
        repo = FakeCategoriesRepo()
        record_category_usage(
            {"product_category": "Artisan Candles", "product_type": "physical", "tenant_id": "t1"}, repo)
        self.assertEqual(repo.recorded, [("artisan_candles", "Artisan Candles", "physical", "t1")])

    def test_skips_curated_categories(self):
        repo = FakeCategoriesRepo()
        record_category_usage(
            {"product_category": "dietary_supplement", "product_type": "physical", "tenant_id": "t1"}, repo)
        self.assertEqual(repo.recorded, [])

    def test_skips_when_no_category_or_tenant(self):
        repo = FakeCategoriesRepo()
        record_category_usage({"product_category": "", "tenant_id": "t1"}, repo)
        record_category_usage({"product_category": "artisan_candles", "tenant_id": ""}, repo)
        self.assertEqual(repo.recorded, [])

    def test_a_recording_failure_never_raises(self):
        class Boom:
            def record_usage(self, *a):
                raise RuntimeError("dynamo down")
        # Must swallow — a category-table hiccup cannot fail a product save.
        record_category_usage(
            {"product_category": "artisan_candles", "product_type": "physical", "tenant_id": "t1"}, Boom())


if __name__ == "__main__":
    unittest.main()
