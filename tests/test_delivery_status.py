"""The Status column is the DELIVERY story, not the payment one.

The author's design (2026-09-25): "Status is the delivery status. 'Not Shippable' is a special status
reserved for digital, services, and physical products that don't have a complete shipping address or an
address that's deliverable."

A refunded order can still be in transit and a paid one can be undeliverable, which is why this is derived
separately from payment_status rather than dressed up from it.
"""
import unittest

from stripe_link.domain.fulfilment import DELIVERY_STATUSES, can_buy_label, delivery_status


def _state(status, reasons=None, shipment=None):
    return {"status": status, "reasons": reasons or [], "shipment": shipment}


class NotShippableTests(unittest.TestCase):
    """The author's three cases, plus the one the packer added."""

    def test_a_digital_order_is_not_shippable(self):
        state = _state("not_shippable", ["No shipping address — this order is not a physical shipment."])
        self.assertEqual(delivery_status({}, state)["label"], "Not Shippable")

    def test_an_order_we_cannot_label_to_is_not_shippable(self):
        state = _state("not_shippable", ["Ships to CA. International labels are not supported yet"])
        self.assertEqual(delivery_status({}, state)["label"], "Not Shippable")

    def test_the_REASON_travels_with_it(self):
        # "Not Shippable" on its own invites a support ticket; the reason answers it in place.
        state = _state("not_shippable", ["No shipping address — this order is not a physical shipment."])
        self.assertIn("No shipping address", delivery_status({}, state)["note"])

    def test_an_UNMEASURED_product_is_NOT_the_same_thing(self):
        """It becomes shippable the moment the tenant types some dimensions. Calling it unshippable would
        send them looking for the wrong fix -- an address, when what is missing is a tape measure."""
        state = _state("needs_info", ["Creatine Gummies has no size — add its measurements to buy a label."])
        result = delivery_status({}, state)
        self.assertEqual(result["label"], "Needs info")
        self.assertNotEqual(result["label"], "Not Shippable")


class ProgressTests(unittest.TestCase):
    def test_a_shippable_unshipped_order_is_ready(self):
        self.assertEqual(delivery_status({}, _state("ready"))["label"], "Ready to ship")

    def test_a_bought_label_says_so(self):
        state = _state("shipped", shipment={"status": "purchased"})
        self.assertEqual(delivery_status({}, state)["label"], "Label purchased")

    def test_a_MANUALLY_shipped_parcel_tops_out_at_in_transit(self):
        """We have no carrier scan for it, so claiming delivery would be inventing one."""
        state = _state("shipped", shipment={"status": "shipped"})
        self.assertEqual(delivery_status({}, state)["label"], "In transit")

    def test_a_failed_purchase_says_so_rather_than_looking_unshipped(self):
        state = _state("ready", shipment={"status": "failed", "error": "Carrier refused"})
        result = delivery_status({}, state)
        self.assertEqual(result["label"], "Label failed")
        self.assertIn("Carrier refused", result["note"])


class TrackingTests(unittest.TestCase):
    """Once a carrier has spoken, what our gates think stopped mattering."""

    def test_delivered_outranks_everything(self):
        state = _state("needs_info", ["something"],
                       shipment={"status": "purchased", "tracking_status": "DELIVERED"})
        self.assertEqual(delivery_status({}, state)["label"], "Delivered")

    def test_a_return_to_sender_is_Returned(self):
        for word in ("RETURNED", "RETURN_TO_SENDER"):
            state = _state("shipped", shipment={"status": "purchased", "tracking_status": word})
            self.assertEqual(delivery_status({}, state)["label"], "Returned")

    def test_pre_transit_is_a_bought_label_not_a_moving_parcel(self):
        state = _state("shipped", shipment={"status": "purchased", "tracking_status": "PRE_TRANSIT"})
        self.assertEqual(delivery_status({}, state)["label"], "Label purchased")

    def test_a_vocabulary_we_do_not_KNOW_falls_back_rather_than_guessing(self):
        state = _state("shipped", shipment={"status": "purchased", "tracking_status": "SOMETHING_NEW"})
        self.assertEqual(delivery_status({}, state)["label"], "Label purchased")


class BadgeTests(unittest.TestCase):
    def test_every_status_has_a_label_and_a_badge(self):
        for key, (label, badge) in DELIVERY_STATUSES.items():
            self.assertTrue(label, f"{key} has no label")
            self.assertIn(badge, {"active", "warning", "inactive", "archived"}, f"{key}: {badge}")

    def test_an_unknown_state_degrades_to_Not_Shippable_rather_than_a_raw_enum(self):
        self.assertEqual(delivery_status({}, _state("something_invented"))["label"], "Not Shippable")

    def test_it_reads_the_order_when_no_state_is_passed(self):
        order = {"fulfilment": _state("ready")}
        self.assertEqual(delivery_status(order)["label"], "Ready to ship")


class LabelButtonTests(unittest.TestCase):
    def test_only_a_ready_order_can_have_a_label_bought(self):
        self.assertTrue(can_buy_label({"eligible": True}))
        for state in ({"eligible": False}, {}, None):
            self.assertFalse(can_buy_label(state))


if __name__ == "__main__":
    unittest.main()
