"""A Site's two Stripe modes must not share one public hostname.

Found on prod 2026-09-20 while baselining a deploy: `poliaxis-nutrition.jbay.uk/link-bio` and
`jbay.page/poliaxis-nutrition` both 404'd. The Sites table holds TWO rows for one Site -- `SITE#live#…` and
`SITE#test#…` -- but the edge index holds one row per hostname, so both modes projected onto it and the last
publish won. The live Site was archived and the test Site active; the shared row said archived, so the
hostname served nothing in either mode.

The collision predates this week. Archiving used to leave `status: "active"`, so mode-fighting only swapped
routes invisibly; making archive stop serving turned it into one mode's kill switch for the other.

Shape chosen by the author, matching stripe-cart's separate `test.juniorbay.com`: `{label}-test.{domain}`.
One label level, so the existing `*.jbay.uk` certificate and the zone-wide Worker route both cover it.
"""
import os
import unittest
from unittest import mock

from handlers.sites import (
    TEST_HOST_SUFFIX, _ensure_platform_hostname, platform_hostname_for, platform_label)
from stripe_link.domain.custom_domains import creator_domain_index_record, site_index_records

ENV = {"PLATFORM_HOSTING_DOMAIN": "jbay.uk"}


def _site(**over):
    site = {
        "tenant_id": "t1", "site_id": "site_1", "status": "active", "environment": "live",
        "hosting": {"type": "platform", "platform_hostname": "maria.jbay.uk"},
        "pages": {"/links": {"page_id": "hub", "composition": "lead_social"}},
    }
    site.update(over)
    return site


class HostnameShapeTests(unittest.TestCase):
    def test_live_keeps_the_bare_label(self):
        with mock.patch.dict(os.environ, ENV):
            doc = {"hosting": {"type": "platform", "platform_subdomain": "maria"}}
            _ensure_platform_hostname(doc, "live")
            self.assertEqual(doc["hosting"]["platform_hostname"], "maria.jbay.uk")

    def test_test_mode_gets_its_own(self):
        with mock.patch.dict(os.environ, ENV):
            doc = {"hosting": {"type": "platform", "platform_subdomain": "maria"}}
            _ensure_platform_hostname(doc, "test")
            self.assertEqual(doc["hosting"]["platform_hostname"], "maria-test.jbay.uk")

    def test_an_existing_hostname_from_the_WRONG_mode_is_corrected(self):
        """The migration case: every test Site made before this carries its live twin's hostname."""
        with mock.patch.dict(os.environ, ENV):
            doc = {"hosting": {"type": "platform", "platform_hostname": "maria.jbay.uk"}}
            _ensure_platform_hostname(doc, "test")
            self.assertEqual(doc["hosting"]["platform_hostname"], "maria-test.jbay.uk")

    def test_a_correct_hostname_is_left_alone(self):
        with mock.patch.dict(os.environ, ENV):
            for mode, host in (("live", "maria.jbay.uk"), ("test", "maria-test.jbay.uk")):
                doc = {"hosting": {"type": "platform", "platform_hostname": host}}
                _ensure_platform_hostname(doc, mode)
                self.assertEqual(doc["hosting"]["platform_hostname"], host, mode)

    def test_the_label_is_recoverable_from_either_hostname(self):
        self.assertEqual(platform_label("maria.jbay.uk"), "maria")
        self.assertEqual(platform_label("maria-test.jbay.uk"), "maria")
        # A label that merely ENDS in the suffix is still that label on the live host.
        self.assertEqual(platform_hostname_for("maria", "jbay.uk", "test"), f"maria{TEST_HOST_SUFFIX}.jbay.uk")
        self.assertEqual(platform_hostname_for("maria", "jbay.uk", "live"), "maria.jbay.uk")


class PairedReservationTests(unittest.TestCase):
    """`maria-test` is itself a legal label, so claiming `maria` must claim it too.

    Otherwise a second tenant could register `maria-test` and take over the first tenant's test host -- the
    one hole in choosing a suffix over a whole extra subdomain level.
    """

    def test_both_names_are_claimed(self):
        import pathlib

        handler = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
                   / "sites.py").read_text(encoding="utf-8")
        block = handler.split("def _reserve_subdomain(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('for name in (label, f"{label}{TEST_HOST_SUFFIX}")', block)
        self.assertIn("platform_label(hostname)", block)


class IndexRowsNoLongerCollideTests(unittest.TestCase):
    def test_the_two_modes_write_different_rows(self):
        live = {r["domain"] for r in site_index_records(_site(), "jbay.page")}
        test_site = _site(environment="test")
        test_site["hosting"]["platform_hostname"] = "maria-test.jbay.uk"
        test_rows = {r["domain"] for r in site_index_records(test_site, "jbay.page")}
        self.assertIn("maria.jbay.uk", live)
        self.assertIn("maria-test.jbay.uk", test_rows)
        self.assertFalse(live & test_rows, "the modes still share a row")

    def test_archiving_one_mode_cannot_reach_the_other(self):
        """The actual prod symptom: an archived live Site took the active test Site off the air."""
        archived_live = _site(status="archived")
        active_test = _site(environment="test")
        active_test["hosting"]["platform_hostname"] = "maria-test.jbay.uk"
        live_rows = {r["domain"]: r for r in site_index_records(archived_live, "jbay.page")}
        test_rows = {r["domain"]: r for r in site_index_records(active_test, "jbay.page")}
        self.assertEqual(live_rows["maria.jbay.uk"]["status"], "archived")
        self.assertEqual(test_rows["maria-test.jbay.uk"]["status"], "active")


class CreatorApexIsLiveOnlyTests(unittest.TestCase):
    def test_a_test_site_never_claims_the_creator_url(self):
        """One public name per creator. The apex is an identity, not a sandbox."""
        self.assertIsNone(creator_domain_index_record(_site(environment="test"), "jbay.page"))

    def test_the_live_site_still_does(self):
        record = creator_domain_index_record(_site(), "jbay.page")
        self.assertEqual(record["domain"], "jbay.page/maria")

    def test_and_it_is_absent_from_a_test_site_record_set(self):
        test_site = _site(environment="test")
        test_site["hosting"]["platform_hostname"] = "maria-test.jbay.uk"
        domains = {r["domain"] for r in site_index_records(test_site, "jbay.page")}
        self.assertNotIn("jbay.page/maria", domains)


if __name__ == "__main__":
    unittest.main()
