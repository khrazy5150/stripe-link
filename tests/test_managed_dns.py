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
        self.assertFalse(review(imported, imported)["blocked"])

    def test_an_mx_the_scan_missed_blocks_the_switch(self):
        # The failure this exists for. Found before the nameserver change it is a non-event; found after,
        # it is a business not receiving email until DNS propagates twice.
        imported = [WEB, SPF]
        observed = [WEB, SPF, *GOOGLE_MX]
        missing = mail_discrepancies(imported, observed)
        self.assertEqual(missing, ["MX alt1.aspmx.l.google.com", "MX aspmx.l.google.com"])
        self.assertTrue(review(imported, observed)["blocked"])

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
    def test_no_mail_found_is_called_out_as_the_dangerous_answer(self):
        """A domain with no MX is either a domain with no mail or a scan that missed it, and the two look
        identical. The screen says so instead of reading as an all-clear."""
        summary = review([WEB], [WEB])
        self.assertFalse(summary["mail"]["present"])
        self.assertIn("NO mail records were found", summary["confirm_prompt"])
        self.assertIn("stop here", summary["confirm_prompt"])

    def test_a_recognised_provider_is_named_in_the_prompt(self):
        imported = [*GOOGLE_MX, SPF, WEB]
        summary = review(imported, imported)
        self.assertEqual(summary["mail"]["provider"], "Google Workspace")
        self.assertIn("Google Workspace", summary["confirm_prompt"])

    def test_the_warning_is_present_even_when_the_comparison_is_clean(self):
        # The scan cannot prove a negative, and the tenant is the only one who knows what the domain
        # does. A clean comparison lowers the risk; it does not remove it.
        imported = [*GOOGLE_MX, SPF, WEB]
        self.assertIn("will stop working", review(imported, imported)["confirm_prompt"])

    def test_records_are_grouped_so_mail_can_be_shown_apart(self):
        summary = review([*GOOGLE_MX, SPF, WEB,
                          {"type": "TXT", "name": "example.com",
                           "content": "google-site-verification=x"}], [])
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
