"""`put_if_absent` and `increment_counter` on the real DynamoDocumentRepository.

Both exist for the coupon redemption ledger (plans/COUPONS_COMPLETION.md, Option B slice 1), and both are
about the same failure: counting a thing twice, or losing a count. Exercised against a table that actually
honours a ConditionExpression and an ADD, because a fake repository would only test the fake.
"""

import unittest

from stripe_link.repositories.documents import DynamoDocumentRepository
from tests.test_mode_scoped_repository import FakeTable


class ConditionalFakeTable(FakeTable):
    """FakeTable plus the two behaviours these primitives depend on."""

    class ConditionalCheckFailedException(Exception):
        pass

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["PK"], Item["SK"])
        if ConditionExpression and "attribute_not_exists" in ConditionExpression and key in self.items:
            raise self.ConditionalCheckFailedException("The conditional request failed")
        super().put_item(Item=Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, ReturnValues=None):
        assert UpdateExpression.startswith("ADD "), UpdateExpression
        field = ExpressionAttributeNames["#field"]
        amount = ExpressionAttributeValues[":amount"]
        item = self.items.setdefault((Key["PK"], Key["SK"]), dict(Key))
        item[field] = int(item.get(field) or 0) + amount
        return {"Attributes": {field: item[field]}}


def _repo(table):
    return DynamoDocumentRepository(
        "jb-fake-table", document_type="coupon_redemption", id_field="redemption_id", table=table)


def _document(redemption_id="redemption_cs_1"):
    return {"document_type": "coupon_redemption", "tenant_id": "t1",
            "redemption_id": redemption_id, "discount_amount": 1000}


class PutIfAbsentTests(unittest.TestCase):
    def setUp(self):
        self.table = ConditionalFakeTable()
        self.repo = _repo(self.table)

    def test_the_first_write_wins(self):
        self.assertTrue(self.repo.put_if_absent(_document()))
        self.assertEqual(self.repo.get("t1", "redemption_cs_1")["discount_amount"], 1000)

    def test_the_second_is_refused_and_changes_nothing(self):
        self.repo.put_if_absent(_document())

        second = {**_document(), "discount_amount": 9999}
        self.assertFalse(self.repo.put_if_absent(second))
        self.assertEqual(self.repo.get("t1", "redemption_cs_1")["discount_amount"], 1000)

    def test_a_different_id_is_not_blocked(self):
        self.repo.put_if_absent(_document())
        self.assertTrue(self.repo.put_if_absent(_document("redemption_cs_2")))

    def test_a_real_failure_is_not_swallowed_as_a_duplicate(self):
        class Broken(ConditionalFakeTable):
            def put_item(self, Item, ConditionExpression=None):
                raise RuntimeError("table is on fire")

        with self.assertRaises(RuntimeError):
            _repo(Broken()).put_if_absent(_document())

    def test_it_refuses_a_document_with_no_id(self):
        from stripe_link.repositories.documents import RepositoryError

        with self.assertRaises(RepositoryError):
            self.repo.put_if_absent({"tenant_id": "t1"})


class IncrementCounterTests(unittest.TestCase):
    def setUp(self):
        self.table = ConditionalFakeTable()
        self.repo = DynamoDocumentRepository(
            "jb-fake-table", document_type="coupon", id_field="coupon_id", table=self.table)
        self.repo.put({"document_type": "coupon", "tenant_id": "t1", "coupon_id": "c1",
                       "redemption_count": 0})

    def test_it_returns_the_new_value(self):
        self.assertEqual(self.repo.increment_counter("t1", "c1", "redemption_count"), 1)
        self.assertEqual(self.repo.increment_counter("t1", "c1", "redemption_count"), 2)

    def test_concurrent_bumps_all_land(self):
        # The reason this is an ADD and not a read-modify-write put: on a cap of 500, a lost increment is
        # a 501st buyer getting a discount the tenant capped.
        for _ in range(50):
            self.repo.increment_counter("t1", "c1", "redemption_count")

        self.assertEqual(self.repo.get("t1", "c1")["redemption_count"], 50)

    def test_an_absent_counter_starts_at_the_amount(self):
        self.repo.put({"document_type": "coupon", "tenant_id": "t1", "coupon_id": "c2"})
        self.assertEqual(self.repo.increment_counter("t1", "c2", "redemption_count"), 1)


if __name__ == "__main__":
    unittest.main()
