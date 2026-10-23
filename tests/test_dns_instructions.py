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
