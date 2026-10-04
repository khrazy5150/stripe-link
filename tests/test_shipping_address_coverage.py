"""Does EVERY way of selling a physical thing record where to send it -- and what shipping COST the buyer?

Asked 2026-09-25 after three upsells were found with no destination. The answer was no, in two places, and
the paths are not interchangeable -- each acquires its address differently, so each needs checking:

    checkout          a Checkout Session collects it              -> order_record_from_session
    order bump        rides the SAME session as a line item       -> inherits it, no second order exists
    upsell / downsell charged OFF-SESSION, no session of its own  -> read from the original session
    subscription      renews with no session at all               -> read from the cycle invoice

The two that were broken: an upsell never recorded one, and a SUBSCRIPTION never even asked -- shipping
address collection was restricted to `mode == "payment"`, so a monthly tub of creatine could not be
shipped on any cycle, including the first.

**The same question, asked of the AMOUNT (2026-09-30, plans/SHIPPING_CHARGES.md).** A destination with no
record of what the buyer paid to reach it leaves the ledger unable to separate shipping revenue from product
revenue, and a refund unable to know whether shipping comes back. `shipping_cost` rides the same two paths, so
the same four cases apply.
"""
import pathlib
import unittest

from handlers.stripe_webhook import order_record_from_invoice, order_record_from_session
from stripe_link.domain.shipping import (
    destination_address_from_invoice,
    destination_address_from_session,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

ADDRESS = {"line1": "1493 Osage St", "line2": "Apt 542-A", "city": "Denver", "state": "CO",
           "postal_code": "80204", "country": "US"}
SESSION = {
    "id": "cs_1", "mode": "payment", "payment_intent": "pi_1", "payment_status": "paid",
    "amount_total": 1834, "currency": "usd", "created": 1790000000,
    "customer_details": {"name": "Ada", "email": "ada@example.com", "phone": "+13035551212"},
    "shipping_details": {"name": "Ada", "address": ADDRESS},
    "metadata": {"order_bump_ids": "price_bump"},
}


class CheckoutTests(unittest.TestCase):
    def test_a_checkout_order_records_the_destination(self):
        record = order_record_from_session(SESSION, "t1", 100, {})
        self.assertEqual(record["shipping_address"]["city"], "Denver")

    def test_an_ORDER_BUMP_needs_no_address_of_its_own(self):
        """A bump is an optional_item on the SAME session, so it is a line on the same order. Only two
        code paths in the whole codebase create an order -- the webhook and the upsell handler -- so a
        bump cannot become an orphan without a destination."""
        source = (ROOT / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
        self.assertIn("is_order_bump", source)
        record = order_record_from_session(
            {**SESSION, "id": "cs_2"}, "t1", 100, {},
            line_items=[{"description": "Main", "quantity": 1, "price": {"id": "price_main"}},
                        {"description": "Bump", "quantity": 1, "price": {"id": "price_bump"}}])
        self.assertTrue(record["has_order_bumps"])
        self.assertEqual(record["shipping_address"]["city"], "Denver")

    def test_a_session_that_collected_nothing_records_nothing(self):
        record = order_record_from_session({**SESSION, "shipping_details": None}, "t1", 100, {})
        self.assertNotIn("shipping_address", record)


class SubscriptionCheckoutTests(unittest.TestCase):
    """The bug that made a physical subscription unshippable by design."""

    SOURCE = (ROOT / "src" / "handlers" / "checkout.py").read_text(encoding="utf-8")

    def test_shipping_is_collected_in_SUBSCRIPTION_mode_too(self):
        self.assertIn('payload["mode"] in {"payment", "subscription"}', self.SOURCE)

    def test_it_is_no_longer_restricted_to_one_time_payments(self):
        """Asserted by BUILDING a subscription payload rather than by searching the source.

        This was a `assertNotIn('collect_shipping and payload["mode"] == "payment"', SOURCE)`, which had two
        faults: it passed if someone deleted the address block entirely (the string is absent either way), and
        it false-tripped when an unrelated feature legitimately needed a payment-only condition -- which
        shipping options did on 2026-09-30. Asserting the behaviour cannot do either.
        """
        from handlers.checkout import build_checkout_payload

        products = {"p1": {"product_id": "p1", "name": "Creatine", "product_type": "physical",
                           "prices": [{"price_id": "pr1", "unit_amount": 3291, "currency": "usd"}]}}
        built = build_checkout_payload(
            tenant_id="t1", offer={"offer_id": "o1", "stripe_mode": "test",
                                   "checkout": {"mode": "subscription"}},
            products_by_id=products,
            resolved={"items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1,
                                 "unit_amount": 3291, "currency": "usd",
                                 "recurring": {"interval": "month"}}],
                      "subtotal": 3291, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c")
        self.assertEqual(built["mode"], "subscription")
        self.assertEqual(built["shipping_address_collection[allowed_countries][0]"], "US")

    def test_it_is_still_gated_on_there_being_something_physical(self):
        # A service subscription must not start demanding an address it has no use for.
        self.assertIn("collect_shipping and", self.SOURCE)
        self.assertIn('product.get("product_type") == "physical"', self.SOURCE)


CYCLE_INVOICE = {
    "id": "in_1", "billing_reason": "subscription_cycle", "created": 1790000000,
    "amount_paid": 3291, "currency": "usd",
    "customer_name": "Keith Harris", "customer_email": "k@example.com",
    "lines": {"data": []},
}


class WhatTheBuyerPaidForShipping(unittest.TestCase):
    """The amount, on the same four paths as the address."""

    def test_a_checkout_order_records_it(self):
        session = {**SESSION, "shipping_cost": {"amount_total": 795, "amount_tax": 64,
                                               "shipping_rate": "shr_ground"}}
        record = order_record_from_session(session, "t1", 100, {})
        self.assertEqual(record["shipping_amount"], 795)
        self.assertEqual(record["shipping_tax"], 64)
        self.assertEqual(record["shipping_rate_id"], "shr_ground")

    def test_a_DIGITAL_order_records_no_amount_at_all(self):
        """Absent, not zero. A stored 0 would claim shipping was offered and the buyer declined to pay."""
        record = order_record_from_session(SESSION, "t1", 100, {})
        self.assertNotIn("shipping_amount", record)

    def test_FREE_shipping_records_a_zero(self):
        """Stripe reported a shipping line of zero, which is a different fact from no shipping at all -- the
        buyer WAS offered shipping and it cost them nothing."""
        session = {**SESSION, "shipping_cost": {"amount_total": 0}}
        self.assertEqual(order_record_from_session(session, "t1", 100, {})["shipping_amount"], 0)

    def test_a_RENEWAL_records_it_from_the_invoice(self):
        """A subscription has no session of its own, so a monthly box's postage arrives on each cycle's
        invoice -- the same `shipping_cost` shape, which is why one reader serves both paths."""
        invoice = {**CYCLE_INVOICE, "shipping_details": {"name": "Keith", "address": ADDRESS},
                   "shipping_cost": {"amount_total": 500}}
        self.assertEqual(order_record_from_invoice(invoice, "t1", 100, {})["shipping_amount"], 500)

    def test_the_CARRIER_cost_is_never_taken_from_stripe(self):
        """order.shipping_cost is what the carrier charged the tenant. Stripe does not know it, and nobody
        does until a label is bought -- so it is absent rather than zero."""
        session = {**SESSION, "shipping_cost": {"amount_total": 795}}
        self.assertNotIn("shipping_cost", order_record_from_session(session, "t1", 100, {}))

    def test_both_order_builders_use_the_SAME_reader(self):
        """Two builders drifting apart is how the address bug happened in the first place.

        Checks each function's OWN body rather than counting occurrences in the file, so adding a third order
        path without the reader fails here instead of passing on a coincidental total.
        """
        source = (ROOT / "src" / "handlers" / "stripe_webhook.py").read_text(encoding="utf-8")
        for builder in ("order_record_from_session", "order_record_from_invoice"):
            start = source.index(f"def {builder}(")
            body = source[start:source.index("\ndef ", start + 1)]
            self.assertIn("buyer_paid_shipping(", body, f"{builder} does not record what shipping cost")


class RenewalTests(unittest.TestCase):
    def test_a_renewal_takes_its_destination_from_the_invoice(self):
        invoice = {**CYCLE_INVOICE, "shipping_details": {"name": "Keith", "address": ADDRESS}}
        record = order_record_from_invoice(invoice, "t1", 100, {})
        self.assertEqual(record["shipping_address"]["city"], "Denver")
        self.assertEqual(record["shipping_address"]["name"], "Keith")

    def test_the_older_customer_shipping_shape_works_too(self):
        invoice = {**CYCLE_INVOICE, "customer_shipping": {"name": "Keith", "address": ADDRESS}}
        self.assertEqual(destination_address_from_invoice(invoice)["postal_code"], "80204")

    def test_the_BILLING_address_is_never_used_as_a_destination(self):
        """Measured on a real invoice: customer_address held a St. George UT address while BOTH shipping
        fields were null. Shipping to the billing address is the kind of plausible-looking wrong answer
        that posts a parcel to the wrong place and tells nobody."""
        invoice = {**CYCLE_INVOICE, "customer_shipping": None, "shipping_details": None,
                   "customer_address": {"line1": "176 W 300 S St Apt 19", "city": "St. George",
                                        "state": "UT", "postal_code": "84770", "country": "US"}}

        self.assertEqual(destination_address_from_invoice(invoice), {})
        self.assertNotIn("shipping_address", order_record_from_invoice(invoice, "t1", 100, {}))

    def test_a_service_renewal_has_no_destination_and_that_is_correct(self):
        self.assertNotIn("shipping_address", order_record_from_invoice(CYCLE_INVOICE, "t1", 100, {}))

    def test_a_partial_address_is_refused_rather_than_half_recorded(self):
        """A destination missing its postcode buys a label that cannot be delivered."""
        invoice = {**CYCLE_INVOICE,
                   "shipping_details": {"name": "K", "address": {**ADDRESS, "postal_code": ""}}}
        self.assertEqual(destination_address_from_invoice(invoice), {})


class UpsellTests(unittest.TestCase):
    """The upsell path is covered end to end in test_upsell_handler.py; this pins the shared contract."""

    def test_the_session_parser_is_what_both_paths_use(self):
        self.assertEqual(destination_address_from_session(SESSION)["city"], "Denver")
        source = (ROOT / "src" / "handlers" / "upsell.py").read_text(encoding="utf-8")
        self.assertIn("destination_address_from_session", source)

    def test_a_downsell_goes_through_the_SAME_handler_so_it_is_covered_too(self):
        """A downsell is an in-place swap on decline, charged by process_upsell with the downsell price
        context -- not a separate code path that could be forgotten."""
        source = (ROOT / "src" / "handlers" / "upsell.py").read_text(encoding="utf-8")
        self.assertIn('"allowed_price_contexts": ["upsell", "downsell"]', source)
        self.assertEqual(source.count("orders_repo.put(order_record)"), 1)


if __name__ == "__main__":
    unittest.main()


class AndAPhoneNumberForTheCarrierTests(unittest.TestCase):
    """The destination plumbing has carried `customer.phone` since it was written -- 
    `destination_address_from_session` reads it, and the label buyer sends it to the carrier, because a
    courier may need to call the recipient for a failed delivery, a gate code or a signature.

    Hosted Checkout never asked for it, so it was always empty (author, 2026-10-04). Nothing downstream
    needed changing; the field simply had to be collected.
    """

    SOURCE = (ROOT / "src" / "handlers" / "checkout.py").read_text()

    def test_the_session_asks_for_one(self):
        self.assertIn('payload["phone_number_collection[enabled]"] = "true"', self.SOURCE)

    def test_it_is_asked_for_ONLY_where_there_is_a_parcel(self):
        """Stripe's hosted Checkout has no optional mode for this field: when collection is on, the buyer
        must fill it in. Enabling it unconditionally would put a required field in front of every download
        and every tip, for a delivery that can never happen."""
        block = self.SOURCE.split("shipping_address_collection[allowed_countries]", 1)[1][:900]
        self.assertIn("phone_number_collection", block)
        # Inside the shipping branch: the collection line and the allowed-countries loop share a parent.
        countries_indent = self._indent_of('            payload[f"shipping_address_collection[allowed_countries]')
        phone_indent = self._indent_of('        payload["phone_number_collection[enabled]"]')
        self.assertLess(phone_indent, countries_indent)
        self.assertGreater(phone_indent, 4, "must be nested inside the shipping guard, not at handler scope")

    def _indent_of(self, prefix):
        for line in self.SOURCE.splitlines():
            if line.startswith(prefix):
                return len(line) - len(line.lstrip())
        raise AssertionError(f"no line starting {prefix!r}")

    def test_a_collected_phone_still_reaches_the_destination(self):
        # The half that already worked, asserted so the two cannot drift apart again.
        self.assertEqual(destination_address_from_session(SESSION)["phone"], "+13035551212")
