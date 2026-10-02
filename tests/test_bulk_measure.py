"""P0d: the warning becomes the fix.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md. `product_readiness` has named the unmeasured products since
2026-09-24 and the count has not moved -- 2 of 15 dev and 0 of 4 prod shippable products carry dimensions.
A better warning will not move it either. **Fourteen empty forms was the obstacle, not one form.**
"""
import json
import pathlib
import unittest

from handlers.shipping import measure_products
from stripe_link.domain.shipping import unmeasured_products

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

MEASURED = {"length_in": 4, "width_in": 3, "height_in": 2, "weight_lb": 1}


def product(pid, name, category="Supplement", dims=None, ships=True, ptype="physical"):
    fulfillment = {"requires_shipping": ships}
    if dims:
        fulfillment["item_dimensions"] = dims
    return {"product_id": pid, "name": name, "category": category, "product_type": ptype,
            "fulfillment": fulfillment}


class WhichProductsAndWhatToSuggestTests(unittest.TestCase):
    CATALOGUE = [
        product("a", "Beta Alanine", dims=MEASURED),
        product("b", "Creatine Gummies"),
        product("c", "Paint Set", category="Art"),
        product("d", "Ebook", ships=False, ptype="digital"),
    ]

    def test_only_shippable_unmeasured_products_are_listed(self):
        names = [row["name"] for row in unmeasured_products(self.CATALOGUE)]
        self.assertEqual(names, ["Creatine Gummies", "Paint Set"])

    def test_a_measured_product_in_the_same_category_becomes_a_suggestion(self):
        rows = {r["name"]: r for r in unmeasured_products(self.CATALOGUE)}
        self.assertEqual(rows["Creatine Gummies"]["suggestion"]["from_name"], "Beta Alanine")
        self.assertEqual(rows["Creatine Gummies"]["suggestion"]["length_in"], 4)

    def test_a_category_with_nothing_measured_gets_no_suggestion(self):
        rows = {r["name"]: r for r in unmeasured_products(self.CATALOGUE)}
        self.assertIsNone(rows["Paint Set"].get("suggestion"))

    def test_three_of_four_is_not_measured(self):
        partial = [product("x", "Half", dims={"length_in": 4, "width_in": 3, "height_in": 2})]
        self.assertEqual(len(unmeasured_products(partial)), 1)


class Repo:
    def __init__(self, products):
        self.docs = {p["product_id"]: p for p in products}
        self.writes = []

    def get(self, tenant_id, product_id):
        return self.docs.get(product_id)

    def put(self, document):
        self.writes.append(document)
        self.docs[document["product_id"]] = document
        return document

    def list_for_tenant(self, tenant_id):
        return list(self.docs.values())


def measure(rows, products):
    repo = Repo(products)
    event = {"requestContext": {"authorizer": {"claims": {"sub": "t1"}}}, "httpMethod": "POST",
             "body": json.dumps({"measurements": rows})}
    return json.loads(measure_products(event, None, products_repo=repo)["body"]), repo


class BulkMeasureTests(unittest.TestCase):
    PRODUCTS = [product("b", "Creatine Gummies"), product("c", "Paint Set", category="Art")]

    def test_it_writes_item_dimensions(self):
        body, repo = measure([{"product_id": "b", **MEASURED}], self.PRODUCTS)
        self.assertEqual(body["saved"], ["b"])
        self.assertEqual(repo.docs["b"]["fulfillment"]["item_dimensions"]["length_in"], 4.0)

    def test_it_measures_several_at_once(self):
        body, _ = measure([{"product_id": "b", **MEASURED}, {"product_id": "c", **MEASURED}],
                          self.PRODUCTS)
        self.assertEqual(sorted(body["saved"]), ["b", "c"])

    def test_a_partial_row_is_skipped_not_half_written(self):
        # Three sides still cannot be rated, and a product that LOOKS measured and is not is worse than
        # one that is plainly blank.
        body, repo = measure([{"product_id": "b", "length_in": 4, "width_in": 3}], self.PRODUCTS)
        self.assertEqual(body["saved"], [])
        self.assertEqual(body["skipped"], ["b"])
        self.assertEqual(repo.writes, [])

    def test_everything_else_on_the_product_is_left_alone(self):
        rich = [{**product("b", "Creatine Gummies"), "description": "keep me", "prices": [{"x": 1}]}]
        _, repo = measure([{"product_id": "b", **MEASURED}], rich)
        self.assertEqual(repo.docs["b"]["description"], "keep me")
        self.assertEqual(repo.docs["b"]["prices"], [{"x": 1}])

    def test_an_unknown_product_is_skipped_rather_than_failing_the_batch(self):
        body, _ = measure([{"product_id": "nope", **MEASURED}, {"product_id": "b", **MEASURED}],
                          self.PRODUCTS)
        self.assertEqual(body["saved"], ["b"])
        self.assertIn("nope", body["skipped"])

    def test_it_returns_what_is_still_missing(self):
        body, _ = measure([{"product_id": "b", **MEASURED}], self.PRODUCTS)
        self.assertEqual([r["name"] for r in body["unmeasured_products"]], ["Paint Set"])

    def test_nothing_to_measure_is_refused(self):
        event = {"requestContext": {"authorizer": {"claims": {"sub": "t1"}}}, "httpMethod": "POST",
                 "body": json.dumps({"measurements": []})}
        self.assertEqual(json.loads(measure_products(event, None, products_repo=Repo([]))["body"])["error"],
                         "missing_measurements")


class TheScreenEditsInPlaceTests(unittest.TestCase):
    def test_the_readiness_list_became_editable_rows(self):
        self.assertIn("unmeasuredProducts", SCREEN)
        self.assertIn("measurements[row.product_id].length_in", SCREEN)

    def test_a_suggestion_is_offered_not_applied(self):
        # Silently copying another product's measurements would manufacture data that reads as measured
        # and is not -- exactly what P0a exists to stop.
        self.assertIn("useSuggestion(row)", SCREEN)
        self.assertIn("Same as {{ row.suggestion.from_name }}", SCREEN)

    def test_only_complete_rows_are_sent(self):
        block = SCREEN.split("const completeMeasurements = computed", 1)[1][:400]
        for field in ("length_in", "width_in", "height_in", "weight_lb"):
            self.assertIn(field, block)
        self.assertIn("Number(row[field]) > 0", block)

    def test_a_blank_row_is_allowed_to_stay_blank(self):
        self.assertIn("Leave a row blank to come back to it.", SCREEN)

    def test_saving_refreshes_what_is_still_missing(self):
        block = SCREEN.split("async function saveMeasurements", 1)[1][:700]
        self.assertIn("body.unmeasured_products", block)


class GrantsAndRoutingTests(unittest.TestCase):
    def test_it_may_write_the_products_it_measures(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  ShippingFunction:", 1)[1].split("      Events:", 1)[0]
        products = block.split("TableName: !Ref ProductsTable", 1)[0]
        self.assertIn("DynamoDBCrudPolicy", products.rsplit("- ", 1)[-1] or products[-80:])
        self.assertIn("/shipping/measure", template)

    def test_it_is_dispatched(self):
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        self.assertIn('_action(event) == "measure"', source)
