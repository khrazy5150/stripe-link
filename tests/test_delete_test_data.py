"""DEV-only delete-all-test-data admin handler (parity with stripe-cart)."""
import json
import os
import unittest
from unittest.mock import patch

from handlers.admin_delete_test_data import handler


def _condition_strings(condition):
    """Collect the literal string operands from a boto3 KeyConditionExpression tree (so the fake can honor an
    SK begins_with without a real DynamoDB)."""
    values = []
    get_expression = getattr(condition, "get_expression", None)
    if not get_expression:
        return [condition] if isinstance(condition, str) else []
    for operand in get_expression().get("values", ()):
        if isinstance(operand, str):
            values.append(operand)
        elif getattr(operand, "get_expression", None):
            values.extend(_condition_strings(operand))
    return values


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
        # Items are pre-tagged with _match. Honor an SK begins_with by matching the item's _sk_prefix tag so a
        # prefix-scoped delete only hits its own document type in a shared table.
        strings = _condition_strings(kwargs.get("KeyConditionExpression"))
        prefixes = [s for s in strings if s.endswith("#") and s not in ("TENANT#",) and not s.startswith("TENANT#")]
        items = [i for i in self.items if i.get("_match")]
        if prefixes:
            items = [i for i in items if i.get("_sk_prefix") in prefixes]
        else:
            items = [i for i in items if "_sk_prefix" not in i]  # whole-partition query skips prefix-only rows
        return {"Items": items}

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
                      "CUSTOMERS_TABLE", "ORDERS_TABLE", "REFUNDS_TABLE", "LEDGER_TABLE",
                      "CHECKOUT_SESSIONS_TABLE", "SERVICES_TABLE"]
        tables = {}
        for name in table_envs:
            env[name] = name.lower()
            if name == "PRODUCTS_TABLE":
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [_pk_item(), _pk_item()], "pk")
            elif name == "CHECKOUT_SESSIONS_TABLE":
                tables[name.lower()] = FakeTable(name, ["session_id", "tenant_id"], [{"session_id": "cs1", "tenant_id": "t1", "_match": True}], "session")
            elif name == "SERVICES_TABLE":
                # A shared table: appointment + slot_lock are DATA (delete by prefix); service is SETUP (keep).
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [
                    {"PK": "TENANT#t1", "SK": "APPOINTMENT#a1", "_match": True, "_sk_prefix": "APPOINTMENT#"},
                    {"PK": "TENANT#t1", "SK": "SLOTLOCK#f#2026", "_match": True, "_sk_prefix": "SLOTLOCK#"},
                    {"PK": "TENANT#t1", "SK": "SERVICE#s1", "_match": True},  # setup — no prefix tag → never returned
                ], "pk")
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
        # Booking DATA deleted by SK prefix; the SERVICES row (setup) in the same table is left alone.
        self.assertEqual(body["deleted"]["appointments"], 1)
        self.assertEqual(body["deleted"]["slot_locks"], 1)
        services_deleted = tables["services_table"].deleted
        self.assertTrue(all(k["SK"] != "SERVICE#s1" for k in services_deleted))
        self.assertEqual(len(services_deleted), 2)  # appointment + slot_lock, not the service
        # No test key configured → Stripe cleanup skipped, not attempted.
        self.assertEqual(body["stripe"], {"skipped": "no_test_key"})


if __name__ == "__main__":
    unittest.main()
