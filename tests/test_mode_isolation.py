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
    def __init__(self, items):
        self.items = items

    def query(self, **kwargs):
        return {"Items": list(self.items)}


LIVE_SALE = {"tenant_id": "t1", "entry_id": "le_live", "mode": "live", "occurred_at": 20,
             "amounts": {"gross": 10000}}
TEST_SALE = {"tenant_id": "t1", "entry_id": "le_test", "mode": "test", "occurred_at": 10,
             "amounts": {"gross": 500000}}
LEGACY = {"tenant_id": "t1", "entry_id": "le_old", "occurred_at": 5, "amounts": {"gross": 700}}


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

    def test_no_mode_still_returns_everything(self):
        # Internal callers that genuinely want the whole ledger are unaffected.
        repo = LedgerRepository("jb-ledger-test", table=FakeTable([LIVE_SALE, TEST_SALE]), mode=None)
        self.assertEqual(len(repo.list_for_tenant("t1")), 2)

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
