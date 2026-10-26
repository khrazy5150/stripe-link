"""Creating and running a tenant's DNS zone on our account (plans/MANAGED_DNS.md P2).

Every call here goes through an injected `opener`, which is not a convenience: the live token cannot
create zones at all (probed 2026-10-25 — `com.cloudflare.api.account.zone.create` is missing), so fakes
are the only way this code runs until a token exists. It should be correct before it is reachable.
"""

import io
import json
import unittest
from urllib.error import HTTPError

from stripe_link.domain.cloudflare_zones import (
    cloudflare_account_request,
    create_dns_record,
    create_worker_route,
    create_zone,
    delete_zone,
    get_zone,
    list_zone_dns_records,
    worker_route_patterns,
)
from stripe_link.domain.custom_domains import CustomDomainError


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Keys on (method, FULL url) including the query string, and accepts a list to return in order —
    both needed for paging, where the same path is asked twice with different `page` values."""

    def __init__(self, responses):
        self.responses = {k: (list(v) if isinstance(v, list) else v) for k, v in responses.items()}
        self.calls = []

    def __call__(self, request, timeout=20):
        key = (request.get_method(), request.full_url)
        self.calls.append((key[0], key[1], json.loads(request.data.decode()) if request.data else None))
        entry = self.responses.get(key)
        if entry is None:
            raise AssertionError(f"Unexpected request {key}")
        if isinstance(entry, list):
            entry = entry.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return FakeResponse(entry)


def ok(result):
    return {"success": True, "errors": [], "result": result}


BASE = "https://api.cloudflare.com/client/v4"


class CreateZoneTests(unittest.TestCase):
    def test_it_asks_for_a_full_setup_with_the_import_scan_on(self):
        opener = FakeOpener({("POST", f"{BASE}/zones"): ok({"id": "z1", "status": "pending"})})
        zone = create_zone("Example.COM.", account_id="acct1", api_token="tok", opener=opener)
        self.assertEqual(zone["id"], "z1")
        _, _, body = opener.calls[0]
        self.assertEqual(body["name"], "example.com")            # normalised before it is sent
        self.assertEqual(body["account"], {"id": "acct1"})
        # full = Cloudflare becomes authoritative, which is what lets the apex be a proxied record.
        self.assertEqual(body["type"], "full")
        # The import scan. Not the authority -- managed_dns.review() compares it against live DNS -- but
        # without it the tenant would re-enter their whole zone by hand.
        self.assertTrue(body["jump_start"])

    def test_a_domain_that_is_not_one_never_reaches_cloudflare(self):
        opener = FakeOpener({})
        for bad in ("", "   ", "localhost"):
            with self.assertRaises(CustomDomainError):
                create_zone(bad, account_id="a", api_token="t", opener=opener)
        self.assertEqual(opener.calls, [])

    def test_cloudflares_refusal_is_surfaced_in_its_own_words(self):
        # The one that actually happens today, and a paraphrase would send someone looking in the wrong
        # place: it is a token scope, not a domain problem.
        body = json.dumps({"success": False, "errors": [
            {"code": 0, "message": 'Requires permission "com.cloudflare.api.account.zone.create" '
                                   "to create zones for the selected account"}]}).encode()
        opener = FakeOpener({("POST", f"{BASE}/zones"):
                             HTTPError(f"{BASE}/zones", 403, "Forbidden", {}, io.BytesIO(body))})
        with self.assertRaises(CustomDomainError) as caught:
            create_zone("example.com", account_id="a", api_token="t", opener=opener)
        self.assertIn("com.cloudflare.api.account.zone.create", caught.exception.message)
        self.assertEqual(caught.exception.status_code, 403)


class RecordListingTests(unittest.TestCase):
    def test_it_reads_every_page(self):
        """Cloudflare returns 100 per page. A zone with several MX, SPF, DMARC, a DKIM key per selector
        and whatever the old host left behind can pass that — and a truncated list is indistinguishable
        from a complete one at exactly the moment that decides whether someone keeps receiving email."""
        first = [{"type": "A", "name": f"h{i}.example.com", "content": "203.0.113.1"} for i in range(100)]
        second = [{"type": "MX", "name": "example.com", "content": "aspmx.l.google.com", "priority": 1}]
        opener = FakeOpener({
            ("GET", f"{BASE}/zones/z1/dns_records?per_page=100&page=1"): ok(first),
            ("GET", f"{BASE}/zones/z1/dns_records?per_page=100&page=2"): ok(second),
        })
        records = list_zone_dns_records("z1", api_token="tok", opener=opener)
        self.assertEqual(len(records), 101)
        self.assertEqual(records[-1]["type"], "MX")
        self.assertEqual(len(opener.calls), 2)

    def test_a_short_page_ends_the_walk(self):
        opener = FakeOpener({("GET", f"{BASE}/zones/z1/dns_records?per_page=100&page=1"): ok([{"type": "A"}])})
        self.assertEqual(len(list_zone_dns_records("z1", api_token="tok", opener=opener)), 1)
        self.assertEqual(len(opener.calls), 1)

    def test_an_empty_zone_reads_as_empty_not_as_an_error(self):
        opener = FakeOpener({("GET", f"{BASE}/zones/z1/dns_records?per_page=100&page=1"): ok([])})
        self.assertEqual(list_zone_dns_records("z1", api_token="tok", opener=opener), [])


class WorkerRouteTests(unittest.TestCase):
    def test_both_patterns_are_needed_because_the_wildcard_misses_the_apex(self):
        """`*.example.com/*` does not match `example.com/*` — the wildcard needs a label to stand for.
        One pattern leaves the apex falling through to the placeholder origin, which routes nowhere: a
        dead root domain and a working www on the same zone, which reads as a DNS problem and is not."""
        self.assertEqual(worker_route_patterns("Example.com."), ["example.com/*", "*.example.com/*"])

    def test_nonsense_produces_no_patterns(self):
        self.assertEqual(worker_route_patterns(""), [])
        self.assertEqual(worker_route_patterns("localhost"), [])

    def test_the_route_is_bound_to_the_named_script(self):
        opener = FakeOpener({("POST", f"{BASE}/zones/z1/workers/routes"): ok({"id": "r1"})})
        create_worker_route("z1", "example.com/*", "jb-custom-domain-router-dev",
                            api_token="tok", opener=opener)
        _, _, body = opener.calls[0]
        self.assertEqual(body, {"pattern": "example.com/*", "script": "jb-custom-domain-router-dev"})


class ZoneLifecycleTests(unittest.TestCase):
    def test_status_is_read_from_cloudflare_rather_than_inferred(self):
        opener = FakeOpener({("GET", f"{BASE}/zones/z1"): ok({"id": "z1", "status": "active"})})
        self.assertEqual(get_zone("z1", api_token="tok", opener=opener)["status"], "active")

    def test_delete_is_a_single_explicit_call(self):
        # Reachable only when a tenant asks to leave. Disconnecting a Site must never arrive here: that
        # removes a claim on a hostname, this removes authority over a whole domain, mail included.
        opener = FakeOpener({("DELETE", f"{BASE}/zones/z1"): ok({"id": "z1"})})
        delete_zone("z1", api_token="tok", opener=opener)
        self.assertEqual([(m, u) for m, u, _ in opener.calls], [("DELETE", f"{BASE}/zones/z1")])

    def test_serving_records_are_posted_as_given(self):
        opener = FakeOpener({("POST", f"{BASE}/zones/z1/dns_records"): ok({"id": "d1"})})
        create_dns_record("z1", {"type": "A", "name": "example.com", "content": "192.0.2.1",
                                 "proxied": True}, api_token="tok", opener=opener)
        self.assertTrue(opener.calls[0][2]["proxied"])


class ErrorContractTests(unittest.TestCase):
    def test_a_success_false_body_raises_rather_than_returning_empty(self):
        opener = FakeOpener({("GET", f"{BASE}/zones/z1"):
                             {"success": False, "errors": [{"message": "Zone not found"}]}})
        with self.assertRaises(CustomDomainError) as caught:
            get_zone("z1", api_token="tok", opener=opener)
        self.assertIn("Zone not found", caught.exception.message)

    def test_a_non_json_error_body_still_raises_cleanly(self):
        opener = FakeOpener({("GET", f"{BASE}/zones/z1"):
                             HTTPError(f"{BASE}/zones/z1", 502, "Bad Gateway", {}, io.BytesIO(b"<html>"))})
        with self.assertRaises(CustomDomainError) as caught:
            get_zone("z1", api_token="tok", opener=opener)
        self.assertEqual(caught.exception.status_code, 502)

    def test_it_raises_the_same_type_the_zone_scoped_helper_does(self):
        # One exception for one API. A second type would grow a second except clause at every call site
        # that does exactly the same thing.
        opener = FakeOpener({("GET", f"{BASE}/zones/z1"): {"success": False, "errors": []}})
        with self.assertRaises(CustomDomainError):
            cloudflare_account_request("GET", "/zones/z1", api_token="tok", opener=opener)


if __name__ == "__main__":
    unittest.main()
