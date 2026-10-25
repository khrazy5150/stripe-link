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
        # Route 53 has no redirect of its own, so "just forward it" would be a confidently-wrong
        # instruction. It names what actually answers HTTP, and points at the step that walks through it
        # rather than compressing a four-resource recipe into a sentence.
        fix = self._advice("coderbay.net", "route53")["fix"]
        self.assertIn("CloudFront", fix)
        self.assertIn("answers HTTP", fix)
        self.assertNotIn("S3", fix)

    def test_a_subdomain_under_a_multipart_tld_is_not_mistaken_for_an_apex(self):
        self.assertIsNone(self._advice("shop.example.co.uk", "route53"))
        self.assertIsNotNone(self._advice("example.co.uk", "route53"))

    def test_nothing_is_said_when_there_is_nothing_to_warn_about(self):
        self.assertIsNone(self._advice("shop.coderbay.net", "route53"))   # a subdomain is fine anywhere
        self.assertIsNone(self._advice("coderbay.net", "namecheap"))      # ALIAS at the root
        self.assertIsNone(self._advice("coderbay.net", "cloudflare"))     # flattening
        self.assertIsNone(self._advice("", "route53"))


class ApexRedirectStepTests(unittest.TestCase):
    """The optional last step: make the apex land on the www hostname the tenant connected.

    Without it the root is orphaned — someone who types `example.com` gets NXDOMAIN and concludes the
    business is gone, which is exactly the limbo a Route 53 tenant is left in after taking our advice to
    connect `www`. It is OPTIONAL and has to read that way: the site works without it, and a step that
    looks outstanding on a verified domain is a notice with no action behind it.
    """

    def _step(self, domain, provider, target="domains.jbay.be"):
        script = f"""
        import {{ apexRedirectStep }} from {json.dumps(str(MODULE))};
        console.log(JSON.stringify(apexRedirectStep({json.dumps(domain)}, {json.dumps(provider)}, {json.dumps(target)})));
        """
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, cwd=ROOT, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def test_offered_only_when_the_apex_is_actually_orphaned(self):
        self.assertIsNotNone(self._step("www.coderbay.net", "route53"))
        # A connected apex already provisions its own www→apex redirect, and a plain subdomain has no
        # orphaned root to rescue. Offering it there would be noise.
        self.assertIsNone(self._step("coderbay.net", "route53"))
        self.assertIsNone(self._step("shop.coderbay.net", "route53"))

    def test_it_is_marked_optional_and_says_the_site_works_without_it(self):
        step = self._step("www.coderbay.net", "route53")
        self.assertTrue(step["optional"])
        self.assertIn("Optional", step["note"])
        self.assertIn("works without this", step["note"])

    def _node(self, expr):
        script = f"""
        import * as m from {json.dumps(str(MODULE))};
        console.log(JSON.stringify({expr}));
        """
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                                capture_output=True, text=True, cwd=ROOT, timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def test_the_walkthrough_closes_the_gaps_a_first_timer_actually_hit(self):
        """Each of these is a place the author stopped, doing it by hand on 2026-10-25.

        The instructions had been written for someone who already knows the AWS console. They are a
        walkthrough now, which is a different thing: the console moves you between three services, and
        every handoff is somewhere to get lost.
        """
        lines = " ".join(self._step("www.coderbay.net", "route53")["instructions"])
        # The region has to be switched there AND back -- obvious to us, invisible to a first-timer, and
        # leaving the console on us-east-1 makes every other resource they own look deleted.
        self.assertIn("N. Virginia", lines)
        self.assertIn("Switch the region back", lines)
        # An empty required field with a format rule is where people freeze, so name it for them.
        self.assertIn("redirect-coderbay-net-to-www", lines)
        self.assertIn("cloudfront-js-2.0", lines)
        # Publishing without associating is the silent failure: it looks finished and does nothing.
        self.assertIn("Viewer request", lines)
        self.assertIn("published but not associated", lines)
        # The value carried between two services, and the exact Route 53 controls once you are there.
        self.assertIn("Domain name (standard)", lines)
        self.assertIn("Record name blank", lines)
        self.assertIn("Alias to CloudFront distribution", lines)

    def test_the_decisive_details_are_emphasised(self):
        # A walkthrough where the one value that must be exact sits in the middle of a grey paragraph is
        # a walkthrough that gets misread.
        step = self._step("www.coderbay.net", "route53")
        bold = {seg["text"] for line in step["instructions"]
                for seg in self._node(f"m.emphasise({json.dumps(line)})") if seg["bold"]}
        for decisive in ("us-east-1 / N. Virginia", "Issued", "Viewer request", "A",
                         "Alias to CloudFront distribution", "cloudfront-js-2.0"):
            self.assertIn(decisive, bold, decisive)

    def test_emphasis_is_segments_not_markup(self):
        # These strings interpolate a tenant's domain. The day one of them is parsed as markup instead of
        # text, it stops being a styling choice.
        self.assertEqual(self._node('m.emphasise("plain **bold** plain")'),
                         [{"text": "plain ", "bold": False}, {"text": "bold", "bold": True},
                          {"text": " plain", "bold": False}])
        self.assertEqual(self._node('m.emphasise("")'), [])
        self.assertEqual(self._node('m.emphasise("<script>x</script>")'),
                         [{"text": "<script>x</script>", "bold": False}])

    def test_route53_gets_one_route_and_it_is_the_one_that_serves_https(self):
        """S3 is deliberately absent.

        Every guide online offers the S3-website-bucket redirect as the simple option, and it is a dead
        end: those endpoints cannot serve HTTPS, and no business page is served over plain HTTP. Offering
        two routes where one of them silently breaks `https://example.com` is worse than offering one.
        """
        step = self._step("www.coderbay.net", "route53")
        lines = " ".join(step["instructions"])
        self.assertIn("us-east-1", lines)              # ACM region, the usual first mistake
        self.assertIn("CloudFront", lines)
        self.assertIn("Alias", lines)
        self.assertNotIn("S3", lines)
        self.assertNotIn("bucket", lines.lower())
        # Requesting a second certificate for a domain that already has one is a quiet way to waste
        # someone's afternoon on DNS validation they did not need.
        self.assertIn("already exists", lines)

    def test_the_cloudfront_function_is_handed_over_not_described(self):
        # It is the one piece a tenant cannot reasonably guess, and the shape is exact -- AWS's own
        # example returns {statusCode, statusDescription, headers:{location:{value}}}.
        code = self._step("www.coderbay.net", "route53")["code"]
        self.assertIn("function handler(event)", code)
        self.assertIn("statusCode: 301", code)
        self.assertIn("statusDescription: 'Moved Permanently'", code)
        self.assertIn("headers: { location: { value: 'https://www.coderbay.net'", code)
        self.assertIn("event.request.uri", code)

    def test_the_function_preserves_the_query_string(self):
        # On an ad platform this is not a nicety: dropping ?utm_source kills attribution for every
        # visitor who typed the root instead of the www address.
        code = self._step("www.coderbay.net", "route53")["code"]
        self.assertIn("event.request.querystring", code)
        self.assertIn("search", code)

    def test_only_route53_carries_code(self):
        # GoDaddy has a checkbox; handing it a CloudFront function would be noise.
        for provider in ("godaddy", "cloudflare", "namecheap", "azure", ""):
            self.assertEqual(self._step("www.coderbay.net", provider)["code"], "", provider)

    def test_godaddy_gets_its_own_feature_not_a_cloudfront_recipe(self):
        lines = " ".join(self._step("www.coderbay.net", "godaddy")["instructions"])
        self.assertIn("Forwarding", lines)
        self.assertNotIn("CloudFront", lines)

    def test_apex_capable_providers_are_offered_the_better_answer_first(self):
        # Serving the root beats bouncing it. A tenant on Cloudflare or Namecheap connected www by
        # choice or by accident; either way they should know the root can simply serve.
        for provider in ("cloudflare", "namecheap", "googlecloud"):
            first = self._step("www.coderbay.net", provider)["instructions"][0]
            self.assertIn("DIRECTLY", first, provider)
            self.assertIn("domains.jbay.be", first, provider)

    def test_the_target_hostname_is_the_one_the_site_was_actually_given(self):
        # Not a hardcoded jbay.uk: the two deployments hand out different fallback origins, and this
        # step is read beside the CNAME row that names the real one.
        first = self._step("www.coderbay.net", "cloudflare", "domains.jbay.uk")["instructions"][0]
        self.assertIn("domains.jbay.uk", first)

    def test_an_unknown_provider_is_told_the_truth_about_dns(self):
        lines = " ".join(self._step("www.coderbay.net", "")["instructions"])
        self.assertIn("301", lines)
        # The sentence that stops someone hunting for a record type that does not exist.
        self.assertIn("nothing in DNS will do it", lines)

    def test_the_component_renders_it_without_a_pass_fail_badge(self):
        vue = SITES_VUE.read_text(encoding="utf-8")
        self.assertIn("apexRedirectStep", vue)
        self.assertIn('statusText: "Optional"', vue)
        self.assertIn("rec.instructions", vue)
