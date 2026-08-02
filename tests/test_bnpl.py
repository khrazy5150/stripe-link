import unittest

from stripe_link.domain.bnpl import (
    BNPL_METHODS,
    apply_capability_statuses,
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


class ApplyCapabilityStatusesTests(unittest.TestCase):
    def test_refreshes_present_capabilities_and_preserves_enabled(self):
        cfg = {"klarna": {"enabled": True, "capability_status": "pending"}}
        out, changed = apply_capability_statuses(cfg, {"klarna_payments": "active"}, 100)
        self.assertTrue(changed)
        self.assertEqual(out["klarna"]["capability_status"], "active")
        self.assertTrue(out["klarna"]["enabled"])          # intent preserved
        self.assertEqual(out["klarna"]["updated_at"], 100)

    def test_absent_capability_is_left_untouched(self):
        # A partial event that omits every BNPL capability must not clobber any cached status.
        cfg = {"affirm": {"enabled": True, "capability_status": "active"}}
        out, changed = apply_capability_statuses(cfg, {"card_payments": "active"}, 100)
        self.assertFalse(changed)
        self.assertEqual(out["affirm"]["capability_status"], "active")

    def test_no_change_when_status_matches(self):
        cfg = {"klarna": {"enabled": True, "capability_status": "active"}}
        out, changed = apply_capability_statuses(cfg, {"klarna_payments": "active"}, 100)
        self.assertFalse(changed)

    def test_seeds_a_method_not_yet_in_config(self):
        out, changed = apply_capability_statuses({}, {"klarna_payments": "active"}, 100)
        self.assertTrue(changed)
        self.assertEqual(out["klarna"], {"capability_status": "active", "enabled": False, "updated_at": 100})


if __name__ == "__main__":
    unittest.main()
