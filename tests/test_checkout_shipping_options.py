"""Shipping options on the Checkout Session — the last thing wired, on purpose.

plans/SHIPPING_CHARGES.md phase 6. Checkout is the one consumer that cannot be corrected after the fact: a
session that quoted the wrong postage has already told someone a price. So the two economic rules (the fee
base, and the Smart Pricing invariant) were settled before this existed.
"""
import pathlib
import unittest

from handlers.checkout import _flatten_params, build_checkout_payload

ROOT = pathlib.Path(__file__).resolve().parents[1]

GROUND = {"label": "Ground (5-7 days)", "amount": 0, "transit_days_min": 5, "transit_days_max": 7}
OVERNIGHT = {"label": "Overnight", "amount": 2500, "transit_days_min": 1, "transit_days_max": 1}


def offer(*options, mode="payment", free_above_amount=None):
    shipping = {"options": list(options)} if options else {}
    if free_above_amount is not None:
        shipping["free_above_amount"] = free_above_amount
    out = {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": mode}}
    if shipping:
        out["shipping"] = shipping
    return out


def resolved(quantity=1, subtotal=2000, recurring=None, digital=False):
    item = {"product_id": "d1" if digital else "p1", "price_id": "pr1", "quantity": quantity,
            "unit_amount": subtotal // max(1, quantity), "currency": "usd"}
    if recurring:
        item["recurring"] = recurring
    return {"items": [item], "subtotal": subtotal, "currency": "usd"}


PRODUCTS = {
    "p1": {"product_id": "p1", "name": "Shirt", "product_type": "physical",
           "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]},
    "d1": {"product_id": "d1", "name": "Ebook", "product_type": "digital",
           "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]},
}


def payload(the_offer, the_resolved=None):
    return build_checkout_payload(
        tenant_id="t1", offer=the_offer, products_by_id=PRODUCTS,
        resolved=the_resolved or resolved(), success_url="https://x/s", cancel_url="https://x/c",
    )


def option_keys(built):
    return {k: v for k, v in built.items() if k.startswith("shipping_options")}


class WhenOptionsAreSent(unittest.TestCase):
    def test_a_physical_payment_session_carries_them(self):
        built = payload(offer(GROUND, OVERNIGHT))
        self.assertEqual(built["shipping_options[0][shipping_rate_data][display_name]"], "Ground (5-7 days)")
        self.assertEqual(built["shipping_options[0][shipping_rate_data][fixed_amount][amount]"], "0")
        self.assertEqual(built["shipping_options[1][shipping_rate_data][display_name]"], "Overnight")
        self.assertEqual(built["shipping_options[1][shipping_rate_data][fixed_amount][amount]"], "2500")

    def test_the_shipping_tax_code_travels(self):
        built = payload(offer(OVERNIGHT))
        self.assertEqual(built["shipping_options[0][shipping_rate_data][tax_code]"], "txcd_92010001")

    def test_delivery_estimates_travel(self):
        built = payload(offer(OVERNIGHT))
        self.assertEqual(built["shipping_options[0][shipping_rate_data][delivery_estimate][minimum][unit]"],
                         "business_day")
        self.assertEqual(built["shipping_options[0][shipping_rate_data][delivery_estimate][maximum][value]"],
                         "1")

    def test_an_offer_with_no_shipping_block_sends_nothing(self):
        """Today's behaviour, unchanged: the address is collected and no postage is charged."""
        built = payload(offer())
        self.assertEqual(option_keys(built), {})
        self.assertEqual(built["shipping_address_collection[allowed_countries][0]"], "US")

    def test_a_digital_only_cart_sends_nothing(self):
        built = payload(offer(OVERNIGHT), resolved(digital=True))
        self.assertEqual(option_keys(built), {})


class SubscriptionsAreExcludedDeliberately(unittest.TestCase):
    """Two unresolved things gate them, and neither is an oversight.

    Whether the chosen shipping recurs on every invoice is UNVERIFIED against Stripe -- a monthly box needs
    postage each cycle, a one-shipment subscription does not, and guessing wrong either double-charges a buyer
    every month or ships eleven parcels free. And a subscription fee is a PERCENT, so with buyer-chosen
    shipping the absolute platform fee cannot be made exact.
    """

    def test_a_recurring_session_charges_no_postage(self):
        built = payload(offer(GROUND, OVERNIGHT), resolved(recurring={"interval": "month"}))
        self.assertEqual(option_keys(built), {})

    def test_but_it_still_collects_an_address(self):
        """It must, or a monthly tub of creatine cannot be shipped at all -- the 2026-09-25 bug."""
        built = payload(offer(GROUND), resolved(recurring={"interval": "month"}))
        self.assertEqual(built["shipping_address_collection[allowed_countries][0]"], "US")


class CartContextReachesTheCalculator(unittest.TestCase):
    def test_per_item_counts_PHYSICAL_units_only(self):
        """Three shirts and an ebook is three things to post, not four."""
        per_item = {"label": "Ground", "kind": "per_item", "amount": 200, "first_item_amount": 795}
        built = build_checkout_payload(
            tenant_id="t1", offer=offer(per_item), products_by_id=PRODUCTS,
            resolved={"items": [{"product_id": "p1", "price_id": "pr1", "quantity": 3, "unit_amount": 2000,
                                 "currency": "usd"},
                                {"product_id": "d1", "price_id": "pr1", "quantity": 1, "unit_amount": 500,
                                 "currency": "usd"}],
                      "subtotal": 6500, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c")
        # 795 + 200*2 = 1195, not 795 + 200*3
        self.assertEqual(built["shipping_options[0][shipping_rate_data][fixed_amount][amount]"], "1195")

    def test_the_free_above_threshold_uses_the_resolved_subtotal(self):
        built = payload(offer({"label": "Ground", "amount": 800}, OVERNIGHT, free_above_amount=5000),
                        resolved(subtotal=5000))
        self.assertEqual(built["shipping_options[0][shipping_rate_data][fixed_amount][amount]"], "0")
        self.assertEqual(built["shipping_options[1][shipping_rate_data][fixed_amount][amount]"], "2500")

    def test_below_the_threshold_the_baseline_is_charged(self):
        built = payload(offer({"label": "Ground", "amount": 800}, free_above_amount=5000),
                        resolved(subtotal=4999))
        self.assertEqual(built["shipping_options[0][shipping_rate_data][fixed_amount][amount]"], "800")


class TheFormEncoder(unittest.TestCase):
    def test_it_nests_three_deep(self):
        flat = _flatten_params({"a": {"b": {"c": 1}}})
        self.assertEqual(flat, {"[a][b][c]": "1"})

    def test_booleans_become_stripe_booleans(self):
        self.assertEqual(_flatten_params({"enabled": True}), {"[enabled]": "true"})

    def test_none_is_omitted_not_stringified(self):
        """`display_name: "None"` on a checkout page is the failure this prevents."""
        self.assertEqual(_flatten_params({"a": None, "b": 1}), {"[b]": "1"})

    def test_lists_are_indexed(self):
        self.assertEqual(_flatten_params({"x": ["p", "q"]}), {"[x][0]": "p", "[x][1]": "q"})


class AnnotationsMustRESOLVE(unittest.TestCase):
    """Python 3.14 evaluates annotations lazily; Lambda runs **python3.12**, which evaluates them eagerly.

    A bare `Any` with no import passed locally and imported fine, and would have raised NameError on import in
    production — taking every checkout down. Caught here rather than in a deploy, because the local
    interpreter cannot be relied on to notice.
    """

    def test_the_runtime_is_still_older_than_lazy_annotations(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertIn("Runtime: python3.12", template,
                      "if the runtime moved, revisit whether this guard is still needed")

    def test_every_handler_module_has_resolvable_annotations(self):
        import importlib
        import inspect

        for path in sorted((ROOT / "src" / "handlers").glob("*.py")):
            if path.stem == "__init__":
                continue
            module = importlib.import_module(f"handlers.{path.stem}")
            for name, member in vars(module).items():
                if not inspect.isfunction(member) or member.__module__ != module.__name__:
                    continue
                with self.subTest(module=path.stem, function=name):
                    # Touching __annotations__ forces evaluation, which is what python3.12 does at def time.
                    member.__annotations__  # noqa: B018


if __name__ == "__main__":
    unittest.main()
