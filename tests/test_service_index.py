"""The slim service list projection, and the shared index-list machinery it pilots.

Services are loaded whole by THREE screens — their own, Offers (item names + the unified item picker) and
Invoices — so the full-document payload was paid three times. 2,000 services was ~3.9MB against the 6MB
Lambda response ceiling.

This is also the first consumer of composables/indexedList.js. Four screens had four implementations of
the same load-index/filter-locally/fetch-full-on-edit shape; the field lists differ legitimately, the
machinery does not, and virtualized rendering and pagination adoption are both still to come.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

from handlers.services import handler
from stripe_link.domain.service_index import service_index_entry
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "indexedList.js"

FULL_SERVICE = {
    "tenant_id": "t1", "service_id": "svc_1", "name": "60-Minute Mobile Massage",
    "description": "In-home massage.", "location_mode": "customer_address",
    "fulfillment_mode": "scheduled", "booking_flow": "pay_then_book", "default_price_id": "pr1",
    "allowed_fulfillers": ["f1"], "active": True, "duration_minutes": 60,
    "presentation": {"image_url": "https://img/massage.jpg"},
    "booking_rules": {"lead_time_minutes": 120, "buffer_before": 15, "notes": "x" * 120},
    "image_dims": {"base": [800, 800]},
    "prices": [{"price_id": "pr1", "context": "standard", "unit_amount": 12000, "currency": "usd",
                "stripe_price_id": "price_x", "fee_handling": "standard",
                "fee_breakdown": {"platform_fee": 240}, "previous_price_id": "old"}],
}


class ServiceIndexEntryTests(unittest.TestCase):
    def test_keeps_what_the_card_search_and_item_picker_read(self):
        entry = service_index_entry(FULL_SERVICE)
        for field in ("service_id", "name", "description", "location_mode", "fulfillment_mode",
                      "booking_flow", "default_price_id", "presentation", "prices", "active"):
            with self.subTest(field=field):
                self.assertIn(field, entry)

    def test_drops_what_only_the_editor_needs(self):
        blob = json.dumps(service_index_entry(FULL_SERVICE))
        for dropped in ("booking_rules", "image_dims", "fee_breakdown", "previous_price_id"):
            with self.subTest(dropped=dropped):
                self.assertNotIn(dropped, blob)

    def test_active_false_survives(self):
        self.assertIs(service_index_entry({**FULL_SERVICE, "active": False})["active"], False)

    def test_is_smaller(self):
        full = len(json.dumps(FULL_SERVICE))
        slim = len(json.dumps(service_index_entry(FULL_SERVICE)))
        self.assertLess(slim, full * 0.75, f"{slim}B vs {full}B")


class ListServicesIndexViewTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("service_id")
        for i in range(3):
            self.repository.put({**FULL_SERVICE, "service_id": f"svc_{i}"})

    def _get(self, query=None):
        # The handler builds every repo it might need up front, so a test has to inject them all even
        # though only the services one is exercised.
        event = {"httpMethod": "GET", "path": "/services",
                 "queryStringParameters": {"tenant_id": "t1", **(query or {})}}
        response = handler(
            event, None,
            services_repo=self.repository,
            fulfillers_repo=FakeDocumentRepository("fulfiller_id"),
            availability_repo=FakeDocumentRepository("tenant_id"),
            exceptions_repo=FakeDocumentRepository("exception_id"),
            appointments_repo=FakeDocumentRepository("appointment_id"),
            tenant_repo=FakeDocumentRepository("tenant_id"),
        )
        return json.loads(response["body"])["services"]

    def test_index_view_is_slim(self):
        rows = self._get({"view": "index"})
        self.assertEqual(len(rows), 3)
        self.assertNotIn("booking_rules", rows[0])
        self.assertIn("prices", rows[0])

    def test_default_view_is_still_the_full_document(self):
        self.assertIn("booking_rules", self._get()[0])


class SharedMachineryTests(unittest.TestCase):
    """composables/indexedList.js — the part four screens will share."""

    def _run(self, body):
        if not shutil.which("node"):
            self.skipTest("node not available")
        script = f"""
        import {{ filterRows, matchesSearch, searchText, shownMessage }} from {json.dumps(str(MODULE))};
        {body}
        """
        proc = subprocess.run(["node", "--input-type=module", "-e", script],
                              capture_output=True, text=True, cwd=str(ROOT / "dashboard"), timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        return json.loads(proc.stdout)

    def test_search_and_status_compose(self):
        out = self._run("""
        const rows = [
          {id:'a', name:'Mobile Massage', active:true},
          {id:'b', name:'Tax Prep', active:false},
          {id:'c', name:'Massage Add-on', active:false},
        ];
        const fields = ['id','name'];
        const statusOf = (r) => (r.active === false ? 'inactive' : 'active');
        console.log(JSON.stringify({
          term: filterRows(rows, {term:'massage', fields}).map(r => r.id),
          status: filterRows(rows, {fields, statusOf, status:'inactive'}).map(r => r.id),
          both: filterRows(rows, {term:'massage', fields, statusOf, status:'inactive'}).map(r => r.id),
          none: filterRows(rows, {fields}).map(r => r.id),
        }));
        """)
        self.assertEqual(out["term"], ["a", "c"])
        self.assertEqual(out["status"], ["b", "c"])
        self.assertEqual(out["both"], ["c"], "search and status must compose, not override")
        self.assertEqual(out["none"], ["a", "b", "c"])

    def test_array_fields_and_derived_extra_text_are_searchable(self):
        # tags[] on a product; item names joined in for offers.
        out = self._run("""
        const rows = [{id:'a', tags:['supplement','nad']}, {id:'b', tags:[]}];
        console.log(JSON.stringify({
          tag: filterRows(rows, {term:'nad', fields:['id','tags']}).map(r => r.id),
          extra: filterRows(rows, {term:'shaker', fields:['id'],
                   extraText: (r) => (r.id === 'b' ? 'Protein Shaker Bottle' : '')}).map(r => r.id),
        }));
        """)
        self.assertEqual(out["tag"], ["a"])
        self.assertEqual(out["extra"], ["b"], "a screen must be able to join in derived text")

    def test_a_function_field_is_supported(self):
        out = self._run("""
        const rows = [{route:{slug:'my-page'}}, {route:{slug:'other'}}];
        console.log(JSON.stringify(
          filterRows(rows, {term:'my-page', fields:[(r) => r.route?.slug]}).length));
        """)
        self.assertEqual(out, 1)

    def test_shown_message(self):
        out = self._run("""
        console.log(JSON.stringify([shownMessage(3,12,'service'), shownMessage(1,1,'offer'), shownMessage(0,0,'product')]));
        """)
        self.assertEqual(out[0], "3 of 12 services shown.")
        self.assertEqual(out[1], "1 of 1 offer shown.")


if __name__ == "__main__":
    unittest.main()
