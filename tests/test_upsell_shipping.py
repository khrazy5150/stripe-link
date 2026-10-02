"""P1: an upsell charges postage, because nothing ever stopped it.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md. The author feared having to build shipping into every price
because bumps and upsells shipped free. Half of that was a real constraint and half was an assumption:
an ORDER BUMP is chosen on Stripe's hosted page after `shipping_options` is fixed, but an UPSELL is a
PaymentIntent we build ourselves -- no fixed options, no session to reopen, destination already known.
"""
import unittest

from handlers.upsell import quote_upsell_shipping

ITEMS = [{"product_id": "p1", "quantity": 1}]
TO = {"country": "US", "postal_code": "80202", "state": "CO"}
MEASURED = {"product_id": "p1", "name": "Shaker", "product_type": "physical",
            "fulfillment": {"requires_shipping": True, "weight_lb": 1.0,
                            "item_dimensions": {"length_in": 4, "width_in": 3, "height_in": 2,
                                                "weight_lb": 1.0}}}
UNMEASURED = {"product_id": "p1", "name": "Shaker", "product_type": "physical",
              "fulfillment": {"requires_shipping": True}}

BOXES = [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15}]
SERVICES = [{"service_token": "usps_ground", "label": "Ground"}]


def config(rule, **over):
    base = {"boxes": BOXES, "enabled_services": SERVICES,
            "ship_from_address": {"postal_code": "80301", "country": "US", "city": "Denver",
                                  "state": "CO"},
            "provider": {"name": "mock", "api_key_ref": "ref_1"},
            "zones": [{"destinations": [{"country": "US"}], "rule": rule}]}
    base.update(over)
    return base


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


def quote(cfg, products=None, destination=TO):
    import handlers.upsell as module
    import stripe_link.repositories.documents as docs

    class Repo:
        def get(self, tenant_id, doc_id=None):
            return cfg

    real = docs.shipping_config_repository
    docs.shipping_config_repository = lambda *a, **k: Repo()
    try:
        return quote_upsell_shipping("t1", ITEMS, products or {"p1": MEASURED},
                                     destination=destination, mode="test", secret_cipher=Cipher())
    finally:
        docs.shipping_config_repository = real


class TheTenantsOwnZonesDecideTests(unittest.TestCase):
    """Routed through `resolve_options`, not an upsell-specific rule -- a second pricing path would drift
    from the first within a release."""

    def test_a_live_zone_is_rated(self):
        result = quote(config({"type": "live"}))
        self.assertGreater(result["amount"], 0)
        self.assertTrue(result["service_token"])

    def test_a_flat_zone_charges_its_amount(self):
        self.assertEqual(quote(config({"type": "flat", "amount": 700}))["amount"], 700)

    def test_a_free_offers_upsells_stay_free(self):
        result = quote(config({"type": "free"}))
        self.assertEqual(result["amount"], 0)

    def test_the_cheapest_service_is_chosen_because_nobody_is_there_to_pick(self):
        # An upsell is one click by design; a service picker would cost more sales than ground-vs-overnight.
        result = quote(config({"type": "live"}))
        self.assertEqual(result["service_token"], "usps_ground")


class EveryFailureIsAZeroTests(unittest.TestCase):
    """The buyer has already clicked. Refusing a sale because a carrier was slow is a worse outcome than
    posting one parcel unpaid."""

    def test_no_destination_charges_nothing(self):
        result = quote(config({"type": "live"}), destination={})
        self.assertEqual((result["amount"], result["reason"]), (0, "no_destination"))

    def test_an_unmeasured_product_charges_nothing(self):
        # P0a applies to upsells for the same reason: a parcel nobody measured must not produce a price.
        result = quote(config({"type": "live"}), products={"p1": UNMEASURED})
        self.assertEqual((result["amount"], result["reason"]), (0, "unmeasured"))

    def test_a_carrier_failure_charges_nothing_and_says_why(self):
        result = quote(config({"type": "live"}, provider={"name": "mock", "api_key_ref": ""}))
        self.assertEqual((result["amount"], result["reason"]), (0, "carrier_error"))

    def test_an_unserved_country_charges_nothing(self):
        result = quote(config({"type": "live"}), destination={"country": "JP", "postal_code": "100"})
        self.assertEqual(result["amount"], 0)


class TheChargeAndTheRecordTests(unittest.TestCase):
    SOURCE = None

    @classmethod
    def setUpClass(cls):
        import inspect

        import handlers.upsell as module
        cls.SOURCE = inspect.getsource(module.process_upsell)

    def test_postage_is_added_to_what_the_buyer_pays(self):
        self.assertIn("charged = subtotal + shipping_amount", self.SOURCE)
        self.assertIn('"amount": str(charged)', self.SOURCE)

    def test_the_order_total_is_what_left_the_card(self):
        # Anything else and every downstream reconciliation disagrees with Stripe.
        self.assertIn('"amount_total": charged', self.SOURCE)

    def test_postage_is_recorded_apart_from_merchandise(self):
        self.assertIn('"shipping_amount": shipping_amount', self.SOURCE)

    def test_the_platform_fee_stays_on_merchandise_only(self):
        # `fee_context` was computed from the subtotal, so adding postage above cannot grow the cut.
        fee = self.SOURCE.split("platform_fee = int(fee_context", 1)[1][:420]
        self.assertIn("MERCHANDISE ONLY", fee)
        self.assertNotIn("charged", fee.split("application_fee_amount", 1)[1][:60])

    def test_the_fee_context_is_still_built_from_the_subtotal(self):
        self.assertNotIn("fee_context[\"platform_fee\"] = ", self.SOURCE)


class GrantsTests(unittest.TestCase):
    def test_the_upsell_may_read_the_zones_it_now_obeys(self):
        import pathlib

        template = (pathlib.Path(__file__).resolve().parents[1]
                    / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  UpsellFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("!Ref ShippingConfigTable", block)


class TheButtonTellsTheBuyerTests(unittest.TestCase):
    """The accept label states a price -- "Yes, I'll Take This Deal for $29". Charging more than it says
    is a misstatement to a buyer, not a rounding detail. The page is a published artifact and the
    destination is only known per session, so the figure arrives at runtime."""

    import pathlib as _pathlib

    HTML = (_pathlib.Path(__file__).resolve().parents[1]
            / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
    UPSELL = (_pathlib.Path(__file__).resolve().parents[1]
              / "src/handlers/upsell.py").read_text(encoding="utf-8")

    def test_the_session_endpoint_can_quote_the_upsells_postage(self):
        self.assertIn('"shipping": _session_shipping_quote(', self.UPSELL)

    def test_it_only_quotes_when_the_page_names_its_offer(self):
        # A page that does not send one gets no shipping figure, which is what every page did until now.
        self.assertIn('if offer_id else {}', self.UPSELL)

    def test_a_failed_disclosure_charges_nothing_rather_than_breaking_the_page(self):
        block = self.UPSELL.split("def _session_shipping_quote", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"reason": "unavailable"', block)

    def test_the_island_asks_for_it(self):
        self.assertIn("&offer=${encodeURIComponent(cta.dataset.checkoutOfferId", self.HTML)

    def test_the_island_shows_it_beside_the_button(self):
        self.assertIn("sl-upsell-shipping", self.HTML)
        self.assertIn("' shipping'", self.HTML)

    def test_it_does_not_rewrite_the_tenants_own_label(self):
        # The label is the tenant's words; folding a different number into it would be its own kind of lie.
        # Just the shipping branch -- `cta.textContent` legitimately appears in the catch handler after it.
        block = self.HTML.split("const ship = (body && body.shipping)", 1)[1].split("})", 1)[0]
        self.assertNotIn("cta.textContent =", block)
        self.assertIn("line.textContent", block)

    def test_zero_postage_shows_no_line_at_all(self):
        block = self.HTML.split("const ship = (body && body.shipping)", 1)[1][:200]
        self.assertIn("if (ship.amount > 0)", block)
