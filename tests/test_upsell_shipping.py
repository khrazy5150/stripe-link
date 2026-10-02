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


def quote(cfg, products=None, destination=TO, baseline=None):
    import handlers.upsell as module
    import stripe_link.repositories.documents as docs

    class Repo:
        def get(self, tenant_id, doc_id=None):
            return cfg

    real = docs.shipping_config_repository
    docs.shipping_config_repository = lambda *a, **k: Repo()
    try:
        return quote_upsell_shipping("t1", ITEMS, products or {"p1": MEASURED},
                                     destination=destination, mode="test", secret_cipher=Cipher(),
                                     baseline=baseline)
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

    def test_it_only_quotes_when_the_page_names_its_offer_AND_product(self):
        # The offer alone is not enough: an upsell page's CTA carries the funnel's SOURCE offer, whose
        # items are the original bundle. Quoting those disclosed the wrong parcel entirely.
        self.assertIn('if offer_id and product_id else {}', self.UPSELL)

    def test_the_disclosure_rates_the_UPSELLS_product_not_the_offers_bundle(self):
        block = self.UPSELL.split("def _session_shipping_quote", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('[{"product_id": wanted, "quantity": 1}]', block)
        self.assertNotIn('offer.get("items")', block)

    def test_the_disclosure_uses_the_SAME_baseline_as_the_charge(self):
        # Otherwise the button prices a standalone parcel while the card prices the delta: "+ $6.11" for
        # an item the charge added for $0.08.
        self.assertIn("baseline=session_shipping_baseline(session_id", self.UPSELL)
        block = self.UPSELL.split("def _session_shipping_quote", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("baseline=baseline", block)

    def test_the_island_sends_the_product(self):
        import pathlib as _p

        html = (_p.Path(__file__).resolve().parents[1]
                / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        self.assertIn("product_id=${encodeURIComponent(cta.dataset.checkoutProductId", html)

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


class TheDeltaNotASecondParcelTests(unittest.TestCase):
    """The author, 2026-10-02, shown "+ $6.11" for one supplement added to an order already paying $6.11:
    *"the complete bundle costs $6.11, so there should be no additional shipping charge."*

    An item that rides in a parcel already going costs close to nothing to add. Billing a full second
    parcel for it is an overcharge dressed up as a quote.
    """

    BASELINE = {"items": [{"product_id": "p1", "quantity": 1}], "amount": 611}

    def test_an_item_that_fits_the_same_box_adds_nothing(self):
        result = quote(config({"type": "flat", "amount": 611}), baseline=self.BASELINE)
        self.assertEqual(result["amount"], 0)
        self.assertEqual(result["reason"], "combined_delta")

    def test_the_buyer_pays_only_the_difference(self):
        # A flat zone cannot grow, so a baseline that paid LESS than the flat rate shows the delta plainly.
        result = quote(config({"type": "flat", "amount": 700}), baseline={**self.BASELINE, "amount": 500})
        self.assertEqual(result["amount"], 200)

    def test_it_never_goes_negative(self):
        result = quote(config({"type": "flat", "amount": 400}), baseline={**self.BASELINE, "amount": 900})
        self.assertEqual(result["amount"], 0)

    def test_without_a_baseline_it_falls_back_to_a_full_rate(self):
        # An older order, an expired quote row. Over-charging a tenant's own postage is recoverable where
        # under-charging silently is not, so this stays the safe direction when nothing better is known.
        result = quote(config({"type": "flat", "amount": 700}))
        self.assertEqual((result["amount"], result["reason"]), (700, "standalone"))

    def test_a_baseline_with_no_recorded_payment_is_not_used(self):
        result = quote(config({"type": "flat", "amount": 700}), baseline={**self.BASELINE, "amount": 0})
        self.assertEqual(result["reason"], "standalone")

    def test_the_distinct_failure_reasons_survive(self):
        # `unmeasured`, `carrier_error` and `no_options` are three different problems with three different
        # fixes; collapsing them would make a silent zero unexplainable.
        self.assertEqual(quote(config({"type": "live"}), products={"p1": UNMEASURED})["reason"],
                         "unmeasured")
        self.assertEqual(
            quote(config({"type": "live"}, provider={"name": "mock", "api_key_ref": ""}))["reason"],
            "carrier_error")


class TheUpsellReachesTheLedgerTests(unittest.TestCase):
    """An upsell wrote an ORDER and nothing else. It is a PaymentIntent we create directly, so no
    `checkout.session.completed` fires and the webhook -- which appends every other sale -- never hears
    about it. Two upsell orders were on the books with neither in the ledger (2026-10-02)."""

    ORDER = {"tenant_id": "t1", "order_id": "order_up_1", "payment_intent_id": "pi_up_1",
             "amount_total": 2013, "currency": "usd", "mode": "test", "shipping_amount": 568,
             "line_item_type": "upsell", "fees": {"stripe_fee": 72, "platform_fee": 72}}

    def test_the_sale_is_appended(self):
        from handlers.upsell import record_upsell_ledger_entry

        class Repo:
            def __init__(self):
                self.rows = []

            def append(self, entry):
                self.rows.append(entry)

        repo = Repo()
        self.assertTrue(record_upsell_ledger_entry(self.ORDER, ledger_repo=repo))
        amounts = repo.rows[0]["amounts"]
        self.assertEqual(amounts["gross"], 2013)
        self.assertEqual(amounts["shipping_revenue"], 568)
        self.assertEqual(amounts["platform_fee"], -72)

    def test_its_postage_is_partitioned_like_any_other_sale(self):
        from handlers.upsell import record_upsell_ledger_entry
        from stripe_link.domain.ledger import summarize

        captured = []

        class Repo:
            def append(self, entry):
                captured.append(entry)

        record_upsell_ledger_entry(self.ORDER, ledger_repo=Repo())
        summary = summarize(captured)
        self.assertEqual(summary["merchandise_revenue"], 1445)
        self.assertEqual(summary["shipping_revenue"], 568)

    def test_a_ledger_outage_never_undoes_a_charge(self):
        from handlers.upsell import record_upsell_ledger_entry

        class Broken:
            def append(self, entry):
                raise RuntimeError("dynamo down")

        self.assertFalse(record_upsell_ledger_entry(self.ORDER, ledger_repo=Broken()))

    def test_the_function_may_write_the_ledger(self):
        import pathlib

        template = (pathlib.Path(__file__).resolve().parents[1]
                    / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  UpsellFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("!Ref LedgerTable", block)


class TheBaselineComesFromTheSessionTests(unittest.TestCase):
    """A buyer reaches the first upsell seconds after paying, and the ORDER is written by the webhook.

    Reading the baseline from the order lost that race: in one real run the first upsell fell back to a
    full standalone parcel at $6.27 while the second, moments later, got its delta of $0.08 -- for
    comparably sized items (author, 2026-10-02). The SESSION carries the same facts the instant checkout
    completes, because `metadata[shipping_quote_id]` and `[shipping_quoted_amount]` are stamped at
    session creation.
    """

    import pathlib as _p

    UPSELL = (_p.Path(__file__).resolve().parents[1]
              / "src/handlers/upsell.py").read_text(encoding="utf-8")

    def test_the_baseline_is_read_from_stripe_not_the_orders_table(self):
        block = self.UPSELL.split("def session_shipping_baseline", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("/checkout/sessions/", block)
        self.assertIn('meta.get("shipping_quote_id")', block)
        self.assertIn('meta.get("shipping_quoted_amount")', block)

    def test_the_order_based_lookup_is_gone(self):
        self.assertNotIn("original_shipping_baseline", self.UPSELL)

    def test_checkout_stamps_what_it_reads(self):
        import pathlib as _p

        checkout = (_p.Path(__file__).resolve().parents[1]
                    / "src/handlers/checkout.py").read_text(encoding="utf-8")
        self.assertIn('payload["metadata[shipping_quote_id]"]', checkout)
        self.assertIn('payload["metadata[shipping_quoted_amount]"]', checkout)

    def test_an_unreachable_session_falls_back_rather_than_failing(self):
        block = self.UPSELL.split("def session_shipping_baseline", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("return {}", block)
