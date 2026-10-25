"""The DNS instructions a tenant follows at their own provider (plans/SITE_OBJECT.md 2.6b).

Both rules here were learned from a real failed connect on 2026-10-23, the first day apex domains were
live. `coderbay.net` is on Route 53, which was the whole reason for shipping A/AAAA apex records -- and
the instructions handed to that tenant could not be followed:

    Error occurred: A record with the specified name already exists.
    (Tried to create resource record set [name='\\100.coderbay.net.', type='A'] but it already exists)

`\\100` is `@`. The first address had been created at a record literally named `@.coderbay.net`, which
resolved perfectly and served nothing; the second was then refused for colliding with it. Two separate
mistakes in one screenshot, and neither was the tenant's.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "dnsInstructions.js"
SITES_VUE = ROOT / "dashboard" / "src" / "components" / "Sites.vue"

# What the server emits for an apex Site on the sandbox zone: two addresses at the apex, plus the DCV
# delegation, which is a subdomain and therefore ordinary.
APEX_RECORDS = [
    {"type": "A", "name": "coderbay.net", "value": "104.21.88.48", "apex": "true"},
    {"type": "A", "name": "coderbay.net", "value": "172.67.173.6", "apex": "true"},
    {"type": "AAAA", "name": "coderbay.net", "value": "2606:4700:3033::6815:5830", "apex": "true"},
    {"type": "AAAA", "name": "coderbay.net", "value": "2606:4700:3030::ac43:ad06", "apex": "true"},
    {"type": "CNAME", "name": "_acme-challenge.coderbay.net",
     "value": "coderbay.net.uuid.dcv.cloudflare.com"},
]


def _steps(records, domain, provider):
    script = f"""
    import {{ dnsRecordSteps }} from {json.dumps(str(MODULE))};
    const steps = dnsRecordSteps({json.dumps(records)}, {json.dumps({"domain": domain, "providerId": provider})});
    console.log(JSON.stringify(steps));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            capture_output=True, text=True, cwd=ROOT, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class DnsInstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node is not available")

    def test_route53_is_told_to_leave_the_name_blank(self):
        """THE BUG. Route 53 has no `@`: it creates a record literally called `@.coderbay.net`."""
        a_record = _steps(APEX_RECORDS, "coderbay.net", "route53")[0]
        self.assertEqual(a_record["displayName"], "")
        self.assertTrue(a_record["nameIsBlank"])
        self.assertIn("blank", a_record["nameNote"])

    def test_every_other_provider_still_gets_the_at_sign(self):
        # The fix must not become a different wrong answer: @ IS correct at Cloudflare, GoDaddy, Namecheap.
        for provider in ("cloudflare", "godaddy", "namecheap"):
            step = _steps(APEX_RECORDS, "coderbay.net", provider)[0]
            self.assertEqual(step["displayName"], "@", provider)
            self.assertFalse(step["nameIsBlank"], provider)
            self.assertEqual(step["nameNote"], "", provider)

    def test_a_full_name_provider_gets_the_whole_hostname(self):
        step = _steps(APEX_RECORDS, "coderbay.net", "other")[0]
        self.assertEqual(step["displayName"], "coderbay.net")

    def test_two_addresses_are_one_record_not_two_steps(self):
        """THE SECOND BUG. Listing them separately reads as 'create a record', twice -- and the second
        create is refused for colliding with the first, which is a correct refusal that looks like a
        broken instruction."""
        steps = _steps(APEX_RECORDS, "coderbay.net", "route53")
        self.assertEqual([s["type"] for s in steps], ["A", "AAAA", "CNAME"])
        self.assertEqual(steps[0]["values"], ["104.21.88.48", "172.67.173.6"])
        self.assertEqual(steps[1]["values"],
                         ["2606:4700:3033::6815:5830", "2606:4700:3030::ac43:ad06"])
        self.assertIn("ONE record", steps[0]["valueNote"])
        self.assertEqual(steps[2]["valueNote"], "")      # a single value says nothing

    def test_a_subdomain_connect_is_unchanged(self):
        # The ordinary case must not acquire apex copy: one CNAME, a sub-label, no notes.
        records = [{"type": "CNAME", "name": "shop.coderbay.net", "value": "domains.jbay.be"},
                   {"type": "CNAME", "name": "_acme-challenge.shop.coderbay.net", "value": "x.dcv"}]
        steps = _steps(records, "shop.coderbay.net", "route53")
        self.assertEqual([s["displayName"] for s in steps], ["shop", "_acme-challenge.shop"])
        self.assertEqual([s["nameNote"] for s in steps], ["", ""])
        self.assertFalse(any(s["nameIsBlank"] for s in steps))

    def test_the_certificate_record_is_still_its_own_step(self):
        # Grouping is by type AND name, so the DCV CNAME never folds into the routing records.
        steps = _steps(APEX_RECORDS, "coderbay.net", "route53")
        self.assertTrue(steps[-1]["isSsl"])
        self.assertEqual(steps[-1]["displayName"], "_acme-challenge")

    def test_the_component_renders_through_the_composable(self):
        """The rules live in one place. A copy of `@` left in the component would be a second answer that
        only one of the two screens obeys."""
        vue = SITES_VUE.read_text(encoding="utf-8")
        self.assertIn("dnsRecordSteps", vue)
        self.assertNotIn('if (fullName === root) return "@"', vue)
        self.assertIn("rec.nameIsBlank", vue)
        self.assertIn('v-for="v in rec.values"', vue)


if __name__ == "__main__":
    unittest.main()


class ProviderDetectionTests(unittest.TestCase):
    """Reading the provider off the domain's own nameservers, instead of a `<select>` defaulting to
    Route 53.

    The default was harmless while every provider got the same advice. It stopped being harmless when the
    advice started differing in KIND — "add an ALIAS record" versus "your provider cannot do this at
    all" — because then a wrong default is not vague, it is confidently wrong in the expensive direction.
    """

    def _detect(self, nameservers):
        script = f"""
        import {{ detectProvider }} from {json.dumps(str(MODULE))};
        console.log(JSON.stringify(detectProvider({json.dumps(nameservers)})));
        """
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, cwd=ROOT, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def _advice(self, domain, provider):
        script = f"""
        import {{ apexAdvice }} from {json.dumps(str(MODULE))};
        console.log(JSON.stringify(apexAdvice({json.dumps(domain)}, {json.dumps(provider)})));
        """
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, cwd=ROOT, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def test_each_provider_is_recognised_from_its_nameservers(self):
        # coderbay.net's real nameservers are the Route 53 case, verbatim.
        self.assertEqual(self._detect(["ns-334.awsdns-41.com.", "ns-1297.awsdns-34.org.",
                                       "ns-2027.awsdns-61.co.uk."]), "route53")
        self.assertEqual(self._detect(["ns1-05.azure-dns.com.", "ns2-05.azure-dns.net."]), "azure")
        self.assertEqual(self._detect(["kim.ns.cloudflare.com.", "walt.ns.cloudflare.com."]), "cloudflare")
        self.assertEqual(self._detect(["ns-cloud-a1.googledomains.com."]), "googlecloud")
        self.assertEqual(self._detect(["ns01.domaincontrol.com."]), "godaddy")
        self.assertEqual(self._detect(["dns1.registrar-servers.com."]), "namecheap")
        self.assertEqual(self._detect(["ns1.digitalocean.com."]), "digitalocean")

    def test_a_cpanel_host_is_recognised_by_the_names_cpanel_publishes(self):
        """cPanel almost always runs vanity nameservers, so the NS name itself says nothing. The names
        cPanel publishes are the only hint DNS gives -- its service ports (2082/2083, 2086/2087) are not
        reachable from a browser."""
        self.assertEqual(self._detect(["cpanel.somehost.com."]), "cpanel")
        self.assertEqual(self._detect(["webmail.somehost.com."]), "cpanel")

    def test_azure_is_warned_like_route53(self):
        advice = self._advice("coderbay.net", "azure")
        self.assertEqual(advice["reason"],
                         "The apex domain (coderbay.net) can't be pointed at an external host from "
                         "Azure DNS. Use www.coderbay.net instead.")
        self.assertIn("Front Door", advice["fix"])      # Azure DNS cannot redirect on its own

    def test_google_cloud_dns_is_not_warned_because_it_can(self):
        # It has an apex ALIAS, reachable via gcloud/API. Classifying it with Route 53 would tell a
        # tenant to give up a root domain that works.
        self.assertIsNone(self._advice("coderbay.net", "googlecloud"))

    def test_an_unclassified_provider_is_not_told_to_give_up(self):
        # DigitalOcean and cPanel are deliberately unverified either way. The harmless failure is to show
        # the generic ALIAS instruction; the harmful one is to tell someone their domain cannot work.
        for provider in ("digitalocean", "cpanel", ""):
            self.assertIsNone(self._advice("coderbay.net", provider), provider)

    def test_an_unrecognised_provider_does_not_guess(self):
        # Falls through to the generic apex instruction rather than asserting someone's DNS is Route 53.
        self.assertEqual(self._detect(["a.iana-servers.net."]), "")
        self.assertEqual(self._detect([]), "")

    def test_an_apex_on_a_provider_that_cannot_is_warned_before_connecting(self):
        advice = self._advice("coderbay.net", "route53")
        self.assertEqual(advice["suggestion"], "www.coderbay.net")
        self.assertEqual(advice["reason"],
                         "The apex domain (coderbay.net) can't be pointed at an external host from "
                         "AWS Route 53. Use www.coderbay.net instead.")

    def test_godaddy_is_pointed_at_its_own_forwarding(self):
        # It has one, and it carries HTTPS automatically — so for GoDaddy the redirect is genuinely easy.
        self.assertIn("Domain Forwarding", self._advice("coderbay.net", "godaddy")["fix"])

    def test_route53_is_not_promised_a_redirect_it_does_not_have(self):
        # Route 53 has no redirect of its own, and the usual S3 answer is HTTP-only. Saying "just forward
        # it" would be the third confidently-wrong instruction on this domain.
        fix = self._advice("coderbay.net", "route53")["fix"]
        self.assertIn("S3", fix)
        self.assertIn("HTTPS needs CloudFront", fix)

    def test_a_subdomain_under_a_multipart_tld_is_not_mistaken_for_an_apex(self):
        self.assertIsNone(self._advice("shop.example.co.uk", "route53"))
        self.assertIsNotNone(self._advice("example.co.uk", "route53"))

    def test_nothing_is_said_when_there_is_nothing_to_warn_about(self):
        self.assertIsNone(self._advice("shop.coderbay.net", "route53"))   # a subdomain is fine anywhere
        self.assertIsNone(self._advice("coderbay.net", "namecheap"))      # ALIAS at the root
        self.assertIsNone(self._advice("coderbay.net", "cloudflare"))     # flattening
        self.assertIsNone(self._advice("", "route53"))
