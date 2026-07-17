import unittest

from stripe_link.domain.categories import is_promoted
from stripe_link.repositories.documents import ProductCategoriesRepository


class FakeCategoriesTable:
    """A faithful-enough DynamoDB double for the exact operations record_usage/get/list use: string-set ADD
    (atomic, idempotent) and SET with if_not_exists. Not a general expression engine."""

    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get(Key["category_key"])
        return {"Item": dict(item)} if item else {}

    def scan(self, **kwargs):
        return {"Items": [dict(v) for v in self.items.values()]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        item = self.items.setdefault(Key["category_key"], {"category_key": Key["category_key"]})
        # ADD clause: union string sets.
        add = UpdateExpression.split("ADD ", 1)[1].split(" SET ", 1)[0]
        for part in add.split(","):
            field, valref = part.strip().split(" ")
            item.setdefault(field, set())
            item[field] = set(item[field]) | set(ExpressionAttributeValues[valref])
        # SET clause: if_not_exists writes only on first sight; updated_at always.
        if "label = if_not_exists(label, :label)" in UpdateExpression:
            item.setdefault("label", ExpressionAttributeValues[":label"])
        if "created_at = if_not_exists(created_at, :now)" in UpdateExpression:
            item.setdefault("created_at", ExpressionAttributeValues[":now"])
        item["updated_at"] = ExpressionAttributeValues[":now"]


class ProductCategoriesRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeCategoriesTable()
        self.repo = ProductCategoriesRepository("jb-product-categories-test", table=self.table)

    def test_distinct_tenants_accumulate_and_dedup(self):
        self.repo.record_usage("artisan_candles", "Artisan Candles", "physical", "tenant_a", now=1)
        self.repo.record_usage("artisan_candles", "Artisan Candles", "physical", "tenant_a", now=2)  # same tenant
        self.repo.record_usage("artisan_candles", "Artisan Candles", "physical", "tenant_b", now=3)
        item = self.repo.get("artisan_candles")
        self.assertEqual(item["tenant_ids"], {"tenant_a", "tenant_b"})  # a counted once
        self.assertFalse(is_promoted(item))
        self.repo.record_usage("artisan_candles", "Artisan Candles", "physical", "tenant_c", now=4)
        self.assertTrue(is_promoted(self.repo.get("artisan_candles")))

    def test_first_label_wins_and_types_accumulate(self):
        self.repo.record_usage("artisan_candles", "Artisan Candles", "physical", "a", now=1)
        self.repo.record_usage("artisan_candles", "artisan candles", "digital", "b", now=2)  # different casing + type
        item = self.repo.get("artisan_candles")
        self.assertEqual(item["label"], "Artisan Candles")   # first write wins
        self.assertEqual(item["types"], {"physical", "digital"})

    def test_blank_key_or_tenant_is_a_noop(self):
        self.repo.record_usage("", "x", "physical", "a", now=1)
        self.repo.record_usage("k", "x", "physical", "", now=1)
        self.assertEqual(self.repo.list_all(), [])

    def test_non_jb_table_refused(self):
        with self.assertRaises(Exception):
            ProductCategoriesRepository("product-categories-test")  # missing jb- prefix


if __name__ == "__main__":
    unittest.main()
