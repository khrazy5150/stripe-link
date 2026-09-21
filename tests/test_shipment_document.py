"""The shipment document, and why its id is not random (plans/SHIPPING_PROVIDERS.md P0).

A label is money spent at a carrier, immediately and irreversibly. The two ways to lose that money are a
double-clicked button buying two labels, and a crash between spending and recording that loses the one we
bought. Both are decided by the document, not by the handler, which is why the id is derived and the row is
claimed before the provider is called.
"""
import json
import pathlib
import unittest

from stripe_link.domain.shipping import (
    ShipmentError,
    build_shipment,
    mark_failed,
    mark_purchased,
    shipment_id_for,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

ORDER = {
    "order_id": "order_cs_test_123", "tenant_id": "t1", "stripe_mode": "test",
    "shipping_address": {"name": "Ada Lovelace", "street1": "12 Analytical Way", "city": "Torrance",
                         "state": "CA", "postal_code": "90501", "country": "US", "phone": "+13105551212"},
}
ORIGIN = {"name": "The Shop", "street1": "1 Main St", "city": "Los Angeles", "state": "CA",
          "postal_code": "90001", "country": "US"}
PARCEL = {"length": 10, "width": 8, "height": 4, "weight": 1.5, "distance_unit": "in", "mass_unit": "lb"}


def _shipment(**over):
    args = {"order": ORDER, "from_address": ORIGIN, "parcel": PARCEL, "now": 100}
    args.update(over)
    return build_shipment(**args)


class IdempotencyTests(unittest.TestCase):
    def test_the_same_order_always_produces_the_same_id(self):
        """The id IS the idempotency key. Two clicks claim one row; the loser returns the first shipment
        rather than buying a second label."""
        self.assertEqual(_shipment()["shipment_id"], _shipment()["shipment_id"])
        self.assertEqual(shipment_id_for("order_cs_test_123"), "shp_order_cs_test_123_outbound_1")

    def test_a_deliberate_split_has_to_ask(self):
        # An accident cannot produce sequence 2, because it would have to request it.
        self.assertNotEqual(shipment_id_for("o1", "outbound", 1), shipment_id_for("o1", "outbound", 2))

    def test_a_return_label_is_a_different_shipment(self):
        self.assertNotEqual(shipment_id_for("o1", "outbound"), shipment_id_for("o1", "return"))

    def test_nonsense_is_refused(self):
        for args in (("",), ("o1", "sideways"), ("o1", "outbound", 0), ("o1", "outbound", "two")):
            with self.subTest(args=args):
                with self.assertRaises(ShipmentError):
                    shipment_id_for(*args)


class ClaimBeforeSpendingTests(unittest.TestCase):
    def test_a_new_shipment_is_claimed_not_purchased(self):
        """Write the row, THEN spend the money.

        A crash in between leaves a row saying "we were buying this", carrying the provider idempotency key
        needed to find out whether it happened. The other order -- spend, then record -- loses the label
        silently and bills the tenant for it.
        """
        self.assertEqual(_shipment()["status"], "purchasing")

    def test_only_a_claimed_shipment_can_be_purchased(self):
        purchased = mark_purchased(_shipment(), purchase={"carrier": "USPS"}, now=200)
        with self.assertRaises(ShipmentError):
            mark_purchased(purchased, purchase={"carrier": "USPS"}, now=300)

    def test_what_the_provider_sold_is_recorded(self):
        purchased = mark_purchased(_shipment(), purchase={
            "carrier": "USPS", "service": "Priority", "tracking_number": "9400111",
            "label_url": "https://x/l.pdf", "cost": {"amount": 812, "currency": "USD"},
            "provider": {"name": "shippo", "transaction_id": "tx_1"},
        }, now=200)
        self.assertEqual(purchased["cost"], {"amount": 812, "currency": "usd"})
        self.assertEqual(purchased["provider"]["transaction_id"], "tx_1")
        self.assertEqual(purchased["purchased_at"], 200)

    def test_a_failure_is_kept_not_deleted(self):
        # The row is the evidence that the attempt was made, and it carries the id needed to reconcile.
        failed = mark_failed(_shipment(), "carrier rejected the address", now=300)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("rejected", failed["error"]["message"])


class SnapshotTests(unittest.TestCase):
    def test_addresses_are_copied_not_referenced(self):
        """A label is a historical fact. An order corrected next week must not change what was printed."""
        order = json.loads(json.dumps(ORDER))
        shipment = _shipment(order=order)
        order["shipping_address"]["street1"] = "SOMEWHERE ELSE"
        self.assertEqual(shipment["to_address"]["street1"], "12 Analytical Way")

    def test_the_mode_travels_with_the_shipment(self):
        # One prod endpoint serves both modes; a sandbox label must not appear in a live list.
        self.assertEqual(_shipment()["stripe_mode"], "test")
        self.assertEqual(_shipment(order={**ORDER, "stripe_mode": "live"})["stripe_mode"], "live")

    def test_the_estimate_is_recorded_when_one_set_the_price(self):
        """Estimate-vs-actual cannot be backfilled, so it is written before anything reads it."""
        self.assertEqual(_shipment(estimated_cost=890)["estimated_cost"], 890)
        self.assertNotIn("estimated_cost", _shipment())

    def test_what_went_in_the_box_is_recorded(self):
        # A bundle is packed, not summed, so the label has to say what it packed.
        self.assertEqual(_shipment(packed_from=["p1", "p2"])["packed_from"], ["p1", "p2"])


class RefusalTests(unittest.TestCase):
    def test_an_order_with_no_destination_cannot_ship(self):
        """The gap P0 exists to close -- for most of this codebase's life, no order had one."""
        with self.assertRaises(ShipmentError):
            _shipment(order={**ORDER, "shipping_address": {}})

    def test_an_incomplete_address_on_either_end_is_refused(self):
        for field in ("street1", "city", "state", "postal_code", "country"):
            with self.subTest(missing=field, end="destination"):
                address = {k: v for k, v in ORDER["shipping_address"].items() if k != field}
                with self.assertRaises(ShipmentError):
                    _shipment(order={**ORDER, "shipping_address": address})
            with self.subTest(missing=field, end="origin"):
                with self.assertRaises(ShipmentError):
                    _shipment(from_address={k: v for k, v in ORIGIN.items() if k != field})

    def test_no_parcel_no_label(self):
        with self.assertRaises(ShipmentError):
            _shipment(parcel={})


class SchemaTests(unittest.TestCase):
    SCHEMA = json.loads((ROOT / "schemas/Shipment.schema.json").read_text(encoding="utf-8"))

    def test_the_builder_emits_only_fields_the_schema_allows(self):
        allowed = set(self.SCHEMA["properties"])
        for shipment in (_shipment(), _shipment(estimated_cost=1, packed_from=["p1"]),
                         mark_purchased(_shipment(), purchase={"carrier": "USPS", "provider": {"name": "shippo"}}),
                         mark_failed(_shipment(), "nope")):
            with self.subTest(status=shipment["status"]):
                self.assertEqual(set(shipment) - allowed, set())

    def test_everything_the_schema_requires_is_built(self):
        self.assertEqual(set(self.SCHEMA["required"]) - set(_shipment()), set())

    def test_the_address_shape_matches_the_one_shipping_config_uses(self):
        """Origin and destination have to look alike, or a provider call translates between two dialects."""
        config = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(self.SCHEMA["$defs"]["address"], config["$defs"]["address"])
        self.assertEqual(self.SCHEMA["$defs"]["parcel"], config["$defs"]["parcel"])


if __name__ == "__main__":
    unittest.main()
