"""A ledger entry's mode must come from the field every order actually carries.

`sale_entry_from_order` read `order["mode"]`. The webhook's checkout path writes that field; nothing else
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
        self.assertEqual(sale_entry_from_order(order(stripe_mode="live"), now_epoch=1)["mode"], "live")

    def test_a_live_checkout_is_still_live(self):
        entry = sale_entry_from_order(order(mode="live", stripe_mode="live"), now_epoch=1)
        self.assertEqual(entry["mode"], "live")

    def test_a_test_upsell_is_recorded_as_test(self):
        self.assertEqual(sale_entry_from_order(order(stripe_mode="test"), now_epoch=1)["mode"], "test")

    def test_the_repository_stamp_outranks_the_webhook_field(self):
        """`stripe_mode` is what the repository writes on every order; `mode` only on some. Where they
        disagree the stamped one is the one storage actually filters on."""
        entry = sale_entry_from_order(order(mode="test", stripe_mode="live"), now_epoch=1)
        self.assertEqual(entry["mode"], "live")

    def test_an_order_carrying_neither_is_test(self):
        """Anything not explicitly live is test: under-reporting real revenue is recoverable, reporting
        test money as real is not."""
        self.assertEqual(sale_entry_from_order(order(), now_epoch=1)["mode"], "test")

    def test_case_and_whitespace_do_not_decide_whether_money_is_real(self):
        for raw in ("LIVE", " live ", "Live"):
            with self.subTest(raw=raw):
                self.assertEqual(sale_entry_from_order(order(stripe_mode=raw), now_epoch=1)["mode"], "live")

    def test_a_stray_value_never_lands_in_live(self):
        for raw in ("production", "prod", "1", True):
            with self.subTest(raw=raw):
                self.assertEqual(sale_entry_from_order(order(stripe_mode=raw), now_epoch=1)["mode"], "test")


if __name__ == "__main__":
    unittest.main()
