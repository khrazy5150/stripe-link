"""Does EVERY way of selling a physical thing record where to send it?

Asked 2026-09-25 after three upsells were found with no destination. The answer was no, in two places, and
the paths are not interchangeable -- each acquires its address differently, so each needs checking:

    checkout          a Checkout Session collects it              -> order_record_from_session
    order bump        rides the SAME session as a line item       -> inherits it, no second order exists
    upsell / downsell charged OFF-SESSION, no session of its own  -> read from the original session
    subscription      renews with no session at all               -> read from the cycle invoice

The two that were broken: an upsell never recorded one, and a SUBSCRIPTION never even asked -- shipping
address collection was restricted to `mode == "payment"`, so a monthly tub of creatine could not be
shipped on any cycle, including the first.
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
        self.assertNotIn('collect_shipping and payload["mode"] == "payment"', self.SOURCE)

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
