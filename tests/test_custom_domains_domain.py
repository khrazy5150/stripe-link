import io
import json
import unittest
from urllib.error import HTTPError

from stripe_link.domain.custom_domains import (
    CustomDomainError,
    assert_valid_domain,
    build_domain,
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

    def test_assert_valid_domain_accepts_subdomain(self):
        assert_valid_domain("shop.example.com")


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
    def test_pending_dns_when_not_verified(self):
        status, ssl_status = derive_status(dns_verified=False, cloudflare_hostname={"ssl": {"status": "pending_validation"}})
        self.assertEqual(status, "pending_dns")
        self.assertEqual(ssl_status, "pending_validation")

    def test_pending_ssl_when_dns_verified_but_ssl_not_active(self):
        status, _ = derive_status(dns_verified=True, cloudflare_hostname={"ssl": {"status": "pending_issuance"}, "status": "pending"})
        self.assertEqual(status, "pending_ssl")

    def test_active_when_dns_verified_and_ssl_active(self):
        status, _ = derive_status(dns_verified=True, cloudflare_hostname={"ssl": {"status": "active"}, "status": "active"})
        self.assertEqual(status, "active")

    def test_failed_when_ssl_status_expired(self):
        status, _ = derive_status(dns_verified=True, cloudflare_hostname={"ssl": {"status": "validation_timed_out"}, "status": "pending"})
        self.assertEqual(status, "failed")

    def test_failed_when_hostname_moved_or_deleted(self):
        status, _ = derive_status(dns_verified=True, cloudflare_hostname={"ssl": {"status": "active"}, "status": "moved"})
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
