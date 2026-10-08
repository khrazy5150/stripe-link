"""The raw order write has to carry the keys the table actually has.

`_claim_order` writes straight to the boto3 table rather than through a repository, because the
repository cannot express the conditional put that makes exactly one webhook delivery win. That bypass is
what broke: the mode retrofit moved orders to PK/SK and converted every repository, but a put that never
goes through one kept writing the old shape. DynamoDB answered

    ValidationException: Missing the key PK in the item

and a LIVE sale (2026-10-07, evt_1UO4iD21lLbLd4Y5O1NsMIx1) was taken by Stripe and recorded nowhere.

6,179 tests passed throughout, because they all drive the `orders_repo` branch and never the raw one. A
fake that accepts any item cannot fail this way, so the fake here enforces the key schema the real table
has -- the same lesson as the mode-isolation fake that returned every row for every query.
"""
import unittest

from handlers.stripe_webhook import _claim_order


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class KeySchemaEnforcingTable:
    """Rejects a write without PK, the way the real table does."""

    def __init__(self):
        self.items = {}

    def put_item(self, *, Item, ConditionExpression=None):
        if "PK" not in Item:
            raise AssertionError("Missing the key PK in the item")
        if "SK" not in Item:
            raise AssertionError("Missing the key SK in the item")
        key = (Item["PK"], Item["SK"])
        if ConditionExpression == "attribute_not_exists(PK)" and key in self.items:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = Item


ORDER = {"order_id": "ord_1", "amount_total": 145}


class TheClaimCarriesTheKeysTests(unittest.TestCase):
    def test_it_writes_pk_and_sk_scoped_to_tenant_and_mode(self):
        table = KeySchemaEnforcingTable()
        self.assertTrue(_claim_order(table, dict(ORDER), tenant_id="t_1", mode="live"))
        (pk, sk), item = next(iter(table.items.items()))
        self.assertEqual(pk, "TENANT#t_1#live")
        self.assertEqual(sk, "ord_1")
        self.assertEqual(item["stripe_mode"], "live")

    def test_test_and_live_do_not_collide(self):
        table = KeySchemaEnforcingTable()
        _claim_order(table, dict(ORDER), tenant_id="t_1", mode="live")
        _claim_order(table, dict(ORDER), tenant_id="t_1", mode="test")
        self.assertEqual(sorted(pk for pk, _ in table.items),
                         ["TENANT#t_1#live", "TENANT#t_1#test"])

    def test_a_second_delivery_of_the_same_order_does_not_win(self):
        table = KeySchemaEnforcingTable()
        self.assertTrue(_claim_order(table, dict(ORDER), tenant_id="t_1", mode="live"))
        self.assertFalse(_claim_order(table, dict(ORDER), tenant_id="t_1", mode="live"),
                         "the retry must not re-fire the receipt, notification and ledger entry")
        self.assertEqual(len(table.items), 1)

    def test_a_real_error_is_not_swallowed_as_a_lost_race(self):
        class Broken:
            def put_item(self, **_):
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")

        with self.assertRaises(Exception):
            _claim_order(Broken(), dict(ORDER), tenant_id="t_1", mode="live")
