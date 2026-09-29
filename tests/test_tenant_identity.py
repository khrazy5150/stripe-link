"""Authoritative tenant resolution, and the marker that says when it can be trusted.

The gap this addresses is not that capability checks are wrong — it is that they rest on a tenant_id the
REQUEST supplies. `tenant_id from request → capability → quota` is not authorization, however correct each
step is (author, 2026-09-29). So two things exist before the authorizer does: a resolution path that prefers
a verified identity, and a marker recording every capability GRANTED without one.

Neither changes behaviour today. Both are how Phase 2 becomes attaching an authorizer and deleting a fallback
rather than re-deriving the tenant across 63 handlers.
"""
import io
import json
import unittest
from contextlib import redirect_stdout

from stripe_link.api_auth import note_capability_decision, resolved_tenant, verified_claims
from stripe_link.common import tenant_id_from_event


def authorized_event(tenant, **extra):
    """What API Gateway writes AFTER an authorizer has verified signature and expiry."""
    return {"requestContext": {"authorizer": {"claims": {"custom:client_id": tenant}}}, **extra}


class VerifiedClaimsTests(unittest.TestCase):
    def test_no_authorizer_means_no_claims(self):
        # True of every request today, which is the point of measuring rather than assuming.
        self.assertEqual(verified_claims({}), {})
        self.assertEqual(verified_claims({"requestContext": {}}), {})

    def test_a_bearer_header_alone_is_NOT_verified(self):
        # The decisive distinction. A token in a header has been checked by nobody; only an authorizer
        # writes requestContext.authorizer.claims, and only after verifying the signature.
        event = {"headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x"}}
        self.assertEqual(verified_claims(event), {})
        self.assertEqual(resolved_tenant(event), ("", False))

    def test_a_malformed_authorizer_block_does_not_raise(self):
        for bad in ({"authorizer": None}, {"authorizer": {"claims": "nope"}}, {"authorizer": []}):
            with self.subTest(bad=bad):
                self.assertEqual(verified_claims({"requestContext": bad}), {})


class ResolvedTenantTests(unittest.TestCase):
    def test_a_verified_identity_is_authoritative(self):
        self.assertEqual(resolved_tenant(authorized_event("t_verified")), ("t_verified", True))

    def test_nothing_verified_is_not_authoritative(self):
        self.assertEqual(resolved_tenant({}), ("", False))


class TenantResolutionOrderTests(unittest.TestCase):
    def test_the_request_still_supplies_the_tenant_today(self):
        # Unchanged behaviour, deliberately: no authorizer exists, so the fallback is the only path.
        with redirect_stdout(io.StringIO()):
            self.assertEqual(tenant_id_from_event({}, {"tenant_id": "t_claimed"}), "t_claimed")

    def test_a_VERIFIED_identity_wins_over_the_body(self):
        # The forged-tenant case, and the reason resolution is written before enforcement: once claims are
        # present, what the body asked for stops mattering.
        event = authorized_event("t_verified")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(tenant_id_from_event(event, {"tenant_id": "t_someone_else"}), "t_verified")

    def test_the_log_records_whether_the_tenant_was_PROVEN(self):
        out = io.StringIO()
        with redirect_stdout(out):
            tenant_id_from_event({"resource": "/orders", "httpMethod": "GET"}, {"tenant_id": "t1"})
        records = [json.loads(line)["api_auth"] for line in out.getvalue().splitlines() if line.strip()]
        self.assertTrue(records, "the phase-1 measurement must still fire")
        self.assertFalse(records[0]["authoritative"])


class CapabilityMarkerTests(unittest.TestCase):
    def _record(self, event, **kwargs):
        out = io.StringIO()
        with redirect_stdout(out):
            note_capability_decision(event, **kwargs)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        return json.loads(lines[0])["capability_gate"] if lines else None

    def test_a_grant_on_an_unproven_identity_is_recorded(self):
        # THE event that matters: a plan-gated feature handed to a caller nobody verified.
        record = self._record({"resource": "/ai/generate"},
                              capability="ai_builder", tenant_id="t1", granted=True)
        self.assertEqual(record["capability"], "ai_builder")
        self.assertFalse(record["authoritative"])
        self.assertFalse(record["enforced"])

    def test_a_refusal_is_not_recorded(self):
        # Harmless: the caller was told no, and a forged tenant_id gains nothing by being refused more
        # precisely. Logging refusals would bury the grants that matter.
        self.assertIsNone(self._record({}, capability="ai_builder", tenant_id="t1", granted=False))

    def test_a_grant_on_a_VERIFIED_identity_is_not_recorded(self):
        # Nothing to report once the identity is proven — that is the state this marker exists to reach.
        self.assertIsNone(
            self._record(authorized_event("t1"), capability="ai_builder", tenant_id="t1", granted=True))

    def test_the_marker_can_never_fail_a_request(self):
        # Non-empty on purpose: an EMPTY dict is falsy, so `event or {}` would swap it out and the hostile
        # get would never run — the first version of this test proved nothing.
        class Hostile(dict):
            def get(self, *a, **k):
                raise RuntimeError("boom")

        hostile = Hostile(resource="/ai/generate")
        self.assertTrue(hostile, "must be truthy or the guard never sees it")
        self.assertIsNone(self._record(hostile, capability="ai_builder", tenant_id="t", granted=True))


if __name__ == "__main__":
    unittest.main()
