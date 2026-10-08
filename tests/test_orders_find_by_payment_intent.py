"""A KEYS_ONLY GSI gives back keys, not the document.

`PaymentIntentIndex` on the orders table is `KEYS_ONLY`, so the query answers with the base-table keys and
nothing else. That was harmless while the keys WERE `tenant_id` + `order_id`: a keys-only projection
happened to carry everything a caller needed. The mode retrofit changed the keys to PK/SK, and
`without_keys()` strips exactly those — leaving `{payment_intent_id}` and nothing to identify the order.

Measured on a LIVE refund, 2026-10-07:

    RepositoryError: Document tenant_id is required.
      reconcile_charge_refunded -> orders_repo.put(updated)

The refund reached Stripe and the buyer, and the webhook could not write it back. Nothing in the suite
noticed, because the fake repository implements `find_by_payment_intent` itself and never runs this code.
The fake table here answers a GSI query the way DynamoDB does.
"""
import unittest

from stripe_link.repositories.documents import TenantRangeRepository, tenant_mode_pk


ORDER = {
    "PK": tenant_mode_pk("t_1", "live"),
    "SK": "ord_1",
    "tenant_id": "t_1",
    "order_id": "ord_1",
    "payment_intent_id": "pi_1",
    "amount_total": 145,
    "stripe_mode": "live",
}


class KeysOnlyIndexTable:
    """Answers a PaymentIntentIndex query with the KEYS the real index projects, and nothing more."""

    def __init__(self, items):
        self.items = {(i["PK"], i["SK"]): i for i in items}
        self.get_item_calls = 0

    def query(self, **kwargs):
        assert kwargs.get("IndexName") == "PaymentIntentIndex"
        wanted = kwargs["KeyConditionExpression"]._values[1]
        hits = [i for i in self.items.values() if i.get("payment_intent_id") == wanted]
        # KEYS_ONLY: base-table keys plus the index key. Nothing else crosses the wire.
        return {"Items": [{"PK": h["PK"], "SK": h["SK"], "payment_intent_id": h["payment_intent_id"]}
                          for h in hits[:kwargs.get("Limit", 10)]]}

    def put_item(self, Item, **kwargs):
        self.items[(Item["PK"], Item["SK"])] = Item

    def get_item(self, Key):
        self.get_item_calls += 1
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": item} if item else {}


class ResolvingAnOrderFromAPaymentIntentTests(unittest.TestCase):
    def _repo(self, table):
        return TenantRangeRepository("jb-orders-test", id_field="order_id", table=table, mode="live")

    def test_it_returns_the_whole_order_not_the_index_stub(self):
        table = KeysOnlyIndexTable([ORDER])
        order = self._repo(table).find_by_payment_intent("pi_1")
        self.assertIsNotNone(order)
        self.assertEqual(order["tenant_id"], "t_1", "a stub with no tenant_id cannot be written back")
        self.assertEqual(order["order_id"], "ord_1")
        self.assertEqual(order["amount_total"], 145)
        self.assertEqual(table.get_item_calls, 1, "the row has to be fetched; the index does not carry it")

    def test_the_result_can_be_written_back(self):
        """The actual failure: reconcile_charge_refunded sets aggregates and puts the order."""
        table = KeysOnlyIndexTable([ORDER])
        repo = self._repo(table)
        order = repo.find_by_payment_intent("pi_1")
        order["amount_refunded"] = 145
        repo.put(order)  # raised "Document tenant_id is required." before the fix

    def test_keys_are_still_stripped_from_the_result(self):
        order = self._repo(KeysOnlyIndexTable([ORDER])).find_by_payment_intent("pi_1")
        self.assertNotIn("PK", order)
        self.assertNotIn("SK", order)

    def test_an_unknown_payment_intent_is_none(self):
        self.assertIsNone(self._repo(KeysOnlyIndexTable([ORDER])).find_by_payment_intent("pi_absent"))
