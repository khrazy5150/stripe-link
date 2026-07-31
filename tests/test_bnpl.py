import unittest

from stripe_link.domain.bnpl import (
    BNPL_METHODS,
    capability_name,
    checkout_payment_method_types,
    country_eligible,
    currency_eligible,
    is_valid_method,
)


class BnplDomainTests(unittest.TestCase):
    def test_method_metadata(self):
        self.assertTrue(is_valid_method("klarna"))
        self.assertFalse(is_valid_method("sezzle"))  # not a Stripe-native method — out of scope
        self.assertEqual(capability_name("klarna"), "klarna_payments")
        self.assertEqual(capability_name("afterpay_clearpay"), "afterpay_clearpay_payments")
        self.assertEqual(capability_name("nope"), "")

    def test_eligibility(self):
        self.assertTrue(currency_eligible("klarna", "USD"))   # case-insensitive
        self.assertTrue(currency_eligible("klarna", "eur"))
        self.assertFalse(currency_eligible("affirm", "eur"))  # Affirm = USD/CAD only
        self.assertTrue(country_eligible("affirm", "US"))
        self.assertFalse(country_eligible("affirm", "GB"))    # Affirm = US/CA only

    def test_checkout_types_includes_only_enabled_active_currency_eligible(self):
        config = {
            "klarna": {"enabled": True, "capability_status": "active"},
            "afterpay_clearpay": {"enabled": True, "capability_status": "pending"},   # not active yet
            "affirm": {"enabled": False, "capability_status": "active"},              # not enabled
            "zip": {"enabled": True, "capability_status": "active"},
        }
        # USD: klarna (active+enabled+usd) and zip (active+enabled+usd) qualify; afterpay pending, affirm off.
        self.assertEqual(checkout_payment_method_types(config, "usd"), ["klarna", "zip"])

    def test_checkout_types_currency_gates_out(self):
        config = {"zip": {"enabled": True, "capability_status": "active"}}  # zip = usd/aud only
        self.assertEqual(checkout_payment_method_types(config, "eur"), [])  # eur not supported → dropped
        self.assertEqual(checkout_payment_method_types(config, "aud"), ["zip"])

    def test_checkout_types_empty_config(self):
        self.assertEqual(checkout_payment_method_types(None, "usd"), [])
        self.assertEqual(checkout_payment_method_types({}, "usd"), [])

    def test_order_follows_registry(self):
        config = {m: {"enabled": True, "capability_status": "active"} for m in BNPL_METHODS}
        types = checkout_payment_method_types(config, "usd")
        # klarna, afterpay, then... affirm(usd ok), zip(usd ok) — registry order, currency-filtered.
        self.assertEqual(types[0], "klarna")
        self.assertEqual(types[1], "afterpay_clearpay")


if __name__ == "__main__":
    unittest.main()
