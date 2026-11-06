"""The Sites editor's Save button, and the two ways it was able to do nothing at all.

These read the dashboard source, the way `tests/test_site_brands.py` does: the Vue screens are not
executed in this suite, so what can be pinned is the shape of the code. Both behaviours below were
reported the same way -- *"Save doesn't close the modal"* -- which is what a dead control looks like from
the outside, and neither left an error anywhere.
"""
import re
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "src"
SITES_SCREEN = (DASHBOARD / "components" / "Sites.vue").read_text(encoding="utf-8")
SUBDOMAIN_CHECK = (DASHBOARD / "composables" / "useSubdomainCheck.js").read_text(encoding="utf-8")


class AFailedCheckIsNotAVerdictTests(unittest.TestCase):
    """`checked` means we ASKED and got an answer. It used to also mean "the request threw"."""

    def test_the_catch_branch_does_not_claim_the_check_completed(self):
        """THE ONE THAT MATTERS.

        Save is gated on `checked && !available`. Setting `checked = true` from the catch made a network
        blip indistinguishable from "that address is taken", and the button stayed disabled until the
        tenant happened to retype the field -- which nobody does to a value they did not change.
        """
        catch = SUBDOMAIN_CHECK.split("} catch (error) {", 1)[1].split("} finally {", 1)[0]
        self.assertIn("state.failed = true", catch)
        self.assertNotIn("state.checked = true", catch)

    def test_the_success_branch_still_records_a_real_answer(self):
        success = SUBDOMAIN_CHECK.split("const res = await store.checkSubdomain", 1)[1].split(
            "} catch (error) {", 1)[0]
        self.assertIn("state.checked = true", success)
        self.assertIn("state.failed = false", success)

    def test_failed_is_cleared_whenever_a_new_check_starts(self):
        """Otherwise one blip marks the field as unchecked for the rest of the session."""
        self.assertIn("state.checking = true;\n    state.failed = false;", SUBDOMAIN_CHECK)

    def test_an_empty_address_clears_it_too(self):
        empty = SUBDOMAIN_CHECK.split("if (!trimmed) {", 1)[1].split("return;", 1)[0]
        self.assertIn("state.failed", empty)

    def test_save_is_still_blocked_by_a_REAL_negative(self):
        """The gate must keep refusing an address that genuinely came back taken."""
        self.assertIn("editCheck.state.checked && !editCheck.state.available", SITES_SCREEN)

    def test_the_tenant_is_told_the_check_did_not_run(self):
        """Silence here is what sent someone hunting for a broken Save button."""
        self.assertIn("state.failed", SITES_SCREEN.split("function availabilityText", 1)[1][:400])


class TheSaveClickAlwaysReportsSomethingTests(unittest.TestCase):
    def test_building_the_document_happens_inside_a_try(self):
        """The whole document was built BEFORE the try. One bad value anywhere in a long form threw
        synchronously, so the click made no request, showed no message and left the dialog open."""
        head = SITES_SCREEN.split("async function saveEdit(", 1)[1].split("function buildEditDocument",
                                                                          1)[0]
        self.assertIn("try {", head.split("buildEditDocument()", 1)[0])
        self.assertIn("formError.value", head)

    def test_the_failure_names_the_stage_it_failed_at(self):
        self.assertIn("could not be prepared for saving", SITES_SCREEN)

    def test_buildEditDocument_returns_the_document(self):
        body = SITES_SCREEN.split("function buildEditDocument(", 1)[1]
        self.assertIn("return doc;", body[:body.index("\n}\n")])


class TheWeekStartsOnSundayTests(unittest.TestCase):
    """Opening-hours day chips. Display order only -- days are stored and sent by NAME."""

    def test_sunday_is_first_and_saturday_is_last(self):
        block = SITES_SCREEN.split("const WEEK_DAYS = [", 1)[1].split("];", 1)[0]
        days = re.findall(r'\["(\w+)",', block)
        self.assertEqual(days[0], "Sunday")
        self.assertEqual(days[-1], "Saturday")

    def test_every_day_is_present_exactly_once(self):
        block = SITES_SCREEN.split("const WEEK_DAYS = [", 1)[1].split("];", 1)[0]
        days = re.findall(r'\["(\w+)",', block)
        self.assertEqual(sorted(days), sorted(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                               "Saturday", "Sunday"]))

    def test_the_stored_names_still_match_what_the_server_accepts(self):
        """Re-ordering a picker must never become a renaming of the data behind it."""
        from stripe_link.domain.documents import _ORG_DAYS

        block = SITES_SCREEN.split("const WEEK_DAYS = [", 1)[1].split("];", 1)[0]
        self.assertEqual(set(re.findall(r'\["(\w+)",', block)), set(_ORG_DAYS))


class TheHelpTextRendersTests(unittest.TestCase):
    def test_no_literal_unicode_escapes_leak_into_the_markup(self):
        """`\\u2014` inside a template TEXT NODE is not a string literal -- it printed on screen."""
        # A blanket rule over the whole template, with no exception to remember: inside `{{ }}` the
        # escape would be interpreted and inside a text node it would not, and nobody should have to
        # work out which kind of context they are typing in. Write the character.
        template = SITES_SCREEN.split("<script", 1)[0]
        self.assertNotIn("\\u", template)


if __name__ == "__main__":
    unittest.main()
