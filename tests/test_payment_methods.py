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


def make_caller(*, capabilities=None, country="US", record=None, requirements=None,
                link_url="https://connect.stripe.com/setup/acct/xyz", fail_paths=()):
    """A fake stripe_request: GET /accounts/{id} returns the account; POST /accounts/{id}/capabilities/{cap}
    requests it (→ pending, with any configured `requirements`); POST /account_links mints a hosted link."""
    caps = dict(capabilities or {})
    reqs = dict(requirements or {})               # {capability: {"currently_due": [...], "past_due": [...]}}

    def caller(method, path, *, api_key, stripe_account="", params=None, data=None, **kwargs):
        if record is not None:
            record.append({"method": method, "path": path, "api_key": api_key, "data": data})
        if any(fp in path for fp in fail_paths):
            raise StripeApiError(400, "forced failure")
        if method == "POST" and "/capabilities/" in path:
            cap = path.rsplit("/", 1)[-1]
            if (data or {}).get("requested") and caps.get(cap) != "active":
                caps[cap] = "pending"
            return {"id": cap, "status": caps.get(cap, "pending"),
                    "requirements": reqs.get(cap, {"currently_due": [], "past_due": []})}
        if method == "POST" and path == "/account_links":
            return {"url": link_url}
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

    def test_enable_klarna_reads_status_and_persists_intent(self):
        # Standard accounts self-manage capabilities (Klarna active by default). Enabling stores DISPLAY intent +
        # the live status we READ — it must NOT POST a capability request (that's live-only / restricted).
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(capabilities={"klarna_payments": "active"}, record=record)
        resp = self._put({"tenant_id": "t1", "mode": "test", "method": "klarna", "enabled": True}, repo, caller)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["capability_status"], "active")
        self.assertTrue(any(c["method"] == "GET" for c in record))         # read the account
        self.assertFalse(any(c["method"] == "POST" for c in record))       # never requested a capability
        saved = repo.get("t1", "test")["payment_methods"]["bnpl"]["klarna"]
        self.assertEqual((saved["enabled"], saved["capability_status"]), (True, "active"))

    def test_disable_stops_offering(self):
        repo = FakeStripeKeysRepo([{**CONNECTED, "payment_methods": {"bnpl": {"klarna": {"enabled": True, "capability_status": "active"}}}}])
        record = []
        resp = self._put({"tenant_id": "t1", "method": "klarna", "enabled": False}, repo,
                         make_caller(capabilities={"klarna_payments": "active"}, record=record))
        self.assertEqual(resp["statusCode"], 200)
        self.assertFalse(any(c["method"] == "POST" for c in record))       # no capability revoke POST
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

    def test_stripe_read_failure_degrades_not_errors(self):
        # If we can't read the account, the toggle still records the tenant's intent (status falls to unrequested);
        # a later screen load refreshes it. It must not fail the toggle.
        def boom(*a, **k):
            raise StripeApiError(400, "unreachable")
        resp = self._put({"tenant_id": "t1", "method": "klarna", "enabled": True}, FakeStripeKeysRepo([CONNECTED]), boom)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertTrue(body["enabled"])
        self.assertEqual(body["capability_status"], "unrequested")

    def test_enable_non_active_method_requests_the_capability(self):
        # Affirm starts unrequested → enabling it REQUESTS the capability for the tenant (no dashboard trip).
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(capabilities={"affirm_payments": "unrequested"}, record=record)
        resp = self._put({"tenant_id": "t1", "method": "affirm", "enabled": True}, repo, caller)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["capability_status"], "pending")   # request kicked it off
        req = next(c for c in record if c["method"] == "POST" and "/capabilities/affirm_payments" in c["path"])
        self.assertEqual(req["data"], {"requested": "true"})
        self.assertEqual(req["api_key"], "sk_platform_test")                         # platform key, edits the account
        self.assertEqual(repo.get("t1", "test")["payment_methods"]["bnpl"]["affirm"]["capability_status"], "pending")

    def test_leftover_requirements_mint_an_account_link(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(capabilities={"affirm_payments": "unrequested"}, record=record,
                             requirements={"affirm_payments": {"currently_due": ["company.tax_id"], "past_due": []}})
        resp = self._put({"tenant_id": "t1", "method": "affirm", "enabled": True,
                          "return_url": "https://app.example.com/payments"}, repo, caller)
        body = json.loads(resp["body"])
        self.assertEqual(body["requirements_due"], ["company.tax_id"])
        self.assertEqual(body["onboarding_url"], "https://connect.stripe.com/setup/acct/xyz")
        self.assertTrue(any(c["path"] == "/account_links" for c in record))

    def test_no_account_link_without_a_return_url(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(capabilities={"affirm_payments": "unrequested"}, record=record,
                             requirements={"affirm_payments": {"currently_due": ["company.tax_id"]}})
        resp = self._put({"tenant_id": "t1", "method": "affirm", "enabled": True}, repo, caller)   # no return_url
        body = json.loads(resp["body"])
        self.assertEqual(body["requirements_due"], ["company.tax_id"])
        self.assertNotIn("onboarding_url", body)
        self.assertFalse(any(c["path"] == "/account_links" for c in record))

    def test_capability_request_failure_degrades(self):
        # Test mode ('only live keys') / any request error → keep the read status, no crash, toggle still saves intent.
        repo = FakeStripeKeysRepo([CONNECTED])
        caller = make_caller(capabilities={"affirm_payments": "unrequested"}, fail_paths=("/capabilities/",))
        resp = self._put({"tenant_id": "t1", "method": "affirm", "enabled": True}, repo, caller)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertTrue(body["enabled"])
        self.assertEqual(body["capability_status"], "unrequested")                   # degraded, still stored
        self.assertNotIn("onboarding_url", body)

    def test_active_method_is_not_re_requested(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        record = []
        caller = make_caller(capabilities={"afterpay_clearpay_payments": "active"}, record=record)
        self._put({"tenant_id": "t1", "method": "afterpay_clearpay", "enabled": True}, repo, caller)
        self.assertFalse(any("/capabilities/" in c["path"] for c in record))         # already active → no request

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
