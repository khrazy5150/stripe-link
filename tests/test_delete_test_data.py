"""DEV-only delete-all-test-data admin handler (parity with stripe-cart)."""
import json
import os
import unittest
from unittest.mock import patch

from handlers.admin_delete_test_data import handler


class FakeTable:
    def __init__(self, name, key_attrs, items, partition_style):
        self.name = name
        self.key_schema = [{"AttributeName": key_attrs[0], "KeyType": "HASH"}]
        if len(key_attrs) > 1:
            self.key_schema.append({"AttributeName": key_attrs[1], "KeyType": "RANGE"})
        self.items = items  # list of dicts
        self.partition_style = partition_style  # "pk" | "tenant_id" | "session"
        self.deleted = []

    def query(self, **kwargs):
        # Emulate: return items whose partition attr matches the KeyConditionExpression value.
        # We stashed the target value on the condition via a simple contains check on repr — instead, just
        # return items tagged for this tenant (tests pre-tag items with _match=True).
        return {"Items": [i for i in self.items if i.get("_match")]}

    def scan(self, **kwargs):
        return {"Items": [i for i in self.items if i.get("_match")]}

    def batch_writer(self):
        table = self

        class _Batch:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def delete_item(self_inner, Key):
                table.deleted.append(Key)

        return _Batch()


class FakeDynamo:
    def __init__(self, tables):
        self.tables = tables

    def Table(self, name):
        return self.tables[name]


def _pk_item(match=True):
    return {"PK": "TENANT#t1", "SK": "PRODUCT#p1", "_match": match}


class DeleteTestDataTests(unittest.TestCase):
    def _event(self, method="POST"):
        return {"httpMethod": method, "requestContext": {}, "headers": {"X-Tenant-Id": "t1"},
                "body": json.dumps({"tenant_id": "t1"})}

    def test_blocked_in_prod(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "prod"}):
            resp = handler(self._event(), None)
        self.assertEqual(resp["statusCode"], 403)

    def test_options_ok(self):
        resp = handler(self._event("OPTIONS"), None)
        self.assertEqual(resp["statusCode"], 200)

    def test_requires_tenant(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            resp = handler({"httpMethod": "POST", "requestContext": {}, "headers": {}, "body": "{}"}, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_deletes_tenant_partition_and_skips_stripe_without_key(self):
        # Env maps each *_TABLE to a fake table name; only PRODUCTS has a matching item to delete.
        env = {"ENVIRONMENT": "dev"}
        table_envs = ["PRODUCTS_TABLE", "OFFERS_TABLE", "COUPONS_TABLE", "PAGES_TABLE", "LEADS_TABLE",
                      "REVIEWS_TABLE", "CARTS_TABLE", "INVOICES_TABLE", "NOTIFICATIONS_TABLE",
                      "CUSTOMERS_TABLE", "ORDERS_TABLE", "REFUNDS_TABLE", "LEDGER_TABLE", "CHECKOUT_SESSIONS_TABLE"]
        tables = {}
        for name in table_envs:
            env[name] = name.lower()
            if name == "PRODUCTS_TABLE":
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [_pk_item(), _pk_item()], "pk")
            elif name == "CHECKOUT_SESSIONS_TABLE":
                tables[name.lower()] = FakeTable(name, ["session_id", "tenant_id"], [{"session_id": "cs1", "tenant_id": "t1", "_match": True}], "session")
            elif name in ("CUSTOMERS_TABLE", "ORDERS_TABLE", "REFUNDS_TABLE", "LEDGER_TABLE"):
                tables[name.lower()] = FakeTable(name, ["tenant_id", "id"], [], "tenant_id")
            else:
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [], "pk")

        class NoKeyStripeRepo:
            def get(self, tenant_id, mode="test"):
                return {}

        class Cipher:
            def decrypt(self, *a, **k):
                return ""

        with patch.dict(os.environ, env, clear=False):
            resp = handler(self._event(), None, dynamodb=FakeDynamo(tables),
                           stripe_repo=NoKeyStripeRepo(), secret_cipher=Cipher())
        body = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["deleted"]["products"], 2)
        self.assertEqual(body["deleted"]["checkout_sessions"], 1)
        self.assertEqual(body["deleted"]["offers"], 0)
        # No test key configured → Stripe cleanup skipped, not attempted.
        self.assertEqual(body["stripe"], {"skipped": "no_test_key"})


if __name__ == "__main__":
    unittest.main()
