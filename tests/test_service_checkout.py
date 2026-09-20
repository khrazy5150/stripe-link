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


class ServicePricePickerTests(unittest.TestCase):
    """A service with two prices had one picked FOR it, silently.

    Products carry an Item Mode + Price picker in the offer form. Services carried neither: selecting a
    service assigned `default_price_id || prices[0]` and no control anywhere let the tenant change it. A
    service priced both one-time and recurring therefore sold whichever price happened to sort first, and
    the offer form showed no sign that a choice existed.
    """

    import pathlib as _pathlib

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    OFFERS = (ROOT / "dashboard" / "src" / "components" / "Offers.vue").read_text(encoding="utf-8")

    def test_the_tenant_can_choose_which_service_price_the_offer_sells(self):
        self.assertIn('<select v-model="row.price_id">', self.OFFERS)
        self.assertIn("servicePricesFor(row.service_id)", self.OFFERS)

    def test_the_picker_renders_a_service_with_no_price_chosen_yet(self):
        # serviceRows gates on a COMPLETE row (service_id AND price_id); driving the picker off it would
        # hide the picker in exactly the case where it is needed.
        self.assertIn("const serviceEditRows = computed(", self.OFFERS)
        self.assertIn('v-for="row in serviceEditRows"', self.OFFERS)

    def test_the_option_says_when_a_service_price_repeats(self):
        # "$197.92" and "$274.76" side by side say nothing about which one subscribes the customer.
        block = self.OFFERS.split("function servicePriceOptionLabel(price)", 1)[1][:400]
        self.assertIn("recurringSuffix(price)", block)


class ServiceOfferCheckoutModeTests(unittest.TestCase):
    """A service-only offer must still carry a checkout.mode.

    productIntent is derived from the selected PRODUCTS, so with none it reads "mixed" -- and
    inferredCheckoutMode() returns undefined for anything that is not "transaction". The document meanwhile
    stores product_intent "transaction" for a service-only offer, and validate_offer_document requires
    checkout.mode whenever product_intent is "transaction". Two definitions of one question, so the offer
    was built claiming to be a transaction with no mode at all and the save was refused.
    """

    import pathlib as _pathlib

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    OFFERS = (ROOT / "dashboard" / "src" / "components" / "Offers.vue").read_text(encoding="utf-8")

    def test_the_intent_has_one_definition(self):
        self.assertEqual(
            self.OFFERS.count('landingProducts.value.length ? productIntent.value : "transaction"'), 1,
            "the service-only intent rule is written more than once; they will drift",
        )

    def test_the_checkout_mode_guard_reads_that_definition(self):
        block = self.OFFERS.split("function inferredCheckoutMode()", 1)[1][:200]
        self.assertIn("effectiveProductIntent.value", block)
        self.assertNotIn("productIntent.value !== ", block)

    def test_the_document_reads_that_definition_too(self):
        self.assertIn("const effectiveIntent = effectiveProductIntent.value;", self.OFFERS)

    def test_the_backend_requires_the_mode_this_is_about(self):
        # Guards the premise: if checkout.mode stops being required for a transaction, this test is
        # measuring a constraint that no longer exists.
        docs = (self.ROOT / "src" / "stripe_link" / "domain" / "documents.py").read_text(encoding="utf-8")
        block = docs.split('if document.get("product_intent") == "transaction":', 1)[1][:400]
        self.assertIn('require_enum(checkout, "mode", {"payment", "subscription"}', block)
