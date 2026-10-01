"""The controlled variance: what the buyer was quoted, what the carrier charged, and the gap.

plans/LIVE_SHIPPING_RATES.md phase 5. Hosted Checkout prefills a shipping address but gives us no way to
LOCK it, so a buyer quoted for 80202 can type 80205 on Stripe's page. That is irreducible without leaving
hosted Checkout, so it is measured rather than prevented -- and never allowed to block a fulfillment.
"""
import unittest

from handlers.shipping import quoted_service_status, record_shipping_variance
from stripe_link.domain.shipping_quotes import agreed_shipping, variance

META = {"shipping_quote_id": "shq_1", "shipping_service": "ups_ground",
        "shipping_quoted_amount": "642", "shipping_postal_code": "80202"}


class Actuals:
    def __init__(self, fail=False):
        self.rows, self.fail = {}, fail

    def put(self, record):
        # One argument, like the real repository. The tenant must be ON the document.
        if self.fail:
            raise RuntimeError("dynamo down")
        self.rows[(str(record["tenant_id"]), record["order_id"])] = record


def an_order(**over):
    base = {"order_id": "ord_1",
            "shipping_address": {"postal_code": "80205", "country": "US"},
            **agreed_shipping(META, {"postal_code": "80205"})}
    base.update(over)
    return base


def a_shipment(amount=910, service="ups_ground", carrier="ups"):
    return {"cost": {"amount": amount, "currency": "usd"}, "service": service, "carrier": carrier}


class TheOrderKeepsBothAddresses(unittest.TestCase):
    def test_an_order_with_no_quote_gets_no_block_at_all(self):
        # Rather than one full of empty strings claiming a quote that never existed.
        self.assertEqual(agreed_shipping({}, {"postal_code": "80205"}), {})

    def test_both_postcodes_are_recorded(self):
        block = agreed_shipping(META, {"postal_code": "80205"})["shipping_quote"]
        self.assertEqual(block["quoted_postal_code"], "80202")
        self.assertEqual(block["actual_postal_code"], "80205")
        self.assertFalse(block["destination_matches"])

    def test_a_matching_address_is_recorded_as_matching(self):
        block = agreed_shipping(META, {"postal_code": "80202"})["shipping_quote"]
        self.assertTrue(block["destination_matches"])

    def test_formatting_differences_are_not_a_mismatch(self):
        block = agreed_shipping({**META, "shipping_postal_code": "k1a 0b1"},
                                {"postal_code": "K1A0B1"})["shipping_quote"]
        self.assertTrue(block["destination_matches"])

    def test_what_the_buyer_agreed_to_is_kept_in_full(self):
        block = agreed_shipping(META, {})["shipping_quote"]
        self.assertEqual((block["quote_id"], block["service_token"], block["quoted_amount"]),
                         ("shq_1", "ups_ground", 642))


class TheLabelsRealCostIsASeparateRecord(unittest.TestCase):
    def test_the_variance_is_written_against_the_order(self):
        store = Actuals()
        record = record_shipping_variance(an_order(), a_shipment(), "t1", mode="test", now=100,
                                          actuals_repo=store)
        self.assertEqual(record["quoted_amount"], 642)
        self.assertEqual(record["actual_amount"], 910)
        self.assertEqual(record["delta"], 268)
        self.assertTrue(record["flagged"])
        self.assertIn(("t1", "ord_1"), store.rows)

    def test_it_carries_both_destinations_so_it_explains_itself(self):
        record = record_shipping_variance(an_order(), a_shipment(), "t1", mode="test", now=100,
                                          actuals_repo=Actuals())
        self.assertEqual(record["quoted_destination"]["postal_code"], "80202")
        self.assertEqual(record["destination"]["postal_code"], "80205")

    def test_a_cheaper_label_is_recorded_and_not_flagged(self):
        record = record_shipping_variance(an_order(), a_shipment(amount=300), "t1", mode="test", now=100,
                                          actuals_repo=Actuals())
        self.assertEqual(record["direction"], "under")
        self.assertFalse(record["flagged"])

    def test_a_small_rise_is_within_tolerance(self):
        record = record_shipping_variance(an_order(), a_shipment(amount=800), "t1", mode="test", now=100,
                                          actuals_repo=Actuals())
        self.assertFalse(record["flagged"])

    def test_a_substituted_service_is_marked_as_such(self):
        # A different fact from a price that moved, and conflating them would tell the tenant their
        # postage went up when the buyer's chosen speed was never available.
        record = record_shipping_variance(an_order(), a_shipment(service="usps_priority"), "t1",
                                          mode="test", now=100, actuals_repo=Actuals())
        self.assertTrue(record["service_substituted"])
        self.assertEqual(record["quoted_service_token"], "ups_ground")

    def test_the_same_service_is_not_marked_substituted(self):
        record = record_shipping_variance(an_order(), a_shipment(), "t1", mode="test", now=100,
                                          actuals_repo=Actuals())
        self.assertFalse(record["service_substituted"])

    def test_an_order_with_no_quote_records_nothing(self):
        plain = {"order_id": "ord_2", "shipping_address": {"postal_code": "80205"}}
        self.assertEqual(record_shipping_variance(plain, a_shipment(), "t1", mode="test", now=100,
                                                  actuals_repo=Actuals()), {})

    def test_a_label_with_no_cost_records_nothing(self):
        self.assertEqual(record_shipping_variance(an_order(), {"service": "ups_ground"}, "t1",
                                                  mode="test", now=100, actuals_repo=Actuals()), {})

    def test_a_storage_failure_never_fails_the_label_purchase(self):
        # The label is bought and the parcel is going. A bookkeeping write must not read as a failure.
        self.assertEqual(record_shipping_variance(an_order(), a_shipment(), "t1", mode="test", now=100,
                                                  actuals_repo=Actuals(fail=True)), {})

    def test_the_order_document_is_never_rewritten_from_here(self):
        # This handler holds read-only access to orders, and a full put would race the webhook.
        import inspect

        source = inspect.getsource(record_shipping_variance)
        self.assertNotIn("orders_repo", source)
        self.assertNotIn("{**order", source.split('"""', 2)[-1])


class AnUnavailableServiceIsItsOwnException(unittest.TestCase):
    RATES = [{"service_token": "usps_ground", "amount": 718},
             {"service_token": "usps_priority", "amount": 1150}]

    def test_an_order_with_no_quote_says_nothing(self):
        self.assertEqual(quoted_service_status({"order_id": "o"}, self.RATES), {})

    def test_a_still_available_service_is_reported_with_its_price_now(self):
        status = quoted_service_status(
            an_order(), [{"service_token": "ups_ground", "amount": 910}])["quoted_service"]
        self.assertTrue(status["available"])
        self.assertEqual(status["amount_now"], 910)
        self.assertTrue(status["estimate_still_applies"])

    def test_a_service_the_carrier_will_not_carry_is_flagged_not_substituted(self):
        status = quoted_service_status(an_order(), self.RATES)["quoted_service"]
        self.assertFalse(status["available"])
        self.assertIsNone(status["amount_now"])

    def test_the_delivery_promise_is_explicitly_void(self):
        # A buyer promised four days by UPS Ground Saver did not agree to whatever else is going.
        status = quoted_service_status(an_order(), self.RATES)["quoted_service"]
        self.assertFalse(status["estimate_still_applies"])

    def test_the_alternatives_are_still_the_endpoints_own_rate_list(self):
        # No second menu: the tenant picks from `rates`, which this only annotates.
        self.assertEqual(set(quoted_service_status(an_order(), self.RATES)["quoted_service"]),
                         {"service_token", "quoted_amount", "available", "amount_now",
                          "estimate_still_applies"})


class TheTenantSeesItWithoutAnExtraLookup(unittest.TestCase):
    """The durable record is `shipping_actual`, but the Orders view already holds both halves -- the order
    carries the quote, the shipment carries the label's cost. Forty orders must not become forty reads to
    render a badge most of them never show."""

    def test_an_order_with_no_quote_gets_no_variance(self):
        from stripe_link.domain.shipping_quotes import order_variance

        self.assertEqual(order_variance({"order_id": "o"}, a_shipment()), {})

    def test_an_unshipped_order_gets_no_variance(self):
        from stripe_link.domain.shipping_quotes import order_variance

        self.assertEqual(order_variance(an_order(), {}), {})

    def test_it_matches_what_the_label_flow_recorded(self):
        from stripe_link.domain.shipping_quotes import order_variance

        derived = order_variance(an_order(), a_shipment())
        stored = record_shipping_variance(an_order(), a_shipment(), "t1", mode="test", now=100,
                                          actuals_repo=Actuals())
        for field in ("quoted_amount", "actual_amount", "delta", "threshold", "flagged",
                      "service_substituted"):
            with self.subTest(field=field):
                self.assertEqual(derived[field], stored[field])

    def test_it_carries_everything_the_badge_shows(self):
        from stripe_link.domain.shipping_quotes import order_variance

        derived = order_variance(an_order(), a_shipment())
        for field in ("quoted_postal_code", "actual_postal_code", "quoted_amount", "actual_amount",
                      "delta", "threshold", "flagged"):
            self.assertIn(field, derived)

    def test_the_orders_endpoint_attaches_it(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src/handlers/orders.py").read_text(encoding="utf-8")
        self.assertIn("order_variance(order, context[\"shipments\"]", source)
        self.assertIn('order["shipping_variance"] = variance', source)

    def test_the_drawer_states_the_reason_the_amounts_and_both_addresses(self):
        import pathlib

        drawer = (pathlib.Path(__file__).resolve().parents[1]
                  / "dashboard/src/components/orders/OrderDetailDrawer.vue").read_text(encoding="utf-8")
        for phrase in ("Shipping cost variance", "Quoted destination", "Actual destination",
                       "Customer shipping charge", "Actual label cost", "Cost variance",
                       "Order can still be fulfilled"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, drawer)

    def test_the_badge_never_blocks_fulfilment(self):
        import pathlib

        drawer = (pathlib.Path(__file__).resolve().parents[1]
                  / "dashboard/src/components/orders/OrderDetailDrawer.vue").read_text(encoding="utf-8")
        self.assertIn("Order can still be fulfilled", drawer)
        self.assertNotIn("cannot be fulfilled", drawer)

    def test_a_saving_does_not_read_as_a_problem(self):
        import pathlib

        drawer = (pathlib.Path(__file__).resolve().parents[1]
                  / "dashboard/src/components/orders/OrderDetailDrawer.vue").read_text(encoding="utf-8")
        self.assertIn("within tolerance, nothing to do", drawer)
