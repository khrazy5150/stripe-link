import json
import unittest

from handlers.sites import handler
from tests.fakes import FakeDocumentRepository, FakeSubdomainRegistry


def base_site(**overrides):
    site = {
        "schema_version": "2026-07-20",
        "document_type": "site",
        "tenant_id": "tenant_demo",
        "environment": "live",
        "name": "Axel Mart",
        "status": "active",
        "hosting": {"type": "platform", "platform_hostname": "axel-mart.jbay.uk", "custom_domain": None},
        "organization": {"name": "Axel Mart", "entity_type": "OnlineStore"},
        "indexing": {"eligibility": "blocked"},
        "pages": {"/": {"page_id": "page_home01", "page_type": "landing", "enabled": True}},
    }
    site.update(overrides)
    return site


class SitesHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("site_id")
        self.registry = FakeSubdomainRegistry()

    def _post(self, site):
        return handler({"httpMethod": "POST", "body": json.dumps(site)}, None,
                       repository=self.repo, registry=self.registry)

    def _check(self, name, site_id=None):
        params = {"name": name}
        if site_id:
            params["site_id"] = site_id
        resp = handler({"httpMethod": "GET", "resource": "/sites/subdomain",
                        "queryStringParameters": params}, None, repository=self.repo, registry=self.registry)
        return json.loads(resp["body"])

    def test_attach_page_rejects_reserved_funnel_slug(self):
        site_id = json.loads(self._post(base_site())["body"])["site"]["site_id"]
        resp = handler({
            "httpMethod": "POST",
            "resource": "/sites/{site_id}/pages",
            "pathParameters": {"site_id": site_id},
            "body": json.dumps({"tenant_id": "tenant_demo", "page_id": "page_up01", "slug": "/upsell"}),
        }, None, repository=self.repo, registry=self.registry)
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(json.loads(resp["body"])["error"], "reserved_slug")

    def test_create_generates_site_id_and_persists(self):
        resp = self._post(base_site())
        self.assertEqual(resp["statusCode"], 201)
        site = json.loads(resp["body"])["site"]
        self.assertRegex(site["site_id"], r"^site_[A-Za-z0-9]+$")
        self.assertTrue(site["created_at"] and site["updated_at"])
        self.assertEqual(site["hosting"]["type"], "platform")

    def test_platform_hostname_built_from_subdomain_and_config_domain(self):
        import os
        from unittest.mock import patch
        site = base_site(hosting={"type": "platform", "platform_subdomain": "Axel Mart!"})
        with patch.dict(os.environ, {"PLATFORM_HOSTING_DOMAIN": "jbay.uk"}):
            resp = self._post(site)
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(json.loads(resp["body"])["site"]["hosting"]["platform_hostname"], "axel-mart.jbay.uk")

    def test_create_rejects_invalid_site(self):
        resp = self._post(base_site(status="live"))       # bad status
        self.assertEqual(resp["statusCode"], 400)

    def test_one_page_belongs_to_one_site(self):
        first = json.loads(self._post(base_site(site_id="site_AAAA1"))["body"])["site"]
        # a second Site claiming the same page_id must be rejected
        resp = self._post(base_site(site_id="site_BBBB2", name="Other",
                                    pages={"/": {"page_id": "page_home01", "enabled": True}}))
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("only one Site", json.loads(resp["body"])["message"])

    def test_create_site_with_no_pages(self):
        # A brand-new tenant with no landing pages can still create their Site first.
        resp = self._post(base_site(pages={}))
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(json.loads(resp["body"])["site"]["pages"], {})

    def test_subdomain_is_globally_unique(self):
        first = self._post(base_site(site_id="site_AAAA1", tenant_id="tenant_a"))
        self.assertEqual(first["statusCode"], 201)
        # a DIFFERENT tenant asking for the same subdomain is rejected with suggestions
        clash = self._post(base_site(site_id="site_BBBB2", tenant_id="tenant_b",
                                     name="Other", pages={"/": {"page_id": "page_zzz", "enabled": True}},
                                     hosting={"type": "platform", "platform_subdomain": "axel-mart"}))
        self.assertEqual(clash["statusCode"], 400)
        self.assertIn("already taken", json.loads(clash["body"])["message"])

    def test_resave_keeps_own_subdomain(self):
        created = json.loads(self._post(base_site(site_id="site_AAAA1"))["body"])["site"]
        again = self._post(created)   # same site re-claims its own label — idempotent
        self.assertEqual(again["statusCode"], 201)

    def test_reserved_subdomain_rejected(self):
        resp = self._post(base_site(hosting={"type": "platform", "platform_subdomain": "admin"}))
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("reserved", json.loads(resp["body"])["message"].lower())

    def test_check_subdomain_available_then_taken(self):
        avail = self._check("axel-mart")
        self.assertTrue(avail["available"])
        self.assertEqual(avail["normalized"], "axel-mart")
        self.assertEqual(avail["hostname"], "axel-mart.jbay.uk")
        self._post(base_site(site_id="site_AAAA1", hosting={"type": "platform", "platform_subdomain": "axel-mart"}))
        taken = self._check("Axel Mart")
        self.assertFalse(taken["available"])
        self.assertTrue(taken["suggestions"])

    def test_check_subdomain_owner_sees_own_as_available(self):
        self._post(base_site(site_id="site_AAAA1", hosting={"type": "platform", "platform_subdomain": "axel-mart"}))
        mine = self._check("axel-mart", site_id="site_AAAA1")
        self.assertTrue(mine["available"])

    def test_check_subdomain_too_short(self):
        result = self._check("ab")
        self.assertFalse(result["available"])
        self.assertIn("at least", result["reason"])

    def test_update_same_site_keeps_its_pages(self):
        created = json.loads(self._post(base_site(site_id="site_AAAA1"))["body"])["site"]
        resp = self._post({**created, "name": "Renamed"})   # re-post same site_id = update
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(json.loads(resp["body"])["site"]["name"], "Renamed")

    def test_get_and_list(self):
        self._post(base_site(site_id="site_AAAA1"))
        got = handler({"httpMethod": "GET", "pathParameters": {"site_id": "site_AAAA1"},
                       "queryStringParameters": {"tenant_id": "tenant_demo"}}, None, repository=self.repo)
        self.assertEqual(got["statusCode"], 200)
        listed = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "tenant_demo"}},
                         None, repository=self.repo)
        self.assertEqual(len(json.loads(listed["body"])["sites"]), 1)

    def test_status_and_delete(self):
        self._post(base_site(site_id="site_AAAA1"))
        arch = handler({"httpMethod": "PATCH", "resource": "/sites/{site_id}/status",
                        "pathParameters": {"site_id": "site_AAAA1"},
                        "body": json.dumps({"tenant_id": "tenant_demo", "status": "archived"})}, None, repository=self.repo)
        self.assertEqual(json.loads(arch["body"])["site"]["status"], "archived")
        deleted = handler({"httpMethod": "DELETE", "pathParameters": {"site_id": "site_AAAA1"},
                           "queryStringParameters": {"tenant_id": "tenant_demo"}}, None, repository=self.repo)
        self.assertEqual(deleted["statusCode"], 200)
        self.assertIsNone(self.repo.get("tenant_demo", "site_AAAA1"))


if __name__ == "__main__":
    unittest.main()
