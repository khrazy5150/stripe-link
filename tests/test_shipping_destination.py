"""An order has to know WHERE it goes, or nothing in shipping can happen.

Checkout has collected a shipping address from buyers of physical goods all along --
`shipping_address_collection[allowed_countries]` in handlers/checkout.py, US and CA, payment mode -- and
`order_record_from_session` never read it. Every order ever written in either environment knows who bought
and not where it goes, so no label could be bought for any of them, no rate quoted, and an integration
would have nothing to hand a provider.

Invisible from the shipping module, which is why it went unnoticed: the gap is in the webhook.
"""
import unittest

from handlers.stripe_webhook import order_record_from_session
from stripe_link.domain.shipping import destination_address_from_session

SHIPPING = {
    "name": "Ada Lovelace",
    "address": {"line1": "12 Analytical Way", "line2": "Apt 4", "city": "Torrance",
                "state": "CA", "postal_code": "90501", "country": "us"},
}
CUSTOMER = {"name": "A. Lovelace", "email": "ada@example.com", "phone": "+13105551212"}


class DestinationFromSessionTests(unittest.TestCase):
    def test_the_shape_stripe_sends_today(self):
        address = destination_address_from_session({"shipping_details": SHIPPING, "customer_details": CUSTOMER})
        self.assertEqual(address, {
            "name": "Ada Lovelace", "street1": "12 Analytical Way", "street2": "Apt 4",
            "city": "Torrance", "state": "CA", "postal_code": "90501", "country": "US",
            "phone": "+13105551212", "email": "ada@example.com",
        })

    def test_the_shape_newer_api_versions_send(self):
        """Read both. We pin Stripe-Version 2024-06-20 so the flat one arrives today, but a version bump
        that silently emptied every shipping address would be found by a tenant whose labels stopped
        working, not by us."""
        address = destination_address_from_session({
            "collected_information": {"shipping_details": SHIPPING}, "customer_details": CUSTOMER,
        })
        self.assertEqual(address["street1"], "12 Analytical Way")
        self.assertEqual(address["postal_code"], "90501")

    def test_the_parcel_carries_the_shipping_name_not_the_payer(self):
        # A buyer shipping a gift typed a different name; the box has to carry it.
        address = destination_address_from_session({"shipping_details": SHIPPING, "customer_details": CUSTOMER})
        self.assertEqual(address["name"], "Ada Lovelace")

    def test_the_payer_name_is_the_fallback(self):
        address = destination_address_from_session({
            "shipping_details": {"address": SHIPPING["address"]}, "customer_details": CUSTOMER,
        })
        self.assertEqual(address["name"], "A. Lovelace")

    def test_phone_and_email_come_from_the_customer_block(self):
        # Carriers charge more for residential delivery and some require a phone for it; Stripe does not
        # put either on the shipping address.
        address = destination_address_from_session({"shipping_details": SHIPPING, "customer_details": CUSTOMER})
        self.assertEqual(address["phone"], "+13105551212")
        self.assertEqual(address["email"], "ada@example.com")

    def test_the_country_is_normalised(self):
        # Carriers want ISO-3166 alpha-2 uppercase; Stripe is not consistent about case.
        self.assertEqual(destination_address_from_session(
            {"shipping_details": SHIPPING, "customer_details": CUSTOMER})["country"], "US")

    def test_a_digital_order_has_none(self):
        self.assertEqual(destination_address_from_session({"customer_details": CUSTOMER}), {})

    def test_an_incomplete_address_is_refused_not_half_filled(self):
        """A partial destination buys a label that cannot be delivered.

        "No address" is a condition the caller can reason about; "an address missing its postcode" is not --
        it looks shippable right up until the carrier rejects it or the parcel goes nowhere.
        """
        for missing in ("line1", "city", "state", "postal_code", "country"):
            with self.subTest(missing=missing):
                address = dict(SHIPPING["address"])
                address.pop(missing)
                self.assertEqual(destination_address_from_session(
                    {"shipping_details": {"name": "Ada", "address": address},
                     "customer_details": CUSTOMER}), {})

    def test_it_survives_junk(self):
        for session in ({}, {"shipping_details": None}, {"shipping_details": {}},
                        {"shipping_details": {"address": None}}, {"collected_information": "nope"}):
            with self.subTest(session=session):
                self.assertEqual(destination_address_from_session(session), {})


class OrderRecordTests(unittest.TestCase):
    def _order(self, session_extra):
        session = {"id": "cs_test_1", "amount_total": 3900, "currency": "usd",
                   "payment_status": "paid", "customer_details": CUSTOMER, **session_extra}
        return order_record_from_session(session, "tenant_1", 1700000000, {})

    def test_a_physical_order_carries_the_destination(self):
        order = self._order({"shipping_details": SHIPPING})
        self.assertEqual(order["shipping_address"]["street1"], "12 Analytical Way")
        self.assertEqual(order["shipping_address"]["country"], "US")

    def test_a_digital_order_carries_no_empty_block(self):
        # An empty address on every download order is noise in every read of the document.
        self.assertNotIn("shipping_address", self._order({}))

    def test_the_customer_block_is_untouched(self):
        # The destination is additive: who bought is still recorded the way it always was.
        order = self._order({"shipping_details": SHIPPING})
        self.assertEqual(order["customer"]["email"], "ada@example.com")
        self.assertEqual(order["customer"]["name"], "A. Lovelace")


if __name__ == "__main__":
    unittest.main()
