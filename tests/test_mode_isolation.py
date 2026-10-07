"""Test money must never be read as real money.

One PROD endpoint processes both test and live Stripe events -- deliberate, shipped as
plans/STRIPE_MODE_DECOUPLING.md P3 (commit 244328c), so a tenant's sandbox works in the production
dashboard instead of swapping the whole backend. The environment therefore no longer separates test from
live; MODE does, and that isolation has to be enforced on every READ or the design leaks.

It leaked. Ledger entries have carried "test"/"live" since they were written, and nothing filtered on it:
`GET /ledger` summed every entry for the tenant, so a sandbox sale was added to real revenue. The Customers
screen had the same shape for a different reason -- the repository supports mode and the handler simply did
not pass it.

Found 2026-09-20 while checking why dev's orders table was empty: test orders were in the prod table, which
is correct and by design, and the filtering that makes it safe was half-built.
"""
import unittest

from stripe_link.repositories.documents import LedgerRepository


class FakeTable:
    """A table that PARTITIONS, because that is now where the isolation lives.

    The previous fake returned every item for any query, which modelled the old mechanism well enough --
    isolation was a client-side filter, so the fake only had to supply rows. It cannot model the new one:
    a live query and a test query now address different partitions, and a fake that ignores the key
    condition would let a broken repository pass by handing it everything.
    """

    def __init__(self, items):
        self.items = [dict(item) for item in items]

    def _pk_wanted(self, kwargs):
        condition = kwargs.get("KeyConditionExpression")
        values = getattr(condition, "_values", None) or ()
        for value in values:
            if getattr(value, "name", None) == "PK":
                continue
            if isinstance(value, str) and value.startswith("TENANT#"):
                return value
        return None

    def query(self, **kwargs):
        # A GSI query (OrderIndex) spans modes by design -- order ids are globally unique and carry no
        # mode -- so it returns everything and the repository filters. The base-table query does not.
        if kwargs.get("IndexName"):
            return {"Items": list(self.items)}
        wanted = self._pk_wanted(kwargs)
        if wanted is None:
            return {"Items": list(self.items)}
        return {"Items": [i for i in self.items if i.get("PK") == wanted]}


def stored(entry_id, mode, occurred_at, gross, *, tenant="t1", stamped=True):
    """An entry as the repository actually writes it: synthetic keys alongside the document."""
    item = {"tenant_id": tenant, "entry_id": entry_id, "occurred_at": occurred_at,
            "amounts": {"gross": gross},
            "PK": f"TENANT#{tenant}#{mode}", "SK": entry_id}
    if stamped:
        item["stripe_mode"] = mode
    return item


LIVE_SALE = stored("le_live", "live", 20, 10000)
TEST_SALE = stored("le_test", "test", 10, 500000)
# Written before the stamp existed. It still landed in the TEST partition, because `normalize_stripe_mode`
# resolves anything that is not explicitly "live" to test -- the fail-safe direction.
LEGACY = stored("le_old", "test", 5, 700, stamped=False)


class LedgerModeTests(unittest.TestCase):
    def _repo(self, mode):
        return LedgerRepository("jb-ledger-test", table=FakeTable([LIVE_SALE, TEST_SALE, LEGACY]), mode=mode)

    def test_live_never_includes_sandbox_money(self):
        entries = self._repo("live").list_for_tenant("t1")
        self.assertEqual([e["entry_id"] for e in entries], ["le_live"])

    def test_test_mode_sees_only_test(self):
        entries = self._repo("test").list_for_tenant("t1")
        self.assertEqual({e["entry_id"] for e in entries}, {"le_test", "le_old"})

    def test_an_unstamped_entry_counts_as_test_not_live(self):
        """The asymmetry is deliberate: under-reporting real revenue is recoverable, reporting test money
        as real is not. An entry written before the stamp existed is therefore kept OUT of live."""
        self.assertNotIn("le_old", [e["entry_id"] for e in self._repo("live").list_for_tenant("t1")])
        self.assertIn("le_old", [e["entry_id"] for e in self._repo("test").list_for_tenant("t1")])

    def test_a_ledger_without_a_mode_is_refused(self):
        """It used to return every mode's rows. With isolation in the partition key there is no key that
        spans both, so "everything" is no longer a query -- and a caller that forgot the mode would get a
        confident wrong total rather than an error. Every production call site now passes one."""
        from stripe_link.repositories.documents import RepositoryError

        with self.assertRaises(RepositoryError):
            LedgerRepository("jb-ledger-test", table=FakeTable([LIVE_SALE]), mode=None)

    def test_the_synthetic_keys_never_reach_the_caller(self):
        """`PK`/`SK` are storage, not content. A caller must not be able to tell them from real fields."""
        entry = self._repo("live").list_for_tenant("t1")[0]
        self.assertNotIn("PK", entry)
        self.assertNotIn("SK", entry)
        self.assertEqual(entry["tenant_id"], "t1")

    def test_the_per_order_view_is_scoped_too(self):
        entries = self._repo("live").list_for_order("order_1")
        self.assertEqual([e["entry_id"] for e in entries], ["le_live"])


class HandlersPassTheModeTests(unittest.TestCase):
    """Every read of a mode-bearing table has to scope itself; one that forgets is the whole leak."""

    import pathlib as _pathlib

    SRC = _pathlib.Path(__file__).resolve().parents[1] / "src"

    def test_the_ledger_endpoint_scopes_its_read(self):
        source = (self.SRC / "handlers/ledger.py").read_text(encoding="utf-8")
        self.assertIn("ledger_repository(mode=resolve_stripe_mode(event))", source)

    def test_the_customers_endpoint_scopes_its_read(self):
        source = (self.SRC / "handlers/customers.py").read_text(encoding="utf-8")
        self.assertIn("customers_repository(mode=resolve_stripe_mode(event))", source)

    def test_every_orders_read_is_scoped(self):
        """Orders were already correct everywhere; this keeps them that way."""
        import re
        for path in (self.SRC / "handlers").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for call in re.findall(r"orders_repository\(([^)]*)\)", source):
                with self.subTest(handler=path.name, call=call):
                    self.assertIn("mode", call, f"{path.name} reads orders without a mode")


if __name__ == "__main__":
    unittest.main()
