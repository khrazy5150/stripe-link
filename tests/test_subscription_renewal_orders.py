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
    catalog_names_by_stripe_id,
    invoice_subscription_id,
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


class IndexedAttributeTests(unittest.TestCase):
    """No empty string may reach a GSI key.

    `payment_intent_id` indexes PaymentIntentIndex on the orders table, and DynamoDB rejects an empty
    string for an indexed attribute -- the whole PutItem fails. A subscription cycle invoice does not
    always carry a payment_intent, and writing "" took down every renewal on prod (2026-09-22): the handler
    500'd, the dedup row was never written, and Stripe retried the same failure forever.
    """

    INDEXED = ("payment_intent_id",)

    def test_a_missing_payment_intent_is_omitted_not_empty(self):
        record = order_record_from_invoice(_invoice(payment_intent=None), "t1", 100, {})
        for key in self.INDEXED:
            self.assertNotIn(key, record, f"{key} indexes a GSI and must be absent rather than empty")

    def test_a_present_payment_intent_is_kept(self):
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        self.assertEqual(record["payment_intent_id"], "pi_1")

    def test_created_at_is_a_STRING_like_every_other_order(self):
        # created_at is the range key of CreatedAtIndex and the table declares it as S. An int is rejected
        # with "Type mismatch for Index Key created_at Expected: S Actual: N". order_record_from_session
        # stringifies it; this record was copied from a NEIGHBOURING one that does not.
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        self.assertIsInstance(record["created_at"], str)
        self.assertEqual(record["created_at"], "1790000000")

    def test_indexed_attributes_match_the_types_the_table_declares(self):
        # Every GSI key on jb-orders is declared S. Anything else fails the whole PutItem.
        record = order_record_from_invoice(_invoice(), "t1", 100, {})
        for key in ("tenant_id", "order_id", "created_at", "payment_intent_id"):
            if key in record:
                self.assertIsInstance(record[key], str, f"{key} indexes a GSI declared as S")

    def test_no_indexed_attribute_is_ever_an_empty_string(self):
        for invoice in (_invoice(payment_intent=None), _invoice(payment_intent=""), _invoice()):
            record = order_record_from_invoice(invoice, "t1", 100, {})
            for key in self.INDEXED:
                self.assertNotEqual(record.get(key, None), "", f"{key} must never be an empty string")


# The shape Stripe ACTUALLY sends, copied from a stored prod webhook payload (jb-webhook-events-prod,
# invoice.paid, api_version 2026-05-27.preview, read 2026-09-24). The `_invoice()` fixture above is the
# LEGACY shape, and every test built on it passed while prod stored an empty subscription_id, empty price
# and product ids, and no metadata on every single renewal. A fixture invented from older docs cannot fail
# the way the real payload does, so this one is transcribed rather than written.
CURRENT_API_INVOICE = {
    "id": "in_1UJJLa21lLbLd4Y5geENXTnZ", "object": "invoice", "billing_reason": "subscription_cycle",
    "currency": "usd", "amount_paid": 19792, "livemode": False, "created": 1790000000,
    "customer": "cus_1", "customer_email": "buyer@example.com",
    # No top-level "subscription" and no top-level "subscription_details" -- both moved under `parent`.
    "parent": {
        "type": "subscription_details",
        "quote_details": None,
        "subscription_details": {"metadata": {}, "subscription": "sub_1UHrRK21lLbLd4Y5hMpk5nxs"},
    },
    "lines": {"data": [{
        "id": "il_1", "object": "line_item", "description": "1 \u00d7 $197.92 (at $197.92 / day)",
        "amount": 19792, "quantity": 1, "currency": "usd", "metadata": {},
        # No "price" key -- replaced by "pricing".
        "pricing": {"type": "price_details", "unit_amount_decimal": "19792",
                    "price_details": {"price": "price_1UHrQi21lLbLd4Y5fp9SRfD6",
                                      "product": "prod_VISJfB0giFLk8W"}},
        "parent": {"type": "subscription_item_details",
                   "subscription_item_details": {"subscription": "sub_1UHrRK21lLbLd4Y5hMpk5nxs",
                                                 "subscription_item": "si_VISM6KIpWheNhE",
                                                 "proration": False}},
    }]},
}


def _current(**over):
    invoice = {k: v for k, v in CURRENT_API_INVOICE.items()}
    invoice.update(over)
    return invoice


def _with_subscription_metadata(metadata):
    parent = {**CURRENT_API_INVOICE["parent"],
              "subscription_details": {**CURRENT_API_INVOICE["parent"]["subscription_details"],
                                       "metadata": metadata}}
    return _current(parent=parent)


class CurrentStripeApiShapeTests(unittest.TestCase):
    """Read the payload this account's API version actually sends.

    Every field below was present all along and simply read from the place an older API version kept it, so
    nothing raised -- the renewal was stored, just hollow. That is the failure mode to guard: not an error,
    an empty string where an id belongs.
    """

    def test_the_subscription_id_is_found_under_parent(self):
        self.assertEqual(invoice_subscription_id(_current()), "sub_1UHrRK21lLbLd4Y5hMpk5nxs")

    def test_the_legacy_top_level_subscription_still_works(self):
        # Older stored events and any account on an older version must keep working.
        self.assertEqual(invoice_subscription_id(_invoice()), "sub_1")

    def test_a_renewal_order_records_which_subscription_it_came_from(self):
        record = order_record_from_invoice(_current(), "t1", 100, {})

        self.assertEqual(record["subscription_id"], "sub_1UHrRK21lLbLd4Y5hMpk5nxs")

    def test_the_subscriptions_metadata_is_found_under_parent(self):
        # The silo stamp rides here. Looking only at the old location returned {} for every renewal.
        invoice = _with_subscription_metadata({"silo": "sandbox", "offer_id": "offer_x"})

        self.assertEqual(invoice_subscription_metadata(invoice)["silo"], "sandbox")

    def test_a_silo_stamped_subscription_produces_a_stamped_renewal_order(self):
        record = order_record_from_invoice(_with_subscription_metadata({"silo": "sandbox"}), "t1", 100, {})

        self.assertEqual(record["metadata"]["silo"], "sandbox")

    def test_the_price_and_product_ids_are_found_under_pricing(self):
        [line] = order_line_items_from_invoice(_current())

        self.assertEqual(line["stripe_price_id"], "price_1UHrQi21lLbLd4Y5fp9SRfD6")
        self.assertEqual(line["stripe_product_id"], "prod_VISJfB0giFLk8W")

    def test_the_legacy_price_object_still_works(self):
        [line] = order_line_items_from_invoice(_invoice())

        self.assertEqual(line["stripe_price_id"], "price_1")
        self.assertEqual(line["stripe_product_id"], "prod_1")


class RenewalLineNameTests(unittest.TestCase):
    """What the receipt calls the thing.

    A renewal invoice carries no name of ours, only Stripe's generated `description` -- and when Stripe has
    no name for the product either, that description is the AMOUNT: a real receipt read
    "1 x $197.92 (at $197.92 / day)" (prod, 2026-09-24). Our own catalogue name is the better answer, and it
    only became reachable once the product id was read from the right place.
    """

    def test_our_own_product_name_wins_over_stripes_description(self):
        [line] = order_line_items_from_invoice(_current(), {"prod_VISJfB0giFLk8W": "Creatine Gummies"})

        self.assertEqual(line["name"], "Creatine Gummies")

    def test_a_price_id_resolves_it_too(self):
        # A product synced before stripe_product_id was stored can still be found by its price.
        [line] = order_line_items_from_invoice(_current(), {"price_1UHrQi21lLbLd4Y5fp9SRfD6": "Creatine Gummies"})

        self.assertEqual(line["name"], "Creatine Gummies")

    def test_the_name_it_was_SOLD_as_beats_stripes_description(self):
        """Our checkout writes product_name onto subscription_data.metadata, so the subscription remembers
        what it was sold as even when the product is not in the catalogue this backend can read. Verified on
        the real subscription created 2026-09-23: metadata carries product_name '120 minute massage'."""
        invoice = _with_subscription_metadata({"silo": "sandbox", "product_name": "120 minute massage"})

        record = order_record_from_invoice(invoice, "t1", 100, {})

        self.assertEqual(record["line_items"][0]["name"], "120 minute massage")

    def test_the_catalogue_still_outranks_it(self):
        # A renamed product should show its CURRENT name, not the one it carried at the time of sale.
        invoice = _with_subscription_metadata({"product_name": "Old name"})

        [line] = order_line_items_from_invoice(invoice, {"prod_VISJfB0giFLk8W": "New name"},
                                               invoice_subscription_metadata(invoice))

        self.assertEqual(line["name"], "New name")

    def test_a_multi_line_invoice_does_not_label_every_line_the_same(self):
        """product_name describes the SUBSCRIPTION, so with more than one line there is nothing to say which
        line it names. Stripe's per-line description is the better answer there."""
        invoice = _with_subscription_metadata({"product_name": "120 minute massage"})
        line = invoice["lines"]["data"][0]
        invoice = _current(parent=invoice["parent"],
                           lines={"data": [line, {**line, "description": "Add-on", "amount": 500}]})

        names = [item["name"] for item in order_line_items_from_invoice(
            invoice, {}, invoice_subscription_metadata(invoice))]

        self.assertEqual(names[1], "Add-on")
        self.assertNotEqual(names[0], names[1])

    def test_a_product_we_do_not_have_keeps_stripes_description(self):
        """Honest rather than blank: it is the only name that exists. The $197.92 product is in neither
        catalogue, so this line cannot be improved -- only the ones we DO know about."""
        [line] = order_line_items_from_invoice(_current(), {})

        self.assertEqual(line["name"], CURRENT_API_INVOICE["lines"]["data"][0]["description"])
        self.assertIn("$197.92", line["name"])  # the amount standing in for a name: the symptom

    def test_the_index_maps_both_ids_to_the_name(self):
        class Repo:
            @staticmethod
            def list_for_tenant(tenant_id):
                return [{"name": "Creatine Gummies", "stripe_product_id": "prod_A",
                         "prices": [{"stripe_price_id": "price_A"}, {"stripe_price_id": ""}]},
                        {"name": "", "stripe_product_id": "prod_NAMELESS"}]

        index = catalog_names_by_stripe_id(Repo(), "t1")

        self.assertEqual(index["prod_A"], "Creatine Gummies")
        self.assertEqual(index["price_A"], "Creatine Gummies")
        self.assertNotIn("", index)
        self.assertNotIn("prod_NAMELESS", index)  # a nameless product is not an improvement on anything

    def test_a_products_table_that_will_not_read_costs_the_order_nothing(self):
        class Exploding:
            @staticmethod
            def list_for_tenant(tenant_id):
                raise RuntimeError("AccessDeniedException")

        self.assertEqual(catalog_names_by_stripe_id(Exploding(), "t1"), {})

    def test_no_repository_at_all_is_fine(self):
        self.assertEqual(catalog_names_by_stripe_id(None, "t1"), {})


class RenewalCarriesTheSiloTests(unittest.TestCase):
    """A renewal belongs to the silo that SOLD the subscription, not the one processing the webhook.

    S1b stamps `silo` onto subscription_data.metadata at checkout for exactly this reason. This builder
    read that metadata for attribution and dropped the rest, so every renewal order landed unstamped
    (observed on prod, 2026-09-24) -- and the stamp cannot be recovered afterwards, because one webhook
    endpoint serves both silos and the processing side says nothing about where the sale was made.
    """

    @staticmethod
    def _invoice(metadata):
        return {**_invoice(), "subscription_details": {"metadata": metadata}}

    def test_the_subscriptions_silo_travels_onto_the_renewal_order(self):
        record = order_record_from_invoice(self._invoice({"silo": "sandbox"}), "t1", 100, {})

        self.assertEqual(record["metadata"]["silo"], "sandbox")

    def test_a_subscription_sold_before_stamping_is_not_given_a_guessed_one(self):
        # Both directions of guess are wrong, so an unstamped renewal stays unstamped and stays visible.
        record = order_record_from_invoice(_invoice(), "t1", 100, {})

        self.assertEqual(record["metadata"], {})
        self.assertNotIn("silo", record["metadata"])

    def test_the_rest_of_the_subscriptions_metadata_comes_too(self):
        # It is what a checkout order carries, and fulfilment reads the same fields from both.
        record = order_record_from_invoice(self._invoice({"offer_id": "offer_x", "silo": "production"}), "t1", 100, {})

        self.assertEqual(record["metadata"]["offer_id"], "offer_x")


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
