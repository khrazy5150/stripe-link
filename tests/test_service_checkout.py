"""Buying a service.

Author, 2026-09-20, the first time a real service reached checkout: "when the page is created and a purchase
is attempted, there is an error" -- `Price 'price_YfKUTw0dfMF' was not found on product ''`.

Everything on the way in handled services: the loader, the resolver, the fee context, the Stripe payload. The
one function that did not was `apply_tip_amount`, which runs between resolution and payload building and
looked every line up in `products_by_id` to ask "is this a tip jar?". A service has no product document, so
`find_price({}, price_id)` raised and took the whole checkout with it.

Worth noting WHY 59 passing service tests missed it: they cover resolution and rendering, and this is the one
seam where a service line passes through code written for products. Nothing exercised a service through the
checkout HANDLER until a tenant did.
"""
import unittest

from handlers.checkout import apply_tip_amount, build_checkout_payload
from stripe_link.domain.pricing import resolve_offer

SERVICE = {
    "service_id": "svc_1", "name": "120 minute massage", "active": True,
    "fulfillment_mode": "no_booking", "booking_flow": "pay_then_book", "duration_minutes": 0,
    "default_price_id": "price_1",
    "prices": [{"price_id": "price_1", "currency": "usd", "unit_amount": 27476, "stripe_price_id": None}],
}
OFFER = {
    "offer_id": "offer_1", "tenant_id": "t1", "status": "active", "stripe_mode": "test",
    "items": [{"service_id": "svc_1", "price_id": "price_1", "quantity": 1}],
    "checkout": {},
}


def _resolved():
    return resolve_offer(OFFER, {}, {}, services_by_id={"svc_1": SERVICE})


class TipPricingSkipsServicesTests(unittest.TestCase):
    def test_a_service_line_does_not_go_looking_for_a_product(self):
        resolved = _resolved()
        # The reported crash: no exception is the assertion.
        apply_tip_amount(resolved, {}, amount="", source="preset", recurring=False,
                         tenant_id="t1", tenant_repo=None, billing_config_loader=None)
        self.assertEqual(resolved["items"][0]["kind"], "service")

    def test_it_leaves_the_service_line_untouched(self):
        resolved = _resolved()
        before = dict(resolved["items"][0])
        apply_tip_amount(resolved, {}, amount="", source="preset", recurring=False,
                         tenant_id="t1", tenant_repo=None, billing_config_loader=None)
        self.assertEqual(resolved["items"][0], before)

    def test_a_product_tip_jar_still_works(self):
        """The skip must not swallow the case the function exists for."""
        import inspect

        source = inspect.getsource(apply_tip_amount)
        guard = source.split("for line in", 1)[1].split("product =", 1)[0]
        self.assertIn('line.get("kind") == "service"', guard)
        self.assertIn('line.get("service_id")', guard)


class ServiceCheckoutPayloadTests(unittest.TestCase):
    def test_the_whole_chain_produces_a_stripe_line(self):
        resolved = _resolved()
        apply_tip_amount(resolved, {}, amount="", source="preset", recurring=False,
                         tenant_id="t1", tenant_repo=None, billing_config_loader=None)
        payload = build_checkout_payload(
            offer=OFFER, resolved=resolved, products_by_id={}, tenant_id="t1",
            success_url="https://e.com/ok", cancel_url="https://e.com/no",
        )
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], "27476")
        self.assertEqual(payload["line_items[0][price_data][product_data][name]"], "120 minute massage")

    def test_it_is_priced_inline_because_a_service_has_no_stripe_price(self):
        # stripe_price_id is null on every service price; the line is built from price_data instead.
        resolved = _resolved()
        payload = build_checkout_payload(
            offer=OFFER, resolved=resolved, products_by_id={}, tenant_id="t1",
            success_url="https://e.com/ok", cancel_url="https://e.com/no",
        )
        self.assertNotIn("line_items[0][price]", payload)

    def test_the_booking_metadata_travels_with_it(self):
        resolved = _resolved()
        payload = build_checkout_payload(
            offer=OFFER, resolved=resolved, products_by_id={}, tenant_id="t1",
            success_url="https://e.com/ok", cancel_url="https://e.com/no",
        )
        self.assertEqual(payload["metadata[service_id]"], "svc_1")
        self.assertIn("metadata[service_lines]", payload)


if __name__ == "__main__":
    unittest.main()


class FunnelDiagramTests(unittest.TestCase):
    """The purchase-flow diagram only ever knew products.

    Reported alongside the checkout failure: the Offers screen showed NO diagram for a service offer, and the
    landing-page builder showed one whose card read `svc_...` instead of the service's name. Same cause --
    the diagram's lookup and its landing stage were both product-only.
    """

    import pathlib as _pathlib

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    DASH = ROOT / "dashboard" / "src"
    OFFERS = (DASH / "components" / "Offers.vue").read_text(encoding="utf-8")
    LANDING = (DASH / "components" / "LandingPages.vue").read_text(encoding="utf-8")
    STORE = (DASH / "stores" / "products.js").read_text(encoding="utf-8")

    def test_one_adapter_serves_both_screens(self):
        # A third copy of "shape a service like a product" is how the first two drift apart.
        self.assertIn("export function serviceFlowCard(service)", self.STORE)
        for name, src in (("Offers.vue", self.OFFERS), ("LandingPages.vue", self.LANDING)):
            self.assertIn("serviceFlowCard", src, name)

    def test_the_name_resolves_instead_of_showing_an_id(self):
        for name, src in (("Offers.vue", self.OFFERS), ("LandingPages.vue", self.LANDING)):
            block = src.split("resolveProduct:", 1)[1][:400]
            self.assertIn("service", block, name)

    def test_each_screen_reads_the_services_IT_loads(self):
        """LandingPages keeps its own `services` ref and never populates the pinia store.

        Reading the store there would have been permanently empty -- imported, wired, and always blank.
        """
        landing_block = self.LANDING.split("resolveProduct:", 1)[1][:400]
        self.assertIn("services.value", landing_block)
        self.assertNotIn("servicesStore", self.LANDING)
        offers_block = self.OFFERS.split("resolveProduct:", 1)[1][:400]
        self.assertIn("servicesStore.services", offers_block)

    def test_a_service_only_offer_gets_a_landing_stage(self):
        """Services live in form.services, not in the product list -- so the stage was empty and the whole
        diagram was hidden."""
        block = self.OFFERS.split("const offerFunnelStages = computed(", 1)[1].split("if (landing.length)", 1)[0]
        self.assertIn("form.services", block)
        self.assertIn("serviceFlowCard", block)
