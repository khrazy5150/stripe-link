"""Three gates, kept distinct, because conflating them is what produces an unactionable "Rates Unavailable".

plans/ORDER_FULFILMENT.md F2:

  TENANT gate   blocks every row      -> one banner. Already `label_readiness`.
  ORDER gate    blocks this row, tenant CANNOT fix   -> not a failure, just not a parcel.
  PRODUCT gate  blocks this row, tenant CAN fix      -> the only one that earns a call to action,
                                                        and it names the product.
"""
import unittest

from stripe_link.domain.fulfilment import (
    LABELABLE_COUNTRIES,
    order_fulfilment_state,
    order_gate,
    product_gate,
    product_index,
    resolve_order_lines,
)

MEASURED = {"product_id": "p1", "name": "Creatine Gummies", "stripe_product_id": "prod_A",
            "prices": [{"stripe_price_id": "price_A"}],
            "fulfillment": {"requires_shipping": True,
                            "item_dimensions": {"length_in": 4, "width_in": 4, "height_in": 4, "weight_lb": 0.5}}}
UNMEASURED = {"product_id": "p2", "name": "Beta Alanine", "stripe_product_id": "prod_B",
              "fulfillment": {"requires_shipping": True}}
DIGITAL = {"product_id": "p3", "name": "Ebook", "stripe_product_id": "prod_C",
           "fulfillment": {"requires_shipping": False}}
BOXED = {"product_id": "p4", "name": "Kettlebell", "stripe_product_id": "prod_D",
         "fulfillment": {"requires_shipping": True, "ships_alone": True,
                         "length_in": 10, "width_in": 8, "height_in": 6, "weight_lb": 20}}

PRODUCTS = [MEASURED, UNMEASURED, DIGITAL, BOXED]
INDEX = product_index(PRODUCTS)
BY_ID = {p["product_id"]: p for p in PRODUCTS}


def _order(lines=None, address=None, **over):
    return {"order_id": "order_1", "tenant_id": "t1",
            "shipping_address": {"country": "US", "city": "Denver", "state": "CO",
                                 "postal_code": "80204"} if address is None else address,
            "line_items": lines if lines is not None else [{"stripe_product_id": "prod_A", "quantity": 1}],
            **over}


def _state(order, shipment=None):
    return order_fulfilment_state(order, products_by_id=BY_ID, index=INDEX, shipment=shipment)


class ResolverTests(unittest.TestCase):
    """An order line carries stripe ids; packable_items() keys on OUR product_id. Without this bridge an
    order cannot be packed at all, however well measured its products are."""

    def test_a_line_is_resolved_by_stripe_product_id(self):
        [line] = resolve_order_lines(_order(), INDEX)
        self.assertEqual(line["product_id"], "p1")

    def test_a_line_is_resolved_by_stripe_price_id_too(self):
        [line] = resolve_order_lines(_order([{"stripe_price_id": "price_A", "quantity": 1}]), INDEX)
        self.assertEqual(line["product_id"], "p1")

    def test_an_unresolvable_line_is_KEPT(self):
        """Dropping it would silently shrink the parcel -- postage for two items when three go in the box."""
        lines = resolve_order_lines(_order([{"stripe_product_id": "prod_GONE", "quantity": 1}]), INDEX)
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0].get("product_id"))

    def test_an_order_with_no_line_items_falls_back_to_its_product_block(self):
        order = _order(lines=[], product={"product_id": "p1", "name": "Creatine Gummies"})
        [line] = resolve_order_lines(order, INDEX)
        self.assertEqual(line["product_id"], "p1")


class OrderGateTests(unittest.TestCase):
    def test_no_address_is_not_a_failure_it_is_not_a_parcel(self):
        reasons = order_gate(_order(address={}))
        self.assertTrue(any("not a physical shipment" in r for r in reasons))

    def test_canada_is_refused_in_the_ROW_not_at_purchase(self):
        """Checkout already allows CA, so this order can exist today and cannot be labelled without a
        customs declaration. Refusing it here is what stops it failing when money is spent."""
        self.assertIn("US", LABELABLE_COUNTRIES)
        reasons = order_gate(_order(address={"country": "CA", "city": "Toronto"}))
        self.assertTrue(any("International" in r for r in reasons))

    def test_a_refunded_order_is_not_work(self):
        self.assertTrue(order_gate(_order(payment_status="refunded")))

    def test_an_already_shipped_order_is_not_work_either(self):
        self.assertTrue(order_gate(_order(), shipment={"status": "shipped"}))

    def test_a_domestic_paid_order_passes(self):
        self.assertEqual(order_gate(_order(payment_status="paid")), [])


class ProductGateTests(unittest.TestCase):
    def test_it_names_the_product_rather_than_saying_package_required(self):
        state = _state(_order([{"stripe_product_id": "prod_B", "quantity": 1}]))
        self.assertEqual(state["status"], "needs_info")
        self.assertEqual(state["gate"], "product")
        self.assertEqual(state["needs_measurement"][0]["name"], "Beta Alanine")
        self.assertIn("Beta Alanine", " ".join(state["reasons"]))

    def test_the_call_to_action_carries_the_product_id_to_link_to(self):
        state = _state(_order([{"stripe_product_id": "prod_B", "quantity": 1}]))
        self.assertEqual(state["needs_measurement"][0]["product_id"], "p2")

    def test_a_download_in_the_order_is_not_a_missing_measurement(self):
        state = _state(_order([{"stripe_product_id": "prod_A", "quantity": 1},
                               {"stripe_product_id": "prod_C", "quantity": 1}]))
        self.assertEqual(state["status"], "ready")

    def test_a_ships_alone_product_with_a_declared_box_is_complete(self):
        """The declared box is the exception route and it is still a whole answer: an item that always
        ships alone in a known box needs no dimensions of its own."""
        state = _state(_order([{"stripe_product_id": "prod_D", "quantity": 1}]))
        self.assertEqual(state["status"], "ready")

    def test_a_line_not_in_the_catalogue_blocks_but_is_not_blamed_on_the_tenant(self):
        state = _state(_order([{"stripe_product_id": "prod_GONE", "quantity": 1}]))
        self.assertEqual(state["status"], "needs_info")
        self.assertEqual(state["needs_measurement"], [])
        self.assertIn("not in your catalogue", " ".join(state["reasons"]))

    def test_two_unmeasured_products_are_named_not_counted(self):
        extra = {"product_id": "p5", "name": "Creatine Powder", "stripe_product_id": "prod_E",
                 "fulfillment": {"requires_shipping": True}}
        state = order_fulfilment_state(
            _order([{"stripe_product_id": "prod_B"}, {"stripe_product_id": "prod_E"}]),
            products_by_id={**BY_ID, "p5": extra}, index=product_index(PRODUCTS + [extra]))
        joined = " ".join(state["reasons"])
        self.assertIn("Beta Alanine", joined)
        self.assertIn("Creatine Powder", joined)


class EligibilityTests(unittest.TestCase):
    def test_only_a_READY_order_can_be_selected(self):
        self.assertTrue(_state(_order())["eligible"])
        for order in (_order(address={}), _order([{"stripe_product_id": "prod_B"}]),
                      _order(payment_status="refunded")):
            self.assertFalse(_state(order)["eligible"])

    def test_a_shipped_order_reports_shipped_and_is_not_selectable(self):
        state = _state(_order(), shipment={"status": "shipped", "tracking_number": "94001"})
        self.assertEqual(state["status"], "shipped")
        self.assertFalse(state["eligible"])
        self.assertEqual(state["shipment"]["tracking_number"], "94001")

    def test_the_order_gate_outranks_the_product_gate(self):
        """An order with nowhere to ship to is not a measuring problem, and telling the tenant to go and
        measure something would send them to fix the wrong thing."""
        state = _state(_order([{"stripe_product_id": "prod_B"}], address={}))
        self.assertEqual(state["gate"], "order")
        self.assertEqual(state["needs_measurement"], [])


if __name__ == "__main__":
    unittest.main()
