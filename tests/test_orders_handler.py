import json
import unittest

from handlers.orders import handler as orders_handler
from tests.fakes import FakeDocumentRepository


def order(tenant_id, order_id, *, status="paid", name="Ada Buyer", email="ada@example.com", created_at="1781230000"):
    return {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "schema_version": "2026-05-29",
        "document_type": "order",
        "status": status,
        "amount_total": 3709,
        "currency": "usd",
        "customer": {"name": name, "email": email, "phone": "", "stripe_customer_id": "cus_123"},
        "product": {"product_id": "prod_demo", "price_id": "price_demo", "name": "Demo Product"},
        "created_at": created_at,
        "updated_at": 1781230000,
    }


class OrdersHandlerTests(unittest.TestCase):
    def test_list_orders_sorts_newest_first_and_filters(self):
        repository = FakeDocumentRepository("order_id")
        repository.put(order("tenant_demo", "order_1", created_at="1781230000"))
        repository.put(order("tenant_demo", "order_2", created_at="1781240000", status="refunded", name="Zed Buyer", email="zed@example.com"))
        repository.put(order("tenant_other", "order_3", created_at="1781250000"))

        response = orders_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["count"], 2)
        self.assertEqual([o["order_id"] for o in body["orders"]], ["order_2", "order_1"])

        filtered = orders_handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo", "status": "refunded"},
        }, None, repository=repository)
        filtered_body = json.loads(filtered["body"])
        self.assertEqual(filtered_body["count"], 1)
        self.assertEqual(filtered_body["orders"][0]["order_id"], "order_2")

    def test_get_order_returns_not_found_for_missing_order(self):
        repository = FakeDocumentRepository("order_id")
        repository.put(order("tenant_demo", "order_1"))

        response = orders_handler({
            "httpMethod": "GET",
            "pathParameters": {"order_id": "order_missing"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 404)

    def test_get_order_returns_matching_order(self):
        repository = FakeDocumentRepository("order_id")
        repository.put(order("tenant_demo", "order_1"))

        response = orders_handler({
            "httpMethod": "GET",
            "pathParameters": {"order_id": "order_1"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=repository)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["order"]["customer"]["email"], "ada@example.com")

    def test_requires_tenant_id(self):
        repository = FakeDocumentRepository("order_id")

        response = orders_handler({
            "httpMethod": "GET",
            "queryStringParameters": {},
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 400)

    def test_rejects_unsupported_method(self):
        repository = FakeDocumentRepository("order_id")

        response = orders_handler({
            "httpMethod": "PUT",
        }, None, repository=repository)

        self.assertEqual(response["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()
