"""A customer is the sum of what they bought, not the last thing they bought.

Found 2026-10-11 from a Dashboard reading **Customers 0** beside **8 orders**. The cards were right —
products and customers are mode-scoped, and this tenant's only rows are live-mode while the screen was
showing test. But the reason test had none is a real defect, and chasing it found a second.

**1. A subscription renewal recorded no customer.** `persist_subscription_renewal` wrote an order and a
ledger entry; `customers_repo` appeared nowhere in it. So a subscriber never appeared in Customers, and
one already there stopped growing after signup. For a business whose revenue IS renewals, the customer
list was a list of people who once signed up.

**2. A repeat buyer was overwritten.** `customer_record_from_session` builds a record with
`total_orders: 1` and `lifetime_value: <this order>`, and the webhook `put` it. A plain put. A second
purchase reset lifetime value to that purchase's price and discarded the first transaction — every
repeat-customer figure was the most recent order wearing a cumulative name.

Both are now one merge, in one place, because the two write paths disagreeing about whether a customer
accumulates is exactly how this happened.
"""
import unittest

from stripe_link.domain.customers import MAX_TRANSACTIONS, merge_customer


def record(ref, amount, when, *, name="Keith", email="k@example.com", product="Gummies"):
    return {
        "document_type": "customer", "tenant_id": "t1", "customer_id": "cus_1",
        "contact": {"name": name, "email": email, "phone": ""},
        "summary": {"total_orders": 1, "lifetime_value": amount, "currency": "usd",
                    "last_order_at": when},
        "product_affinity": [{"product_id": product.lower(), "product_name": product}],
        "transaction_history": [{"transaction_id": ref, "created_at": when, "amount": amount}],
        "updated_at": when,
    }


class ARepeatPurchaseAccumulates(unittest.TestCase):
    def test_orders_and_value_add_up(self):
        merged = merge_customer(record("cs_1", 3291, 100), record("cs_2", 1999, 200))
        self.assertEqual(merged["summary"]["total_orders"], 2)
        self.assertEqual(merged["summary"]["lifetime_value"], 5290)

    def test_the_first_purchase_is_unaffected(self):
        """Nothing to merge into. The record must pass through untouched rather than be halved."""
        first = record("cs_1", 3291, 100)
        self.assertEqual(merge_customer(None, first), first)
        self.assertEqual(merge_customer({}, first), first)

    def test_history_keeps_both_newest_first(self):
        merged = merge_customer(record("cs_1", 3291, 100), record("cs_2", 1999, 200))
        self.assertEqual([t["transaction_id"] for t in merged["transaction_history"]],
                         ["cs_2", "cs_1"])

    def test_last_seen_never_moves_backwards(self):
        """Events arrive out of order, and a retried older invoice must not drag the customer back."""
        merged = merge_customer(record("cs_1", 3291, 900), record("cs_0", 1999, 100))
        self.assertEqual(merged["summary"]["last_order_at"], 900)

    def test_products_bought_are_collected_not_replaced(self):
        merged = merge_customer(record("cs_1", 3291, 100, product="Gummies"),
                                record("cs_2", 1999, 200, product="Massage"))
        self.assertEqual({p["product_name"] for p in merged["product_affinity"]},
                         {"Gummies", "Massage"})

    def test_the_same_product_twice_is_listed_once(self):
        merged = merge_customer(record("cs_1", 3291, 100), record("cs_2", 1999, 200))
        self.assertEqual(len(merged["product_affinity"]), 1)


class ARedeliveryChangesNothing(unittest.TestCase):
    """Stripe retries, and this runs on every delivery. Without de-duplication a retried webhook adds the
    same payment again and inflates the customer's worth — a money figure, wrong in the flattering
    direction, with no event behind it."""

    def test_the_same_transaction_is_counted_once(self):
        renewal = record("in_2", 3291, 200)
        once = merge_customer(record("cs_1", 3291, 100), renewal)
        twice = merge_customer(once, renewal)
        thrice = merge_customer(twice, renewal)
        for merged in (twice, thrice):
            self.assertEqual(merged["summary"]["total_orders"], 2)
            self.assertEqual(merged["summary"]["lifetime_value"], 6582)
            self.assertEqual(len(merged["transaction_history"]), 2)

    def test_a_genuinely_new_payment_still_counts_after_a_redelivery(self):
        once = merge_customer(record("cs_1", 3291, 100), record("in_2", 3291, 200))
        again = merge_customer(once, record("in_2", 3291, 200))
        third = merge_customer(again, record("in_3", 3291, 300))
        self.assertEqual(third["summary"]["total_orders"], 3)
        self.assertEqual(third["summary"]["lifetime_value"], 9873)


class ARenewalDoesNotEraseWhatCheckoutLearned(unittest.TestCase):
    """Stripe puts the name and phone on the Customer, not on the invoice, so a renewal often carries
    neither. Letting an empty string win would wipe the only identity the tenant has for that buyer."""

    def test_a_blank_name_does_not_overwrite_a_known_one(self):
        merged = merge_customer(record("cs_1", 3291, 100, name="Keith Harris"),
                                record("in_2", 3291, 200, name=""))
        self.assertEqual(merged["contact"]["name"], "Keith Harris")

    def test_the_unknown_email_placeholder_does_not_overwrite_a_real_one(self):
        merged = merge_customer(record("cs_1", 3291, 100, email="k@example.com"),
                                record("in_2", 3291, 200, email="unknown"))
        self.assertEqual(merged["contact"]["email"], "k@example.com")

    def test_a_real_change_does_win(self):
        merged = merge_customer(record("cs_1", 3291, 100, email="old@example.com"),
                                record("in_2", 3291, 200, email="new@example.com"))
        self.assertEqual(merged["contact"]["email"], "new@example.com")


class HistoryIsBounded(unittest.TestCase):
    def test_a_long_subscriber_does_not_carry_every_cycle(self):
        """Three years of weekly renewals is 156 rows read back on every touch of this record. The ledger
        is the financial history; this is the recent slice."""
        merged = record("in_0", 100, 0)
        for index in range(1, MAX_TRANSACTIONS + 20):
            merged = merge_customer(merged, record(f"in_{index}", 100, index))
        self.assertEqual(len(merged["transaction_history"]), MAX_TRANSACTIONS)
        self.assertEqual(merged["transaction_history"][0]["transaction_id"],
                         f"in_{MAX_TRANSACTIONS + 19}", "the cap keeps the NEWEST")

    def test_the_totals_outlive_the_capped_history(self):
        """The count must not silently become `len(history)`."""
        merged = record("in_0", 100, 0)
        for index in range(1, MAX_TRANSACTIONS + 20):
            merged = merge_customer(merged, record(f"in_{index}", 100, index))
        # One starting record plus `range(1, MAX+20)` merges = MAX + 20, comfortably past the cap.
        self.assertEqual(merged["summary"]["total_orders"], MAX_TRANSACTIONS + 20)
        self.assertGreater(merged["summary"]["total_orders"], len(merged["transaction_history"]),
                           "the count must not quietly become len(history)")


class TheRenewalPathBuildsOne(unittest.TestCase):
    def test_an_invoice_becomes_a_customer_record(self):
        from handlers.stripe_webhook import customer_record_from_invoice
        invoice = {
            "id": "in_1", "customer": "cus_9", "customer_email": "k@example.com",
            "customer_name": "Keith Harris", "amount_paid": 19792, "currency": "usd",
            "created": 1791700000,
            "parent": {"subscription_details": {"metadata": {
                "tenant_id": "t1", "product_id": "p1", "product_name": "120 minute massage"}}},
        }
        built = customer_record_from_invoice(invoice, "t1", 1)
        self.assertEqual(built["customer_id"], "cus_9", "the Stripe id, stable across an email change")
        self.assertEqual(built["summary"]["lifetime_value"], 19792)
        self.assertEqual(built["transaction_history"][0]["transaction_id"], "in_1")
        self.assertEqual(built["transaction_history"][0]["type"], "subscription_cycle")
        self.assertEqual(built["product_affinity"][0]["product_name"], "120 minute massage")

    def test_it_matches_the_checkout_shape_so_the_merge_sees_one_thing(self):
        from handlers.stripe_webhook import (customer_record_from_invoice,
                                             customer_record_from_session)
        invoice = {"id": "in_1", "customer": "cus_9", "customer_email": "k@x.com",
                   "amount_paid": 100, "currency": "usd", "created": 5}
        session = {"id": "cs_1", "customer": "cus_9", "amount_total": 100, "currency": "usd",
                   "created": 5, "customer_details": {"email": "k@x.com"}}
        self.assertEqual(set(customer_record_from_invoice(invoice, "t1", 1)),
                         set(customer_record_from_session(session, "t1", 1)))

    def test_an_invoice_with_nobody_on_it_records_nothing(self):
        from handlers.stripe_webhook import customer_record_from_invoice
        self.assertEqual(customer_record_from_invoice({"id": "in_1"}, "t1", 1), {})


class TheWritesAreWired(unittest.TestCase):
    """The builder existing is not the fix; `shipping_cost` sat in the ledger with a builder and no
    writer for months, and this is the second instance of that shape in two days."""

    import pathlib as _pathlib
    SOURCE = (_pathlib.Path(__file__).resolve().parents[1]
              / "src/handlers/stripe_webhook.py").read_text(encoding="utf-8")

    def _function(self, name):
        start = self.SOURCE.index(f"def {name}(")
        return self.SOURCE[start:][:self.SOURCE[start:].index("\ndef ", 1)]

    def test_the_renewal_path_records_a_customer(self):
        body = self._function("persist_subscription_renewal")
        self.assertIn("customer_record_from_invoice(invoice, tenant_id, now)", body)
        self.assertIn("customers_repo.put(", body)

    def test_the_checkout_path_merges_rather_than_overwrites(self):
        self.assertIn("customers_repo.put(_merged_customer(customers_repo, tenant_id, customer_record))",
                      self.SOURCE)
        self.assertNotIn("customers_repo.put(customer_record)", self.SOURCE,
                         "a plain put is what reset a repeat buyer's lifetime value")

    def test_a_customer_write_cannot_fail_a_renewal(self):
        """The money is banked and the subscription is live. A reporting aggregate must not turn that
        into something Stripe retries."""
        body = self._function("persist_subscription_renewal")
        tail = body[body.index("customer_record_from_invoice"):]
        self.assertIn("except Exception", tail)


if __name__ == "__main__":
    unittest.main()
