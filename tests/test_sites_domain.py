import json
import os
import unittest
from unittest.mock import patch

from handlers import sites as sites_handler
from handlers.sites import handler
from stripe_link.domain.custom_domains import CustomDomainError
from tests.fakes import FakeDocumentRepository


def base_site(pages=None, **overrides):
    site = {
        "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_D1",
        # live, because that is the only environment where a custom domain is legal at all -- a test Site
        # serving a real domain would present sandbox pages as a real business. See _reject_non_live_site.
        "tenant_id": "t1", "environment": "live", "name": "Axel Mart", "status": "active",
        "hosting": {"type": "platform", "platform_hostname": "axel-mart.jbay.uk", "custom_domain": None},
        "organization": {"name": "Axel Mart", "entity_type": "OnlineStore"},
        "indexing": {"eligibility": "blocked"},
        "pages": pages if pages is not None else {"/": {"page_id": "page_home01", "enabled": True}},
        "created_at": 1, "updated_at": 1,
    }
    site.update(overrides)
    return site


CF_PENDING = {"id": "cf_123", "ssl": {"status": "pending_validation"},
              "ownership_verification": {"name": "_cf.axelmart.com", "value": "cf-token-xyz"}}
CF_ACTIVE = {"id": "cf_123", "status": "active", "ssl": {"status": "active"},
             "ownership_verification": {"name": "_cf.axelmart.com", "value": "cf-token-xyz"}}


class FakeIndex:
    def __init__(self):
        self.records = {}

    def put(self, doc):
        self.records[doc["domain"]] = doc
        return doc

    def delete(self, tenant_id, domain):
        return self.records.pop(domain, None)


class FakeKeys:
    def __init__(self, verification=None, account_id=None):
        self.verification = verification
        self.account_id = account_id
        self.saved = None

    def get(self, tenant_id, mode="test"):
        doc = {}
        if self.verification:
            doc["connect_verification"] = self.verification
        if self.account_id:
            doc["connect_account_id"] = self.account_id
        return doc or None

    def put(self, document):
        self.saved = document
        self.verification = document.get("connect_verification", self.verification)
        return document


class SetHomepageTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("site_id")
        self.site = {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_H1", "tenant_id": "t1",
            "environment": "live", "name": "Store", "status": "active",
            "hosting": {"type": "platform", "platform_hostname": "store.jbay.uk", "custom_domain": None},
            "organization": {"name": "Store", "entity_type": "OnlineStore"},
            "indexing": {"eligibility": "blocked"},
            "pages": {"/": {"page_id": "page_land01", "page_type": "landing", "label": "Course", "enabled": True}},
            "created_at": 1, "updated_at": 1,
        }
        self.repo.put(self.site)

    def _set(self, **body):
        return handler({"httpMethod": "POST", "resource": "/sites/{site_id}/homepage",
                        "pathParameters": {"site_id": "site_H1"},
                        "body": json.dumps({"tenant_id": "t1", **body})}, None, repository=self.repo)

    def test_sets_new_homepage_and_displaces_old_to_a_slug(self):
        resp = self._set(page_id="page_home02")
        self.assertEqual(resp["statusCode"], 200)
        pages = json.loads(resp["body"])["site"]["pages"]
        self.assertEqual(pages["/"]["page_id"], "page_home02")
        self.assertEqual(pages["/"]["page_type"], "homepage")
        moved = [slug for slug, e in pages.items() if e["page_id"] == "page_land01"]
        self.assertEqual(len(moved), 1)
        self.assertNotEqual(moved[0], "/")  # the old landing page stays served at its own slug

    def test_promotes_an_already_attached_page_to_root(self):
        self.site["pages"]["/deal"] = {"page_id": "page_deal", "page_type": "landing"}
        self.repo.put(self.site)
        pages = json.loads(self._set(page_id="page_deal")["body"])["site"]["pages"]
        self.assertEqual(pages["/"]["page_id"], "page_deal")
        self.assertNotIn("/deal", pages)  # moved from /deal to /, not duplicated

    def test_requires_page_id(self):
        self.assertEqual(self._set()["statusCode"], 400)

    def _attach(self, **body):
        return handler({"httpMethod": "POST", "resource": "/sites/{site_id}/pages",
                        "pathParameters": {"site_id": "site_H1"},
                        "body": json.dumps({"tenant_id": "t1", **body})}, None, repository=self.repo)

    def test_attach_page_at_slug_with_type_and_category(self):
        resp = self._attach(page_id="page_cat01", slug="/category/supplements", page_type="category", category="supplements", label="Supplements")
        self.assertEqual(resp["statusCode"], 200)
        entry = json.loads(resp["body"])["site"]["pages"]["/category/supplements"]
        self.assertEqual(entry["page_id"], "page_cat01")
        self.assertEqual(entry["page_type"], "category")
        self.assertEqual(entry["category"], "supplements")
        self.assertEqual(entry["label"], "Supplements")

    def test_attach_rejects_root_slug(self):
        self.assertEqual(self._attach(page_id="page_x", slug="/")["statusCode"], 400)

    def _detach(self, page_id):
        return handler({"httpMethod": "DELETE", "resource": "/sites/{site_id}/pages",
                        "pathParameters": {"site_id": "site_H1"},
                        "queryStringParameters": {"tenant_id": "t1", "page_id": page_id}}, None, repository=self.repo)

    def test_detach_removes_page_and_frees_it(self):
        self.site["pages"]["/deal"] = {"page_id": "page_deal", "page_type": "landing"}
        self.repo.put(self.site)
        resp = self._detach("page_deal")
        self.assertEqual(resp["statusCode"], 200)
        pages = json.loads(resp["body"])["site"]["pages"]
        self.assertNotIn("/deal", pages)
        self.assertTrue(all(e["page_id"] != "page_deal" for e in pages.values()))

    def test_detach_is_idempotent_for_absent_page(self):
        resp = self._detach("page_not_here")
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("/", json.loads(resp["body"])["site"]["pages"])  # untouched

    def test_detach_requires_page_id(self):
        resp = handler({"httpMethod": "DELETE", "resource": "/sites/{site_id}/pages",
                        "pathParameters": {"site_id": "site_H1"},
                        "queryStringParameters": {"tenant_id": "t1"}}, None, repository=self.repo)
        self.assertEqual(resp["statusCode"], 400)

    def test_attach_rejects_page_owned_by_another_site(self):
        # A second Site already routes page_shared; attaching it here must be refused (one page, one Site).
        other = dict(self.site, site_id="site_H2", hosting={"type": "platform", "platform_hostname": "other.jbay.uk"},
                     pages={"/": {"page_id": "page_shared", "page_type": "landing"}})
        self.repo.put(other)
        self.repo.put(self.site)
        resp = self._attach(page_id="page_shared", slug="/deal")
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("one Site", json.loads(resp["body"])["message"])


class SitesDomainTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("site_id")
        self.index = FakeIndex()
        self.keys = FakeKeys()
        self.pages = FakeDocumentRepository("page_id")
        self.pages.put({"tenant_id": "t1", "page_id": "page_home01", "status": "published", "updated_at": 1})
        self._env = patch.dict(os.environ, {"CLOUDFLARE_ZONE_ID": "zone1", "CUSTOM_DOMAIN_TARGET_HOST": "domains.jbay.uk", "ENVIRONMENT": "prod"})
        self._env.start()
        self._patches = [
            patch.object(sites_handler, "get_cloudflare_api_token", return_value="cf-token"),
            patch.object(sites_handler, "custom_domains_index_repository", return_value=self.index),
            patch.object(sites_handler, "stripe_keys_repository", return_value=self.keys),
            patch.object(sites_handler, "pages_repository", return_value=self.pages),
            # Avoid real DNS-over-HTTPS calls in the not-verified diagnostic path.
            patch.object(sites_handler, "diagnose_dns_records", return_value=[]),
            # Stable DCV delegation UUID (avoids a real Cloudflare call).
            patch.object(sites_handler, "get_dcv_delegation_uuid", return_value="testuuid"),
            # Default: re-trigger is a no-op (overridden where the retrigger path is under test).
            patch.object(sites_handler, "retrigger_ssl_validation", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._env.stop()

    def _connect(self, body):
        return handler({"httpMethod": "POST", "resource": "/sites/{site_id}/domain",
                        "pathParameters": {"site_id": "site_D1"}, "body": json.dumps(body)}, None, repository=self.repo)

    def _check(self):
        return handler({"httpMethod": "POST", "resource": "/sites/{site_id}/domain/check",
                        "pathParameters": {"site_id": "site_D1"}, "queryStringParameters": {"tenant_id": "t1"}},
                       None, repository=self.repo)

    def _provisioned_site(self):
        site = base_site()
        site["hosting"]["custom_domain"] = "shop.axelmart.com"
        site["domain_provisioning"] = {"custom_hostname_id": "cf_123", "homepage_page_id": "page_home01",
                                       "validation_record": {"name": "_cf.axelmart.com", "value": "cf-token-xyz"}}
        return site

    def test_domain_endpoints_are_live_only(self):
        self.repo.put(base_site())
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertEqual(resp["statusCode"], 403)
        self.assertIn("live", json.loads(resp["body"])["message"].lower())

    def test_connect_creates_hostname_and_returns_dns_instructions(self):
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertEqual(resp["statusCode"], 201)
        body = json.loads(resp["body"])
        by_name = {r["name"]: r for r in body["dns_records"]}
        self.assertEqual(by_name["shop.axelmart.com"]["value"], "domains.jbay.uk")   # routing CNAME
        # Stable DCV-delegation CNAME (not a rotating TXT) — the fix for the token-rotation quirk.
        dcv = by_name["_acme-challenge.shop.axelmart.com"]
        self.assertEqual(dcv["type"], "CNAME")
        self.assertEqual(dcv["value"], "shop.axelmart.com.testuuid.dcv.cloudflare.com")
        self.assertEqual(body["dns_target"], "domains.jbay.uk")
        site = self.repo.get("t1", "site_D1")
        self.assertEqual(site["hosting"]["custom_domain"], "shop.axelmart.com")
        self.assertFalse(site["hosting"]["verification"]["verified"])
        self.assertEqual(self.index.records["shop.axelmart.com"]["target_page_id"], "page_home01")

    def test_connect_apex_provisions_www_redirect(self):
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "axelmart.com"})
        self.assertEqual(resp["statusCode"], 201)
        www = self.index.records.get("www.axelmart.com")
        self.assertIsNotNone(www)                       # a paired www→apex redirect record was written
        self.assertEqual(www["redirect_to"], "axelmart.com")
        self.assertIn("www.axelmart.com", [r["name"] for r in json.loads(resp["body"])["dns_records"]])

    def test_connect_subdomain_gets_no_www_redirect(self):
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertNotIn("www.shop.axelmart.com", self.index.records)

    def test_disconnect_tears_down_www_redirect(self):
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            self._connect({"tenant_id": "t1", "domain": "axelmart.com"})
        self.assertIn("www.axelmart.com", self.index.records)
        with patch.object(sites_handler, "delete_custom_hostname", return_value=None):
            handler({"httpMethod": "DELETE", "resource": "/sites/{site_id}/domain",
                     "pathParameters": {"site_id": "site_D1"}, "queryStringParameters": {"tenant_id": "t1"}},
                    None, repository=self.repo)
        self.assertNotIn("www.axelmart.com", self.index.records)   # cleaned up

    def test_connect_reuses_existing_hostname_on_duplicate(self):
        # A prior partial attempt already created the Cloudflare hostname; retry must reuse it, not fail.
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", side_effect=CustomDomainError("Duplicate custom hostname found.", 400)), \
             patch.object(sites_handler, "find_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(self.repo.get("t1", "site_D1")["hosting"]["custom_domain"], "shop.axelmart.com")

    def test_connect_fails_when_hostname_missing_and_not_duplicate(self):
        self.repo.put(base_site())
        with patch.object(sites_handler, "create_custom_hostname", side_effect=CustomDomainError("Cloudflare down", 502)), \
             patch.object(sites_handler, "find_custom_hostname", return_value=None):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertEqual(resp["statusCode"], 502)

    def test_connect_attaches_homepage_when_site_has_no_pages(self):
        # A Site created before its pages existed has an empty map; connecting attaches the chosen homepage.
        self.repo.put(base_site(pages={}))
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com", "homepage_page_id": "page_new1"})
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(self.repo.get("t1", "site_D1")["pages"]["/"]["page_id"], "page_new1")

    def test_connect_requires_homepage_for_multipage_site(self):
        self.repo.put(base_site(pages={"/a": {"page_id": "page_A"}, "/b": {"page_id": "page_B"}}))
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("homepage", json.loads(resp["body"])["message"].lower())

    def test_connect_designates_chosen_homepage(self):
        self.repo.put(base_site(pages={"/a": {"page_id": "page_A"}, "/b": {"page_id": "page_B"}}))
        with patch.object(sites_handler, "create_custom_hostname", return_value=CF_PENDING):
            resp = self._connect({"tenant_id": "t1", "domain": "shop.axelmart.com", "homepage_page_id": "page_B"})
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(self.repo.get("t1", "site_D1")["pages"]["/"]["page_id"], "page_B")

    def test_check_active_verifies_but_pending_without_connect(self):
        self.repo.put(self._provisioned_site())
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_ACTIVE):
            resp = self._check()
        self.assertEqual(json.loads(resp["body"])["status"], "active")
        saved = self.repo.get("t1", "site_D1")
        self.assertEqual(saved["hosting"]["type"], "custom")
        self.assertTrue(saved["hosting"]["verification"]["verified"])
        self.assertEqual(saved["indexing"]["eligibility"], "pending")   # domain verified, Connect not yet

    def test_check_retriggers_dcv_and_verifies_immediately(self):
        # Routing active + cert pending → check re-triggers DCV; Cloudflare issues, so Verify succeeds in one click.
        self.keys.verification = "verified"
        self.repo.put(self._provisioned_site())
        pending = {"id": "cf_123", "status": "active", "ssl": {"status": "pending_validation"}}
        issued = {"id": "cf_123", "status": "active", "ssl": {"status": "active"}}
        with patch.object(sites_handler, "get_custom_hostname", return_value=pending), \
             patch.object(sites_handler, "retrigger_ssl_validation", return_value=issued) as retrig:
            body = json.loads(self._check()["body"])
        retrig.assert_called_once()
        self.assertEqual(body["status"], "active")
        saved = self.repo.get("t1", "site_D1")
        self.assertTrue(saved["hosting"]["verification"]["verified"])
        self.assertEqual(saved["indexing"]["eligibility"], "eligible")

    def test_first_verification_republishes_site_pages(self):
        # Verified-domain-gated publish work (funnel + /sale slugs, canonical/robots) attaches at publish; on the
        # FIRST verification we re-put the Site's pages so those attach for pages published before verification.
        self.repo.put(self._provisioned_site())
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_ACTIVE):
            self._check()
        self.assertNotEqual(self.pages.get("t1", "page_home01")["updated_at"], 1)  # re-put fires the publish stream

    def test_recheck_of_already_verified_domain_does_not_republish(self):
        site = self._provisioned_site()
        site["hosting"]["verification"] = {"verified": True, "method": "cloudflare_saas"}
        self.repo.put(site)
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_ACTIVE):
            self._check()
        self.assertEqual(self.pages.get("t1", "page_home01")["updated_at"], 1)  # already verified -> no re-publish

    def test_still_unverified_check_does_not_republish(self):
        self.repo.put(self._provisioned_site())
        pending = {"id": "cf_123", "status": "pending", "ssl": {"status": "pending_validation"}}
        with patch.object(sites_handler, "get_custom_hostname", return_value=pending):
            self._check()
        self.assertEqual(self.pages.get("t1", "page_home01")["updated_at"], 1)  # not verified yet -> no re-publish

    def test_check_active_generates_indexnow_key(self):
        self.repo.put(self._provisioned_site())
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_ACTIVE):
            self._check()
        self.assertTrue(self.repo.get("t1", "site_D1").get("seo", {}).get("indexnow_key"))

    def test_check_active_with_connect_is_eligible(self):
        self.keys.verification = "verified"
        self.repo.put(self._provisioned_site())
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_ACTIVE):
            self._check()
        self.assertEqual(self.repo.get("t1", "site_D1")["indexing"]["eligibility"], "eligible")

    def test_check_surfaces_ssl_dcv_record_when_pending_cert(self):
        # The real-world case: hostname routing is active but the cert needs the _acme-challenge TXT. We must
        # surface that record and report pending_ssl (not a stuck pending_dns), without gating on our own probe.
        self.repo.put(self._provisioned_site())
        cf = {"id": "cf_123", "status": "active", "ownership_verification": None,
              "ssl": {"status": "pending_validation",
                      "validation_records": [{"txt_name": "_acme-challenge.shop.axelmart.com", "txt_value": "K9rv73"}]}}
        with patch.object(sites_handler, "get_custom_hostname", return_value=cf):
            resp = self._check()
        body = json.loads(resp["body"])
        self.assertEqual(body["status"], "pending_ssl")
        self.assertIn("_acme-challenge.shop.axelmart.com", {r["name"] for r in body["dns_records"]})
        self.assertFalse(self.repo.get("t1", "site_D1")["hosting"]["verification"]["verified"])

    def test_check_hint_points_at_a_missing_record(self):
        self.repo.put(self._provisioned_site())
        cf = {"id": "cf_123", "status": "active", "ssl": {"status": "pending_validation",
              "validation_records": [{"txt_name": "_acme-challenge.shop.axelmart.com", "txt_value": "K9rv"}]}}
        diag = [{"type": "CNAME", "name": "_acme-challenge.shop.axelmart.com", "value": "x", "resolved": False,
                 "note": "found a TXT record here — it must be a CNAME"}]
        with patch.object(sites_handler, "get_custom_hostname", return_value=cf), \
             patch.object(sites_handler, "diagnose_dns_records", return_value=diag):
            body = json.loads(self._check()["body"])
        self.assertIn("_acme-challenge.shop.axelmart.com", body["hint"])
        self.assertIn("must be a CNAME", body["hint"])   # the type-mismatch note is surfaced
        self.assertFalse(body["diagnostics"][0]["resolved"])

    def test_check_hint_says_cert_issuing_when_records_resolve(self):
        self.repo.put(self._provisioned_site())
        cf = {"id": "cf_123", "status": "active", "ssl": {"status": "pending_validation"}}
        diag = [{"type": "CNAME", "name": "shop.axelmart.com", "value": "domains.jbay.uk", "resolved": True}]
        with patch.object(sites_handler, "get_custom_hostname", return_value=cf), \
             patch.object(sites_handler, "diagnose_dns_records", return_value=diag):
            body = json.loads(self._check()["body"])
        self.assertIn("issuing the certificate", body["hint"])

    def test_check_pending_dns_stays_unverified(self):
        self.repo.put(self._provisioned_site())
        with patch.object(sites_handler, "get_custom_hostname", return_value=CF_PENDING):
            self._check()
        saved = self.repo.get("t1", "site_D1")
        self.assertFalse(saved["hosting"]["verification"]["verified"])
        self.assertEqual(saved["hosting"]["type"], "platform")

    def test_list_recomputes_eligibility_and_heals_badge(self):
        # A verified-domain Site with verified Connect should self-heal to 'eligible' when the list loads.
        self.keys.verification = "verified"
        site = base_site(hosting={"type": "custom", "platform_hostname": "axel-mart.jbay.uk",
                                  "custom_domain": "shop.axelmart.com", "verification": {"verified": True}},
                         indexing={"eligibility": "pending"}, environment="live")
        self.repo.put(site)
        resp = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}}, None, repository=self.repo)
        sites = json.loads(resp["body"])["sites"]
        self.assertEqual(sites[0]["indexing"]["eligibility"], "eligible")
        self.assertEqual(self.repo.get("t1", "site_D1")["indexing"]["eligibility"], "eligible")

    def test_connect_state_pulls_live_status_when_never_captured(self):
        # No captured connect_verification, but a connected account exists → pull live status from Stripe.
        self.keys = FakeKeys(account_id="acct_1")
        account = {"charges_enabled": True, "payouts_enabled": True, "details_submitted": True, "requirements": {}}
        with patch.object(sites_handler, "stripe_keys_repository", return_value=self.keys), \
             patch.object(sites_handler, "get_platform_secret_key", return_value="sk_live_x"), \
             patch.object(sites_handler, "stripe_request", return_value=account) as req:
            verified, restricted = sites_handler._connect_state("t1", "live")
        req.assert_called_once()
        self.assertTrue(verified)
        self.assertFalse(restricted)
        self.assertEqual(self.keys.saved["connect_verification"], "verified")   # captured back onto the doc

    def test_disconnect_clears_domain_and_index(self):
        site = base_site(hosting={"type": "custom", "platform_hostname": "axel-mart.jbay.uk",
                                  "custom_domain": "shop.axelmart.com", "verification": {"verified": True}})
        site["domain_provisioning"] = {"custom_hostname_id": "cf_123"}
        site["indexing"] = {"eligibility": "eligible"}
        self.repo.put(site)
        self.index.put({"tenant_id": "t1", "domain": "shop.axelmart.com", "target_page_id": "page_home01", "status": "active"})
        with patch.object(sites_handler, "delete_custom_hostname", return_value={}):
            resp = handler({"httpMethod": "DELETE", "resource": "/sites/{site_id}/domain",
                            "pathParameters": {"site_id": "site_D1"}, "queryStringParameters": {"tenant_id": "t1"}},
                           None, repository=self.repo)
        self.assertEqual(resp["statusCode"], 200)
        saved = self.repo.get("t1", "site_D1")
        self.assertIsNone(saved["hosting"]["custom_domain"])
        self.assertEqual(saved["hosting"]["type"], "platform")
        self.assertEqual(saved["indexing"]["eligibility"], "blocked")   # no domain, no Connect
        self.assertNotIn("shop.axelmart.com", self.index.records)


if __name__ == "__main__":
    unittest.main()


class CustomDomainsAreLiveOnlyTests(unittest.TestCase):
    """A test Site must not be able to serve a real domain.

    The reason is reputational: sandbox pages presenting as a real business is a search reputation the
    tenant cannot get back. Until 2026-09-09 the only guard was on the DEPLOYMENT (ENVIRONMENT != prod),
    which is a different axis -- on the prod deployment a Site with environment="test" sailed past it, and
    the sole remaining obstacle was the dashboard choosing not to render the form.
    """

    def setUp(self):
        self.repo = FakeDocumentRepository("site_id")

    def _test_site(self):
        site = base_site(environment="test")
        site["hosting"] = {"type": "platform", "platform_hostname": "axel-mart.jbay.uk",
                           "custom_domain": None}
        self.repo.put(site)
        return site

    def test_connect_is_refused_for_a_test_site(self):
        self._test_site()
        resp = sites_handler.connect_domain(
            {"body": json.dumps({"tenant_id": "t1", "domain": "shop.example.com"})},
            self.repo, "site_D1")
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "custom_domains_live_only")

    def test_check_is_refused_for_a_test_site(self):
        # Refused BEFORE the "no domain connected" branch: a test Site that somehow acquired a domain
        # (data predating this guard) must not be able to drive it to verified either.
        site = self._test_site()
        site["hosting"]["custom_domain"] = "shop.example.com"
        site["domain_provisioning"] = {"custom_hostname_id": "ch_1"}
        self.repo.put(site)
        resp = sites_handler.check_domain({"queryStringParameters": {"tenant_id": "t1"}}, self.repo, "site_D1")
        self.assertEqual(resp["statusCode"], 403)
        self.assertEqual(json.loads(resp["body"])["error"], "custom_domains_live_only")

    def test_a_live_site_is_not_affected(self):
        self.repo.put(base_site())
        resp = sites_handler.connect_domain(
            {"body": json.dumps({"tenant_id": "t1", "domain": "shop.example.com"})},
            self.repo, "site_D1")
        self.assertNotEqual(resp["statusCode"], 403)
