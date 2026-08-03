import unittest

from stripe_link.repositories.documents import DynamoDocumentRepository


class FakeTable:
    """Minimal in-memory DynamoDB table honouring the key semantics DynamoDocumentRepository relies on:
    get/put/delete by (PK, SK) and a query over PK-eq [+ SK-begins_with] on the base table or GSI1."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def delete_item(self, Key, ReturnValues=None):
        item = self.items.pop((Key["PK"], Key["SK"]), None)
        return {"Attributes": dict(item)} if item else {}

    def query(self, KeyConditionExpression=None, IndexName=None, Limit=None, **_):
        pk_val, sk_prefix, gsi_val = _parse_key_condition(KeyConditionExpression)
        out = []
        for item in self.items.values():
            if IndexName == "GSI1":
                if item.get("GSI1PK") == gsi_val:
                    out.append(dict(item))
            else:
                if item.get("PK") == pk_val and (sk_prefix is None or str(item.get("SK", "")).startswith(sk_prefix)):
                    out.append(dict(item))
            if Limit and len(out) >= Limit:
                break
        return {"Items": out}


def _parse_key_condition(cond):
    """Pull (pk_value, sk_begins_with_prefix, gsi1pk_value) out of a boto3 ConditionBase tree."""
    pk_val = sk_prefix = gsi_val = None
    if cond is None:
        return pk_val, sk_prefix, gsi_val
    for leaf in _leaves(cond):
        expr = leaf.get_expression()
        op = expr["operator"]
        attr = expr["values"][0].name
        value = expr["values"][1]
        if attr == "PK" and op == "=":
            pk_val = value
        elif attr == "SK" and op == "begins_with":
            sk_prefix = value
        elif attr == "GSI1PK" and op == "=":
            gsi_val = value
    return pk_val, sk_prefix, gsi_val


def _leaves(cond):
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        for sub in expr["values"]:
            yield from _leaves(sub)
    else:
        yield cond


def _offer(offer_id, tenant="t1", **extra):
    return {"tenant_id": tenant, "offer_id": offer_id, "name": offer_id, **extra}


class ModeScopedRepositoryTests(unittest.TestCase):
    def _repo(self, table, mode):
        return DynamoDocumentRepository("jb-offers-dev", document_type="offer", id_field="offer_id", table=table, mode=mode)

    def test_same_id_coexists_across_modes(self):
        # The promote case: test + live share an offer_id and must NOT collide (different SK per mode).
        table = FakeTable()
        self._repo(table, "test").put(_offer("off_1", name="test-copy"))
        self._repo(table, "live").put(_offer("off_1", name="live-copy"))

        self.assertEqual(self._repo(table, "test").get("t1", "off_1")["name"], "test-copy")
        self.assertEqual(self._repo(table, "live").get("t1", "off_1")["name"], "live-copy")
        self.assertEqual(len(table.items), 2)

    def test_get_does_not_leak_across_modes(self):
        table = FakeTable()
        self._repo(table, "live").put(_offer("off_live"))
        self.assertIsNone(self._repo(table, "test").get("t1", "off_live"))

    def test_list_is_mode_scoped(self):
        table = FakeTable()
        self._repo(table, "test").put(_offer("off_t"))
        self._repo(table, "live").put(_offer("off_l"))

        test_ids = [o["offer_id"] for o in self._repo(table, "test").list_for_tenant("t1")]
        live_ids = [o["offer_id"] for o in self._repo(table, "live").list_for_tenant("t1")]
        self.assertEqual(test_ids, ["off_t"])
        self.assertEqual(live_ids, ["off_l"])

    def test_put_stamps_stripe_mode_attribute(self):
        table = FakeTable()
        saved = self._repo(table, "test").put(_offer("off_x"))
        self.assertEqual(saved["stripe_mode"], "test")

    def test_delete_is_mode_scoped(self):
        table = FakeTable()
        self._repo(table, "test").put(_offer("off_1"))
        self._repo(table, "live").put(_offer("off_1"))
        # Deleting in test mode leaves the live item intact.
        self.assertIsNotNone(self._repo(table, "test").delete("t1", "off_1"))
        self.assertIsNone(self._repo(table, "test").get("t1", "off_1"))
        self.assertIsNotNone(self._repo(table, "live").get("t1", "off_1"))

    def test_find_by_id_is_mode_scoped(self):
        table = FakeTable()
        self._repo(table, "test").put(_offer("off_1", name="test-copy"))
        self._repo(table, "live").put(_offer("off_1", name="live-copy"))
        self.assertEqual(self._repo(table, "live").find_by_id("off_1")["name"], "live-copy")

    def test_mode_none_keeps_legacy_layout(self):
        table = FakeTable()
        repo = DynamoDocumentRepository("jb-offers-dev", document_type="offer", id_field="offer_id", table=table)
        repo.put(_offer("off_1"))
        (key,) = table.items.keys()
        self.assertEqual(key, ("TENANT#t1", "OFFER#off_1"))
        self.assertNotIn("stripe_mode", table.items[key] | {})  # not force-stamped when mode-agnostic


if __name__ == "__main__":
    unittest.main()
