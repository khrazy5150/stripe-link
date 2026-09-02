"""The slim product list projection: GET /products?view=index.

Products are the payload that hits the 6MB Lambda response ceiling FIRST — documents average ~3.1KB
(larger than offers) and tenants usually have more of them, and BOTH the Products screen and the Offers
screen load the whole catalogue on mount.

Unlike the offer index this cannot drop its dominant field: `prices` is ~57% of a product and the Offers
screen derives funnel roles from every price's `context`. What it drops is the parts of a price that
nothing in dashboard/src reads — verified by grep before choosing, not guessed.
"""

import json
import unittest

from handlers.products import handler
from stripe_link.domain.product_index import product_index_entry
from tests.fakes import FakeDocumentRepository

FULL_PRODUCT = {
    "tenant_id": "t1", "product_id": "p1", "name": "NAD Supplement",
    "description": "5000mg of pure creatine monohydrate.", "product_category": "dietary_supplement",
    "product_type": "physical", "tags": ["supplement", "nad"], "status": "active", "active": True,
    "stripe_product_id": "prod_123", "images": ["https://img/nad.jpg"],
    "refund_policy": {"window_days": 30, "copy": "x" * 300},
    "variants": [{"sku": "a"}], "image_dims": {"base": [800, 800]},
    "sync": {"status": "synced", "last_synced_at": "1788"},
    "prices": [
        {"price_id": "s1", "context": "standard", "unit_amount": 3900, "currency": "usd",
         "pricing_model": "one_time", "quantity": 1, "stripe_price_id": "price_x",
         "compare_at_unit_amount": 6500, "fee_handling": "standard", "suggested_amount": 0,
         "tenant_keyed_amount": 3900, "label": "1 Item",
         "fee_breakdown": {"platform_fee": 45, "net_payout": 798, "tenant_share": 12},
         "previous_price_id": "price_old", "created_at": "1", "updated_at": "2"},
        {"price_id": "u1", "context": "upsell", "unit_amount": 1445, "currency": "usd"},
    ],
}


class ProductIndexEntryTests(unittest.TestCase):
    def test_keeps_every_field_the_dashboard_reads(self):
        entry = product_index_entry(FULL_PRODUCT)
        for field in ("product_id", "name", "description", "product_category", "product_type",
                      "tags", "status", "active", "stripe_product_id", "images"):
            with self.subTest(field=field):
                self.assertIn(field, entry, f"{field} is used by the card, search or status filter")

    def test_keeps_the_price_fields_the_dashboard_reads(self):
        price = product_index_entry(FULL_PRODUCT)["prices"][0]
        for field in ("price_id", "context", "unit_amount", "currency", "pricing_model", "quantity",
                      "stripe_price_id", "compare_at_unit_amount", "fee_handling", "tenant_keyed_amount"):
            with self.subTest(field=field):
                self.assertIn(field, price)

    def test_drops_what_nothing_reads(self):
        blob = json.dumps(product_index_entry(FULL_PRODUCT))
        for dropped in ("fee_breakdown", "previous_price_id", "refund_policy", "variants",
                        "image_dims", "net_payout"):
            with self.subTest(dropped=dropped):
                self.assertNotIn(dropped, blob)

    def test_prices_are_KEPT_because_funnel_roles_derive_from_them(self):
        # The one field this projection must not drop: without contexts the Offers screen cannot tell an
        # upsell from a landing item.
        contexts = [p["context"] for p in product_index_entry(FULL_PRODUCT)["prices"]]
        self.assertEqual(contexts, ["standard", "upsell"])

    def test_active_false_survives_because_it_marks_a_product_archived(self):
        entry = product_index_entry({**FULL_PRODUCT, "active": False})
        self.assertIs(entry["active"], False)

    def test_is_substantially_smaller(self):
        full = len(json.dumps(FULL_PRODUCT))
        slim = len(json.dumps(product_index_entry(FULL_PRODUCT)))
        self.assertLess(slim, full * 0.6, f"index {slim}B vs document {full}B")


class ListProductsIndexViewTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("product_id")
        for i in range(3):
            self.repository.put({**FULL_PRODUCT, "product_id": f"p{i}"})

    def _get(self, query=None):
        event = {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", **(query or {})}}
        return json.loads(handler(event, None, repository=self.repository)["body"])["products"]

    def test_index_view_is_slim(self):
        rows = self._get({"view": "index"})
        self.assertEqual(len(rows), 3)
        self.assertNotIn("refund_policy", rows[0])
        self.assertIn("prices", rows[0])

    def test_default_view_is_still_the_full_document(self):
        self.assertIn("refund_policy", self._get()[0])

    def test_an_unknown_view_falls_back_to_full_documents(self):
        self.assertIn("refund_policy", self._get({"view": "nonsense"})[0])


if __name__ == "__main__":
    unittest.main()
