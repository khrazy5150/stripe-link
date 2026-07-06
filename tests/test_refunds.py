import json
import unittest

from handlers.refunds import handler
from handlers.stripe_webhook import reconcile_charge_refunded
from tests.fakes import FakeDocumentRepository


class FakeStripe:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, method, path, *, api_key, stripe_account="", data=None, idempotency_key=None, **kwargs):
        self.calls.append({"path": path, "data": data, "idempotency_key": idempotency_key, "stripe_account": stripe_account})
        if self.fail:
            from stripe_link.stripe_client import StripeApiError
            raise StripeApiError(400, "charge already refunded", "charge_already_refunded")
        amount = (data or {}).get("amount") or 3709
        return {"id": "re_1", "amount": amount, "status": "succeeded"}


def creds(tenant_id, mode, stripe_keys, secret_cipher):
    return ("sk_test", stripe_keys.get("connect_account_id", ""))


class FakeKeys:
    def get(self, tenant_id, mode="test"):
        return {"connect_account_id": "acct_1"}


class RefundHandlerTests(unittest.TestCase):
    def setUp(self):
        self.requests = FakeDocumentRepository("refund_request_id")
        self.orders = FakeDocumentRepository("order_id")
        self.requests.put({
            "tenant_id": "t1", "refund_request_id": "rr_1", "document_type": "refund_request",
            "status": "new", "order_id": "order_cs_1", "customer": {"email": "a@b.com"},
            "amount": {"currency": "usd", "requested_amount": 0, "paid_amount": 3709},
        })
        self.orders.put({
            "tenant_id": "t1", "order_id": "order_cs_1", "status": "paid",
            "amount_total": 3709, "currency": "usd", "payment_intent_id": "pi_1", "mode": "test",
        })

    def call(self, action, request_id="rr_1", stripe=None, body=None):
        event = {
            "httpMethod": "POST",
            "resource": f"/refunds/{{refund_request_id}}/{action}",
            "pathParameters": {"refund_request_id": request_id},
            "queryStringParameters": {"tenant_id": "t1"},
        }
        if body is not None:
            event["body"] = json.dumps(body)
        return handler(
            event, None,
            requests_repo=self.requests, orders_repo=self.orders, stripe_repo=FakeKeys(),
            secret_cipher=None, caller=stripe or FakeStripe(), credentials_fn=creds, now_fn=lambda: 1781230000,
        )

    def test_approve_then_execute_full_refund(self):
        self.assertEqual(json.loads(self.call("approve")["body"])["refund_request"]["status"], "approved")
        stripe = FakeStripe()
        response = self.call("execute", stripe=stripe)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["refund"]["status"], "refunded")
        self.assertEqual(body["refund"]["amount"], 3709)
        # Stripe called with the payment intent, idempotency key, no explicit amount (full), connect acct
        self.assertEqual(stripe.calls[0]["path"], "/refunds")
        self.assertEqual(stripe.calls[0]["data"]["payment_intent"], "pi_1")
        self.assertNotIn("amount", stripe.calls[0]["data"])
        self.assertEqual(stripe.calls[0]["idempotency_key"], "refund_rr_1")
        self.assertEqual(stripe.calls[0]["stripe_account"], "acct_1")
        # order + request updated
        self.assertEqual(self.orders.get("t1", "order_cs_1")["status"], "refunded")
        self.assertEqual(self.requests.get("t1", "rr_1")["refund"]["stripe_refund_id"], "re_1")

    def test_partial_refund_uses_requested_amount(self):
        self.requests.get("t1", "rr_1")  # warm
        req = self.requests.documents[("t1", "rr_1")]
        req["status"] = "approved"
        req["amount"]["requested_amount"] = 1000
        stripe = FakeStripe()
        response = self.call("execute", stripe=stripe)
        self.assertEqual(stripe.calls[0]["data"]["amount"], 1000)
        self.assertEqual(self.orders.get("t1", "order_cs_1")["status"], "partially_refunded")

    def test_execute_requires_approved(self):
        response = self.call("execute")  # still "new"
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "not_approved")

    def test_execute_is_idempotent_once_refunded(self):
        self.call("approve")
        self.call("execute")
        again = self.call("execute")
        self.assertEqual(json.loads(again["body"])["refund"]["status"], "already_refunded")

    def test_reject_sets_resolved(self):
        response = self.call("reject", body={"reason": "outside window"})
        req = json.loads(response["body"])["refund_request"]
        self.assertEqual(req["status"], "rejected")
        self.assertEqual(req["decision_reason"], "outside window")
        self.assertEqual(req["resolved_at"], 1781230000)

    def test_stripe_error_returns_502(self):
        self.call("approve")
        response = self.call("execute", stripe=FakeStripe(fail=True))
        self.assertEqual(response["statusCode"], 502)


class ReconcileChargeRefundedTests(unittest.TestCase):
    def test_marks_order_refunded_from_metadata(self):
        orders = FakeDocumentRepository("order_id")
        orders.put({"tenant_id": "t1", "order_id": "order_cs_1", "status": "paid", "amount_total": 3709})
        event = {"type": "charge.refunded", "data": {"object": {
            "amount_refunded": 3709, "metadata": {"order_id": "order_cs_1"}}}}
        result = reconcile_charge_refunded(event, tenant_id="t1", orders_repo=orders, now_fn=lambda: 1781230000)
        self.assertEqual(result["status"], "reconciled")
        self.assertEqual(orders.get("t1", "order_cs_1")["status"], "refunded")

    def test_skips_without_order_metadata(self):
        event = {"type": "charge.refunded", "data": {"object": {"amount_refunded": 100, "metadata": {}}}}
        result = reconcile_charge_refunded(event, tenant_id="t1", orders_repo=FakeDocumentRepository("order_id"))
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
