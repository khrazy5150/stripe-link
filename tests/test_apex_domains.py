"""Apex custom domains (plans/SITE_OBJECT.md 2.6b): `example.com`, not just `shop.example.com`.

**The working apex path is the tenant's own CNAME flattening / ALIAS / ANAME, and there is currently no
other one.** This file asserted the opposite for a few hours on 2026-10-23 and was wrong, so the evidence
is here rather than only in a plan.

The claim was that publishing each zone's public anycast pair as A records made apex work everywhere,
Route 53 included. `curl --resolve shop.coderbay.net:443:<either pair>` serving 200 was taken as proof.
It proved ROUTING. The gate is VERIFICATION, and Cloudflare refused the first real apex in its own words:

    "custom hostname does not CNAME to this zone."
    "The hostname is using Cloudflare and cannot be activated with an TXT or HTTP validation token.
     To activate the custom hostname, the DNS target needs to point to the SaaS zone"

Pointing an apex AT Cloudflare makes the hostname "using Cloudflare", which also disqualifies the
token-validation fallback -- so the A-record path does not merely fail, it closes the only other door.
Apex A records need addresses allocated to this SaaS zone through Cloudflare's Apex Proxying add-on,
which we do not have. Hence the parameters are empty and these tests hold them there.
"""

import os
import pathlib
import unittest
from unittest import mock

from stripe_link.domain.custom_domains import custom_hostname_dns_records, is_apex_domain

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")


class DeployConfigTests(unittest.TestCase):
    """Asserted on the deploy script, because that is where the value is decided — the same reason the
    creator apex and the zone IDs are asserted there, and samconfig.toml is never read by a deploy."""

    def test_a_deploy_never_sets_the_apex_addresses(self):
        # Not "not yet procured" -- actively harmful. Set, they suppress the ALIAS/flattening row that is
        # the working apex path and replace it with A records Cloudflare will never activate.
        self.assertNotIn('PARAMETER_OVERRIDES+=("CloudflareApexIpv4', DEPLOY)
        self.assertNotIn('PARAMETER_OVERRIDES+=("CloudflareApexIpv6', DEPLOY)

    def test_the_zones_own_anycast_addresses_are_not_published_as_apex_targets(self):
        # The exact mistake, by value, so re-adding it fails here rather than at a tenant's registrar.
        for address in ("104.21.71.205", "172.67.149.43", "104.21.88.48", "172.67.173.6"):
            self.assertNotIn(f"CloudflareApexIpv4={address}", DEPLOY)
            self.assertNotIn(f"CloudflareApexIpv4=\"{address}", DEPLOY)

    def test_a_stack_carrying_apex_addresses_stops_the_deploy(self):
        """They cannot be passed as empty — the shorthand is rejected and the long form is dropped, so
        CloudFormation keeps the previous value either way (both tried, 2026-10-23). Nothing is passed;
        the live value is compared against the intent instead, and a mismatch fails the deploy rather
        than quietly handing the next apex tenant records that can never verify."""
        block = DEPLOY.split("Apex custom domains", 1)[1].split("Link-in-bio apex", 1)[0]
        self.assertIn("CloudflareApexIpv4'].ParameterValue", block)   # reads the LIVE value
        self.assertIn("exit 1", block)
        self.assertNotIn("PARAMETER_OVERRIDES+=", block)              # passing it does not work

    def test_the_refusal_is_recorded_where_someone_would_readd_them(self):
        block = DEPLOY.split("Apex custom domains", 1)[1].split("Link-in-bio apex", 1)[0]
        self.assertIn("Apex Proxying", block)
        self.assertIn("using Cloudflare", block)          # Cloudflare's own words, not a paraphrase

    def test_the_template_still_declares_the_parameters(self):
        # The code path stays, ready for an Apex Proxying allocation; only the values are withheld.
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
    def _records(self, hostname, **over):
        kwargs = {"dns_target": "domains.jbay.uk", "dcv_delegation_uuid": "u1"}
        kwargs.update(over)
        return custom_hostname_dns_records({}, hostname=hostname, **kwargs)

    def test_an_apex_is_told_to_flatten_a_cname_at_the_root(self):
        # The one shape Cloudflare accepts: the apex must RESOLVE THROUGH the SaaS target, not merely
        # point at Cloudflare. Flattening/ALIAS/ANAME does that; A records at shared addresses do not.
        routing = self._records("example.com")[0]
        self.assertEqual(routing["type"], "ALIAS")
        self.assertEqual(routing["value"], "domains.jbay.uk")
        self.assertEqual(routing["apex"], "true")
        self.assertIn("ALIAS", routing["note"])

    def test_the_certificate_record_is_still_a_subdomain_cname(self):
        # Why apex certificates work at all, and they do -- the cert issued for coderbay.net while the
        # hostname itself stayed pending. `_acme-challenge.example.com` is a subdomain, so it can hold the
        # DCV delegation CNAME that lets Cloudflare renew without the tenant touching anything again.
        dcv = [r for r in self._records("example.com") if r["name"].startswith("_acme-challenge")]
        self.assertEqual([r["type"] for r in dcv], ["CNAME"])
        self.assertIn("dcv.cloudflare.com", dcv[0]["value"])

    def test_a_subdomain_takes_the_ordinary_routing_cname(self):
        records = self._records("shop.example.com")
        self.assertEqual(records[0], {"type": "CNAME", "name": "shop.example.com",
                                      "value": "domains.jbay.uk"})
        self.assertFalse([r for r in records if r.get("apex")])

    def test_the_www_sibling_is_a_subdomain_and_verifies_on_its_own(self):
        # Worth pinning: on the connect that failed, www.coderbay.net went fully active while the apex
        # never could. The www hostname is the fallback a Route 53 tenant is now pointed at.
        self.assertFalse(is_apex_domain("www.example.com"))
        self.assertEqual(self._records("www.example.com")[0]["type"], "CNAME")

    def test_apex_addresses_still_produce_a_and_aaaa_if_they_are_ever_allocated(self):
        # The code path is not deleted -- an Apex Proxying allocation would make it correct. What is
        # withheld is the VALUES; see DeployConfigTests.
        records = self._records("example.com", apex_ipv4=("192.0.2.1",), apex_ipv6=("2606:4700::1",))
        self.assertEqual([r["type"] for r in records if r.get("apex")], ["A", "AAAA"])


class OwnershipTokenTests(unittest.TestCase):
    """Cloudflare offers an apex a `_cf-custom-hostname` TXT, and it is not a way in.

    It was shown to tenants for about an hour on 2026-10-23, because it looked exactly like the missing
    piece: the certificate was active, the hostname was pending, and here was an unused ownership record.
    The tenant added it. Cloudflare's answer:

        "The hostname is using Cloudflare and cannot be activated with an TXT or HTTP validation token.
         To activate the custom hostname, the DNS target needs to point to the SaaS zone"

    There is no configuration in which it helps. An apex pointed at Cloudflare addresses is "using
    Cloudflare" and disqualified; an apex flattened to the SaaS target proves ownership by that CNAME and
    is never asked. A record a tenant can complete and still be refused for is worse than no record.
    """

    OWNERSHIP = {"ownership_verification": {"type": "txt", "name": "_cf-custom-hostname.example.com",
                                            "value": "b2103dcc-9713-49cc-9624-3bcd9d8aafc3"}}

    def test_an_apex_is_not_shown_a_token_cloudflare_will_refuse(self):
        records = custom_hostname_dns_records(
            self.OWNERSHIP, hostname="example.com", dns_target="domains.jbay.uk",
            dcv_delegation_uuid="u1")
        self.assertFalse([r for r in records if r["type"] == "TXT"])
        self.assertEqual([r["type"] for r in records], ["ALIAS", "CNAME"])

    def test_a_subdomain_is_not_shown_one_either(self):
        records = custom_hostname_dns_records(
            self.OWNERSHIP, hostname="shop.example.com", dns_target="domains.jbay.uk",
            dcv_delegation_uuid="u1")
        self.assertFalse([r for r in records if r["type"] == "TXT"])

    def test_the_no_delegation_fallback_still_uses_it(self):
        # A zone without DCV delegation has no DCV CNAME to offer, so Cloudflare's rotating ownership TXT
        # is all there is. That branch is untouched by any of this.
        records = custom_hostname_dns_records(
            self.OWNERSHIP, hostname="shop.example.com", dns_target="domains.jbay.uk",
            dcv_delegation_uuid="")
        self.assertIn("TXT", [r["type"] for r in records])


if __name__ == "__main__":
    unittest.main()


class ProviderGuidanceTests(unittest.TestCase):
    """Which provider can do apex is a claim about the outside world, so it is checkable and gets checked.

    Verified 2026-10-25. The split is NOT "Cloudflare or nothing" -- it is whether the provider has
    ALIAS/ANAME/CNAME-flattening at the apex:

      works   Cloudflare (flattening), Namecheap (ALIAS on Basic/Free/Premium DNS), DNSimple, DNS Made
              Easy, NS1, Porkbun
      cannot  Route 53 -- its ALIAS targets only AWS resources, per AWS's own docs: "An alias record can
              only redirect queries to selected AWS resources"; and GoDaddy, which has no ANAME/ALIAS.

    Namecheap was in the "cannot" column here for two days on a guess. It is not, and telling a tenant to
    give up their root domain when their provider supports it is the same failure as the `@` instruction:
    confidently wrong, and expensive for the person following it.
    """

    SITES_VUE = (ROOT / "dashboard" / "src" / "components" / "Sites.vue").read_text(encoding="utf-8")

    def _hint_for(self, provider):
        block = self.SITES_VUE.split("const byProvider = {", 1)[1].split("};", 1)[0]
        line = [ln for ln in block.splitlines() if ln.strip().startswith(f"{provider}:")]
        self.assertEqual(len(line), 1, provider)
        return line[0]

    def test_providers_that_can_do_apex_are_told_how(self):
        # Google Cloud DNS belongs here, not with Route 53: it HAS an apex ALIAS, reachable through
        # gcloud or the API but not the Cloud console -- so the copy has to say where to find it rather
        # than tell the tenant their provider cannot do it.
        for provider in ("cloudflare", "namecheap", "googlecloud"):
            hint = self._hint_for(provider)
            self.assertIn("root", hint.lower(), provider)
            self.assertNotIn("Connect www", hint, provider)   # not sent away from their own domain
        self.assertIn("gcloud", self._hint_for("googlecloud"))

    def test_providers_that_cannot_are_given_the_two_real_options(self):
        # Azure joined the list 2026-10-25: its alias record sets reference Azure resources (Traffic
        # Manager, CDN, Front Door, public IPs), never an arbitrary external hostname.
        for provider in ("route53", "godaddy", "azure"):
            hint = self._hint_for(provider)
            self.assertIn("www", hint, provider)
            self.assertIn("move DNS", hint, provider)
