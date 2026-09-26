"""Which routes may be called without a dashboard session.

`tenant_id` is read from the request and nothing verifies the caller, so anyone who knows a tenant_id can
act as that tenant. The fix is an authorizer at the API; the HARD part is this table, because getting it
wrong in either direction is expensive:

  a route wrongly PRIVATE  -> buyers stop being able to check out the moment enforcement lands
  a route wrongly PUBLIC   -> the hole stays open and looks closed

So the table is checked against template.yaml in both directions, and the default is PRIVATE: an endpoint
nobody classified must not be reachable by everybody.
"""
import pathlib
import re
import unittest

from stripe_link.api_auth import (
    ASYMMETRIC,
    PRIVATE,
    PUBLIC,
    PUBLIC_ROUTES,
    bearer_token,
    caller_tenant,
    classify,
    unverified_claims,
    verified_claims,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")


def declared_routes() -> set[tuple[str, str]]:
    """Every (METHOD, path) the template actually exposes. `ANY` is expanded, because it is every verb."""
    routes = set()
    for path, method in re.findall(r"Path:\s*(\S+)\s*\n\s*Method:\s*(\w+)", TEMPLATE):
        verb = method.upper()
        if verb == "ANY":
            for real in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                routes.add((real, path))
        else:
            routes.add((verb, path))
    return routes


ROUTES = declared_routes()


class TableIsRealTests(unittest.TestCase):
    def test_the_template_parsed_at_all(self):
        self.assertGreater(len(ROUTES), 150, "the route scrape is broken; every assertion below is empty")

    def test_every_PUBLIC_route_exists_in_the_template(self):
        """A typo here is the dangerous direction: the route stays private, and checkout breaks the day
        enforcement lands. Catching it now costs nothing."""
        missing = sorted(f"{m} {p}" for m, p in PUBLIC_ROUTES if (m, p) not in ROUTES)
        self.assertEqual(missing, [], "public routes that no longer exist (or are misspelled):\n"
                                      + "\n".join(missing))

    def test_every_public_route_carries_a_REASON(self):
        """"Why is this reachable by anyone?" has to have an answer written next to it."""
        for key, reason in PUBLIC_ROUTES.items():
            self.assertTrue(str(reason).strip(), f"{key} is public with no reason given")

    def test_ASYMMETRIC_documents_exactly_the_paths_that_are_mixed(self):
        """Derived, not hand-maintained. A path that becomes mixed without being written down is the kind
        of hole a reviewer's eye slides straight past."""
        mixed = set()
        for path in {p for _, p in ROUTES}:
            methods = {m for m, p in ROUTES if p == path}
            public = {m for m, p in PUBLIC_ROUTES if p == path}
            if public and public != methods:
                mixed.add(path)
        self.assertEqual(mixed, set(ASYMMETRIC),
                         f"mixed paths: {sorted(mixed)}\ndocumented: {sorted(ASYMMETRIC)}")

    def test_the_documented_asymmetry_is_the_dangerous_way_round(self):
        # POST /leads public, GET /leads private -- not the reverse.
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/leads"}), PUBLIC)
        self.assertEqual(classify({"httpMethod": "GET", "resource": "/leads"}), PRIVATE)


class FailsClosedTests(unittest.TestCase):
    def test_an_unclassified_route_is_PRIVATE(self):
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/route/invented/today"}), PRIVATE)

    def test_a_classified_one_is_public(self):
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/webhook/stripe"}), PUBLIC)

    def test_the_method_matters_not_only_the_path(self):
        """POST /leads is a stranger submitting a form. GET /leads returns those strangers' addresses."""
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/leads"}), PUBLIC)
        self.assertEqual(classify({"httpMethod": "GET", "resource": "/leads"}), PRIVATE)

    def test_a_CORS_preflight_is_public_whatever_the_route(self):
        # It carries no credentials by definition; refusing it breaks the browser before the real request.
        self.assertEqual(classify({"httpMethod": "OPTIONS", "resource": "/stripe/keys"}), PUBLIC)

    def test_the_templated_resource_is_what_matches_not_the_live_path(self):
        """Matching on `path` would let /orders/anything miss the table entirely."""
        event = {"httpMethod": "GET", "resource": "/orders/{order_id}", "path": "/orders/order_abc"}
        self.assertEqual(classify(event), PRIVATE)


class TheDangerousRoutesAreProtectedTests(unittest.TestCase):
    """Named individually because these are the ones the TODO called out by blast radius."""

    def test_writing_a_tenants_STRIPE_KEYS_is_private(self):
        """Overwriting them points that tenant's checkout at somebody else's Stripe account."""
        for method in ("PUT", "GET"):
            self.assertEqual(classify({"httpMethod": method, "resource": "/stripe/keys"}), PRIVATE)

    def test_provisioning_a_tip_jar_is_private(self):
        """It claims a GLOBALLY UNIQUE platform subdomain that is never recycled by design."""
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/tip-jar"}), PRIVATE)

    def test_reading_customer_PII_is_private(self):
        for method, path in (("GET", "/customers"), ("GET", "/leads"),
                             ("GET", "/coupons/{coupon_id}/grants"), ("GET", "/orders")):
            self.assertEqual(classify({"httpMethod": method, "resource": path}), PRIVATE, path)

    def test_deleting_test_data_is_private(self):
        self.assertEqual(classify({"httpMethod": "POST", "resource": "/admin/delete-test-data"}), PRIVATE)


class ClaimsTests(unittest.TestCase):
    def test_the_bearer_token_is_read_case_insensitively(self):
        for header in ("Authorization", "authorization", "AUTHORIZATION"):
            self.assertEqual(bearer_token({"headers": {header: "Bearer abc"}}), "abc")

    def test_a_non_bearer_authorization_is_not_a_token(self):
        self.assertEqual(bearer_token({"headers": {"Authorization": "Basic abc"}}), "")

    def test_no_header_is_no_token(self):
        self.assertEqual(bearer_token({}), "")
        self.assertEqual(bearer_token({"headers": None}), "")

    def test_verified_claims_are_empty_until_an_authorizer_is_attached(self):
        """The only trustworthy identity in a Lambda is the one API Gateway already checked."""
        self.assertEqual(verified_claims({}), {})
        event = {"requestContext": {"authorizer": {"claims": {"sub": "u1"}}}}
        self.assertEqual(verified_claims(event)["sub"], "u1")

    def test_unverified_claims_decode_without_checking_anything(self):
        import base64, json
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "u1"}).encode()).decode().rstrip("=")
        token = f"header.{payload}.signature"
        self.assertEqual(unverified_claims({"headers": {"Authorization": f"Bearer {token}"}})["sub"], "u1")

    def test_a_malformed_token_is_a_measurement_not_a_crash(self):
        for bad in ("", "nonsense", "a.b", "a.!!!.c"):
            self.assertEqual(unverified_claims({"headers": {"Authorization": f"Bearer {bad}"}}), {})

    def test_the_tenant_comes_from_the_custom_claim_when_there_is_one(self):
        self.assertEqual(caller_tenant({"custom:client_id": "t1", "sub": "u9"}), "t1")

    def test_and_falls_back_to_sub_which_is_what_an_ACCESS_token_carries(self):
        # Measured 2026-09-25: every user_profile in dev and prod has user_id == tenant_id.
        self.assertEqual(caller_tenant({"sub": "u9"}), "u9")

    def test_no_claims_is_no_tenant_rather_than_a_guess(self):
        self.assertEqual(caller_tenant({}), "")
        self.assertEqual(caller_tenant(None), "")


if __name__ == "__main__":
    unittest.main()
