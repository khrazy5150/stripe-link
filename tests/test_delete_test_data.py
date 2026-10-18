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


def _pk_item(match=True, mode="test", pid="p1"):
    """A mode-scoped document as the repository writes it: the mode is in the SK AND on the row."""
    return {"PK": "TENANT#t1", "SK": f"PRODUCT#{mode}#{pid}", "stripe_mode": mode, "_match": match}


def _unmoded_item(sk="REVIEW#r1"):
    """A document from a type that is NOT mode-scoped (reviews, leads, notifications). Nothing on it says
    which books it belongs to, so nothing may assume."""
    return {"PK": "TENANT#t1", "SK": sk, "_match": True}


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
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [
                    _pk_item(mode="test", pid="p1"), _pk_item(mode="test", pid="p2"),
                    _pk_item(mode="live", pid="p3"),   # the tenant's real product, in the same partition
                ], "pk")
            elif name == "CHECKOUT_SESSIONS_TABLE":
                # Real session ids carry their books: cs_test_… / cs_live_…
                tables[name.lower()] = FakeTable(name, ["session_id", "tenant_id"], [
                    {"session_id": "cs_test_1", "tenant_id": "t1", "_match": True},
                    {"session_id": "cs_live_2", "tenant_id": "t1", "_match": True},
                ], "session")
            elif name == "SERVICES_TABLE":
                # A shared table: appointment + slot_lock are DATA (delete by prefix); service is SETUP (keep).
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [
                    {"PK": "TENANT#t1", "SK": "APPOINTMENT#test#a1", "stripe_mode": "test",
                     "_match": True, "_sk_prefix": "APPOINTMENT#"},
                    {"PK": "TENANT#t1", "SK": "SLOTLOCK#test#f#2026", "stripe_mode": "test",
                     "_match": True, "_sk_prefix": "SLOTLOCK#"},
                    {"PK": "TENANT#t1", "SK": "SERVICE#s1", "_match": True},  # setup — no prefix tag → never returned
                ], "pk")
            elif name in ("CUSTOMERS_TABLE", "ORDERS_TABLE", "REFUNDS_TABLE", "LEDGER_TABLE"):
                # Money tables key on PK=TENANT#{id}#{mode} since the decoupling — not on `tenant_id`.
                tables[name.lower()] = FakeTable(name, ["PK", "SK"], [
                    {"PK": "TENANT#t1#test", "SK": "order_cs_test_1", "_match": True},
                ], "pk")
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
        self.assertEqual(body["deleted"]["orders"], 1)  # money tables query PK=TENANT#t1#test
        self.assertEqual(body["deleted"]["checkout_sessions"], 1)  # the live session survives
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


class LiveDataSurvivesTests(unittest.TestCase):
    """What this action must NEVER do, now that a tenant can be in test mode on a backend holding their
    live documents (plans/STRIPE_MODE_DECOUPLING.md). Before this, it deleted the whole partition."""

    def _run(self, items, *, mode="test", key_attrs=("PK", "SK")):
        env = {"ENVIRONMENT": "dev", "PRODUCTS_TABLE": "products_table"}
        table = FakeTable("PRODUCTS_TABLE", list(key_attrs), items, "pk")
        event = {"httpMethod": "POST", "requestContext": {}, "headers": {"X-Tenant-Id": "t1"},
                 "body": json.dumps({"tenant_id": "t1", "mode": mode})}

        class NoKeyStripeRepo:
            def get(self, tenant_id, mode="test"):
                return {}

        class Cipher:
            def decrypt(self, *a, **k):
                return ""

        with patch.dict(os.environ, env, clear=False):
            resp = handler(event, None, dynamodb=FakeDynamo({"products_table": table}),
                           stripe_repo=NoKeyStripeRepo(), secret_cipher=Cipher())
        return resp, table, json.loads(resp["body"])

    def test_a_live_document_in_the_same_partition_is_not_deleted(self):
        """THE regression this guards. Both modes share PK=TENANT#{id}; only the sort key separates them."""
        _, table, body = self._run([_pk_item(mode="live", pid="real")])
        self.assertEqual(table.deleted, [])
        self.assertEqual(body["deleted"]["products"], 0)

    def test_test_and_live_side_by_side(self):
        _, table, body = self._run([_pk_item(mode="test", pid="t"), _pk_item(mode="live", pid="l")])
        self.assertEqual(body["deleted"]["products"], 1)
        self.assertEqual([k["SK"] for k in table.deleted], ["PRODUCT#test#t"])

    def test_a_document_that_proves_nothing_is_KEPT_and_counted(self):
        """Leads, reviews and notifications are not mode-scoped. Nothing on them says which books they
        belong to, so they are left alone — and said out loud rather than silently skipped."""
        _, table, body = self._run([_unmoded_item()])
        self.assertEqual(table.deleted, [])
        self.assertEqual(body["kept_not_mode_scoped"]["products"], 1)

    def test_the_sort_key_alone_is_proof_enough(self):
        """A document written before `stripe_mode` was stored still reads TYPE#test#id."""
        _, table, body = self._run([{"PK": "TENANT#t1", "SK": "PRODUCT#test#old", "_match": True}])
        self.assertEqual(body["deleted"]["products"], 1)

    def test_live_mode_is_refused_outright(self):
        """Not scoped down to test behind the caller's back — refused, so the mistake is visible."""
        resp, table, body = self._run([_pk_item(mode="test")], mode="live")
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(body["error"], "live_mode")
        self.assertEqual(table.deleted, [])

    def test_the_response_names_the_mode_it_acted_on(self):
        _, _, body = self._run([_pk_item()])
        self.assertEqual(body["mode"], "test")


if __name__ == "__main__":
    unittest.main()
