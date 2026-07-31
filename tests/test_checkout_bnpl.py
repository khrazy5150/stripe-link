import unittest

from handlers.checkout import build_checkout_payload


def _offer(mode="payment"):
    return {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": mode}}


def _resolved(currency="usd"):
    return {"items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1, "unit_amount": 2000, "currency": currency}],
            "subtotal": 2000, "currency": currency}


def _products():
    return {"p1": {"product_id": "p1", "name": "Widget",
                   "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}}


def _payload(bnpl, mode="payment"):
    return build_checkout_payload(
        tenant_id="t1", offer=_offer(mode), products_by_id=_products(), resolved=_resolved(),
        success_url="https://x/s", cancel_url="https://x/c", bnpl_payment_method_types=bnpl,
    )


class CheckoutBnplPayloadTests(unittest.TestCase):
    def test_bnpl_adds_card_plus_methods_in_payment_mode(self):
        payload = _payload(["klarna"])
        self.assertEqual(payload["payment_method_types[0]"], "card")   # card must be included when explicit
        self.assertEqual(payload["payment_method_types[1]"], "klarna")

    def test_no_bnpl_leaves_payment_methods_to_stripe_defaults(self):
        payload = _payload([])
        self.assertNotIn("payment_method_types[0]", payload)           # don't override when nothing to add

    def test_subscription_mode_never_sets_bnpl(self):
        payload = _payload(["klarna"], mode="subscription")
        self.assertNotIn("payment_method_types[0]", payload)           # BNPL is one-time only

    def test_card_not_duplicated_if_passed(self):
        payload = _payload(["card", "klarna"])
        self.assertEqual(payload["payment_method_types[0]"], "card")
        self.assertEqual(payload["payment_method_types[1]"], "klarna")
        self.assertNotIn("payment_method_types[2]", payload)


if __name__ == "__main__":
    unittest.main()
