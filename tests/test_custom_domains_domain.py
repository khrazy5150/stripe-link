import io
import json
import unittest
from urllib.error import HTTPError

from stripe_link.domain.custom_domains import (
    CustomDomainError,
    assert_valid_domain,
    build_domain,
    custom_hostname_dns_records,
    domain_index_record,
    is_apex_domain,
    normalize_route_path,
    route_table,
    cloudflare_request,
    create_custom_hostname,
    delete_custom_hostname,
    derive_status,
    dns_record_matches,
    get_custom_hostname,
    normalize_domain,
    validation_record_from_hostname,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def __call__(self, request, timeout=20):
        self.requests.append(request)
        key = (request.get_method(), request.full_url.split("?")[0])
        entry = self.responses.get(key)
        if entry is None:
            raise AssertionError(f"Unexpected request {key}")
        if isinstance(entry, Exception):
            raise entry
        return FakeResponse(entry)


def http_error(status, payload):
    body = json.dumps(payload).encode("utf-8")
    return HTTPError("https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames", status, "error", {}, io.BytesIO(body))


class NormalizeAndValidateTests(unittest.TestCase):
    def test_normalize_strips_scheme_path_and_trailing_dot(self):
        self.assertEqual(normalize_domain("HTTPS://Shop.Example.com/some/path"), "shop.example.com")
        self.assertEqual(normalize_domain("shop.example.com."), "shop.example.com")
        self.assertEqual(normalize_domain("  shop.example.com  "), "shop.example.com")

    def test_build_domain_combines_apex_and_label(self):
        self.assertEqual(build_domain("Example.com", "Shop"), "shop.example.com")

    def test_build_domain_requires_both_parts(self):
        with self.assertRaises(CustomDomainError):
            build_domain("", "shop")
        with self.assertRaises(CustomDomainError):
            build_domain("example.com", "")

    def test_assert_valid_domain_rejects_bare_domain(self):
        with self.assertRaises(CustomDomainError):
            assert_valid_domain("example")

    def test_assert_valid_domain_accepts_apex(self):
        # Apex is supported (2.6b) via ALIAS/flattening or apex proxying — no longer rejected.
        for apex in ("example.com", "automizepro.com", "example.co.uk"):
            assert_valid_domain(apex)

    def test_assert_valid_domain_accepts_subdomain(self):
        assert_valid_domain("shop.example.com")


class ApexDnsRecordTests(unittest.TestCase):
    def test_is_apex_domain(self):
        self.assertTrue(is_apex_domain("example.com"))
        self.assertTrue(is_apex_domain("example.co.uk"))
        self.assertFalse(is_apex_domain("shop.example.com"))
        self.assertFalse(is_apex_domain("www.example.co.uk"))

    def test_subdomain_uses_a_routing_cname(self):
        records = custom_hostname_dns_records({}, hostname="shop.example.com", dns_target="domains.jbay.uk", dcv_delegation_uuid="u1")
        self.assertEqual(records[0], {"type": "CNAME", "name": "shop.example.com", "value": "domains.jbay.uk"})
        self.assertEqual(records[1]["name"], "_acme-challenge.shop.example.com")  # DCV delegation

    def test_apex_default_uses_alias_flattening(self):
        records = custom_hostname_dns_records({}, hostname="example.com", dns_target="domains.jbay.uk", dcv_delegation_uuid="u1")
        routing = records[0]
        self.assertEqual(routing["type"], "ALIAS")
        self.assertEqual(routing["value"], "domains.jbay.uk")
        self.assertEqual(routing["apex"], "true")
        self.assertIn("ALIAS", routing["note"])
        self.assertEqual(records[1]["name"], "_acme-challenge.example.com")  # DCV still a subdomain CNAME

    def test_apex_with_proxy_ips_uses_a_and_aaaa(self):
        records = custom_hostname_dns_records(
            {}, hostname="example.com", dns_target="domains.jbay.uk", dcv_delegation_uuid="u1",
            apex_ipv4=("192.0.2.1", "192.0.2.2"), apex_ipv6=("2606:4700::1",))
        types = [(r["type"], r["value"]) for r in records if r.get("apex")]
        self.assertIn(("A", "192.0.2.1"), types)
        self.assertIn(("A", "192.0.2.2"), types)
        self.assertIn(("AAAA", "2606:4700::1"), types)
        self.assertTrue(any(r["name"] == "_acme-challenge.example.com" for r in records))
        assert_valid_domain("www.automizepro.com")
        assert_valid_domain("shop.example.co.uk")   # subdomain under a multi-part TLD


class CloudflareRequestTests(unittest.TestCase):
    def test_create_custom_hostname_returns_result(self):
        opener = FakeOpener({
            ("POST", "https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames"): {
                "success": True,
                "result": {"id": "ch_123", "hostname": "shop.example.com"},
            },
        })
        result = create_custom_hostname("shop.example.com", zone_id="z1", api_token="tok", opener=opener)
        self.assertEqual(result["id"], "ch_123")
        request = opener.requests[0]
        self.assertEqual(request.headers.get("Authorization"), "Bearer tok")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body, {"hostname": "shop.example.com", "ssl": {"method": "txt", "type": "dv"}})

    def test_get_custom_hostname_returns_result(self):
        opener = FakeOpener({
            ("GET", "https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames/ch_123"): {
                "success": True,
                "result": {"id": "ch_123", "status": "active"},
            },
        })
        result = get_custom_hostname("ch_123", zone_id="z1", api_token="tok", opener=opener)
        self.assertEqual(result["status"], "active")

    def test_delete_custom_hostname_returns_result(self):
        opener = FakeOpener({
            ("DELETE", "https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames/ch_123"): {
                "success": True,
                "result": {"id": "ch_123"},
            },
        })
        result = delete_custom_hostname("ch_123", zone_id="z1", api_token="tok", opener=opener)
        self.assertEqual(result["id"], "ch_123")

    def test_raises_custom_domain_error_on_success_false(self):
        opener = FakeOpener({
            ("POST", "https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames"): {
                "success": False,
                "errors": [{"message": "hostname already exists"}],
            },
        })
        with self.assertRaisesRegex(CustomDomainError, "already exists"):
            create_custom_hostname("shop.example.com", zone_id="z1", api_token="tok", opener=opener)

    def test_raises_custom_domain_error_on_http_error(self):
        opener = FakeOpener({
            ("POST", "https://api.cloudflare.com/client/v4/zones/z1/custom_hostnames"):
                http_error(400, {"errors": [{"message": "invalid hostname"}]}),
        })
        with self.assertRaisesRegex(CustomDomainError, "invalid hostname"):
            create_custom_hostname("shop.example.com", zone_id="z1", api_token="tok", opener=opener)

    def test_cloudflare_request_raises_for_unexpected_request(self):
        opener = FakeOpener({})
        with self.assertRaises(AssertionError):
            cloudflare_request("GET", "/custom_hostnames/nope", zone_id="z1", api_token="tok", opener=opener)


class ValidationRecordTests(unittest.TestCase):
    def test_extracts_ownership_verification_txt_record(self):
        record = validation_record_from_hostname({
            "ownership_verification": {"type": "txt", "name": "_cf-custom-hostname.shop.example.com", "value": "abc123"},
        })
        self.assertEqual(record, {"type": "TXT", "name": "_cf-custom-hostname.shop.example.com", "value": "abc123"})

    def test_missing_ownership_verification_returns_empty_fields(self):
        record = validation_record_from_hostname({})
        self.assertEqual(record, {"type": "TXT", "name": "", "value": ""})


class DnsRecordMatchesTests(unittest.TestCase):
    def opener_for(self, answer_value):
        def opener(request, timeout=10):
            payload = {"Answer": [{"data": answer_value}]} if answer_value is not None else {}
            return FakeResponse(payload)
        return opener

    def test_matches_when_answer_value_equals_expected(self):
        self.assertTrue(dns_record_matches("_cf.shop.example.com", "TXT", "abc123", opener=self.opener_for('"abc123"')))

    def test_does_not_match_different_value(self):
        self.assertFalse(dns_record_matches("_cf.shop.example.com", "TXT", "abc123", opener=self.opener_for('"different"')))

    def test_no_answer_returns_false(self):
        self.assertFalse(dns_record_matches("_cf.shop.example.com", "TXT", "abc123", opener=self.opener_for(None)))

    def test_request_failure_returns_false(self):
        def failing_opener(request, timeout=10):
            raise OSError("network down")
        self.assertFalse(dns_record_matches("_cf.shop.example.com", "TXT", "abc123", opener=failing_opener))

    def test_missing_name_or_value_returns_false_without_request(self):
        self.assertFalse(dns_record_matches("", "TXT", "abc123", opener=self.opener_for("abc123")))
        self.assertFalse(dns_record_matches("_cf.shop.example.com", "TXT", "", opener=self.opener_for("abc123")))


class DeriveStatusTests(unittest.TestCase):
    def test_pending_dns_when_hostname_not_active(self):
        # Routing CNAME not yet seen by Cloudflare (hostname status not active).
        status, ssl_status = derive_status(cloudflare_hostname={"ssl": {"status": "pending_validation"}})
        self.assertEqual(status, "pending_dns")
        self.assertEqual(ssl_status, "pending_validation")

    def test_pending_ssl_when_hostname_active_but_cert_not(self):
        # The real-world state: routing works, cert still issuing (needs the _acme-challenge DCV record).
        status, _ = derive_status(cloudflare_hostname={"ssl": {"status": "pending_validation"}, "status": "active"})
        self.assertEqual(status, "pending_ssl")

    def test_active_when_hostname_and_ssl_active(self):
        status, _ = derive_status(cloudflare_hostname={"ssl": {"status": "active"}, "status": "active"})
        self.assertEqual(status, "active")

    def test_failed_when_ssl_status_expired(self):
        status, _ = derive_status(cloudflare_hostname={"ssl": {"status": "validation_timed_out"}, "status": "pending"})
        self.assertEqual(status, "failed")

    def test_failed_when_hostname_moved_or_deleted(self):
        status, _ = derive_status(cloudflare_hostname={"ssl": {"status": "active"}, "status": "moved"})
        self.assertEqual(status, "failed")


class RouteTableTests(unittest.TestCase):
    def test_normalize_route_path_folds_to_canonical_slug(self):
        self.assertEqual(normalize_route_path(""), "/")
        self.assertEqual(normalize_route_path("/"), "/")
        self.assertEqual(normalize_route_path("/Upsell-1/"), "/upsell-1")
        self.assertEqual(normalize_route_path("thank-you"), "/thank-you")
        self.assertEqual(normalize_route_path("  /A/B/  "), "/a/b")

    def test_route_table_projects_enabled_flag_and_skips_empty(self):
        site = {"pages": {
            "/": {"page_id": "page_home", "page_type": "landing"},
            "/upsell-1": {"page_id": "page_up", "enabled": True},
            "/retired": {"page_id": "page_old", "enabled": False},
            "/broken": {"page_type": "landing"},  # no page_id -> skipped
        }}
        table = route_table(site)
        self.assertEqual(table["/"], {"page_id": "page_home", "enabled": True})
        self.assertEqual(table["/upsell-1"], {"page_id": "page_up", "enabled": True})
        self.assertEqual(table["/retired"], {"page_id": "page_old", "enabled": False})
        self.assertNotIn("/broken", table)

    def test_route_table_carries_price_context_for_sale_slugs(self):
        # The resolver serves /sale //flash-sale from the sibling artifact by reading price_context off the
        # denormalized index — so the projection MUST carry it (was dropped, breaking context views on domains).
        site = {"pages": {
            "/": {"page_id": "page_home"},
            "/sale": {"page_id": "page_home", "price_context": "sale", "enabled": True},
            "/flash-sale": {"page_id": "page_home", "price_context": "flash_sale", "enabled": True},
        }}
        table = route_table(site)
        self.assertEqual(table["/sale"], {"page_id": "page_home", "enabled": True, "price_context": "sale"})
        self.assertEqual(table["/flash-sale"]["price_context"], "flash_sale")
        self.assertNotIn("price_context", table["/"])  # only carried when present

    def test_route_table_empty_when_no_pages(self):
        self.assertEqual(route_table({}), {})

    def test_domain_index_record_projects_site(self):
        site = {
            "tenant_id": "t1", "site_id": "site_1",
            "hosting": {"custom_domain": "shop.example.com"},
            "domain_provisioning": {"status": "active"},
            "pages": {"/": {"page_id": "page_home"}, "/upsell-1": {"page_id": "page_up", "enabled": True}},
        }
        record = domain_index_record(site)
        self.assertEqual(record["tenant_id"], "t1")
        self.assertEqual(record["site_id"], "site_1")
        self.assertEqual(record["domain"], "shop.example.com")
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["target_page_id"], "page_home")
        self.assertEqual(record["routes"]["/upsell-1"], {"page_id": "page_up", "enabled": True})


if __name__ == "__main__":
    unittest.main()
