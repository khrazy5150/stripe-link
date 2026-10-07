"""A ledger entry's mode must come from the field every order actually carries.

`sale_entry_from_order` read `order["stripe_mode"]`. The webhook's checkout path writes that field; nothing else
does. An upsell's `order_record` has 28 keys and none of them is `mode` -- its mode reaches storage only
as `stripe_mode`, stamped by the repository on write, after the in-memory dict has already been handed to
the ledger.

So a LIVE upsell wrote a ledger entry stamped "test", and the fail-safe default is what made it silent:
live upsell revenue would simply be absent from live financial reports, with nothing anywhere saying so.
Found 2026-10-07 while tracing why one concept has two field names.
"""
import unittest

from stripe_link.domain.ledger import sale_entry_from_order


def order(**extra):
    return {"tenant_id": "t", "order_id": "o", "payment_intent_id": "pi", "amount_total": 1000,
            "currency": "usd", "created_at": 1, **extra}


class LedgerModeTests(unittest.TestCase):
    def test_a_live_upsell_is_recorded_as_live(self):
        """The bug. An upsell carries `stripe_mode` and no `mode`."""
        self.assertEqual(sale_entry_from_order(order(stripe_mode="live"), now_epoch=1)["stripe_mode"], "live")

    def test_a_live_checkout_is_still_live(self):
        entry = sale_entry_from_order(order(mode="live", stripe_mode="live"), now_epoch=1)
        self.assertEqual(entry["stripe_mode"], "live")

    def test_a_test_upsell_is_recorded_as_test(self):
        self.assertEqual(sale_entry_from_order(order(stripe_mode="test"), now_epoch=1)["stripe_mode"], "test")

    def test_the_repository_stamp_outranks_the_webhook_field(self):
        """`stripe_mode` is what the repository writes on every order; `mode` only on some. Where they
        disagree the stamped one is the one storage actually filters on."""
        entry = sale_entry_from_order(order(mode="test", stripe_mode="live"), now_epoch=1)
        self.assertEqual(entry["stripe_mode"], "live")

    def test_an_order_carrying_neither_is_test(self):
        """Anything not explicitly live is test: under-reporting real revenue is recoverable, reporting
        test money as real is not."""
        self.assertEqual(sale_entry_from_order(order(), now_epoch=1)["stripe_mode"], "test")

    def test_case_and_whitespace_do_not_decide_whether_money_is_real(self):
        for raw in ("LIVE", " live ", "Live"):
            with self.subTest(raw=raw):
                self.assertEqual(sale_entry_from_order(order(stripe_mode=raw), now_epoch=1)["stripe_mode"], "live")

    def test_a_stray_value_never_lands_in_live(self):
        for raw in ("production", "prod", "1", True):
            with self.subTest(raw=raw):
                self.assertEqual(sale_entry_from_order(order(stripe_mode=raw), now_epoch=1)["stripe_mode"], "test")


if __name__ == "__main__":
    unittest.main()


class TheUpsellOrderCarriesItsOwnModeTests(unittest.TestCase):
    """The fix at the source, rather than at the reader.

    The repository stamps `stripe_mode` on write, but the ledger is handed the in-memory dict BEFORE that
    happens. So the record has to carry its own mode or the ledger is guessing -- and its fail-safe guess
    is "test", which is how live upsell revenue went missing silently.
    """

    def _stored_order(self, mode):
        from tests.test_upsell_handler import FakeStripeOpener, ProcessUpsellTests

        case = ProcessUpsellTests("test_process_upsell_charges_saved_payment_method_and_records_order")
        case.setUp()
        try:
            opener = FakeStripeOpener({
                ("GET", "/v1/customers/cus_123"): {
                    "id": "cus_123", "invoice_settings": {"default_payment_method": {"id": "pm_1"}}},
                ("POST", "/v1/payment_intents"): {"id": "pi_1", "status": "succeeded"},
            })
            response = case.handle(case.base_event(mode=mode), opener)
            self.assertEqual(response["statusCode"], 201, response.get("body"))
            return case.orders_repo.get("tenant_demo", "order_cs_test_123_upsell_1")
        finally:
            case.tearDown()

    def test_a_live_upsell_records_itself_as_live(self):
        """The bug, end to end: charge in live mode, and the stored order must say so."""
        record = self._stored_order("live")
        self.assertIsNotNone(record, "the upsell did not store an order")
        self.assertEqual(record.get("stripe_mode"), "live")
        self.assertEqual(sale_entry_from_order(record, now_epoch=1)["stripe_mode"], "live")

    def test_a_test_upsell_records_itself_as_test(self):
        record = self._stored_order("test")
        self.assertIsNotNone(record)
        self.assertEqual(record.get("stripe_mode"), "test")
        self.assertEqual(sale_entry_from_order(record, now_epoch=1)["stripe_mode"], "test")


class EveryOrderRecordHandedToTheLedgerCarriesItTests(unittest.TestCase):
    """Guarding the class, not just the instance.

    Three builders produce order records that go to the ledger. Two always carried a mode; the upsell did
    not, and the omission was silent for as long as nobody sold anything live. A fourth builder added
    later would be just as silent.
    """

    from pathlib import Path as _Path
    ROOT = _Path(__file__).resolve().parents[1]

    def _record_keys(self, path, marker, end="\n    }"):
        import re
        source = (self.ROOT / path).read_text(encoding="utf-8")
        block = source.split(marker, 1)[1].split(end, 1)[0]
        return set(re.findall(r'^\s*"(\w+)":', block, re.M))

    def test_the_upsell_record_declares_its_mode(self):
        keys = self._record_keys("src/handlers/upsell.py", "    order_record = {")
        self.assertIn("stripe_mode", keys)

    def test_both_webhook_records_declare_theirs(self):
        import re
        source = (self.ROOT / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
        for fn in ("order_record_from_session", "order_record_from_invoice"):
            with self.subTest(builder=fn):
                body = source.split(f"def {fn}(", 1)[1].split("\n\ndef ", 1)[0]
                keys = set(re.findall(r'^\s*"(\w+)":', body, re.M))
                self.assertIn("stripe_mode", keys)
