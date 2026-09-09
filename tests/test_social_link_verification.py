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
    UNVERIFIABLE,
    UNVERIFIED,
    VERIFIED,
    display_entries,
    initial_verification,
    is_checkable,
    is_verified,
    preserve_verification,
    url_key,
    verified_urls,
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
