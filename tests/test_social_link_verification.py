"""same_as verification is server-owned.

The point of these tests is adversarial: a client that can set verification state can assert any
brand's real social profile as its own identity in our JSON-LD, which is precisely what gating sameAs
on verification is meant to prevent. Before 2026-09-09 `verified` was a plain client-settable boolean,
so the guarantee did not exist. See plans/SOCIAL_MEDIA_PAGES.md §7a-i.
"""
import json
import unittest

from handlers.sites import handler
from stripe_link.domain.documents import DocumentValidationError, validate_site
from stripe_link.domain.social_links import (
    FAILED,
    ProfileFetchError,
    UNVERIFIABLE,
    UNVERIFIED,
    VERIFIED,
    display_entries,
    initial_verification,
    is_checkable,
    is_verified,
    preserve_verification,
    site_backlink_host,
    url_key,
    verified_urls,
    verify_entry,
)
from tests.fakes import FakeDocumentRepository, FakeSubdomainRegistry
from tests.test_sites_handler import base_site


class SameAsHostClassificationTests(unittest.TestCase):
    def test_hosts_that_cannot_be_checked_are_not_merely_unchecked(self):
        # Measured from a Lambda 2026-09-09: both serve a login wall / JS shell to any unauthenticated
        # fetch. There is nothing to retry, so they must not sit at "pending" forever.
        self.assertFalse(is_checkable("https://instagram.com/nasa"))
        self.assertFalse(is_checkable("https://www.tiktok.com/@nasa"))
        self.assertEqual(initial_verification("https://instagram.com/nasa")["state"], UNVERIFIABLE)

    def test_publicly_editable_hosts_are_never_auto_verifiable(self):
        # Anyone can edit these, so finding our URL there proves nothing about who controls the subject.
        self.assertFalse(is_checkable("https://en.wikipedia.org/wiki/NASA"))
        self.assertFalse(is_checkable("https://www.wikidata.org/wiki/Q23548"))

    def test_ordinary_profile_hosts_are_checkable(self):
        for url in ("https://github.com/sindresorhus", "https://www.linkedin.com/company/nasa/",
                    "https://x.com/nasa", "https://www.youtube.com/@NASA"):
            self.assertTrue(is_checkable(url), url)
        self.assertEqual(initial_verification("https://github.com/x")["state"], UNVERIFIED)

    def test_url_key_ignores_scheme_www_and_trailing_slash_but_not_path_case(self):
        self.assertEqual(url_key("HTTPS://WWW.GitHub.com/Foo/"), url_key("http://github.com/Foo"))
        # Path case is preserved: on some hosts these are different people, and carrying a proof
        # across them would grant it for a URL it was never issued for.
        self.assertNotEqual(url_key("https://github.com/Foo"), url_key("https://github.com/foo"))


class PreserveVerificationTests(unittest.TestCase):
    def test_client_supplied_verification_is_discarded(self):
        incoming = {"same_as": [{"url": "https://github.com/acme", "verification": {"state": VERIFIED}}]}
        merged = preserve_verification(incoming, {"same_as": []})
        self.assertEqual(merged[0]["verification"]["state"], UNVERIFIED)

    def test_stored_verification_survives_an_unrelated_edit(self):
        existing = {"same_as": [{"url": "https://github.com/acme",
                                 "verification": {"state": VERIFIED, "method": "url_presence"}}]}
        incoming = {"same_as": [{"url": "https://github.com/acme", "label": "Our code"}]}
        merged = preserve_verification(incoming, existing)
        self.assertEqual(merged[0]["verification"]["state"], VERIFIED)
        self.assertEqual(merged[0]["label"], "Our code")

    def test_repointing_a_verified_link_drops_its_proof(self):
        # The check said "we found our page ON THIS URL". That finding does not travel.
        existing = {"same_as": [{"url": "https://github.com/acme", "verification": {"state": VERIFIED}}]}
        incoming = {"same_as": [{"url": "https://github.com/someone-else"}]}
        merged = preserve_verification(incoming, existing)
        self.assertEqual(merged[0]["verification"]["state"], UNVERIFIED)

    def test_legacy_boolean_is_stripped_not_carried(self):
        merged = preserve_verification({"same_as": [{"url": "https://github.com/a", "verified": True}]}, {})
        self.assertNotIn("verified", merged[0])
        self.assertEqual(merged[0]["verification"]["state"], UNVERIFIED)


class SameAsValidationTests(unittest.TestCase):
    def _site(self, same_as):
        site = base_site(site_id="site_axel01")
        site["organization"] = {"name": "Axel Mart", "entity_type": "OnlineStore", "same_as": same_as}
        return site

    def test_legacy_verified_boolean_is_refused_outright(self):
        with self.assertRaisesRegex(DocumentValidationError, "server-owned"):
            validate_site(self._site([{"url": "https://github.com/a", "verified": True}]))

    def test_unknown_verification_state_is_refused(self):
        with self.assertRaisesRegex(DocumentValidationError, "must be one of"):
            validate_site(self._site([{"url": "https://github.com/a", "verification": {"state": "yes"}}]))


class RenderGateTests(unittest.TestCase):
    ORG = {"same_as": [
        {"url": "https://github.com/acme", "verification": {"state": VERIFIED}},
        {"url": "https://instagram.com/acme", "verification": {"state": UNVERIFIABLE}},
        {"url": "https://x.com/acme", "verification": {"state": UNVERIFIED}},
    ]}

    def test_only_verified_entries_enter_same_as(self):
        self.assertEqual(verified_urls(self.ORG), ["https://github.com/acme"])

    def test_display_is_not_gated_on_verification(self):
        # The whole point of the two-tier model: Instagram and TikTok links still render, they just
        # never make an identity claim. Verification gates sameAs, not traffic.
        self.assertEqual(len(display_entries(self.ORG)), 3)

    def test_is_verified_rejects_anything_that_is_not_the_state(self):
        for entry in ({"verified": True}, {"verification": True}, {"verification": {"state": "pending"}}, {}):
            self.assertFalse(is_verified(entry), entry)


class SiteWriteBoundaryTests(unittest.TestCase):
    """End to end through the real handler -- the boundary is only worth anything if it is wired in."""

    def setUp(self):
        self.repo = FakeDocumentRepository("site_id")
        self.registry = FakeSubdomainRegistry()

    def _post(self, site):
        return handler({"httpMethod": "POST", "body": json.dumps(site)}, None,
                       repository=self.repo, registry=self.registry)

    def _with_links(self, same_as, site_id=None):
        site = base_site()
        site["organization"] = {"name": "Axel Mart", "entity_type": "OnlineStore", "same_as": same_as}
        if site_id:
            site["site_id"] = site_id
        return site

    def test_a_client_cannot_verify_its_own_link(self):
        resp = self._post(self._with_links(
            [{"url": "https://github.com/acme", "verification": {"state": VERIFIED}}]))
        self.assertEqual(resp["statusCode"], 201)
        saved = json.loads(resp["body"])["site"]
        self.assertEqual(saved["organization"]["same_as"][0]["verification"]["state"], UNVERIFIED)

    def test_a_client_cannot_re_verify_by_resaving(self):
        site_id = json.loads(self._post(self._with_links(
            [{"url": "https://github.com/acme"}]))["body"])["site"]["site_id"]
        # The verifier does its job out of band.
        stored = self.repo.get("tenant_demo", site_id)
        stored["organization"]["same_as"][0]["verification"] = {"state": VERIFIED, "method": "url_presence"}
        self.repo.put(stored)
        # Client now re-saves, trying to verify a SECOND link while keeping the first.
        resp = self._post(self._with_links([
            {"url": "https://github.com/acme"},
            {"url": "https://x.com/acme", "verification": {"state": VERIFIED}},
        ], site_id=site_id))
        entries = json.loads(resp["body"])["site"]["organization"]["same_as"]
        self.assertEqual(entries[0]["verification"]["state"], VERIFIED)    # genuinely verified, preserved
        self.assertEqual(entries[1]["verification"]["state"], UNVERIFIED)  # forged, discarded


if __name__ == "__main__":
    unittest.main()


class VerifyEntryTests(unittest.TestCase):
    """The decision logic, with the network injected out.

    This is where the security weight sits, so it must not be the part that only runs against live
    Instagram. The fetcher is a parameter precisely so these cases are reachable.
    """

    HOST = "axel-mart.jbay.uk"

    def test_a_backlink_verifies(self):
        result = verify_entry({"url": "https://github.com/acme"}, self.HOST, 100,
                              fetcher=lambda url: '<a href="https://axel-mart.jbay.uk/">our shop</a>')
        self.assertEqual(result["state"], VERIFIED)
        self.assertEqual(result["method"], "url_presence")
        self.assertEqual(result["checked_at"], 100)

    def test_a_percent_encoded_backlink_still_verifies(self):
        # YouTube and Facebook route outbound links through redirectors that encode the destination.
        # A raw-only match would tell the tenant their link is missing when it is plainly on the page.
        result = verify_entry({"url": "https://www.youtube.com/@acme"}, self.HOST, 100,
                              fetcher=lambda url: "/redirect?q=https%3A%2F%2Faxel-mart.jbay.uk%2F")
        self.assertEqual(result["state"], VERIFIED)

    def test_a_page_without_the_backlink_fails(self):
        result = verify_entry({"url": "https://github.com/acme"}, self.HOST, 100,
                              fetcher=lambda url: "<html>nothing here</html>")
        self.assertEqual(result["state"], FAILED)

    def test_an_unreadable_profile_is_not_reported_as_a_failure(self):
        # "failed" means "we looked and your link is not there" -- a statement about the tenant's
        # profile. A network error is a statement about US. Conflating them tells a tenant to go fix
        # something that is already correct.
        def boom(url):
            raise ProfileFetchError("connection reset")
        result = verify_entry({"url": "https://github.com/acme"}, self.HOST, 100, fetcher=boom)
        self.assertEqual(result["state"], UNVERIFIED)
        self.assertIn("connection reset", result["detail"])

    def test_unfetchable_hosts_are_never_even_attempted(self):
        def explode(url):
            raise AssertionError("must not fetch an unverifiable host")
        for url in ("https://instagram.com/acme", "https://www.tiktok.com/@acme",
                    "https://en.wikipedia.org/wiki/Acme"):
            result = verify_entry({"url": url}, self.HOST, 100, fetcher=explode)
            self.assertEqual(result["state"], UNVERIFIABLE, url)

    def test_the_backlink_host_follows_the_verified_custom_domain(self):
        platform = {"hosting": {"platform_hostname": "axel-mart.jbay.uk", "custom_domain": None}}
        self.assertEqual(site_backlink_host(platform), "axel-mart.jbay.uk")
        unverified = {"hosting": {"platform_hostname": "axel-mart.jbay.uk",
                                  "custom_domain": "shop.example.com",
                                  "verification": {"verified": False}}}
        # Not yet verified, so the tenant is still being shown the platform address -- ask for that.
        self.assertEqual(site_backlink_host(unverified), "axel-mart.jbay.uk")
        verified = {"hosting": {"platform_hostname": "axel-mart.jbay.uk",
                                "custom_domain": "shop.example.com",
                                "verification": {"verified": True}}}
        self.assertEqual(site_backlink_host(verified), "shop.example.com")


class VerifierIsTheOnlyProducerTests(unittest.TestCase):
    def test_a_check_writes_state_that_a_client_save_then_preserves(self):
        # The two halves must compose: the verifier is the only writer, and the write boundary must not
        # then throw its work away on the tenant's next save.
        entry = {"url": "https://github.com/acme"}
        entry["verification"] = verify_entry(
            entry, "axel-mart.jbay.uk", 100,
            fetcher=lambda url: '<a href="https://axel-mart.jbay.uk/">shop</a>')
        self.assertEqual(entry["verification"]["state"], VERIFIED)
        merged = preserve_verification({"same_as": [{"url": "https://github.com/acme"}]},
                                       {"same_as": [entry]})
        self.assertEqual(merged[0]["verification"]["state"], VERIFIED)
