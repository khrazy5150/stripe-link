"""The confirmation a registrant receives (plans/WEBINAR.md P2).

The `.ics` matters more than any reminder we send: it puts the session in their own calendar, where their
own device reminds them, on the phone they actually carry. A reminder email competes with every other
email; a calendar entry does not.

RFC 5545 fails SILENTLY — a file with LF endings or an unescaped comma is accepted by one client and
ignored by another, which is the worst kind of bug to have in an attachment nobody opens until the morning
of the session. Hence the mechanics are tested here rather than improvised at a call site.
"""
import unittest

from stripe_link.domain.ics import calendar_invite, invite_for_occurrence
from stripe_link.domain.registration_email import registration_confirmation

START = 1_800_000_000
EVENT = {"title": "Build a $10K/month newsletter", "description": "The exact system.",
         "join_url": "https://meet.google.com/abc-defg-hij", "duration_minutes": 75}
OCC = {"occurrence_id": "occ_1", "starts_at": START, "timezone": "America/New_York"}


class TheCalendarFileIsWellFormed(unittest.TestCase):
    def setUp(self):
        self.ics = invite_for_occurrence(EVENT, OCC, now=START - 86_400)

    def test_every_line_ends_crlf(self):
        """§3.1. A bare LF is accepted by some clients and ignored by others."""
        self.assertEqual(self.ics.count("\r\n"), self.ics.count("\n"))
        self.assertFalse(self.ics.replace("\r\n", "").count("\r"))

    def test_it_is_a_complete_document(self):
        self.assertTrue(self.ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(self.ics.rstrip().endswith("END:VCALENDAR"))
        self.assertIn("BEGIN:VEVENT", self.ics)
        self.assertIn("END:VEVENT", self.ics)

    def test_times_are_utc(self):
        """A floating local time means something different to every reader."""
        self.assertIn("DTSTART:20270115T080000Z", self.ics)
        self.assertIn("DTEND:20270115T091500Z", self.ics)   # +75 minutes

    def test_the_duration_comes_from_the_event(self):
        short = invite_for_occurrence({**EVENT, "duration_minutes": 30}, OCC, now=START)
        self.assertIn("DTEND:20270115T083000Z", short)

    def test_text_values_are_escaped(self):
        ics = invite_for_occurrence({**EVENT, "title": "Sell more, faster; really",
                                     "description": "a\\b"}, OCC, now=START)
        self.assertIn(r"SUMMARY:Sell more\, faster\; really", ics)
        self.assertIn(r"DESCRIPTION:a\\b", ics)

    def test_a_newline_in_a_value_cannot_break_the_file(self):
        ics = invite_for_occurrence({**EVENT, "description": "one\ntwo"}, OCC, now=START)
        self.assertIn(r"DESCRIPTION:one\ntwo", ics)
        self.assertNotIn("\r\ntwo", ics)

    def test_long_lines_fold_at_75_octets(self):
        ics = invite_for_occurrence({**EVENT, "title": "x" * 300}, OCC, now=START)
        for line in ics.split("\r\n"):
            with self.subTest(line=line[:30]):
                self.assertLessEqual(len(line.encode("utf-8")), 75)

    def test_folding_never_splits_a_character(self):
        """Counted in octets; split on a character boundary, or a multi-byte title renders as mojibake."""
        ics = invite_for_occurrence({**EVENT, "title": "é" * 200}, OCC, now=START)
        ics.encode("utf-8").decode("utf-8")   # would raise if a sequence were cut
        self.assertIn("SUMMARY:", ics)

    def test_continuations_are_marked_with_a_space(self):
        ics = invite_for_occurrence({**EVENT, "title": "y" * 200}, OCC, now=START)
        folded = [line for line in ics.split("\r\n") if line.startswith(" ")]
        self.assertTrue(folded)

    def test_the_uid_is_stable_for_a_sitting(self):
        """A calendar treats a repeated UID as an UPDATE, so resending moves the entry rather than
        leaving two."""
        first = invite_for_occurrence(EVENT, OCC, now=START - 100)
        second = invite_for_occurrence(EVENT, OCC, now=START - 10)
        self.assertIn("UID:occ_1@juniorbay", first)
        self.assertIn("UID:occ_1@juniorbay", second)

    def test_the_join_url_is_the_location(self):
        """Most clients make LOCATION tappable, which is the one thing needed when the entry fires."""
        self.assertIn("LOCATION:https://meet.google.com/abc-defg-hij", self.ics)

    def test_it_publishes_rather_than_invites(self):
        """REQUEST is an invitation expecting an RSVP; they already said yes on the page."""
        self.assertIn("METHOD:PUBLISH", self.ics)
        self.assertNotIn("METHOD:REQUEST", self.ics)

    def test_a_sitting_with_no_start_has_nothing_to_describe(self):
        self.assertEqual(invite_for_occurrence(EVENT, {"occurrence_id": "x"}), "")

    def test_a_missing_end_falls_back_rather_than_producing_a_zero_length_event(self):
        ics = calendar_invite(uid="u", title="T", starts_at=START, ends_at=0, now=START)
        self.assertIn("DTEND:", ics)


class TheConfirmationSaysTheTwoThingsThatMatter(unittest.TestCase):
    def setUp(self):
        self.message = registration_confirmation(EVENT, OCC, name="Jane", brand="Quill")

    def test_the_date_is_in_the_subject(self):
        """A phone shows the subject and the first line and nothing else."""
        self.assertIn("2027", self.message["subject"])
        self.assertIn("Build a $10K/month newsletter", self.message["subject"])

    def test_the_join_link_is_in_both_bodies(self):
        self.assertIn("https://meet.google.com/abc-defg-hij", self.message["text"])
        self.assertIn("https://meet.google.com/abc-defg-hij", self.message["html"])

    def test_it_greets_by_name_when_given_one(self):
        self.assertIn("Hi Jane,", self.message["text"])

    def test_it_stays_polite_without_one(self):
        self.assertIn("Hi,", registration_confirmation(EVENT, OCC)["text"])

    def test_no_link_yet_says_so_plainly(self):
        """A confirmation with no link and no explanation reads as a broken email."""
        message = registration_confirmation({**EVENT, "join_url": ""}, OCC)
        self.assertIn("email you the link", message["text"])
        self.assertIn("email you the link", message["html"])

    def test_the_html_escapes_the_tenants_words(self):
        message = registration_confirmation({**EVENT, "title": "<script>x</script>"}, OCC)
        self.assertIn("&lt;script&gt;", message["html"])
        self.assertNotIn("<script>", message["html"])

    def test_the_time_is_the_hosts_zone(self):
        """Matching the page. The .ics carries UTC so the registrant's calendar converts."""
        self.assertIn("EST", self.message["text"])

    def test_nothing_is_sent_for_a_sitting_with_no_date(self):
        self.assertEqual(registration_confirmation(EVENT, {"occurrence_id": "x"})["subject"], "")


class TheMailerCarriesIt(unittest.TestCase):
    def test_an_attachment_switches_to_raw_mime(self):
        """SESv2's Simple content cannot carry one."""
        from stripe_link.mailer import _raw_message
        raw = _raw_message(sender="a@b.co", recipient="c@d.co", subject="s", html="<p>h</p>",
                           text="t", reply_to="", calendar="BEGIN:VCALENDAR\r\n", filename="session.ics")
        body = raw.decode("utf-8", "replace")
        for probe in ("multipart/mixed", "multipart/alternative", "text/calendar",
                      'filename="session.ics"', 'method="PUBLISH"'):
            with self.subTest(probe=probe):
                self.assertIn(probe, body)

    def test_both_bodies_survive_the_switch(self):
        from stripe_link.mailer import _raw_message
        body = _raw_message(sender="a@b.co", recipient="c@d.co", subject="s", html="<p>html here</p>",
                            text="text here", reply_to="", calendar="X", filename="f.ics").decode()
        self.assertIn("text/plain", body)
        self.assertIn("text/html", body)

    def test_a_failed_confirmation_never_costs_the_registration(self):
        """The lead is already stored; a visitor who sees an error submits again and takes a second seat
        they already hold."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers" / "leads.py").read_text()
        block = source[source.index("def _send_registration_confirmation"):][:1800]
        self.assertIn("except Exception", block)
        self.assertIn("logger.warning", block)


if __name__ == "__main__":
    unittest.main()
