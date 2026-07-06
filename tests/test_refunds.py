import json
import unittest

from handlers.refunds import handler
from handlers.stripe_webhook import reconcile_charge_refunded, reconcile_dispute
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
        self.refunds = FakeDocumentRepository("refund_id")
        self.requests.put({
            "tenant_id": "t1", "refund_request_id": "rr_1", "document_type": "refund_request",
            "status": "new", "order_id": "order_cs_1", "customer": {"email": "a@b.com"},
            "amount": {"currency": "usd", "requested_amount": 0, "paid_amount": 3709},
        })
        self.orders.put({
            "tenant_id": "t1", "order_id": "order_cs_1", "payment_status": "paid",
            "amount_total": 3709, "amount_paid": 3709, "amount_refunded": 0, "refund_count": 0,
            "currency": "usd", "payment_intent_id": "pi_1", "mode": "test",
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
            requests_repo=self.requests, orders_repo=self.orders, refunds_repo=self.refunds, stripe_repo=FakeKeys(),
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
        # order aggregates + ledger + request updated
        order = self.orders.get("t1", "order_cs_1")
        self.assertEqual(order["payment_status"], "refunded")
        self.assertEqual(order["amount_refunded"], 3709)
        self.assertEqual(order["refundable_amount"], 0)
        self.assertEqual(order["refund_count"], 1)
        self.assertEqual(self.refunds.get("t1", "re_1")["amount"], 3709)  # ledger row keyed by stripe refund id
        self.assertEqual(self.requests.get("t1", "rr_1")["refund"]["stripe_refund_id"], "re_1")

    def test_partial_refund_uses_requested_amount(self):
        self.requests.get("t1", "rr_1")  # warm
        req = self.requests.documents[("t1", "rr_1")]
        req["status"] = "approved"
        req["amount"]["requested_amount"] = 1000
        stripe = FakeStripe()
        response = self.call("execute", stripe=stripe)
        self.assertEqual(stripe.calls[0]["data"]["amount"], 1000)
        order = self.orders.get("t1", "order_cs_1")
        self.assertEqual(order["payment_status"], "partially_refunded")
        self.assertEqual(order["amount_refunded"], 1000)
        self.assertEqual(order["refundable_amount"], 2709)

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
    def setUp(self):
        self.orders = FakeDocumentRepository("order_id")
        self.refunds = FakeDocumentRepository("refund_id")
        self.orders.put({
            "tenant_id": "t1", "order_id": "order_cs_1", "payment_status": "paid",
            "amount_total": 5000, "amount_paid": 5000, "amount_refunded": 0, "refund_count": 0,
            "currency": "usd", "payment_intent_id": "pi_1",
        })

    def event(self, amount_refunded, refunds):
        return {"type": "charge.refunded", "data": {"object": {
            "id": "ch_1", "payment_intent": "pi_1", "amount_refunded": amount_refunded,
            "refunds": {"data": refunds}}}}

    def test_external_refund_resolved_by_payment_intent_and_ledgered(self):
        event = self.event(2000, [{"id": "re_ext", "amount": 2000, "reason": "requested_by_customer", "status": "succeeded", "metadata": {}}])
        result = reconcile_charge_refunded(event, tenant_id="t1", orders_repo=self.orders, refunds_repo=self.refunds, now_fn=lambda: 1781230000)
        self.assertEqual(result["status"], "reconciled")
        order = self.orders.get("t1", "order_cs_1")
        self.assertEqual(order["payment_status"], "partially_refunded")
        self.assertEqual(order["amount_refunded"], 2000)
        self.assertEqual(order["refundable_amount"], 3000)
        ledger = self.refunds.get("t1", "re_ext")
        self.assertEqual(ledger["initiated_by"], "stripe_dashboard")
        self.assertEqual(ledger["amount"], 2000)

    def test_dedupes_refund_already_in_ledger(self):
        # simulate our execute path already recorded this stripe refund
        self.refunds.put({"tenant_id": "t1", "refund_id": "re_ours", "order_id": "order_cs_1",
                          "stripe_refund_id": "re_ours", "amount": 5000, "initiated_by": "admin"})
        event = self.event(5000, [{"id": "re_ours", "amount": 5000, "status": "succeeded", "metadata": {"refund_request_id": "rr_1"}}])
        result = reconcile_charge_refunded(event, tenant_id="t1", orders_repo=self.orders, refunds_repo=self.refunds, now_fn=lambda: 1781230000)
        self.assertEqual(result["ledger_written"], 0)  # not double-written
        self.assertEqual(self.orders.get("t1", "order_cs_1")["payment_status"], "refunded")

    def test_skips_when_order_not_found_by_pi(self):
        event = {"type": "charge.refunded", "data": {"object": {"payment_intent": "pi_unknown", "amount_refunded": 100, "refunds": {"data": []}}}}
        result = reconcile_charge_refunded(event, tenant_id="t1", orders_repo=self.orders, refunds_repo=self.refunds)
        self.assertEqual(result["status"], "skipped")


class ReconcileDisputeTests(unittest.TestCase):
    def test_flags_order_disputed(self):
        orders = FakeDocumentRepository("order_id")
        orders.put({"tenant_id": "t1", "order_id": "order_cs_1", "payment_status": "paid", "payment_intent_id": "pi_1"})
        event = {"type": "charge.dispute.created", "data": {"object": {"payment_intent": "pi_1"}}}
        result = reconcile_dispute(event, tenant_id="t1", orders_repo=orders, now_fn=lambda: 1781230000)
        self.assertEqual(result["status"], "disputed")
        self.assertEqual(orders.get("t1", "order_cs_1")["payment_status"], "disputed")


if __name__ == "__main__":
    unittest.main()
