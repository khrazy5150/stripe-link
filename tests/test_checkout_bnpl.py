import unittest

from handlers.checkout import build_checkout_payload, create_checkout_session_with_bnpl_fallback


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

    def test_recurring_line_excludes_bnpl(self):
        # A payment-mode session that still carries a recurring price_data line must not offer BNPL.
        products = {"p1": {"product_id": "p1", "name": "Sub",
                           "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd",
                                       "recurring": {"interval": "month"}}]}}
        payload = build_checkout_payload(
            tenant_id="t1", offer=_offer("payment"), products_by_id=products, resolved=_resolved(),
            success_url="s", cancel_url="c", bnpl_payment_method_types=["klarna"])
        self.assertIn("line_items[0][price_data][recurring][interval]", payload)  # recurring line present
        self.assertNotIn("payment_method_types[0]", payload)                      # ...so no BNPL


class _Ok:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return b'{"url": "https://checkout.stripe.com/ok"}'


class BnplCheckoutFallbackTests(unittest.TestCase):
    def test_retries_without_bnpl_when_session_fails(self):
        calls = []

        def opener(request, timeout=None):
            body = request.data.decode("utf-8")
            calls.append(body)
            if "payment_method_types" in body:   # first attempt (with BNPL) fails; retry without succeeds
                raise RuntimeError("Stripe 400: klarna not available for this currency/account")
            return _Ok()

        payload = {"mode": "payment", "payment_method_types[0]": "card", "payment_method_types[1]": "klarna", "success_url": "s"}
        result = create_checkout_session_with_bnpl_fallback(payload, api_key="sk", stripe_account="a", opener=opener, had_bnpl=True)
        self.assertEqual(result["url"], "https://checkout.stripe.com/ok")
        self.assertEqual(len(calls), 2)                          # failed once, retried once
        self.assertNotIn("payment_method_types", calls[1])       # retry dropped BNPL

    def test_no_retry_when_no_bnpl(self):
        def opener(request, timeout=None):
            raise RuntimeError("unrelated failure")
        payload = {"mode": "payment", "success_url": "s"}
        with self.assertRaises(RuntimeError):                    # had_bnpl False → surface, don't swallow/retry
            create_checkout_session_with_bnpl_fallback(payload, api_key="sk", stripe_account="a", opener=opener, had_bnpl=False)


if __name__ == "__main__":
    unittest.main()
