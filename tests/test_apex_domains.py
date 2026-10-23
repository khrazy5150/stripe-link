"""Apex custom domains (plans/SITE_OBJECT.md 2.6b): `example.com`, not just `shop.example.com`.

DNS forbids a CNAME at a zone apex, and Route 53's ALIAS only targets AWS resources -- so until the apex
IPs were published, a tenant whose DNS lives at Route 53, GoDaddy or Namecheap could not point their root
domain at us at all. The record builder has handled both shapes for a while; what was missing was the
addresses, which the deploy script decides.
"""

import os
import pathlib
import unittest
from unittest import mock

from stripe_link.domain.custom_domains import custom_hostname_dns_records, is_apex_domain

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")


def _apex_branch(environment):
    """The deploy script's apex block for one environment, so a prod value cannot satisfy a dev assertion."""
    block = DEPLOY.split("Re-read with `dig +short A domains.jbay.uk`", 1)[1]
    prod, dev = block.split("else", 1)
    return prod if environment == "prod" else dev.split("\nfi", 1)[0]


def _zone_branch(environment):
    """The block above it that picks the Cloudflare zone and the routing target."""
    block = DEPLOY.split("Both zones are already configured for SaaS", 1)[1]
    prod, dev = block.split("else", 1)
    return prod if environment == "prod" else dev.split("\nfi", 1)[0]


class DeployConfigTests(unittest.TestCase):
    """Asserted on the deploy script, because that is where the value is actually decided — the same
    reason the creator apex and the zone IDs are asserted there. A constant in Python would be a second
    copy of a fact CloudFormation owns, and samconfig.toml is never read by a deploy.sh deploy."""

    def test_both_environments_publish_apex_addresses_at_all(self):
        # Empty is the "not procured yet" state, and it silently downgrades every apex tenant to
        # ALIAS/ANAME guidance their provider may not support.
        for environment in ("prod", "dev"):
            branch = _apex_branch(environment)
            self.assertIn("CloudflareApexIpv4=", branch)
            self.assertIn("CloudflareApexIpv6=", branch)
            self.assertNotIn("CloudflareApexIpv4=\"\"", branch)

    def test_each_environment_publishes_its_own_zone_pair(self):
        # The pair must come from the zone the tenant's custom hostname lives on. Both stacks carried the
        # jbay.uk zone until 2026-10-23 and a sandbox domain verified then served a 404; this is the same
        # mistake one layer down, and it would look like a working apex that serves nothing.
        prod, dev = _apex_branch("prod"), _apex_branch("dev")
        self.assertIn("104.21.71.205", prod)        # domains.jbay.uk
        self.assertIn("104.21.88.48", dev)          # domains.jbay.be
        self.assertNotIn("104.21.88.48", prod)
        self.assertNotIn("104.21.71.205", dev)

    def test_ipv6_is_published_too(self):
        # A tenant whose resolver is IPv6-only gets nothing from A records alone.
        self.assertIn("2606:4700:3035::6815:47cd", _apex_branch("prod"))
        self.assertIn("2606:4700:3033::6815:5830", _apex_branch("dev"))

    def test_the_apex_pair_and_the_routing_target_name_the_same_zone(self):
        # Whatever the addresses are, they and CustomDomainTargetHost must describe ONE zone per
        # environment. The addresses carry the zone they were read from as a trailing comment, which is
        # what makes that checkable here instead of only by resolving them.
        for environment, zone in (("prod", "jbay.uk"), ("dev", "jbay.be")):
            self.assertIn(zone, _apex_branch(environment))
            self.assertIn(f"CustomDomainTargetHost=domains.{zone}", _zone_branch(environment))

    def test_the_template_declares_and_hands_over_the_parameters(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertIn("CloudflareApexIpv4:", template)
        self.assertIn("CLOUDFLARE_APEX_IPV4: !Ref CloudflareApexIpv4", template)
        self.assertIn("CLOUDFLARE_APEX_IPV6: !Ref CloudflareApexIpv6", template)


class ProxyIpParsingTests(unittest.TestCase):
    def test_a_comma_list_becomes_a_tuple_and_spaces_are_tolerated(self):
        from handlers.sites import _apex_proxy_ips

        with mock.patch.dict(os.environ, {"CLOUDFLARE_APEX_IPV4": "192.0.2.1, 192.0.2.2",
                                          "CLOUDFLARE_APEX_IPV6": "2606:4700::1"}):
            self.assertEqual(_apex_proxy_ips(), (("192.0.2.1", "192.0.2.2"), ("2606:4700::1",)))

    def test_unset_means_no_apex_proxying_rather_than_an_empty_string_record(self):
        from handlers.sites import _apex_proxy_ips

        with mock.patch.dict(os.environ, {"CLOUDFLARE_APEX_IPV4": "", "CLOUDFLARE_APEX_IPV6": ""}):
            self.assertEqual(_apex_proxy_ips(), ((), ()))
        with mock.patch.dict(os.environ, {"CLOUDFLARE_APEX_IPV4": ",, ,"}, clear=False):
            self.assertEqual(_apex_proxy_ips()[0], ())


class RecordsGivenToTheTenantTests(unittest.TestCase):
    PROD_V4 = ("104.21.71.205", "172.67.149.43")
    PROD_V6 = ("2606:4700:3035::6815:47cd",)

    def _records(self, hostname, **over):
        kwargs = {"dns_target": "domains.jbay.uk", "dcv_delegation_uuid": "u1",
                  "apex_ipv4": self.PROD_V4, "apex_ipv6": self.PROD_V6}
        kwargs.update(over)
        return custom_hostname_dns_records({}, hostname=hostname, **kwargs)

    def test_a_route53_tenant_gets_records_route53_can_actually_create(self):
        # The whole point of 2.6b. An ALIAS row is unactionable at Route 53 (its ALIAS targets only AWS
        # resources), so the presence of A/AAAA and the ABSENCE of ALIAS are both the requirement.
        records = self._records("example.com")
        self.assertEqual([r["type"] for r in records if r.get("apex")], ["A", "A", "AAAA"])
        self.assertNotIn("ALIAS", [r["type"] for r in records])
        self.assertEqual([r["name"] for r in records if r.get("apex")], ["example.com"] * 3)

    def test_the_certificate_record_is_still_a_subdomain_cname(self):
        # Why apex certificates work at all: `_acme-challenge.example.com` is a subdomain, so it can hold
        # the DCV delegation CNAME that lets Cloudflare renew without the tenant touching anything again.
        dcv = [r for r in self._records("example.com") if r["name"].startswith("_acme-challenge")]
        self.assertEqual([r["type"] for r in dcv], ["CNAME"])
        self.assertIn("dcv.cloudflare.com", dcv[0]["value"])

    def test_a_subdomain_is_unaffected_by_apex_addresses_being_configured(self):
        records = self._records("shop.example.com")
        self.assertEqual(records[0], {"type": "CNAME", "name": "shop.example.com",
                                      "value": "domains.jbay.uk"})
        self.assertFalse([r for r in records if r.get("apex")])

    def test_the_www_sibling_takes_a_cname_because_it_is_a_subdomain(self):
        # An apex Site also provisions `www.<apex>` to 301 at the canonical root. Giving it the apex
        # addresses would be wrong twice: unnecessary, and it would survive an addressing change.
        self.assertFalse(is_apex_domain("www.example.com"))
        records = self._records("www.example.com")
        self.assertEqual(records[0]["type"], "CNAME")

    def test_without_addresses_the_apex_falls_back_to_alias_guidance(self):
        # The pre-2.6b behaviour has to keep working: a new environment deploys with these unset.
        records = self._records("example.com", apex_ipv4=(), apex_ipv6=())
        routing = records[0]
        self.assertEqual(routing["type"], "ALIAS")
        self.assertIn("ALIAS", routing["note"])


if __name__ == "__main__":
    unittest.main()
