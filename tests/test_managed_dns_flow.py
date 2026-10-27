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

    def test_the_five_states_come_from_the_server(self):
        self.assertEqual(node("m.managedDnsState(null, null)"), "choose")
        self.assertEqual(node('m.managedDnsState({zone_id:"z"}, {blocked:true})'), "blocked")
        # Unconfirmed is REVIEW, not delegate: the tenant reads what was imported before we hand over
        # the one irreversible instruction.
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"pending"}, {blocked:false})'),
                         "review")
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"pending",'
                              'review:{confirmed_at:1}}, {blocked:false})'), "delegate")
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


class PanelOrderTests(unittest.TestCase):
    """Three things a first organic run surfaced, none of which a test could have predicted."""

    def test_the_apex_warning_comes_after_the_two_choices(self):
        """Typing an AWS domain fired it before the tenant had chosen anything, so the first thing they
        read was an intimidating "you can't do that" about a limitation one of the two cards removes
        entirely. Offer the choice first; qualify the second option afterwards."""
        cards = SITES_VUE.index("dnsChoice = 'own'")
        warning = SITES_VUE.index("connectAdvice && dnsChoice !== 'managed'")
        self.assertLess(cards, warning)

    def test_the_warning_is_framed_as_being_about_the_other_choice(self):
        self.assertIn("If you keep your DNS where it is:", SITES_VUE)

    def test_the_wait_looks_like_it_is_working(self):
        """A line of grey text is indistinguishable from a page that has stopped doing anything, which
        is exactly what a tenant staring at it is trying to find out."""
        self.assertIn("managed-spinner", SITES_VUE)
        self.assertIn("managedChecks", SITES_VUE)
        # Someone watching a nameserver change for ten minutes does not need it animating at them.
        self.assertIn("prefers-reduced-motion", SITES_VUE)

    def test_the_connected_domain_stays_in_the_box(self):
        """It showed its `shop.yourbrand.com` placeholder while the banner underneath said the domain was
        live -- reading as "nothing is connected" and "it is connected" at once."""
        load = SITES_VUE.split("async function loadManagedDns", 1)[1].split("watch(", 1)[0]
        self.assertIn("domainForm.domain = res.zone.domain", load)

    def test_the_site_is_re_read_once_the_domain_attaches(self):
        # Activation attaches the domain server-side; without this the panel keeps rendering from a copy
        # taken before that happened, and never notices it is connected.
        poll = SITES_VUE.split("async function pollManagedDns", 1)[1].split("async function", 1)[0]
        self.assertIn("store.load()", poll)
        self.assertIn("editing.value = { ...fresh }", poll)


class AdviceLifetimeTests(unittest.TestCase):
    def test_a_detection_call_that_was_not_asked_to_advise_leaves_advice_alone(self):
        """The apex warning stopped appearing at all, and the cause was a shared lookup token.

        `detectDnsProvider` assigned `null` on its else branch, so the OTHER caller -- the watcher that
        detects the provider for an already-connected domain -- wiped advice about the domain being
        typed. Both share `providerLookup`, so whichever landed second won; after a successful managed
        run the connected-domain watcher always landed second.
        """
        fn = SITES_VUE.split("async function detectDnsProvider", 1)[1].split("\n}", 1)[0]
        self.assertIn("if (advise) connectAdvice.value", fn)
        self.assertNotIn("connectAdvice.value = advise ?", fn)


class ReversibleChoiceTests(unittest.TestCase):
    def test_a_choice_can_be_unmade(self):
        """Picking a card hid both of them, so the only way back was a hard refresh — after the tenant
        had already typed their domain."""
        self.assertIn('@click="dnsChoice = \'\'"', SITES_VUE)
        self.assertIn("dns-chosen", SITES_VUE)

    def test_only_while_nothing_has_been_created(self):
        # Once a zone exists, backing out is "Move this domain elsewhere" -- a different, heavier thing
        # that deletes a zone and hands back a file, not a toggle.
        self.assertIn('v-if="dnsChoice && (managedState === CHOOSE || managedState === DETECTED)"', SITES_VUE)


class WwwGuardTests(unittest.TestCase):
    """Typing `www.example.com` and choosing managed DNS.

    The server already normalises to the registrable root, so nothing breaks — but a backstop the screen
    contradicts is a backstop that confuses. The box would keep saying www while the nameserver step,
    the banner and the live domain all said the root, and the tenant would have no idea which of the two
    the product thought it was doing.
    """

    def test_choosing_managed_rewrites_a_subdomain_to_the_root(self):
        self.assertIn("domainForm.domain = managedRoot.value", SITES_VUE)
        self.assertIn("watch(dnsChoice", SITES_VUE)

    def test_it_says_why_rather_than_silently_editing_what_they_typed(self):
        """Silently changing someone's input is its own small betrayal; saying what happened costs one
        line and makes the rest of the flow legible."""
        self.assertIn("managedNarrowedFrom", SITES_VUE)
        self.assertIn("covers your whole domain", SITES_VUE)

    def test_the_note_clears_when_they_switch_back(self):
        watcher = SITES_VUE.split("watch(dnsChoice", 1)[1].split("});", 1)[0]
        self.assertIn('managedNarrowedFrom.value = ""', watcher)
        self.assertIn('if (choice !== "managed") return', watcher)

    def test_an_apex_is_left_exactly_as_typed(self):
        # The common case must not acquire a note about something that did not happen.
        watcher = SITES_VUE.split("watch(dnsChoice", 1)[1].split("});", 1)[0]
        self.assertIn("typed !== managedRoot.value", watcher)


class ConnectedBranchTests(unittest.TestCase):
    """A managed domain IS connected, so it lands in the connected branch — which used to offer the
    custom-hostname Disconnect.

    That button clears the Site and leaves the Cloudflare zone on our account with the tenant's
    nameservers still pointing at it: the orphan this feature spent a day learning not to make, reached
    by the most obvious button on the screen.
    """

    def test_a_managed_domain_is_recognised_from_the_site(self):
        # Off the Site, not off `managedZone`: the Site is what the connected branch renders from and is
        # authoritative the moment the panel loads, while the zone arrives a request later.
        self.assertIn('verification?.method || "") === "managed_dns"', SITES_VUE)

    def test_it_is_offered_the_right_exit(self):
        branch = SITES_VUE.split('v-if="isManagedDomain"', 1)[1].split('v-if="!isManagedDomain', 1)[0]
        self.assertIn("Move this domain elsewhere", branch)
        self.assertIn("leaveManagedDns", branch)

    def test_the_custom_hostname_disconnect_is_withheld_from_it(self):
        self.assertIn('v-if="!isManagedDomain" class="button-row"', SITES_VUE)
        self.assertIn('v-if="!isManagedDomain && !editing.hosting.verification?.verified"', SITES_VUE)

    def test_leaving_returns_the_panel_to_a_usable_state(self):
        # The Site is detached server-side; without re-reading it the panel keeps rendering the
        # connected branch for a domain it no longer has.
        leave = SITES_VUE.split("async function leaveManagedDns", 1)[1].split("\n}", 1)[0]
        for expected in ("store.load()", "editing.value = { ...fresh }", 'dnsChoice.value = ""'):
            self.assertIn(expected, leave, expected)


class ExitBannerTests(unittest.TestCase):
    def test_it_appears_even_when_the_originals_are_unknown(self):
        """An empty list is something to REPORT, not a reason to say nothing. The banner is gated on
        having left, not on having nameservers to offer."""
        self.assertIn("managedLeft", SITES_VUE)
        self.assertIn('v-if="managedLeft"', SITES_VUE)

    def test_it_says_so_rather_than_offering_our_own(self):
        self.assertIn("do not have this domain's previous nameservers on file", SITES_VUE)
        self.assertIn("the zone here is gone", SITES_VUE)

    def test_known_originals_are_presented_as_what_they_are(self):
        self.assertIn("they are the ones\n                    this domain used before us", SITES_VUE)


class ConfirmStepTests(unittest.TestCase):
    """A clean review used to go straight to the nameservers.

    The summary of what we had imported was computed and then shown to nobody — the one screen that
    tells a tenant what we are about to take responsibility for. "There is no message about how many
    records there are", and there wasn't: it only ever appeared when the review objected.
    """

    def test_a_clean_review_stops_to_be_read(self):
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"pending",'
                              'review:{blocked:false}}, {blocked:false})'), "review")

    def test_and_moves_on_once_confirmed(self):
        self.assertEqual(node('m.managedDnsState({zone_id:"z",status:"pending",'
                              'review:{blocked:false,confirmed_at:1}}, {blocked:false})'), "delegate")

    def test_the_confirmation_lives_on_the_zone_not_in_the_tab(self):
        # A confirmation that survives only in one browser tab is not a confirmation — reload and the
        # tenant would be asked again, or worse, waved through.
        self.assertIn("zone.review.confirmed_at", node_source())

    def test_the_summary_says_what_was_read(self):
        self.assertEqual(node('m.importSummary({review:{records:21,mail_count:5,'
                              'provider:"Google Workspace"}})'),
                         "21 records imported · 5 of them mail · Google Workspace")
        self.assertEqual(node('m.importSummary({review:{records:3,mail_count:0}})'),
                          "3 records imported · none of them mail")

    def test_the_screen_warns_about_what_cannot_be_discovered(self):
        # The limit is real and the tenant is the only one who can cover it: DKIM keys and validation
        # records have random names, and DNS cannot list a zone.
        review = SITES_VUE.split("managedState === REVIEW", 1)[1].split("managedState === DELEGATE", 1)[0]
        self.assertIn("cannot be discovered", review)
        self.assertIn("Cancel", review)


def node_source():
    return (ROOT / "dashboard" / "src" / "composables" / "managedDns.js").read_text(encoding="utf-8")


class ExplicitWatchTests(unittest.TestCase):
    """Nothing is happening until the tenant changes the nameservers.

    Polling used to begin the moment they appeared, which asserted progress nobody had made and offered
    no way to stop or back out. It also made the panel claim "you can close this and come back; it keeps
    running", which was never true -- an interval dies with the page.
    """

    def test_watching_starts_off(self):
        self.assertIn("const managedWatching = ref(false)", SITES_VUE)

    def test_the_tenant_says_when_they_are_ready(self):
        self.assertIn("I've updated my nameservers", SITES_VUE)
        self.assertIn('v-if="!managedWatching"', SITES_VUE)

    def test_there_is_a_way_back_out(self):
        # Cancel goes through the normal exit, which deletes the zone -- nothing has been delegated yet,
        # so abandoning is the correct outcome rather than leaving an orphan on our account.
        delegate = SITES_VUE.split("managedState === DELEGATE", 1)[1].split("managedState === LIVE", 1)[0]
        self.assertIn("leaveManagedDns", delegate)
        self.assertIn("Cancel", delegate)

    def test_and_a_way_to_stop_checking(self):
        self.assertIn("stopManagedWatching", SITES_VUE)

    def test_the_promise_matches_what_actually_happens(self):
        # An interval dies with the page; saying otherwise is a small lie that costs trust later.
        self.assertIn("stops when you close the page", SITES_VUE)
        self.assertNotIn("it keeps running", SITES_VUE)


class VerdictSurvivesReloadTests(unittest.TestCase):
    def test_the_stored_review_comes_back_with_the_zone(self):
        """The third door onto the same bypass. `status` returned no review, so a reload dropped a
        BLOCKED verdict, the state fell through to DELEGATE, and the gate was skipped by pressing F5."""
        # The whole review now comes back, not just whether it objected -- the counts are what the
        # confirm screen is made of, and they have to survive a reload too.
        self.assertIn("managedReview.value = res.review ?", SITES_VUE)

    def test_the_endpoint_carries_it(self):
        import pathlib
        api = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
               / "managed_dns_api.py").read_text(encoding="utf-8")
        self.assertIn('"review": record.get("review") or {}', api)


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

    def test_the_panel_reconstitutes_an_in_progress_zone_on_load(self):
        """Without this a tenant who closes the tab mid-flow comes back to a blank "choose" screen --
        with a zone on our account and their nameservers already changed, and nothing on screen to
        finish it or undo it. The exit existed in the API and was unreachable from the UI."""
        self.assertIn("loadManagedDns", SITES_VUE)
        self.assertIn("watch(() => editing.value?.site_id", SITES_VUE)
        # Asked WITHOUT a domain, because not knowing it is the returning tenant's situation.
        self.assertIn("store.managedDnsStatus(siteId)", SITES_VUE)
        self.assertIn("domain = \"\"", STORE)

    def test_switching_sites_does_not_carry_the_previous_zone_across(self):
        load = SITES_VUE.split("async function loadManagedDns", 1)[1].split("watch(", 1)[0]
        for cleared in ("managedZone.value = null", "managedReview.value = null",
                        "clearInterval(managedPoll)"):
            self.assertIn(cleared, load, cleared)

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


class OfferedOnlyAfterCheckingTests(unittest.TestCase):
    """The two choice cards must not appear before we know which routes are available.

    Found on a real screen, 2026-10-27: typing an AWS-hosted domain drew both cards immediately, with
    "Let us handle the DNS" marked **Recommended** -- the one route that would then be refused, and the
    tenant only discovered it after choosing. A recommendation made before the check is not a
    recommendation, so the cards now wait for the verdict.
    """

    def test_the_cards_require_an_eligible_verdict(self):
        self.assertIn('v-else-if="domainForm.domain && !dnsChoice && managedDetection?.eligible" class="dns-choice"',
                      SITES_VUE)

    def test_a_refusal_is_explained_where_the_choice_would_have_been(self):
        self.assertIn('managedDetection && !managedDetection.eligible', SITES_VUE)

    def test_something_is_shown_while_checking(self):
        # Otherwise the panel is simply blank for the length of a DNS lookup, which reads as broken.
        self.assertIn('Checking this domain\'s DNS…', SITES_VUE)

    def test_the_apex_banner_drops_its_conditional_lead_in_when_there_is_no_choice(self):
        """"If you keep your DNS where it is" implies an alternative. For a domain we will not move,
        keeping their own DNS is the only route and the "if" is a lie about what is on offer."""
        self.assertIn('v-if="managedDetection?.eligible"', SITES_VUE)

    def test_detection_runs_from_the_domain_watcher_not_only_a_button(self):
        self.assertIn("readMyDns(domain);", SITES_VUE)

    def test_the_lookup_is_race_guarded(self):
        """It runs while someone is typing, so an earlier slow answer must not overwrite a later one --
        the same guard the provider lookup already needed."""
        self.assertIn("if (token !== detectionLookup) return;", SITES_VUE)
