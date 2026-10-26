"""The managed-DNS dashboard flow (plans/MANAGED_DNS.md P4).

Which state the screen is in is decided by the SERVER on every poll, never inferred from what the UI
last did — because every interesting failure here is "the server knows something the screen does not":
a mail record the import missed, a delegation half the internet can see.
"""

import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "dashboard" / "src" / "composables" / "managedDns.js"
SITES_VUE = (ROOT / "dashboard" / "src" / "components" / "Sites.vue").read_text(encoding="utf-8")
STORE = (ROOT / "dashboard" / "src" / "stores" / "sites.js").read_text(encoding="utf-8")


def node(expr):
    script = f"import * as m from {json.dumps(str(MODULE))}; console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, cwd=ROOT, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node is not available")

    def test_the_four_states_come_from_the_server(self):
        self.assertEqual(node("m.managedDnsState(null, null)"), "choose")
        self.assertEqual(node('m.managedDnsState({zone_id:"z"}, {blocked:true})'), "blocked")
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"pending"}, {blocked:false})'),
                         "delegate")
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"active"}, {blocked:false})'),
                         "live")

    def test_active_wins_over_a_stale_blocked_review(self):
        """A review is a snapshot; the zone's status is current. If Cloudflare says the delegation is
        live, the screen must not still be showing a gate the tenant already cleared."""
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"active"}, {blocked:true})'), "live")


class InstructionTests(unittest.TestCase):
    def test_route53_is_pointed_at_the_registrar_not_the_hosted_zone(self):
        """The hour-costing distinction. The hosted zone contains an NS record that looks exactly like
        the setting to change, and editing it does nothing — the registrar is what the internet asks."""
        lines = " ".join(node('m.nameserverInstructions("route53", "example.com")'))
        self.assertIn("Registered domains", lines)
        self.assertIn("Not the hosted zone", lines)

    def test_a_cloudflare_tenant_is_told_there_is_nothing_to_do(self):
        # Their DNS is already here; sending them to change nameservers would be busywork that breaks
        # a working setup.
        lines = " ".join(node('m.nameserverInstructions("cloudflare", "example.com")'))
        self.assertIn("already on Cloudflare", lines)

    def test_an_unknown_registrar_gets_the_distinction_that_actually_trips_people(self):
        lines = " ".join(node('m.nameserverInstructions("", "example.com")'))
        self.assertIn("registrar", lines)
        self.assertIn("may not be where its DNS is edited", lines)
        self.assertIn("Replace every entry", lines)


class WaitingTests(unittest.TestCase):
    def test_the_early_wait_does_not_suggest_anything_is_wrong(self):
        # Measured on the live run: Cloudflare saw the delegation in 3m30s. A tenant refreshing at two
        # minutes is watching DNS work exactly as designed.
        self.assertIn("usually takes a few minutes", node("m.waitingMessage(60)"))

    def test_the_long_wait_still_says_this_is_normal(self):
        message = node("m.waitingMessage(900)")
        self.assertIn("that is normal", message)
        self.assertIn("come back", message)

    def test_only_after_an_hour_does_it_suggest_a_mistake_and_name_it(self):
        message = node("m.waitingMessage(7200)")
        self.assertIn("REGISTRAR", message)
        self.assertIn("replaced every entry", message)


class MailSummaryTests(unittest.TestCase):
    def test_it_is_phrased_to_be_checkable_not_audited(self):
        summary = node('m.mailSummary({mail:{present:true,provider:"Google Workspace",spf:true,'
                       'dmarc:true,dkim:["google"]}})')
        self.assertEqual(summary, "Mail is handled by Google Workspace · SPF · DMARC · 1 DKIM key")

    def test_an_unrecognised_host_still_gets_a_count(self):
        self.assertIn("2 mail servers", node('m.mailSummary({mail:{present:true,mx_count:2}})'))

    def test_no_mail_says_the_dangerous_thing_out_loud(self):
        self.assertIn("stop and tell us", node('m.mailSummary({mail:{present:false}})'))


class RootDomainTests(unittest.TestCase):
    """Nameservers belong to the REGISTERED domain. There is no registered domain called
    `www.example.com`, so sending someone to find one in Route 53's Registered domains list sends them
    to find nothing — which is what the first real run did."""

    def test_the_registrar_instruction_names_the_root_whatever_was_typed(self):
        for typed in ("www.creditfix.cloud", "creditfix.cloud", "shop.creditfix.cloud"):
            line = node(f'm.nameserverInstructions("route53", {json.dumps(typed)})')[0]
            self.assertIn("creditfix.cloud", line)
            self.assertNotIn("www.creditfix.cloud", line, typed)

    def test_a_multipart_tld_is_not_truncated_to_the_public_suffix(self):
        line = node('m.nameserverInstructions("route53", "shop.example.co.uk")')[0]
        self.assertIn("example.co.uk", line)


class ApexAdviceTests(unittest.TestCase):
    def test_the_apex_warning_is_suppressed_once_managed_dns_is_chosen(self):
        """There the apex is exactly what works — it is the whole reason the option exists — so "use www
        instead" does not merely duplicate, it talks the tenant out of the thing they just chose. It did,
        on the first run through the UI."""
        self.assertIn("connectAdvice && dnsChoice !== 'managed'", SITES_VUE)


class WiringTests(unittest.TestCase):
    def test_the_component_renders_every_state(self):
        # Named once: `<script setup>` exposes the imported constants to the template, so the state
        # names are not written as literals in one place and constants in the other.
        for marker in ("managedState === CHOOSE", "managedState === BLOCKED",
                       "managedState === DELEGATE", "managedState === LIVE"):
            self.assertIn(marker, SITES_VUE, marker)

    def test_no_state_falls_through_to_the_live_message(self):
        """The live branch is named, not a bare v-else. "Your domain is live" is the one message that
        must never be shown on a guess, and a fifth state added later would land in an else."""
        self.assertNotIn("<template v-else>", SITES_VUE.split("managed-dns", 1)[1].split("</div>", 1)[0])

    def test_the_gate_is_shown_instead_of_the_nameservers_not_beside_them(self):
        blocked = SITES_VUE.split("managedState === BLOCKED", 1)[1].split("</template>", 1)[0]
        self.assertNotIn("managedNameServers", blocked)

    def test_keeping_your_own_dns_remains_available(self):
        # Recommended is not the same as forced; a tenant whose IT owns their DNS must still get through.
        self.assertIn("dnsChoice = 'own'", SITES_VUE)
        self.assertIn('v-if="dnsChoice !== \'managed\'"', SITES_VUE)

    def test_polling_stops_when_the_zone_goes_live(self):
        # A poll that runs forever on a forgotten tab is a cost nobody sees.
        self.assertIn("clearInterval(managedPoll)", SITES_VUE)
        self.assertIn("onBeforeUnmount", SITES_VUE)

    def test_the_exit_hands_over_a_file_and_the_old_nameservers(self):
        self.assertIn("zone_file", SITES_VUE)
        self.assertIn("managedRestoreTo", SITES_VUE)
        self.assertIn("stopManagedDns", STORE)

    def test_the_zone_is_addressed_by_domain_not_by_site(self):
        # It outlives any one Site's claim on that hostname, so the API keys on the domain.
        self.assertIn("managed-dns?domain=", STORE)


if __name__ == "__main__":
    unittest.main()
