"""Every record written to the orders table must satisfy that table's GSI contract.

DynamoDB refuses an indexed attribute that is NULL, an empty string, or the wrong declared type, and it
fails the ENTIRE PutItem -- not just the index. In this handler the order write comes first, so losing it
loses the notification, the ledger entry and the receipt with it.

This has now shipped twice, on two sibling builders writing the SAME table:

  2026-09-22  order_record_from_invoice  created_at as int, payment_intent_id as ""  -> every RENEWAL
  2026-09-20  order_record_from_session  payment_intent_id as None                   -> every SUBSCRIPTION
     .. and again 09-22, and again 09-23 23:28 on a real subscription, Stripe retrying each to no avail

The second is the instructive one. When the renewal broke, the fix and a thorough test class went onto
`order_record_from_invoice` alone -- while its neighbour kept writing `session.get("payment_intent", "")`
into the same index. That default never fires for a subscription: Stripe sends `"payment_intent": null`,
so the key IS present and `.get` returns None. A per-function test could not catch that. This one is
driven by the TABLE, and every builder must pass it.
"""
import pathlib
import re
import unittest

from handlers.stripe_webhook import order_record_from_invoice, order_record_from_session

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")


def orders_table_index_keys() -> dict[str, str]:
    """The orders table's indexed attributes and the types it DECLARES for them, read from the template.

    Asking the template rather than hardcoding a list is the point: add a GSI and every builder is held to
    it without anyone remembering to update this file.
    """
    block = TEMPLATE.split("\n  OrdersTable:", 1)[1].split("\n  ", 1)[0] if "\n  OrdersTable:" in TEMPLATE else ""
    # A generous window: the resource's own body, up to the next top-level resource.
    start = TEMPLATE.index("\n  OrdersTable:")
    rest = TEMPLATE[start + 1:]
    body = re.split(r"\n  [A-Z][A-Za-z0-9]*:\n", rest, maxsplit=1)[0]
    declared = dict(re.findall(r"- AttributeName: (\w+)\s*\n\s*AttributeType: \"?(\w+)\"?", body))
    keyed = set(re.findall(r"- AttributeName: (\w+)\s*\n\s*KeyType: (?:HASH|RANGE)", body))
    assert declared and keyed, f"could not parse OrdersTable ({len(declared)} declared, {len(keyed)} keyed)"
    assert block is not None
    return {name: declared[name] for name in keyed if name in declared}


SUBSCRIPTION_SESSION = {
    # Stripe's real shape for a subscription checkout: the key is PRESENT and null. This is what broke it.
    "id": "cs_test_sub", "mode": "subscription", "payment_intent": None, "subscription": "sub_1",
    "payment_status": "paid", "amount_total": 3291, "currency": "usd", "created": 1790000000,
    "customer_details": {"email": "buyer@example.com", "name": "Buyer"},
    "metadata": {"offer_id": "offer_x", "product_name": "Creatine Gummies"},
}
ONE_TIME_SESSION = {**SUBSCRIPTION_SESSION, "id": "cs_test_pay", "mode": "payment",
                    "payment_intent": "pi_123", "subscription": None}
CYCLE_INVOICE = {"id": "in_1", "billing_reason": "subscription_cycle", "created": 1790000000,
                 "amount_paid": 3291, "currency": "usd", "payment_intent": None,
                 "customer_email": "buyer@example.com", "lines": {"data": []}}

# builder -> the inputs it must survive. A new order-record builder goes here; the completeness test below
# fails until it does.
BUILDERS = {
    "order_record_from_session": [
        ("a subscription (no payment_intent)", lambda: order_record_from_session(SUBSCRIPTION_SESSION, "t1", 100, {})),
        ("a one-time payment", lambda: order_record_from_session(ONE_TIME_SESSION, "t1", 100, {})),
    ],
    "order_record_from_invoice": [
        ("a renewal cycle invoice", lambda: order_record_from_invoice(CYCLE_INVOICE, "t1", 100, {})),
        ("a renewal that does carry one", lambda: order_record_from_invoice({**CYCLE_INVOICE, "payment_intent": "pi_9"}, "t1", 100, {})),
    ],
}

PY_TYPE = {"S": str, "N": (int, float, str)}


class OrdersTableIndexContractTests(unittest.TestCase):
    def test_no_builder_writes_an_indexed_attribute_dynamodb_would_refuse(self):
        index_keys = orders_table_index_keys()
        self.assertIn("payment_intent_id", index_keys, "the index that broke must be among those checked")

        for builder, cases in BUILDERS.items():
            for label, build in cases:
                record = build()
                for attribute, declared in index_keys.items():
                    with self.subTest(builder=builder, case=label, attribute=attribute):
                        if attribute not in record:
                            continue  # absent is the correct way to say "no value" for an indexed key
                        value = record[attribute]
                        self.assertIsNotNone(
                            value, f"{builder} writes {attribute}=None for {label}; DynamoDB reads that as "
                                   "NULL and fails the whole PutItem. Omit the key instead.")
                        self.assertNotEqual(
                            value, "", f"{builder} writes {attribute}='' for {label}; DynamoDB refuses an "
                                       "empty string for an indexed attribute. Omit the key instead.")
                        self.assertIsInstance(
                            value, PY_TYPE[declared],
                            f"{builder} writes {attribute}={value!r} for {label}, but the table declares "
                            f"{attribute} as {declared}")

    def test_the_builder_list_is_complete(self):
        """A third builder must not inherit the blind spot by simply not being listed here."""
        source = (ROOT / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
        found = set(re.findall(r"\ndef (order_record_from_\w+)\(", source))
        self.assertEqual(found, set(BUILDERS), "an order-record builder is missing from BUILDERS")


class SubscriptionPurchasePersistsTests(unittest.TestCase):
    """The end-to-end shape, through a table that refuses what the real one refuses.

    Every existing test of this path passed while prod was losing every subscription purchase, because the
    fake table accepted anything. A fake that enforces the index is the only kind that could have caught it.
    """

    class StrictOrdersTable:
        """Rejects indexed attributes exactly as DynamoDB does, so this test fails without the fix."""

        INDEXED = ("tenant_id", "order_id", "created_at", "payment_intent_id")

        def __init__(self):
            self.items = []

        def put_item(self, Item, **kwargs):  # noqa: N803 - boto3's own signature
            for key in self.INDEXED:
                if key not in Item:
                    continue
                value = Item[key]
                if value is None:
                    raise AssertionError(
                        f"ValidationException: Type mismatch for Index Key {key} Expected: S Actual: NULL")
                if value == "":
                    raise AssertionError(
                        f"ValidationException: A value specified for a secondary index key is not "
                        f"supported. The AttributeValue for {key} must not be empty")
                if not isinstance(value, str):
                    raise AssertionError(
                        f"ValidationException: Type mismatch for Index Key {key} Expected: S Actual: N")
            self.items.append(Item)

    class PlainTable:
        def __init__(self):
            self.items = []

        def put_item(self, Item, **kwargs):  # noqa: N803
            self.items.append(Item)

    def _persist(self, session):
        from handlers.stripe_webhook import persist_checkout_session_completed

        orders = self.StrictOrdersTable()
        sent = []
        result = persist_checkout_session_completed(
            {"id": "evt_1", "livemode": False, "data": {"object": session}},
            tenant_id="tenant_demo",
            checkout_sessions_table=self.PlainTable(),
            orders_table=orders,
            receipt_mailer=lambda **kw: sent.append(kw),
            email_context_loader=lambda tid: {"business_name": "Acme", "support_email": "h@a.com"},
        )
        return result, orders, sent

    def test_a_subscription_purchase_is_recorded_as_an_order(self):
        result, orders, _ = self._persist(SUBSCRIPTION_SESSION)

        self.assertEqual(result["status"], "stored")
        self.assertEqual(len(orders.items), 1)
        self.assertNotIn("payment_intent_id", orders.items[0])

    def test_and_therefore_its_receipt_is_sent(self):
        """The receipt is sent AFTER the order write, so the lost write took the email with it -- which is
        why a real subscription produced a session row and nothing else (prod, 2026-09-23 23:28)."""
        _, _, sent = self._persist(SUBSCRIPTION_SESSION)

        self.assertEqual(len(sent), 1)

    def test_a_one_time_purchase_still_keeps_its_payment_intent(self):
        # The refund path looks an order up by payment_intent_id; omitting it when Stripe DID send one
        # would trade one bug for another.
        _, orders, _ = self._persist(ONE_TIME_SESSION)

        self.assertEqual(orders.items[0]["payment_intent_id"], "pi_123")


if __name__ == "__main__":
    unittest.main()
