import json
import unittest

from handlers.ledger import handler
from stripe_link.domain.documents import DocumentValidationError, validate_ledger_entry
from stripe_link.domain.ledger import refund_entry, sale_entry, sale_entry_from_order, summarize


class FakeLedgerRepository:
    def __init__(self):
        self.entries = {}

    def append(self, document):
        self.entries[(document["tenant_id"], document["entry_id"])] = dict(document)
        return document

    def list_for_tenant(self, tenant_id):
        return [dict(v) for (t, _), v in self.entries.items() if t == tenant_id]

    def list_for_order(self, order_id):
        return [dict(v) for v in self.entries.values() if v.get("order_id") == order_id]


ORDER = {
    "tenant_id": "tenant-1",
    "order_id": "order_1",
    "amount_paid": 7000,
    "currency": "usd",
    "stripe_fee": 300,
    "platform_fee": 500,
    "payment_intent_id": "pi_abc",
    "mode": "live",
    "customer": {"email": "c@example.com", "name": "Casey"},
}


class LedgerDomainTests(unittest.TestCase):
    def test_sale_entry_sign_convention(self):
        entry = sale_entry(
            tenant_id="t", entry_id="le_1", occurred_at=100, mode="live", currency="usd",
            gross=7000, stripe_fee=300, platform_fee=500, idempotency_key="sale:pi_abc",
        )
        self.assertEqual(entry["amounts"], {"gross": 7000, "stripe_fee": -300, "platform_fee": -500})
        validate_ledger_entry(entry)  # builder output must be schema-valid

    def test_refund_entry_reverses_gross_keeps_platform_fee(self):
        entry = refund_entry(
            tenant_id="t", entry_id="le_r", occurred_at=100, mode="test", currency="usd",
            refund_amount=7000, idempotency_key="refund:re_1",
        )
        self.assertEqual(entry["amounts"], {"gross": -7000})  # platform_fee 0 dropped as non-signal
        validate_ledger_entry(entry)

    def test_sale_entry_from_order(self):
        entry = sale_entry_from_order(ORDER, now_epoch=1_800_000_000)
        self.assertEqual(entry["entry_id"], "le_sale_pi_abc")
        self.assertEqual(entry["mode"], "live")
        self.assertEqual(entry["amounts"], {"gross": 7000, "stripe_fee": -300, "platform_fee": -500})
        self.assertEqual(entry["order_id"], "order_1")
        self.assertEqual(entry["customer_ref"], {"email": "c@example.com", "name": "Casey"})

    def test_sale_entry_from_order_needs_amount_and_key(self):
        self.assertIsNone(sale_entry_from_order({"tenant_id": "t"}, now_epoch=1))

    def test_summarize_is_additive(self):
        sale = sale_entry(tenant_id="t", entry_id="le_s", occurred_at=1, mode="test", currency="usd",
                          gross=7000, stripe_fee=300, platform_fee=500, idempotency_key="sale:1")
        refund = refund_entry(tenant_id="t", entry_id="le_r", occurred_at=2, mode="test", currency="usd",
                              refund_amount=1000, idempotency_key="refund:1")
        summary = summarize([sale, refund])
        # net = gross - fees; after a 1000 refund: (7000-1000) - 300 - 500
        self.assertEqual(summary["totals"]["gross"], 6000)
        self.assertEqual(summary["net"], 6000 - 300 - 500)
        self.assertEqual(summary["counts"], {"sale": 1, "refund": 1})

    def test_invalid_entry_type_rejected(self):
        entry = sale_entry(tenant_id="t", entry_id="le_1", occurred_at=1, mode="test", currency="usd",
                           gross=100, idempotency_key="sale:1")
        entry["entry_type"] = "bogus"
        with self.assertRaises(DocumentValidationError):
            validate_ledger_entry(entry)


class WebhookWiringTests(unittest.TestCase):
    def test_record_sale_ledger_entry_appends_valid_entry(self):
        from handlers.stripe_webhook import record_sale_ledger_entry

        repo = FakeLedgerRepository()
        self.assertTrue(record_sale_ledger_entry(ORDER, repo, now=1_800_000_000))
        stored = repo.list_for_order("order_1")
        self.assertEqual(len(stored), 1)
        validate_ledger_entry(stored[0])

    def test_record_sale_ledger_entry_noops_without_amount(self):
        from handlers.stripe_webhook import record_sale_ledger_entry

        repo = FakeLedgerRepository()
        self.assertFalse(record_sale_ledger_entry({"tenant_id": "t", "order_id": "o"}, repo, now=1))
        self.assertEqual(repo.list_for_tenant("t"), [])


class LedgerHandlerTests(unittest.TestCase):
    def test_get_ledger_for_tenant_returns_summary(self):
        repo = FakeLedgerRepository()
        repo.append(sale_entry_from_order(ORDER, now_epoch=1))
        event = {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "tenant-1"}}
        response = handler(event, None, repository=repo)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["summary"]["net"], 7000 - 300 - 500)

    def test_get_ledger_by_order(self):
        repo = FakeLedgerRepository()
        repo.append(sale_entry_from_order(ORDER, now_epoch=1))
        event = {"httpMethod": "GET", "queryStringParameters": {"order_id": "order_1"}}
        response = handler(event, None, repository=repo)
        self.assertEqual(json.loads(response["body"])["count"], 1)


if __name__ == "__main__":
    unittest.main()
