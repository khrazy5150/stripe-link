import json
import unittest

from handlers.payment_methods import handler
from stripe_link.stripe_client import StripeApiError


class FakeStripeKeysRepo:
    """Stripe-keys repo scoped by (tenant_id, mode), matching StripeKeysRepository.get(tenant, mode)/put(doc)."""
    def __init__(self, docs=None):
        self.docs = {}
        for doc in docs or []:
            self.docs[(doc["tenant_id"], doc.get("mode", "test"))] = dict(doc)

    def get(self, tenant_id, mode="test"):
        doc = self.docs.get((tenant_id, mode))
        return dict(doc) if doc else None

    def put(self, document):
        self.docs[(document["tenant_id"], document.get("mode", "test"))] = dict(document)
        return document


def make_caller(*, capabilities=None, country="US", record=None):
    """A fake stripe_request: POST /accounts/{id} echoes the requested capability; GET returns the account."""
    caps = dict(capabilities or {})

    def caller(method, path, *, api_key, stripe_account="", params=None, data=None, **kwargs):
        if record is not None:
            record.append({"method": method, "path": path, "api_key": api_key, "data": data})
        if method == "POST" and path.startswith("/accounts/"):
            requested = (data or {}).get("capabilities") or {}
            for cap, cfg in requested.items():
                caps[cap] = "pending" if cfg.get("requested") else "inactive"
            return {"id": path.split("/")[-1], "country": country, "capabilities": dict(caps)}
        if method == "GET" and path.startswith("/accounts/"):
            return {"id": path.split("/")[-1], "country": country, "capabilities": dict(caps)}
        raise AssertionError(f"unexpected call {method} {path}")
    return caller


def _key_loader(mode):
    return f"sk_platform_{mode}"


CONNECTED = {"schema_version": "2026-01-01", "document_type": "stripe_keys", "tenant_id": "t1", "mode": "test",
             "connect_account_id": "acct_123"}


class PaymentMethodsHandlerTests(unittest.TestCase):
    def _put(self, body, repo, caller):
        return handler({"httpMethod": "PUT", "body": json.dumps(body)}, None,
                       stripe_repo=repo, stripe_caller=caller, platform_key_loader=_key_loader)

    def test_enable_klarna_requests_capability_and_persists(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(record=record)
        resp = self._put({"tenant_id": "t1", "mode": "test", "method": "klarna", "enabled": True}, repo, caller)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["capability_status"], "pending")
        # It POSTed the capability request with the platform key, no Stripe-Account header (edits the account).
        self.assertEqual(record[0]["path"], "/accounts/acct_123")
        self.assertEqual(record[0]["data"], {"capabilities": {"klarna_payments": {"requested": True}}})
        self.assertEqual(record[0]["api_key"], "sk_platform_test")
        # Persisted on the stripe_keys doc.
        saved = repo.get("t1", "test")["payment_methods"]["bnpl"]["klarna"]
        self.assertEqual((saved["enabled"], saved["capability_status"]), (True, "pending"))

    def test_disable_revokes(self):
        repo = FakeStripeKeysRepo([{**CONNECTED, "payment_methods": {"bnpl": {"klarna": {"enabled": True, "capability_status": "active"}}}}])
        record = []
        resp = self._put({"tenant_id": "t1", "method": "klarna", "enabled": False}, repo, make_caller(capabilities={"klarna_payments": "active"}, record=record))
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(record[0]["data"], {"capabilities": {"klarna_payments": {"requested": False}}})
        self.assertIs(repo.get("t1", "test")["payment_methods"]["bnpl"]["klarna"]["enabled"], False)

    def test_unknown_method_rejected(self):
        resp = self._put({"tenant_id": "t1", "method": "sezzle", "enabled": True}, FakeStripeKeysRepo([CONNECTED]), make_caller())
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(json.loads(resp["body"])["error"], "invalid_method")

    def test_toggle_without_connected_account_errors(self):
        repo = FakeStripeKeysRepo([{"schema_version": "2026-01-01", "document_type": "stripe_keys",
                                    "tenant_id": "t1", "mode": "test", "publishable_key": "pk_test_x"}])
        resp = self._put({"tenant_id": "t1", "method": "klarna", "enabled": True}, repo, make_caller())
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(json.loads(resp["body"])["error"], "stripe_not_connected")

    def test_stripe_error_surfaces(self):
        def boom(*a, **k):
            raise StripeApiError(400, "capability not available")
        resp = self._put({"tenant_id": "t1", "method": "klarna", "enabled": True}, FakeStripeKeysRepo([CONNECTED]), boom)
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(json.loads(resp["body"])["error"], "capability_error")

    def test_get_returns_status_and_country_eligibility_and_refreshes_cache(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        # Live account shows klarna active; country US → affirm eligible, but not enabled.
        caller = make_caller(capabilities={"klarna_payments": "active"}, country="US")
        resp = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", "mode": "test"}}, None,
                       stripe_repo=repo, stripe_caller=caller, platform_key_loader=_key_loader)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertTrue(body["connected"])
        self.assertEqual(body["account_country"], "US")
        klarna = next(m for m in body["methods"] if m["method"] == "klarna")
        self.assertEqual(klarna["capability_status"], "active")
        self.assertTrue(klarna["country_eligible"])
        # Cache was refreshed from the live status.
        self.assertEqual(repo.get("t1", "test")["payment_methods"]["bnpl"]["klarna"]["capability_status"], "active")

    def test_get_marks_country_ineligible(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        caller = make_caller(country="GB")  # UK account: Affirm (US/CA only) is ineligible
        resp = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}}, None,
                       stripe_repo=repo, stripe_caller=caller, platform_key_loader=_key_loader)
        affirm = next(m for m in json.loads(resp["body"])["methods"] if m["method"] == "affirm")
        self.assertFalse(affirm["country_eligible"])
        klarna = next(m for m in json.loads(resp["body"])["methods"] if m["method"] == "klarna")
        self.assertTrue(klarna["country_eligible"])  # Klarna covers GB


if __name__ == "__main__":
    unittest.main()
