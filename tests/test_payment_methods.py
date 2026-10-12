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
                link_url="https://connect.stripe.com/setup/acct/xyz", fail_paths=(), tax=None):
    """A fake stripe_request: GET /accounts/{id} returns the account; POST /accounts/{id}/capabilities/{cap}
    requests it (→ pending, with any configured `requirements`); POST /account_links mints a hosted link;
    GET /tax/settings returns the account's sales-tax settings (plans/TAX_STATUS_AND_THRESHOLDS.md)."""
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
        if method == "GET" and path == "/tax/settings":
            # Default `pending`, which is every tenant's real state: nothing in this codebase enables
            # Stripe Tax, so a fake that defaulted to `active` would be testing a fiction.
            return tax if tax is not None else {
                "object": "tax.settings", "status": "pending",
                "defaults": {"tax_code": None, "tax_behavior": None},
                "status_details": {"pending": {"missing_fields": ["head_office"]}}}
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


ACTIVE_TAX = {"object": "tax.settings", "status": "active",
              "defaults": {"tax_code": None, "tax_behavior": "exclusive"},
              "status_details": {"active": {}}}


class SalesTaxRidesTheSameRoute(unittest.TestCase):
    """Folded onto /payment-methods rather than given its own route: it belongs on this screen, and the
    stack sits close enough to CloudFormation's 1MB transform ceiling that a route is a cost to justify
    (plans/TRANSFORM_BUDGET.md). A body key costs nothing."""

    def _get(self, repo, caller):
        return handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", "mode": "test"}},
                       None, stripe_repo=repo, stripe_caller=caller, platform_key_loader=_key_loader)

    def _put(self, body, repo, caller):
        return handler({"httpMethod": "PUT", "body": json.dumps(body)}, None,
                       stripe_repo=repo, stripe_caller=caller, platform_key_loader=_key_loader)

    def test_the_get_returns_a_tax_block_beside_the_methods(self):
        resp = self._get(FakeStripeKeysRepo([CONNECTED]), make_caller(tax=ACTIVE_TAX))
        body = json.loads(resp["body"])
        self.assertEqual(body["tax"]["state"], "active")
        self.assertTrue(body["tax"]["may_enable"])
        self.assertFalse(body["tax"]["enabled"], "ready is not the same as on")
        self.assertIn("methods", body, "the BNPL half still answers")

    def test_the_get_caches_the_status_so_checkout_never_asks_stripe(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        self._get(repo, make_caller(tax=ACTIVE_TAX))
        stored = (repo.get("t1", mode="test") or {}).get("payment_methods", {}).get("tax") or {}
        self.assertEqual(stored.get("status"), "active")
        self.assertEqual(stored.get("tax_behavior"), "exclusive")

    def test_turning_it_on_is_refused_while_stripe_says_pending(self):
        """The screen hides the control, but a client is not a permission -- the server re-reads."""
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": True},
                         FakeStripeKeysRepo([CONNECTED]), make_caller())
        self.assertEqual(resp["statusCode"], 400)
        body = json.loads(resp["body"])
        self.assertEqual(body["error"], "tax_not_active")
        self.assertIn("head office address", body["message"])
        self.assertEqual(body["tax"]["state"], "pending",
                         "the refusal carries fresh status so the screen corrects itself")

    def test_turning_it_on_is_honoured_when_stripe_says_active(self):
        repo = FakeStripeKeysRepo([CONNECTED])
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": True},
                         repo, make_caller(tax=ACTIVE_TAX))
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(json.loads(resp["body"])["tax"]["calculating"])
        stored = (repo.get("t1", mode="test") or {}).get("payment_methods", {}).get("tax") or {}
        self.assertTrue(stored["enabled"])

    def test_turning_it_off_is_always_allowed(self):
        """A tenant must be able to stop us adding tax even while their account is mid-change, so this
        path never asks Stripe for permission."""
        repo = FakeStripeKeysRepo([dict(CONNECTED, payment_methods={
            "tax": {"enabled": True, "status": "active", "tax_behavior": "exclusive"}})])
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": False}, repo, make_caller())
        self.assertEqual(resp["statusCode"], 200)
        self.assertFalse(json.loads(resp["body"])["tax"]["enabled"])

    def test_a_tax_request_is_not_mistaken_for_an_unknown_payment_method(self):
        """It carries no `method`, so without explicit routing it would fail method validation."""
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": False},
                         FakeStripeKeysRepo([CONNECTED]), make_caller())
        self.assertNotEqual(json.loads(resp["body"]).get("error"), "invalid_method")

    def test_an_unreadable_tax_settings_read_does_not_clear_a_good_status(self):
        """A momentary outage must not flip a calculating tenant to `unknown`, stop automatic_tax on the
        next sale, and silently drop tax from their checkout."""
        repo = FakeStripeKeysRepo([dict(CONNECTED, payment_methods={
            "tax": {"enabled": True, "status": "active", "tax_behavior": "exclusive",
                    "missing_fields": []}})])
        resp = self._get(repo, make_caller(fail_paths=("/tax/settings",)))
        body = json.loads(resp["body"])
        self.assertEqual(body["tax"]["state"], "active")
        self.assertTrue(body["tax"]["calculating"])

    def test_the_stripe_tax_link_names_the_connected_account(self):
        """The bare `dashboard.stripe.com/settings/tax` resolves to whatever account the viewer's session
        is on. For a platform owner testing with a connected account that is the WRONG account -- the
        panel says "not set up on your account" and then links somewhere else, which is how a tenant
        stops believing the panel (found 2026-10-12 by clicking it)."""
        resp = self._get(FakeStripeKeysRepo([CONNECTED]), make_caller())
        url = json.loads(resp["body"])["tax"]["settings_url"]
        self.assertEqual(url, "https://dashboard.stripe.com/acct_123/settings/tax")

    def test_the_refusal_carries_the_same_scoped_link(self):
        """A rejection re-renders the panel, so it must not silently fall back to the generic URL."""
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": True},
                         FakeStripeKeysRepo([CONNECTED]), make_caller())
        self.assertIn("acct_123", json.loads(resp["body"])["tax"]["settings_url"])

    def test_an_unconnected_tenant_is_told_to_connect_rather_than_shown_a_switch(self):
        repo = FakeStripeKeysRepo([{"schema_version": "1", "document_type": "stripe_keys",
                                    "tenant_id": "t1", "mode": "test", "publishable_key": "pk_test_1"}])
        resp = self._put({"tenant_id": "t1", "mode": "test", "tax_enabled": True}, repo, make_caller())
        self.assertEqual(json.loads(resp["body"])["error"], "stripe_not_connected")


if __name__ == "__main__":
    unittest.main()
