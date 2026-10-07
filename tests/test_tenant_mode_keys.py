"""Mode lives in the PARTITION key, so a read of one mode cannot reach the other.

It was a filtered attribute: every read fetched both modes' rows and discarded one half AFTER DynamoDB
had been charged for them. Cost and latency scaled with the rows thrown away -- a tenant with 100k orders,
95% of them test, paid to read ~95k rows on every live report.

Not the SORT key, which this repo's own plan first prescribed: for orders the sort key IS `order_id`, a
value written into Stripe PaymentIntent metadata and used as the partition key of two GSIs. Prefixing it
would leak the mode into an identifier that travels to Stripe and joins three tables.

plans/STRIPE_MODE_STORAGE.md.
"""
import unittest

from stripe_link.repositories.documents import (
    KEY_PARTITION,
    KEY_SORT,
    LedgerRepository,
    RefundsRepository,
    RepositoryError,
    TenantRangeRepository,
    tenant_mode_pk,
    with_tenant_mode_keys,
    without_keys,
)


class RecordingTable:
    """Captures what was asked of DynamoDB, so the test can assert on the REQUEST and not just the rows.

    The point of the change is which rows are read, and a fake that only returns data cannot show that.
    """

    def __init__(self, items=None):
        self.items = [dict(i) for i in (items or [])]
        self.queries = []
        self.puts = []

    def put_item(self, Item):
        self.puts.append(Item)
        self.items.append(dict(Item))

    def get_item(self, Key):
        for item in self.items:
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": dict(item)}
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        condition = kwargs.get("KeyConditionExpression")
        wanted = None
        for value in (getattr(condition, "_values", None) or ()):
            if isinstance(value, str) and value.startswith("TENANT#"):
                wanted = value
        if kwargs.get("IndexName") or wanted is None:
            return {"Items": [dict(i) for i in self.items]}
        return {"Items": [dict(i) for i in self.items if i.get(KEY_PARTITION) == wanted]}

    def scan(self, **kwargs):
        return {"Items": [dict(i) for i in self.items]}


class TheKeyShapeTests(unittest.TestCase):
    def test_the_partition_carries_tenant_and_mode(self):
        self.assertEqual(tenant_mode_pk("t1", "live"), "TENANT#t1#live")
        self.assertNotEqual(tenant_mode_pk("t1", "live"), tenant_mode_pk("t1", "test"))

    def test_anything_not_explicitly_live_partitions_as_test(self):
        """The fail-safe direction, same rule as `normalize_stripe_mode`: a stray value must never land
        a row in live money."""
        for raw in ("test", "TEST", "", "production", None):
            with self.subTest(raw=raw):
                self.assertTrue(tenant_mode_pk("t1", raw).endswith("#test"))

    def test_the_business_identifier_stays_clean(self):
        """`order_id` travels to Stripe in PaymentIntent metadata and partitions two GSIs. The mode must
        not be in it."""
        stored = with_tenant_mode_keys({"tenant_id": "t1", "order_id": "order_abc"},
                                       tenant_id="t1", document_id="order_abc", mode="live")
        self.assertEqual(stored["order_id"], "order_abc")
        self.assertEqual(stored[KEY_SORT], "order_abc")

    def test_synthetic_keys_are_stripped_on_the_way_out(self):
        stored = with_tenant_mode_keys({"tenant_id": "t1", "order_id": "o"},
                                       tenant_id="t1", document_id="o", mode="test")
        read = without_keys(stored)
        self.assertNotIn(KEY_PARTITION, read)
        self.assertNotIn(KEY_SORT, read)
        self.assertEqual(read["tenant_id"], "t1")
        self.assertEqual(read["stripe_mode"], "test")


class ReadsAreKeyConditionsNotFiltersTests(unittest.TestCase):
    """The whole point: DynamoDB should read only the rows of one mode, not read both and discard."""

    def _orders(self, mode, table):
        return TenantRangeRepository("jb-orders-test", id_field="order_id", table=table, mode=mode)

    def test_listing_a_tenant_queries_the_mode_partition(self):
        table = RecordingTable()
        self._orders("live", table).list_for_tenant("t1")
        self.assertEqual(len(table.queries), 1)
        self.assertNotIn("FilterExpression", table.queries[0],
                         "a filter means DynamoDB read rows it then threw away")

    def test_a_live_read_cannot_see_a_test_row(self):
        table = RecordingTable()
        self._orders("test", table).put({"tenant_id": "t1", "order_id": "o_test"})
        self._orders("live", table).put({"tenant_id": "t1", "order_id": "o_live"})
        self.assertEqual([o["order_id"] for o in self._orders("live", table).list_for_tenant("t1")],
                         ["o_live"])
        self.assertEqual([o["order_id"] for o in self._orders("test", table).list_for_tenant("t1")],
                         ["o_test"])

    def test_a_get_in_the_wrong_mode_finds_nothing(self):
        """Not "finds it and filters it" -- the key does not exist in that partition at all."""
        table = RecordingTable()
        self._orders("test", table).put({"tenant_id": "t1", "order_id": "o1"})
        self.assertIsNone(self._orders("live", table).get("t1", "o1"))
        self.assertIsNotNone(self._orders("test", table).get("t1", "o1"))

    def test_two_modes_may_share_an_id_without_colliding(self):
        table = RecordingTable()
        self._orders("test", table).put({"tenant_id": "t1", "order_id": "same", "amount": 1})
        self._orders("live", table).put({"tenant_id": "t1", "order_id": "same", "amount": 2})
        self.assertEqual(self._orders("test", table).get("t1", "same")["amount"], 1)
        self.assertEqual(self._orders("live", table).get("t1", "same")["amount"], 2)


class EveryMoneyTableRefusesAnAbsentModeTests(unittest.TestCase):
    """A confident wrong total is worse than an error, and with isolation in the key there is no longer
    any way to express "both modes" as a query."""

    def test_orders_customers_ledger_and_refunds_all_refuse(self):
        cases = [
            ("orders", lambda: TenantRangeRepository("jb-orders-test", id_field="order_id",
                                                     table=RecordingTable(), mode=None)),
            ("ledger", lambda: LedgerRepository("jb-ledger-test", table=RecordingTable(), mode=None)),
            ("refunds", lambda: RefundsRepository("jb-refunds-test", table=RecordingTable(), mode=None)),
        ]
        for name, build in cases:
            with self.subTest(repository=name):
                with self.assertRaises(RepositoryError):
                    build()

    def test_refunds_gained_the_scoping_it_never_had(self):
        """It took no mode at all until 2026-10-07 -- the ledger's gap, one table over, latent only
        because the table was empty."""
        table = RecordingTable()
        RefundsRepository("jb-refunds-test", table=table, mode="test").put(
            {"tenant_id": "t1", "refund_id": "re_1"})
        RefundsRepository("jb-refunds-test", table=table, mode="live").put(
            {"tenant_id": "t1", "refund_id": "re_2"})
        live = RefundsRepository("jb-refunds-test", table=table, mode="live")
        self.assertIsNone(live.get("t1", "re_1"))
        self.assertIsNotNone(live.get("t1", "re_2"))


if __name__ == "__main__":
    unittest.main()
