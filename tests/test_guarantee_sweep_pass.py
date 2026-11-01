"""The sweep pass that rides the orders scan, and the shipment lookup both passes now share.

The lookup is here rather than beside the overdue tests because fixing it is what made this pass possible:
a sweep about delivery cannot be built on a shipment lookup that never finds a shipment.
"""

import unittest

from handlers.fee_reconciliation import _notify_guarantees_due, _ShipmentsByOrder
from stripe_link.domain.buyer_guarantees import NO_DELIVERY_REFUND
from stripe_link.domain.guarantee_due import DAY_SECONDS
from stripe_link.domain.shipping import shipment_id_for

NOW = 1_800_000_000
ORDER = {"tenant_id": "t1", "order_id": "order_1", "status": "paid",
         "customer": {"name": "Dana Vale"}}
SHIPMENT = {"shipment_id": shipment_id_for("order_1"), "order_id": "order_1", "tenant_id": "t1",
            "shipped_at": NOW - 25 * DAY_SECONDS,
            "tracking_registered_at": NOW - 25 * DAY_SECONDS,
            "tracking_status": "TRANSIT", "tracking_status_at": NOW - 24 * DAY_SECONDS}

ENABLED = {"legal_defaults": {"buyer_guarantees": {NO_DELIVERY_REFUND: {"enabled": True, "days": 20}}}}


class Orders:
    def __init__(self, orders):
        self._orders = orders

    def scan_type(self):
        return list(self._orders)


class Shipments:
    """Stores shipments under their REAL ids and exposes the tenant listing, which is the shape the table
    has. A fake keyed by order id is what hid the lookup bug for as long as it lived."""

    def __init__(self, rows):
        self._rows = rows
        self.listed = []

    def list_for_tenant(self, tenant_id):
        self.listed.append(tenant_id)
        return [row for row in self._rows if row.get("tenant_id") == tenant_id]


class Configs:
    def __init__(self, configs):
        self._configs = configs
        self.reads = []

    def get(self, tenant_id):
        self.reads.append(tenant_id)
        return self._configs.get(tenant_id)


class Notifications:
    def __init__(self, existing=()):
        self.sent = []
        self.deleted = []
        self._rows = list(existing)

    def put(self, document):
        self.sent.append(document)
        self._rows = [r for r in self._rows
                      if r.get("notification_id") != document.get("notification_id")]
        self._rows.append(document)
        return document

    def list_for_tenant(self, tenant_id):
        return [r for r in self._rows if r.get("tenant_id") == tenant_id]

    def delete(self, tenant_id, notification_id):
        self.deleted.append((tenant_id, notification_id))
        self._rows = [r for r in self._rows if r.get("notification_id") != notification_id]


def run(orders, shipments, configs, *, now=NOW, existing=()):
    notifications = Notifications(existing)
    count = _notify_guarantees_due(
        "test", now, orders_repo=Orders(orders),
        shipments_repo=Shipments(shipments) if shipments is not None else None,
        notifications_repo=notifications,
        config_repo=Configs(configs) if configs is not None else None)
    return count, notifications.sent, notifications.deleted


class ThePass(unittest.TestCase):
    def test_a_due_guarantee_is_notified(self):
        count, sent, _ = run([ORDER], [SHIPMENT], {"t1": ENABLED})
        self.assertEqual(count, 1)
        self.assertEqual(sent[0]["notification_id"], "notif_guarantee_no_delivery_refund_order_1")
        self.assertEqual(sent[0]["tenant_id"], "t1")

    def test_a_tenant_who_enabled_nothing_is_never_notified(self):
        count, sent, _ = run([ORDER], [SHIPMENT], {"t1": {}})
        self.assertEqual((count, sent), (0, []))

    def test_a_missing_config_is_not_a_promise(self):
        count, _, _ = run([ORDER], [SHIPMENT], {})
        self.assertEqual(count, 0)

    def test_an_unobservable_parcel_is_never_notified(self):
        """The gate, through the pass rather than only the domain: a tenant with no provider key."""
        unseen = {k: v for k, v in SHIPMENT.items() if k != "tracking_registered_at"}
        count, _, _ = run([ORDER], [unseen], {"t1": ENABLED})
        self.assertEqual(count, 0)

    def test_no_shipments_table_means_no_notices(self):
        """The OPPOSITE of the overdue pass's answer, and right for the opposite reason: there,
        unknowable has to read as "shipped" or it cries wolf; here it means we cannot see a delivery, and
        announcing a broken promise from an absence is the fault this sweep is gated to avoid."""
        count, sent, _ = run([ORDER], None, {"t1": ENABLED})
        self.assertEqual((count, sent), (0, []))

    def test_no_config_table_means_no_notices(self):
        count, sent, _ = run([ORDER], [SHIPMENT], None)
        self.assertEqual((count, sent), (0, []))

    def test_the_config_is_read_once_per_tenant_not_once_per_order(self):
        orders = [dict(ORDER, order_id=f"order_{i}") for i in range(1, 4)]
        shipments = [dict(SHIPMENT, order_id=f"order_{i}",
                          shipment_id=shipment_id_for(f"order_{i}")) for i in range(1, 4)]
        configs = Configs({"t1": ENABLED})
        notifications = Notifications()
        _notify_guarantees_due("test", NOW, orders_repo=Orders(orders),
                               shipments_repo=Shipments(shipments),
                               notifications_repo=notifications, config_repo=configs)
        self.assertEqual(configs.reads, ["t1"])
        self.assertEqual(len(notifications.sent), 3)

    def test_one_bad_order_does_not_stop_the_pass(self):
        count, sent, _ = run([{"tenant_id": "t1"}, ORDER], [SHIPMENT], {"t1": ENABLED})
        self.assertEqual(count, 1)
        self.assertEqual(sent[0]["related"]["order_id"], "order_1")

    def test_a_broken_pass_never_raises(self):
        """It rides a sweep that has real work to do: reconciling fees must not stop because a notice
        could not be written."""
        class Exploding:
            def scan_type(self):
                raise RuntimeError("dynamo is unhappy")

        notifications = Notifications()
        self.assertEqual(_notify_guarantees_due("test", NOW, orders_repo=Exploding(),
                                                shipments_repo=Shipments([SHIPMENT]),
                                                notifications_repo=notifications,
                                                config_repo=Configs({"t1": ENABLED})), 0)

    def test_it_notifies_and_never_refunds(self):
        """The published sentence says "your choice", so a sweep that moved money would deny the buyer the
        choice the page promised. Asserted by SHAPE: nothing this pass writes is a refund."""
        _, sent, _ = run([ORDER], [SHIPMENT], {"t1": ENABLED})
        for document in sent:
            self.assertEqual(document["document_type"], "notification")


class WithdrawingANoticeWhoseCauseIsGone(unittest.TestCase):
    """Every emitter in this codebase writes and none withdraws, so a notice outlived its cause and sat
    unread for ever. Survivable while the notices were right; not survivable once the broken shipment
    lookup made the overdue pass fire on parcels already posted."""

    def stale(self, notification_id):
        return {"tenant_id": "t1", "notification_id": notification_id, "status": "unread",
                "document_type": "notification"}

    def test_a_delivered_parcel_has_its_notice_withdrawn(self):
        arrived = dict(SHIPMENT, delivered_at=NOW - DAY_SECONDS, tracking_status="DELIVERED")
        count, _, deleted = run([ORDER], [arrived], {"t1": ENABLED},
                                existing=[self.stale("notif_guarantee_no_delivery_refund_order_1")])
        self.assertEqual(count, 0)
        self.assertEqual(deleted, [("t1", "notif_guarantee_no_delivery_refund_order_1")])

    def test_a_still_due_notice_is_kept(self):
        _, _, deleted = run([ORDER], [SHIPMENT], {"t1": ENABLED},
                            existing=[self.stale("notif_guarantee_no_delivery_refund_order_1")])
        self.assertEqual(deleted, [])

    def test_other_kinds_of_notice_are_left_alone(self):
        """It clears its OWN prefix. A refund request or a sale is not this pass's business."""
        _, _, deleted = run([ORDER], [dict(SHIPMENT, delivered_at=NOW)], {"t1": ENABLED},
                            existing=[self.stale("notif_refund_rr_1"),
                                      self.stale("notif_overdue_order_1")])
        self.assertEqual(deleted, [])

    def test_an_unreadable_tenant_keeps_its_notices(self):
        """A FAILED READ MUST NOT BECOME A DELETE. Nothing looks due when the table will not answer, and
        withdrawing a true notice is worse than keeping a stale one -- the tenant stops being told about a
        parcel that really is late."""
        class Exploding:
            def list_for_tenant(self, _tenant):
                raise RuntimeError("denied")

        notifications = Notifications([self.stale("notif_guarantee_no_delivery_refund_order_1")])
        _notify_guarantees_due("test", NOW, orders_repo=Orders([ORDER]),
                               shipments_repo=Exploding(), notifications_repo=notifications,
                               config_repo=Configs({"t1": ENABLED}))
        self.assertEqual(notifications.deleted, [])


class TheSharedShipmentLookup(unittest.TestCase):
    """It used to be `repo.get(tenant_id, order_id)`, and a shipment is stored under
    `shp_<order_id>_outbound_1` -- so that key could never exist and every order looked unshipped."""

    def test_a_shipment_is_found_by_its_order(self):
        index = _ShipmentsByOrder(Shipments([SHIPMENT]))
        self.assertEqual(index.for_order(ORDER)["shipment_id"], shipment_id_for("order_1"))

    def test_the_real_id_is_not_the_order_id(self):
        """The regression in one line. If these were equal the old lookup would have worked."""
        self.assertNotEqual(shipment_id_for("order_1"), "order_1")

    def test_an_order_with_no_shipment_answers_none(self):
        index = _ShipmentsByOrder(Shipments([]))
        self.assertIsNone(index.for_order(ORDER))

    def test_the_newest_shipment_wins(self):
        """A re-shipped order has more than one and the latest is the true state."""
        old = dict(SHIPMENT, updated_at=100, tracking_status="PRE_TRANSIT")
        new = dict(SHIPMENT, updated_at=200, tracking_status="DELIVERED")
        index = _ShipmentsByOrder(Shipments([old, new]))
        self.assertEqual(index.for_order(ORDER)["tracking_status"], "DELIVERED")

    def test_it_lists_once_per_tenant(self):
        repo = Shipments([SHIPMENT])
        index = _ShipmentsByOrder(repo)
        for _ in range(3):
            index.for_order(ORDER)
        self.assertEqual(repo.listed, ["t1"])

    def test_no_repository_answers_the_unknowable_sentinel(self):
        """The overdue pass needs "assume shipped" here rather than crying wolf about every order."""
        self.assertEqual(_ShipmentsByOrder(None).for_order(ORDER), {"status": "shipped"})

    def test_an_unreadable_tenant_is_skipped_not_guessed_at(self):
        class Exploding:
            def list_for_tenant(self, _tenant):
                raise RuntimeError("denied")

        self.assertIsNone(_ShipmentsByOrder(Exploding()).for_order(ORDER))


if __name__ == "__main__":
    unittest.main()
