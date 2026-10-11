"""On a private route, who you are comes from the token — not from the request.

The last piece of `plans/API_AUTHENTICATION.md` Phase 2, and smaller than the plan implies, because
attaching the authorizer did it. `resolved_tenant` returns the VERIFIED tenant first, so once claims
arrive the request body stops being consulted on a private route without anything being deleted. An
authenticated caller naming a different tenant is simply ignored.

**A further refusal was tried and removed, and the reason is worth keeping.** The idea was to return
nothing when a private API route arrived with unreadable claims. It guards a case the authorizer already
makes impossible — every private route sits behind `DefaultAuthorizer`, verified on dev and prod as 401
without a token — and it cost 385 tests, because this suite expresses a request as an event with a body
`tenant_id` and no claims. A control that cannot fire, bought at that price, is negative value. The alarm
it would have raised already exists and is cheaper: `enforced: true, authoritative: false` on a log line
means "a private route resolved its tenant from the request", and nothing else produces that pair.

What this file pins is the property that does the work: **the token wins.**
"""
import io
import json
import unittest
from contextlib import redirect_stdout

from stripe_link.common import tenant_id_from_event


def api(method, resource, **extra):
    event = {"httpMethod": method, "resource": resource}
    event.update(extra)
    return event


def claims(**values):
    return {"authorizer": {"claims": values}}


class TheTokenDecides(unittest.TestCase):
    """Each of the five sources the request could supply, beaten by the verified one."""

    def test_verified_claims_beat_a_forged_query_parameter(self):
        event = api("GET", "/orders", requestContext=claims(sub="t_real"),
                    queryStringParameters={"tenant_id": "t_forged"})
        self.assertEqual(tenant_id_from_event(event), "t_real")

    def test_verified_claims_beat_the_alternate_query_spelling(self):
        event = api("GET", "/orders", requestContext=claims(sub="t_real"),
                    queryStringParameters={"tenantID": "t_forged"})
        self.assertEqual(tenant_id_from_event(event), "t_real")

    def test_verified_claims_beat_a_forged_body(self):
        event = api("POST", "/orders", requestContext=claims(sub="t_real"))
        self.assertEqual(tenant_id_from_event(event, {"tenant_id": "t_forged"}), "t_real")

    def test_verified_claims_beat_a_forged_tenant_header(self):
        event = api("GET", "/orders", requestContext=claims(sub="t_real"),
                    headers={"X-Tenant-Id": "t_forged"})
        self.assertEqual(tenant_id_from_event(event), "t_real")

    def test_verified_claims_beat_a_forged_client_header(self):
        event = api("GET", "/orders", requestContext=claims(sub="t_real"),
                    headers={"X-Client-Id": "t_forged"})
        self.assertEqual(tenant_id_from_event(event), "t_real")

    def test_the_authoritative_claim_outranks_sub(self):
        """`custom:client_id` only rides an ID token, which is why the dashboard sends one. `sub` is
        correct today only because every user owns their tenant — a property of the data, not the
        schema, and the one `caller_tenant` is written to make replaceable."""
        event = api("GET", "/orders", requestContext=claims(sub="u_1", **{"custom:client_id": "t_real"}))
        self.assertEqual(tenant_id_from_event(event), "t_real")


class ThePublicPathIsUntouched(unittest.TestCase):
    """The expensive failure is the other direction: a buyer mid-checkout. A buyer carries no token by
    design, and there is nobody to ask who they are."""

    def test_a_buyer_checkout_still_names_its_tenant(self):
        self.assertEqual(tenant_id_from_event(api("POST", "/checkout"), {"tenant_id": "t_shop"}), "t_shop")

    def test_the_shipping_quote_island_still_works(self):
        event = api("GET", "/shipping-quote", queryStringParameters={"tenant_id": "t_shop"})
        self.assertEqual(tenant_id_from_event(event), "t_shop")


class InternalInvocationsAreUntouched(unittest.TestCase):
    """Delivered Lambda-to-Lambda with no `requestContext` and no `httpMethod`."""

    def test_a_synthetic_payload_still_resolves_its_tenant(self):
        self.assertEqual(tenant_id_from_event({"internal_sync": True}, {"tenant_id": "t_1"}), "t_1")

    def test_a_queued_job_still_resolves_its_tenant(self):
        self.assertEqual(tenant_id_from_event({"internal_job": True, "job_id": "j"},
                                              {"tenant_id": "t_1"}), "t_1")


class TheLogSaysWhatActuallyHappened(unittest.TestCase):
    """`enforced` was hardcoded False while Phase 1 only measured. Once the authorizer landed it became a
    field stating the opposite of what happened, in the log a reader consults to find out whether it did.

    It is also the alarm that replaced the refusal: `enforced: true` with `authoritative: false` means a
    private route resolved its tenant from the request, which should now be impossible."""

    def _line(self, event, body=None):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            tenant_id_from_event(event, body)
        lines = [json.loads(l)["api_auth"] for l in buffer.getvalue().splitlines() if "api_auth" in l]
        return lines[0] if lines else None

    def test_a_private_route_with_claims_reports_both_true(self):
        line = self._line(api("GET", "/orders", requestContext=claims(sub="t1")))
        self.assertEqual((line["enforced"], line["authoritative"]), (True, True))

    def test_the_alarm_pair_is_reachable_and_is_what_it_claims(self):
        """If this ever appears in production it means the authorizer let something through unverified."""
        line = self._line(api("GET", "/orders", queryStringParameters={"tenant_id": "t_x"}))
        self.assertEqual((line["enforced"], line["authoritative"]), (True, False))
        self.assertEqual(line["claimed_tenant"], "t_x")

    def test_public_routes_are_not_measured(self):
        """The line exists to answer "is enforcement safe on private routes?". A buyer without a token is
        the design, not a finding, and logging it would bury the pair above in noise."""
        self.assertIsNone(self._line(api("POST", "/checkout"), {"tenant_id": "t_shop"}))


if __name__ == "__main__":
    unittest.main()
