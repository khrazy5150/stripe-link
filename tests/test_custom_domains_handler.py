import json
import unittest

from handlers.custom_domains import handler
from tests.fakes import FakeDocumentRepository, FakeSimpleRepository


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
        return FakeResponse(entry)


CLOUDFLARE_BASE = "https://api.cloudflare.com/client/v4/zones/zone_1/custom_hostnames"


def cloudflare_create_response(hostname_id="ch_1", ssl_status="pending_validation", hostname_status="pending"):
    return {
        "success": True,
        "result": {
            "id": hostname_id,
            "hostname": "shop.example.com",
            "ssl": {"status": ssl_status},
            "status": hostname_status,
            "ownership_verification": {
                "type": "txt",
                "name": "_cf-custom-hostname.shop.example.com",
                "value": "verify-me-123",
            },
        },
    }


def cloudflare_get_response(hostname_id="ch_1", ssl_status="pending_validation", hostname_status="pending"):
    return {
        "success": True,
        "result": cloudflare_create_response(hostname_id, ssl_status, hostname_status)["result"],
    }


def dns_answer(value):
    return {"Answer": [{"data": f'"{value}"'}]}


def dns_no_answer():
    return {}


class CustomDomainsHandlerTests(unittest.TestCase):
    def setUp(self):
        self.config_repo = FakeSimpleRepository("tenant_id")
        self.index_repo = FakeDocumentRepository("domain")

    def call(self, event, opener_responses):
        opener = FakeOpener(opener_responses)
        response = handler(
            event,
            None,
            config_repo=self.config_repo,
            index_repo=self.index_repo,
            zone_id="zone_1",
            api_token="tok",
            opener=opener,
        )
        return response, opener

    def test_create_domain_stores_pending_entry_and_index(self):
        event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({
                "apex_domain": "example.com",
                "subdomain_label": "shop",
                "target_page_id": "page_1",
            }),
        }
        response, opener = self.call(event, {
            ("POST", CLOUDFLARE_BASE): cloudflare_create_response(),
        })

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        self.assertEqual(body["domain"]["domain"], "shop.example.com")
        self.assertEqual(body["domain"]["status"], "pending_dns")
        self.assertEqual(body["domain"]["cloudflare_hostname_id"], "ch_1")

        stored_config = self.config_repo.get("tenant_demo")
        self.assertEqual(len(stored_config["custom_domains"]["domains"]), 1)

        index_record = self.index_repo.get("tenant_demo", "shop.example.com")
        self.assertEqual(index_record["status"], "pending_dns")
        self.assertEqual(index_record["target_page_id"], "page_1")

    def test_create_domain_rejects_duplicate(self):
        event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "shop.example.com", "target_page_id": "page_1"}),
        }
        self.call(event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})
        response, _ = self.call(event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})

        self.assertEqual(response["statusCode"], 409)

    def test_create_domain_rejects_bare_apex_domain(self):
        event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "example", "target_page_id": "page_1"}),
        }
        response, opener = self.call(event, {})

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(opener.requests, [])

    def test_list_domains_returns_dns_target_and_domains(self):
        create_event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "shop.example.com", "target_page_id": "page_1"}),
        }
        self.call(create_event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})

        response, _ = self.call({
            "httpMethod": "GET",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, {})

        body = json.loads(response["body"])
        self.assertEqual(len(body["domains"]), 1)
        self.assertEqual(body["dns_target"], "domains.jbay.uk")

    def test_check_domain_becomes_active_when_dns_and_ssl_verified(self):
        create_event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "shop.example.com", "target_page_id": "page_1"}),
        }
        self.call(create_event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})

        check_event = {
            "httpMethod": "POST",
            "path": "/custom-domains/shop.example.com/check",
            "pathParameters": {"domain": "shop.example.com"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }
        response, _ = self.call(check_event, {
            ("GET", f"{CLOUDFLARE_BASE}/ch_1"): cloudflare_get_response(ssl_status="active", hostname_status="active"),
            ("GET", "https://cloudflare-dns.com/dns-query"): dns_answer("verify-me-123"),
        })

        body = json.loads(response["body"])
        self.assertEqual(body["domain"]["status"], "active")
        self.assertTrue(body["dns_verified"])
        self.assertEqual(self.index_repo.get("tenant_demo", "shop.example.com")["status"], "active")

    def test_check_domain_stays_pending_dns_when_txt_missing(self):
        create_event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "shop.example.com", "target_page_id": "page_1"}),
        }
        self.call(create_event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})

        check_event = {
            "httpMethod": "POST",
            "path": "/custom-domains/shop.example.com/check",
            "pathParameters": {"domain": "shop.example.com"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }
        response, _ = self.call(check_event, {
            ("GET", f"{CLOUDFLARE_BASE}/ch_1"): cloudflare_get_response(),
            ("GET", "https://cloudflare-dns.com/dns-query"): dns_no_answer(),
        })

        body = json.loads(response["body"])
        self.assertEqual(body["domain"]["status"], "pending_dns")
        self.assertFalse(body["dns_verified"])

    def test_check_domain_not_found_returns_404(self):
        response, _ = self.call({
            "httpMethod": "POST",
            "path": "/custom-domains/missing.example.com/check",
            "pathParameters": {"domain": "missing.example.com"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, {})
        self.assertEqual(response["statusCode"], 404)

    def test_delete_domain_removes_entry_and_index(self):
        create_event = {
            "httpMethod": "POST",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
            "body": json.dumps({"domain": "shop.example.com", "target_page_id": "page_1"}),
        }
        self.call(create_event, {("POST", CLOUDFLARE_BASE): cloudflare_create_response()})

        delete_event = {
            "httpMethod": "DELETE",
            "path": "/custom-domains/shop.example.com",
            "pathParameters": {"domain": "shop.example.com"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }
        response, _ = self.call(delete_event, {
            ("DELETE", f"{CLOUDFLARE_BASE}/ch_1"): {"success": True, "result": {"id": "ch_1"}},
        })

        self.assertEqual(response["statusCode"], 200)
        stored_config = self.config_repo.get("tenant_demo")
        self.assertEqual(stored_config["custom_domains"]["domains"], [])
        self.assertIsNone(self.index_repo.get("tenant_demo", "shop.example.com"))

    def test_missing_tenant_id_returns_400(self):
        response, _ = self.call({
            "httpMethod": "GET",
            "path": "/custom-domains",
            "queryStringParameters": {},
        }, {})
        self.assertEqual(response["statusCode"], 400)

    def test_options_returns_empty_response(self):
        response, _ = self.call({"httpMethod": "OPTIONS"}, {})
        self.assertEqual(response["statusCode"], 200)

    def test_rejects_unsupported_method(self):
        response, _ = self.call({
            "httpMethod": "PATCH",
            "path": "/custom-domains",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, {})
        self.assertEqual(response["statusCode"], 405)

    def test_cloudflare_not_configured_returns_500(self):
        opener = FakeOpener({})
        response = handler(
            {
                "httpMethod": "GET",
                "path": "/custom-domains",
                "queryStringParameters": {"tenant_id": "tenant_demo"},
            },
            None,
            config_repo=self.config_repo,
            index_repo=self.index_repo,
            zone_id="",
            api_token="",
            opener=opener,
        )
        self.assertEqual(response["statusCode"], 500)


if __name__ == "__main__":
    unittest.main()
