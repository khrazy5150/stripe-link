"""Export, pickups and manifests — the batch actions on the Orders screen.

A manifest (USPS calls it a SCAN form) and a pickup are both batch operations carrying a constraint that
is the CARRIER's, not ours: one carrier, one ship date, one origin. A mixed batch fails at the carrier,
so the grouping happens on the server and the toolbar can only ever offer a batch that would be accepted.
"""
import json
import unittest

from handlers.orders import handler as orders_handler
from handlers.shipping import handler as shipping_handler
from stripe_link.domain.handover import handover_groups, manifestable, order_csv_row, orders_csv, ship_date

BOUGHT = {"shipment_id": "s1", "order_id": "order_1", "status": "purchased", "carrier": "usps",
          "purchased_at": 1790000000, "provider": {"name": "shippo", "transaction_id": "txn_1"},
          "cost": {"amount": 458, "currency": "usd"}}
BOUGHT_2 = {**BOUGHT, "shipment_id": "s2", "order_id": "order_2", "provider": {"transaction_id": "txn_2"},
            "cost": {"amount": 706, "currency": "usd"}}
UPS = {**BOUGHT, "shipment_id": "s3", "order_id": "order_3", "carrier": "ups",
       "provider": {"transaction_id": "txn_3"}, "cost": {"amount": 5169, "currency": "usd"}}
MANUAL = {"shipment_id": "s4", "order_id": "order_4", "status": "shipped", "carrier": "usps",
          "shipped_at": 1790000000, "provider": {"name": "manual"}}


class GroupingTests(unittest.TestCase):
    def test_labels_group_by_carrier_and_day(self):
        groups = handover_groups([BOUGHT, BOUGHT_2, UPS])
        self.assertEqual(len(groups), 2)
        usps = next(g for g in groups if g["carrier"] == "usps")
        self.assertEqual(sorted(usps["transactions"]), ["txn_1", "txn_2"])
        self.assertEqual(usps["total"], 1164)

    def test_a_manually_shipped_parcel_is_EXCLUDED_not_rejected(self):
        """The tenant bought that postage at the counter, so this provider has no transaction to list and
        the carrier has nothing to scan. They did nothing wrong, so it is simply not in the batch."""
        self.assertEqual(manifestable([MANUAL]), [])
        self.assertEqual(handover_groups([MANUAL]), [])

    def test_an_already_manifested_label_is_not_offered_twice(self):
        self.assertEqual(handover_groups([{**BOUGHT, "manifest_id": "m1"}]), [])

    def test_a_failed_purchase_is_not_a_parcel(self):
        self.assertEqual(handover_groups([{**BOUGHT, "status": "failed"}]), [])

    def test_the_ship_date_is_the_day_the_label_was_bought(self):
        self.assertEqual(ship_date(BOUGHT), "2026-09-21")
        self.assertEqual(ship_date({}), "")


class CsvTests(unittest.TestCase):
    ORDER = {"order_id": "order_1", "created_at": "1790000000", "amount_total": 1834, "currency": "usd",
             "payment_status": "paid", "customer": {"name": "Ada", "email": "ada@example.com"},
             "shipping_address": {"city": "Denver", "state": "CO", "postal_code": "80204", "country": "US"},
             "line_items": [{"name": "Gummies", "quantity": 2}],
             "fulfilment": {"status": "shipped", "shipment": {"carrier": "usps", "service": "Ground Advantage",
                                                              "tracking_number": "9400111122223333444455",
                                                              "cost": {"amount": 458}}}}

    def test_the_header_is_human_readable(self):
        first_line = orders_csv([]).splitlines()[0]
        self.assertTrue(first_line.startswith("Order,Full order id,Order date,Customer"), first_line)

    def test_the_export_leads_with_the_SHORT_reference(self):
        """An exported row has to match what the screen showed, and the screen shows the short one. The
        full id follows it, because a spreadsheet is exactly where someone goes looking for it."""
        row = order_csv_row({**self.ORDER, "short_ref": "b13b4Un3"})
        self.assertEqual(row["short_ref"], "b13b4Un3")
        self.assertEqual(row["order_id"], "order_1")

    def test_fulfilment_columns_are_included_because_that_is_why_people_export(self):
        row = order_csv_row(self.ORDER)
        self.assertEqual(row["carrier"], "usps")
        self.assertEqual(row["tracking_number"], "9400111122223333444455")
        self.assertEqual(row["shipping_cost"], "4.58")

    def test_money_is_written_in_units_not_cents(self):
        self.assertEqual(order_csv_row(self.ORDER)["amount_total"], "18.34")

    def test_every_value_is_a_string(self):
        for key, value in order_csv_row(self.ORDER).items():
            self.assertIsInstance(value, str, f"{key} is not a string")

    def test_an_order_with_nothing_optional_still_exports(self):
        row = order_csv_row({"order_id": "o"})
        self.assertEqual(row["order_id"], "o")
        self.assertEqual(row["carrier"], "")

    def test_excel_line_endings(self):
        self.assertIn("\r\n", orders_csv([self.ORDER]))


class Repo:
    def __init__(self, rows=None, key="order_id"):
        self.rows = list(rows or [])
        self.key = key

    def get(self, tenant_id, doc_id=None):
        if doc_id is None:
            return self.rows[0] if self.rows else None
        return next((r for r in self.rows if r.get(self.key) == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        self.rows = [r for r in self.rows if r.get(self.key) != document.get(self.key)] + [document]
        return document


class Cipher:
    @staticmethod
    def decrypt(ref, **kwargs):
        return ""


CONFIG = {"tenant_id": "t1", "enabled": True,
          "provider": {"name": "mock", "api_key_ref": "", "connection_status": "connected"},
          "ship_from_address": {"name": "Shop", "street1": "9 Elm", "city": "Denver", "state": "CO",
                                "postal_code": "80204", "country": "US"},
          "boxes": [{"name": "S", "length": 8, "width": 6, "height": 4, "empty_weight": 0.2}]}


def _handover(kind, body, shipments=None):
    shipments_repo = shipments if shipments is not None else Repo([BOUGHT, BOUGHT_2], key="shipment_id")
    result = shipping_handler(
        {"httpMethod": "POST", "resource": f"/shipping/{kind}",
         "queryStringParameters": {"tenant_id": "t1"}, "body": json.dumps(body)},
        None, repository=Repo([CONFIG], key="tenant_id"), secret_cipher=Cipher(),
        shipments_repo=shipments_repo, now_fn=lambda: 1790000500)
    return result, shipments_repo


class HandoverEndpointTests(unittest.TestCase):
    def test_a_manifest_covers_the_whole_batch_and_is_recorded_on_each_label(self):
        result, repo = _handover("manifests", {"carrier": "usps", "ship_date": "2026-09-21"})
        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertEqual(body["shipments"], 2)
        self.assertTrue(all(r.get("manifest_id") for r in repo.rows))

    def test_manifesting_the_same_labels_twice_finds_nothing_left_to_hand_over(self):
        """A carrier refuses a second manifest for the same label, and the tenant would have no way to
        tell which document their parcels are actually on."""
        _, repo = _handover("manifests", {"carrier": "usps", "ship_date": "2026-09-21"})
        again, _ = _handover("manifests", {"carrier": "usps", "ship_date": "2026-09-21"}, shipments=repo)
        self.assertEqual(again["statusCode"], 400)
        self.assertEqual(json.loads(again["body"])["error"], "nothing_to_hand_over")

    def test_a_pickup_records_its_confirmation(self):
        result, repo = _handover("pickups", {"carrier": "usps", "ship_date": "2026-09-21",
                                             "start_time": "2026-09-21T14:00:00Z",
                                             "end_time": "2026-09-21T18:00:00Z"})
        self.assertEqual(result["statusCode"], 201)
        self.assertEqual(json.loads(result["body"])["pickup"]["confirmation_code"], "MOCKCONF")
        self.assertTrue(all(r.get("pickup_confirmation") for r in repo.rows))

    def test_a_batch_the_carrier_would_reject_is_refused_BEFORE_the_request(self):
        result, _ = _handover("manifests", {"carrier": "fedex", "ship_date": "2026-09-21"})
        self.assertEqual(result["statusCode"], 400)
        self.assertIn("FEDEX", json.loads(result["body"])["message"])

    def test_a_carrier_and_a_date_are_both_required(self):
        result, _ = _handover("manifests", {"carrier": "usps"})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "missing_batch")


class OrdersResponseTests(unittest.TestCase):
    def _list(self, params=None):
        return orders_handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", **(params or {})}}, None,
            repository=Repo([{"order_id": "order_1", "tenant_id": "t1", "amount_total": 1834,
                              "customer": {"name": "Ada"}, "created_at": "1790000000"}]),
            products_repo=Repo(), shipments_repo=Repo([BOUGHT], key="shipment_id"),
            shipping_config_repo=Repo([CONFIG], key="tenant_id"))

    def test_the_list_carries_the_batches_a_carrier_would_accept(self):
        body = json.loads(self._list()["body"])
        self.assertEqual(len(body["handover_groups"]), 1)
        self.assertEqual(body["handover_groups"][0]["carrier"], "usps")

    def test_the_groups_do_not_ship_whole_shipment_documents_to_the_browser(self):
        # The screen needs the counts and the ids, not every parcel's full record.
        group = json.loads(self._list()["body"])["handover_groups"][0]
        self.assertNotIn("shipments", group)

    def test_csv_comes_back_as_a_file_not_as_json(self):
        result = self._list({"format": "csv"})
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("text/csv", result["headers"]["Content-Type"])
        self.assertIn("attachment", result["headers"]["Content-Disposition"])
        self.assertIn("Order,Full order id,Order date,Customer", result["body"])

    def test_the_export_carries_the_same_fulfilment_join_the_screen_shows(self):
        result = self._list({"format": "csv"})
        self.assertIn("usps", result["body"])


if __name__ == "__main__":
    unittest.main()
