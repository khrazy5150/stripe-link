"""A subscription renewal is an ORDER, because it is work the tenant has to do.

Found from a real renewal on 2026-09-22: two daily subscriptions charged successfully in Stripe and the app
recorded nothing — no order, no ledger entry, no notification, no email. `persist_invoice_event` tracks only
invoices WE created (`metadata.invoice_id`), which is correct for standalone invoicing; a Stripe cycle
invoice has no such id and fell straight through it.

The author's framing, which decides the data model: "A subscription for Creatine means a new order of
creatine that must be fulfilled. A subscription for massage therapy is also an order to fulfill a massage
service." So renewals go in the orders table like any other order, not into a separate record that the
fulfilment screens would never show.
"""
import unittest

from handlers.stripe_webhook import (
    invoice_subscription_metadata,
    order_line_items_from_invoice,
    order_record_from_invoice,
    persist_subscription_renewal,
)


def _invoice(**over):
    invoice = {
        "id": "in_123", "object": "invoice", "billing_reason": "subscription_cycle",
        "subscription": "sub_1", "currency": "usd", "amount_paid": 19792, "livemode": False,
        "customer": "cus_1", "customer_email": "buyer@example.com", "customer_name": "Keith Harris",
        "payment_intent": "pi_1", "created": 1790000000,
        "lines": {"data": [{
            "description": "Creatine Gummies", "amount": 19792, "quantity": 1, "currency": "usd",
            "price": {"id": "price_1", "product": "prod_1"},
        }]},
    }
    invoice.update(over)
    return invoice


def _event(invoice=None):
    return {"id": "evt_1", "type": "invoice.paid", "livemode": False,
            "data": {"object": invoice or _invoice()}}


class Repo:
    def __init__(self):
        self.puts = []
        self.docs = {}

    def get(self, tenant_id, doc_id):
        return self.docs.get((tenant_id, doc_id))

    def put(self, document):
        self.puts.append(document)
        key = (document.get("tenant_id"), document.get("order_id") or document.get("notification_id"))
        self.docs[key] = document
        return document

    def append(self, document):
        return self.put(document)


class RecordShapeTests(unittest.TestCase):
    def test_the_order_id_comes_from_the_invoice_so_redelivery_is_idempotent(self):
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        self.assertEqual(record["order_id"], "order_in_123")

    def test_it_is_marked_as_a_renewal_not_a_first_purchase(self):
        # Otherwise "how many new customers" becomes unanswerable.
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        self.assertEqual(record["line_item_type"], "subscription_cycle")
        self.assertEqual(record["subscription_id"], "sub_1")

    def test_line_items_carry_what_must_be_fulfilled(self):
        items = order_line_items_from_invoice(_invoice())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Creatine Gummies")
        self.assertEqual(items[0]["amount_total"], 19792)
        self.assertEqual(items[0]["stripe_price_id"], "price_1")

    def test_an_invoice_line_calls_its_total_amount_not_amount_total(self):
        # The shape difference that would silently zero every renewal's value.
        self.assertEqual(order_line_items_from_invoice(_invoice())[0]["amount_subtotal"], 19792)

    def test_the_customer_is_carried_so_a_receipt_can_be_sent(self):
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        self.assertEqual(record["customer"]["email"], "buyer@example.com")
        self.assertTrue(record["contact_keys"])

    def test_metadata_is_found_wherever_stripe_put_it(self):
        self.assertEqual(
            invoice_subscription_metadata(_invoice(subscription_details={"metadata": {"offer_id": "o1"}})),
            {"offer_id": "o1"})
        line_meta = _invoice()
        line_meta["lines"]["data"][0]["metadata"] = {"offer_id": "o2"}
        self.assertEqual(invoice_subscription_metadata(line_meta), {"offer_id": "o2"})
        self.assertEqual(invoice_subscription_metadata(_invoice()), {})


class PersistTests(unittest.TestCase):
    def _persist(self, invoice=None, **kw):
        self.orders, self.notifications, self.ledger = Repo(), Repo(), Repo()
        self.sent = []
        return persist_subscription_renewal(
            _event(invoice), tenant_id="t1", mode="test",
            orders_repo=self.orders, notifications_repo=self.notifications, ledger_repo=self.ledger,
            products_repo=None, now_fn=lambda: 1790000500,
            receipt_mailer=lambda *a, **k: self.sent.append((a, k)) or {"status": "sent"},
            email_context_loader=lambda tenant_id: {},
            **kw,
        )

    def test_a_renewal_is_written_as_an_order(self):
        result = self._persist()
        self.assertEqual(result["status"], "stored")
        self.assertIn("order", result["written"])
        self.assertEqual(self.orders.puts[0]["order_id"], "order_in_123")

    def test_the_tenant_is_notified_and_told_it_is_a_renewal(self):
        self._persist()
        self.assertEqual(len(self.notifications.puts), 1)
        note = self.notifications.puts[0]
        self.assertEqual(note["type"], "subscription_renewed")
        self.assertIn("renew", note["title"].lower())
        self.assertIn("Creatine Gummies", note["title"])

    def test_the_first_invoice_of_a_subscription_is_NOT_counted_again(self):
        # checkout.session.completed already made that one an order; counting it here doubles every new
        # subscription on day one.
        result = self._persist(_invoice(billing_reason="subscription_create"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not_a_renewal")
        self.assertEqual(self.orders.puts, [])

    def test_a_repeating_TIP_does_not_become_an_order(self):
        # A tip is a donation with its own renewal email, not something to fulfil.
        tip = _invoice(subscription_details={"metadata": {"tip": "1", "tip_recurring": "month"}})
        result = self._persist(tip)
        self.assertEqual(result["reason"], "tip_renewal")
        self.assertEqual(self.orders.puts, [])

    def test_a_redelivered_invoice_does_not_duplicate_anything(self):
        self._persist()
        first_orders = list(self.orders.puts)
        # same event again, against the repo that already holds the order
        again = persist_subscription_renewal(
            _event(), tenant_id="t1", mode="test",
            orders_repo=self.orders, notifications_repo=self.notifications, ledger_repo=self.ledger,
            products_repo=None, now_fn=lambda: 1790000600,
            receipt_mailer=lambda *a, **k: self.sent.append((a, k)) or {"status": "sent"},
            email_context_loader=lambda tenant_id: {},
        )
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(self.orders.puts, first_orders)
        self.assertEqual(len(self.notifications.puts), 1)
        self.assertEqual(len(self.sent), 1, "a second receipt would email the customer twice")

    def test_a_receipt_is_sent_like_any_other_order(self):
        self._persist()
        self.assertEqual(len(self.sent), 1)


class CheckoutMirrorsMetadataTests(unittest.TestCase):
    """Renewals can be RECORDED without subscription metadata (the lines carry what to fulfil), but they
    cannot be ATTRIBUTED without it. A cycle invoice carries only what the subscription carries, and
    checkout was setting subscription metadata for tips alone."""

    import pathlib as _pathlib
    CHECKOUT = (_pathlib.Path(__file__).resolve().parents[1] / "src/handlers/checkout.py").read_text(encoding="utf-8")

    def test_the_session_metadata_is_mirrored_onto_the_subscription(self):
        self.assertIn('subscription_data[metadata][{key}]', self.CHECKOUT)

    def test_it_only_applies_to_subscriptions(self):
        block = self.CHECKOUT.split("Mirror the session's identifying metadata", 1)[1][:900]
        self.assertIn('payload["mode"] == "subscription"', block)

    def test_the_keys_that_let_a_renewal_be_attributed_are_included(self):
        block = self.CHECKOUT.split("Mirror the session's identifying metadata", 1)[1][:900]
        for key in ("offer_id", "page_id", "product_id", "tenant_id"):
            self.assertIn(f'"{key}"', block, key)

    def test_empty_values_are_not_sent(self):
        # Stripe handles a missing metadata key far better than an empty value.
        block = self.CHECKOUT.split("Mirror the session's identifying metadata", 1)[1][:900]
        self.assertIn("if value:", block)
