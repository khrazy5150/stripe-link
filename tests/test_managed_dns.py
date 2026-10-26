"""Taking over a tenant's DNS without taking down their email (plans/MANAGED_DNS.md).

Moving a tenant's zone to Cloudflare removes the apex limit outright — on Route 53 the alternative is a
certificate, a distribution, a function and an alias record just to redirect a root domain. The price is
that we become authoritative for everything else the domain does, and the part that matters is MAIL.

Cloudflare's import scan is best-effort and its own docs name email records and non-default DKIM
selectors as the usual misses. So the review does not show the scan and ask for a nod: it compares the
scan against what live DNS actually answers, and a discrepancy blocks the nameserver change. These tests
are that comparison.
"""

import unittest

from stripe_link.domain.managed_dns import (
    MAIL,
    OTHER,
    SERVING,
    VERIFICATION,
    classify_record,
    mail_discrepancies,
    mail_provider,
    managed_zone_record,
    review,
    serving_records,
    zone_export,
    zone_state,
)

# Cloudflare's own shape: content is the host, priority is its own field. The zone-file shape (priority
# inside content) reaches the same code from exports and hand-entered records, so both are exercised.
GOOGLE_MX = [
    {"type": "MX", "name": "example.com", "content": "aspmx.l.google.com", "priority": 1},
    {"type": "MX", "name": "example.com", "content": "alt1.aspmx.l.google.com", "priority": 5},
]
ZONE_FILE_MX = {"type": "MX", "name": "example.com", "content": "1 aspmx.l.google.com"}
SPF = {"type": "TXT", "name": "example.com", "content": "v=spf1 include:_spf.google.com ~all"}
DMARC = {"type": "TXT", "name": "_dmarc.example.com", "content": "v=DMARC1; p=none"}
DKIM = {"type": "TXT", "name": "google._domainkey.example.com", "content": "v=DKIM1; k=rsa; p=MIGf"}
WEB = {"type": "A", "name": "example.com", "content": "203.0.113.10"}


class ProviderNamingTests(unittest.TestCase):
    """"We found your Google Workspace mail" is a sentence a tenant can check. Five rows of
    aspmx.l.google.com is not, and a review screen nobody can evaluate is a review screen that gets
    clicked through — which makes it worse than useless, because it transfers the blame."""

    def test_the_common_hosts_are_named(self):
        self.assertEqual(mail_provider(["1 aspmx.l.google.com"]), "Google Workspace")
        self.assertEqual(mail_provider(["0 example-com.mail.protection.outlook.com"]), "Microsoft 365")
        self.assertEqual(mail_provider(["10 mx.zoho.com"]), "Zoho Mail")
        self.assertEqual(mail_provider(["10 mail.protonmail.ch"]), "Proton Mail")
        self.assertEqual(mail_provider(["10 in1-smtp.messagingengine.com"]), "Fastmail")

    def test_an_unrecognised_host_is_not_guessed_at(self):
        # Not naming it costs phrasing, not safety: the records are still shown and the same question is
        # still asked. Naming it WRONG would have a tenant confirm against a provider they do not use.
        self.assertEqual(mail_provider(["10 mail.some-regional-isp.example"]), "")
        self.assertEqual(mail_provider([]), "")

    def test_a_bare_host_without_a_priority_is_accepted(self):
        self.assertEqual(mail_provider(["aspmx.l.google.com."]), "Google Workspace")


class ClassificationTests(unittest.TestCase):
    def test_mail_is_everything_that_carries_mail(self):
        for record in (*GOOGLE_MX, SPF, DMARC, DKIM):
            self.assertEqual(classify_record(record), MAIL, record)

    def test_verification_tokens_are_their_own_category(self):
        # Harmless to lose and annoying to re-earn — but not mail, and filing them as mail would make
        # the one category that gates noisy enough to ignore.
        token = {"type": "TXT", "name": "example.com", "content": "google-site-verification=abc123"}
        self.assertEqual(classify_record(token), VERIFICATION)

    def test_addresses_are_serving_and_the_rest_is_other(self):
        self.assertEqual(classify_record(WEB), SERVING)
        self.assertEqual(classify_record({"type": "CNAME", "name": "shop.example.com",
                                          "content": "domains.jbay.uk"}), SERVING)
        self.assertEqual(classify_record({"type": "SRV", "name": "_sip.example.com",
                                          "content": "0 5 5060 sip.example.com"}), OTHER)

    def test_mail_shaped_hostnames_count_even_when_they_are_address_records(self):
        # `mail.example.com` and `autodiscover` are how Microsoft and cPanel setups break: they are A or
        # CNAME records, so a type-only rule files them as web serving and nobody looks twice.
        self.assertEqual(classify_record({"type": "A", "name": "mail.example.com",
                                          "content": "203.0.113.9"}), MAIL)
        self.assertEqual(classify_record({"type": "CNAME", "name": "autodiscover.example.com",
                                          "content": "autodiscover.outlook.com"}), MAIL)


class DiscrepancyTests(unittest.TestCase):
    """The whole gate. Cloudflare's scan is compared against live DNS, not trusted."""

    def test_a_clean_import_blocks_nothing(self):
        imported = [*GOOGLE_MX, SPF, DMARC, DKIM, WEB]
        self.assertEqual(mail_discrepancies(imported, imported), [])
        self.assertFalse(review(imported, imported, observed_complete=True)["blocked"])

    def test_an_mx_the_scan_missed_blocks_the_switch(self):
        # The failure this exists for. Found before the nameserver change it is a non-event; found after,
        # it is a business not receiving email until DNS propagates twice.
        imported = [WEB, SPF]
        observed = [WEB, SPF, *GOOGLE_MX]
        missing = mail_discrepancies(imported, observed)
        self.assertEqual(missing, ["MX alt1.aspmx.l.google.com", "MX aspmx.l.google.com"])
        self.assertTrue(review(imported, observed, observed_complete=True)["blocked"])

    def test_a_missed_dkim_selector_blocks_too(self):
        # Cloudflare's docs name non-default DKIM selectors specifically: they cannot be enumerated
        # without a zone transfer. Losing one does not bounce mail, it silently fails authentication and
        # the tenant's mail starts landing in spam with nothing to point at.
        self.assertEqual(mail_discrepancies([*GOOGLE_MX, SPF], [*GOOGLE_MX, SPF, DKIM]),
                         ["DKIM key google"])

    def test_spf_and_dmarc_are_each_reported_by_name(self):
        self.assertEqual(mail_discrepancies(GOOGLE_MX, [*GOOGLE_MX, SPF, DMARC]),
                         ["SPF record", "DMARC record"])

    def test_the_other_direction_does_not_block(self):
        """A record the scan found but the live lookup did not is a resolver blip or a record mid-change.
        Blocking on it would stop tenants for no reason, and a gate that fires on noise gets routed
        around."""
        self.assertEqual(mail_discrepancies([*GOOGLE_MX, SPF], [SPF]), [])


class ReviewScreenTests(unittest.TestCase):
    def test_a_domain_with_genuinely_no_mail_is_not_blocked(self):
        """Plenty of domains are web-only, or keep mail on a different name entirely. That is a normal
        state, not a fault, so it asks once and lets them through rather than standing in the way."""
        summary = review([WEB], [WEB], observed_complete=True)
        self.assertFalse(summary["blocked"])
        self.assertFalse(summary["mail"]["present"])
        self.assertIn("no mail records at all", summary["confirm_prompt"])
        self.assertIn("stop here", summary["confirm_prompt"])

    def test_a_failed_lookup_is_not_allowed_to_look_like_no_mail(self):
        """The hole this gate would otherwise have. An empty `observed` means one of two OPPOSITE things
        — the domain has no mail, or we could not ask — and only the caller knows which. Inferring "no
        mail" from silence is how our own failed lookup becomes a tenant's outage. `observed_complete`
        has no default so the safe-looking answer cannot be reached by forgetting it."""
        summary = review([WEB], [], observed_complete=False)
        self.assertTrue(summary["blocked"])
        self.assertIn("could not read", summary["confirm_prompt"])
        # And it must not quietly report a clean comparison it never performed.
        self.assertEqual(summary["missing"], [])
        self.assertTrue(summary["contradictions"])

    def test_the_flag_is_required_so_it_cannot_be_forgotten(self):
        with self.assertRaises(TypeError):
            review([WEB], [WEB])          # type: ignore[call-arg]

    def test_spf_without_mx_is_treated_as_an_incomplete_answer(self):
        """A domain publishing SPF is a domain that sends mail. SPF-and-no-MX is not a mail-less domain,
        it is a partial lookup — and it is exactly the shape a partial lookup takes, because SPF is one
        TXT at the apex while MX enumeration is the part that fails."""
        summary = review([WEB, SPF], [WEB, SPF], observed_complete=True)
        self.assertTrue(summary["blocked"])
        self.assertIn("SPF record but no MX", summary["confirm_prompt"])

    def test_a_recognised_provider_is_named_in_the_prompt(self):
        imported = [*GOOGLE_MX, SPF, WEB]
        summary = review(imported, imported, observed_complete=True)
        self.assertEqual(summary["mail"]["provider"], "Google Workspace")
        self.assertIn("Google Workspace", summary["confirm_prompt"])

    def test_the_warning_is_present_even_when_the_comparison_is_clean(self):
        # The scan cannot prove a negative, and the tenant is the only one who knows what the domain
        # does. A clean comparison lowers the risk; it does not remove it.
        imported = [*GOOGLE_MX, SPF, WEB]
        self.assertIn("will stop working", review(imported, imported, observed_complete=True)["confirm_prompt"])

    def test_records_are_grouped_so_mail_can_be_shown_apart(self):
        imported = [*GOOGLE_MX, SPF, WEB,
                    {"type": "TXT", "name": "example.com", "content": "google-site-verification=x"}]
        summary = review(imported, imported, observed_complete=True)
        self.assertEqual(len(summary["records"][MAIL]), 3)
        self.assertEqual(len(summary["records"][SERVING]), 1)
        self.assertEqual(len(summary["records"][VERIFICATION]), 1)


class ServingRecordTests(unittest.TestCase):
    def test_the_apex_and_www_are_both_proxied(self):
        records = serving_records("example.com")
        self.assertEqual([r["name"] for r in records], ["example.com", "www.example.com"])
        self.assertTrue(all(r["proxied"] for r in records))

    def test_the_origin_is_a_reserved_address_that_routes_nowhere(self):
        """Requests never reach it — the Worker route answers first. A real origin here would be a second
        place the serving path is configured, and the one that silently takes over if the route is ever
        missing. 192.0.2.1 is RFC 5737 TEST-NET-1."""
        self.assertEqual({r["content"] for r in serving_records("example.com")}, {"192.0.2.1"})

    def test_nonsense_input_produces_no_records(self):
        self.assertEqual(serving_records(""), [])
        self.assertEqual(serving_records("localhost"), [])


class ZoneRecordTests(unittest.TestCase):
    ZONE = {"id": "z1", "status": "pending",
            "name_servers": ["Kim.NS.Cloudflare.com", "walt.ns.cloudflare.com"],
            "original_name_servers": ["ns-334.awsdns-41.com"]}

    def test_it_is_its_own_document_not_part_of_the_site(self):
        """A Site's domain_provisioning is discarded on disconnect, and correctly so. A zone is not that:
        it stays authoritative for the whole domain, mail included, until the tenant moves their
        nameservers away. On the Site, disconnecting would orphan a zone still answering for someone's
        business with nothing in our data pointing at it."""
        record = managed_zone_record("t1", "Example.COM.", self.ZONE, now=1_000)
        self.assertEqual(record["document_type"], "managed_zone")
        self.assertEqual(record["domain"], "example.com")
        self.assertEqual(record["tenant_id"], "t1")
        self.assertEqual(record["zone_id"], "z1")

    def test_the_nameservers_are_stored_normalised_both_ways(self):
        # Ours to tell them to set, and theirs to put back if they leave — an exit needs the old values.
        record = managed_zone_record("t1", "example.com", self.ZONE, now=1_000)
        self.assertEqual(record["name_servers"], ["kim.ns.cloudflare.com", "walt.ns.cloudflare.com"])
        self.assertEqual(record["original_name_servers"], ["ns-334.awsdns-41.com"])

    def test_cloudflares_status_is_passed_through_not_reinterpreted(self):
        self.assertEqual(zone_state({"status": "Pending"}), "pending")
        self.assertEqual(zone_state({"status": "active"}), "active")
        self.assertEqual(zone_state({}), "unknown")


class ExportTests(unittest.TestCase):
    """Ships WITH onboarding. An exit built last is an exit that exists in a plan and not in a product,
    and holding a customer's DNS hostage is not a retention strategy."""

    def test_every_record_comes_out_in_a_format_another_provider_accepts(self):
        out = zone_export([*GOOGLE_MX, SPF, WEB], "example.com")
        self.assertIn("example.com.\t300\tIN\tMX\t1 aspmx.l.google.com", out)
        self.assertIn("IN\tTXT\tv=spf1 include:_spf.google.com ~all", out)
        self.assertIn("example.com.\t300\tIN\tA\t203.0.113.10", out)

    def test_mx_priority_survives_the_round_trip(self):
        # Dropping it would deliver all mail to whichever host sorted first, which looks like it works.
        self.assertIn("\tMX\t5 alt1.aspmx.l.google.com", zone_export([GOOGLE_MX[1]], "example.com"))

    def test_a_priority_already_inside_content_is_not_doubled(self):
        """Both shapes reach this code: Cloudflare sends content+priority, a zone file carries one field.
        Emitting "1 1 aspmx..." corrupts the record while still looking like an MX line."""
        self.assertIn("\tMX\t1 aspmx.l.google.com", zone_export([ZONE_FILE_MX], "example.com"))
        self.assertNotIn("1 1", zone_export([ZONE_FILE_MX], "example.com"))

    def test_both_shapes_are_recognised_as_the_same_mail(self):
        # The comparison and the exporter must not disagree about what a record says.
        self.assertEqual(mail_provider([ZONE_FILE_MX["content"]]), "Google Workspace")
        self.assertEqual(mail_discrepancies([ZONE_FILE_MX], [GOOGLE_MX[0]]), [])

    def test_incomplete_records_are_skipped_rather_than_emitted_broken(self):
        out = zone_export([{"type": "A", "name": "", "content": "203.0.113.1"}, WEB], "example.com")
        self.assertEqual(len([ln for ln in out.splitlines() if not ln.startswith(";")]), 1)


if __name__ == "__main__":
    unittest.main()


class FakeZoneRepo:
    def __init__(self):
        self.saved = []

    def put(self, document):
        self.saved.append(dict(document))
        return document


class ProvisionTests(unittest.TestCase):
    """Create the zone, read the import, compare it with live DNS, record the zone."""

    ZONE = {"id": "z1", "status": "pending",
            "name_servers": ["kim.ns.cloudflare.com", "walt.ns.cloudflare.com"]}

    def _provision(self, imported, observed, complete=True, zone=None):
        from stripe_link.domain.managed_dns import provision
        repo = FakeZoneRepo()
        result = provision(
            tenant_id="t1", domain="example.com", now=1_000,
            create_zone_fn=lambda d: zone or self.ZONE,
            list_records_fn=lambda zid: imported,
            observe_fn=lambda d: (observed, complete),
            repository=repo,
        )
        return result, repo

    def test_a_clean_comparison_hands_over_the_nameservers(self):
        records = [*GOOGLE_MX, SPF, WEB]
        result, repo = self._provision(records, records)
        self.assertFalse(result["review"]["blocked"])
        self.assertEqual(result["name_servers"], ["kim.ns.cloudflare.com", "walt.ns.cloudflare.com"])
        self.assertEqual(repo.saved[0]["zone_id"], "z1")

    def test_a_blocked_review_withholds_the_nameservers(self):
        """The only irreversible step in the flow. Once those four lines are followed the domain answers
        from here and the old provider stops, so they are what the gate actually holds back — not the
        zone, which changes nothing on the internet by existing."""
        result, _ = self._provision([WEB], [WEB, *GOOGLE_MX])
        self.assertTrue(result["review"]["blocked"])
        self.assertEqual(result["name_servers"], [])
        self.assertTrue(result["review"]["missing"])

    def test_the_zone_is_recorded_even_when_the_review_blocks(self):
        """It exists on our account from the moment it is created, and a zone nobody is tracking is the
        thing this design exists to never have. Recording it is also what makes either next step
        possible: retry the comparison, or abandon and delete."""
        _, repo = self._provision([WEB], [WEB, *GOOGLE_MX])
        self.assertEqual(len(repo.saved), 1)
        self.assertEqual(repo.saved[0]["domain"], "example.com")
        self.assertTrue(repo.saved[0]["review"]["blocked"])
        self.assertTrue(repo.saved[0]["review"]["missing"])

    def test_a_failed_live_lookup_blocks_rather_than_reading_as_no_mail(self):
        result, repo = self._provision([WEB], [], complete=False)
        self.assertTrue(result["review"]["blocked"])
        self.assertEqual(result["name_servers"], [])
        self.assertTrue(repo.saved[0]["review"]["blocked"])

    def test_the_stored_record_is_the_zone_not_the_site(self):
        _, repo = self._provision([WEB], [WEB])
        saved = repo.saved[0]
        self.assertEqual(saved["document_type"], "managed_zone")
        self.assertEqual(saved["tenant_id"], "t1")
        self.assertNotIn("site_id", saved)      # a zone outlives any one Site's claim on the hostname


class ObserveMailRecordsTests(unittest.TestCase):
    """The independent half of the gate: what DNS says right now, asked directly.

    `_dns_has_records` next door returns False for both "nothing there" and "the lookup fell over". For
    mail those are opposite answers — one means the domain has no email, the other means we do not know —
    and acting on the first while the second is true is how a tenant's mail disappears.
    """

    def _fake(self, answers):
        """answers: {(name, type): payload}. A missing key is a lookup that did not answer."""
        import json as _json
        from urllib.parse import parse_qs, urlparse

        class Resp:
            def __init__(self, payload):
                self._p = _json.dumps(payload).encode()

            def read(self):
                return self._p

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=10):
            q = parse_qs(urlparse(request.full_url).query)
            key = (q["name"][0], q["type"][0])
            if key not in answers:
                raise OSError("resolver did not answer")
            return Resp(answers[key])
        return opener

    def test_a_domain_with_no_mail_reports_empty_and_complete(self):
        # The state creditfix.cloud was actually in: Route 53, nothing published. Allowed, not blocked.
        from stripe_link.domain.custom_domains import observe_mail_records
        noerror = {"Status": 0, "Answer": []}
        answers = {("example.com", "MX"): noerror, ("example.com", "TXT"): noerror,
                   ("_dmarc.example.com", "TXT"): noerror}
        answers.update({(f"{s}._domainkey.example.com", "TXT"): noerror for s in
                        ("google", "default", "selector1", "selector2", "k1", "k2", "mail", "dkim",
                         "s1", "s2", "zoho", "protonmail", "fm1", "mandrill", "sendgrid")})
        records, complete = observe_mail_records("example.com", opener=self._fake(answers))
        self.assertEqual(records, [])
        self.assertTrue(complete)

    def test_a_failed_mx_lookup_marks_the_picture_incomplete(self):
        from stripe_link.domain.custom_domains import observe_mail_records
        # MX absent from the fake = the resolver did not answer. Everything else is fine, and it still
        # must not read as "no mail": `complete` is what review() refuses on.
        answers = {("example.com", "TXT"): {"Status": 0, "Answer": []},
                   ("_dmarc.example.com", "TXT"): {"Status": 0, "Answer": []}}
        _, complete = observe_mail_records("example.com", opener=self._fake(answers))
        self.assertFalse(complete)

    def test_servfail_is_not_an_empty_answer(self):
        from stripe_link.domain.custom_domains import resolve_records
        values, answered = resolve_records("example.com", "MX",
                                           opener=self._fake({("example.com", "MX"): {"Status": 2}}))
        self.assertEqual(values, [])
        self.assertFalse(answered)

    def test_nxdomain_counts_as_answered(self):
        # The resolver spoke and said the name does not exist. That is knowledge, not a failure.
        from stripe_link.domain.custom_domains import resolve_records
        values, answered = resolve_records("nope.example.com", "MX",
                                           opener=self._fake({("nope.example.com", "MX"): {"Status": 3}}))
        self.assertEqual(values, [])
        self.assertTrue(answered)

    def test_a_failed_dkim_probe_does_not_spoil_the_picture(self):
        """DKIM selectors are arbitrary labels that cannot be enumerated, so these are guesses. Treating
        a guess that did not answer as a gap would block every tenant on a slow resolver."""
        from stripe_link.domain.custom_domains import observe_mail_records
        answers = {("example.com", "MX"): {"Status": 0, "Answer": [{"data": "1 aspmx.l.google.com."}]},
                   ("example.com", "TXT"): {"Status": 0, "Answer": []},
                   ("_dmarc.example.com", "TXT"): {"Status": 0, "Answer": []}}
        records, complete = observe_mail_records("example.com", opener=self._fake(answers))
        self.assertTrue(complete)                       # every DKIM probe failed, and that is fine
        self.assertEqual([r["type"] for r in records], ["MX"])

    def test_what_it_finds_feeds_the_gate_unchanged(self):
        from stripe_link.domain.custom_domains import observe_mail_records
        answers = {("example.com", "MX"): {"Status": 0, "Answer": [{"data": "1 aspmx.l.google.com."}]},
                   ("example.com", "TXT"): {"Status": 0,
                                            "Answer": [{"data": '"v=spf1 include:_spf.google.com ~all"'}]},
                   ("_dmarc.example.com", "TXT"): {"Status": 0, "Answer": []}}
        observed, complete = observe_mail_records("example.com", opener=self._fake(answers))
        summary = review([WEB], observed, observed_complete=complete)
        self.assertTrue(summary["blocked"])             # the scan missed all of it
        self.assertEqual(summary["mail"]["provider"], "Google Workspace")
