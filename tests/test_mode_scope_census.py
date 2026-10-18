"""Every mode-agnostic repository is a DECISION, and this is where it is written down.

Four bugs in one week had the same shape: a repository that is deliberately not mode-scoped, read in a
mode-specific context, so a test-mode record showed up in a live-mode screen. Notifications were scoped
and the refund requests beside them were not; lead notifications were scoped and the leads were not.

A mode-SCOPED repository cannot fail this way — it refuses to be built without a mode rather than reading
an empty key space (documents.py says so, loudly). So the entire risk surface is the list below, and this
test exists to make that list impossible to extend by accident: add a repository without a mode and the
suite asks which kind it is.

This is a census, not a rule. It asserts that somebody decided — not that the decision was right.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "stripe_link" / "repositories" / "documents.py").read_text(encoding="utf-8")

# Mode-agnostic AND correct: the same record serves both sets of books.
SETUP_AND_IDENTITY = {
    "calendar_connections_repository",   # one calendar, whichever books you are in
    "oauth_states_repository",           # transient handshake
    "tenant_profiles_repository",        # the tenant is the tenant
    "user_preferences_repository",
    "user_profiles_repository",
    "fulfillers_repository",             # scheduling SETUP; appointments are the transactions
    "tenant_availability_repository",
    "availability_exceptions_repository",
    "legal_pages_repository",            # one set of terms
    "custom_domains_index_repository",   # live-only by nature
    "abuse_reports_repository",          # the platform's queue, not a tenant's books
    "purchase_throttles_repository",     # an abuse gate counts attempts, not sales
    "routes_repository",                 # a shareable link resolves to a page in either mode
    "events_repository",                 # free registration, no Stripe state (documented at the repo)
}

# Mode-agnostic in STORAGE, scoped where they are READ. Each of these was a bug first.
SCOPED_AT_READ_TIME = {
    "refund_requests_repository": ("handlers/notifications.py", "refund_request_mode"),
    "leads_repository": ("handlers/leads.py", "lead_mode"),
}

# Mode-agnostic and KNOWN WRONG — a test record is indistinguishable from a live one, and the fix needs a
# backfill rather than a read filter. Listed so it cannot be forgotten, and so this test fails loudly if
# somebody "fixes" it without removing it from here.
KNOWN_GAP = {
    "reviews_repository",  # plans/TODO.md: a test review renders on the live page and feeds its rating
}


def mode_agnostic_repositories():
    found = set()
    # `\Z` matters: without it the lookahead needs something AFTER the definition, so the LAST
    # repository in the file is never matched — and a new repository is usually appended at the end,
    # which is precisely the case this guard exists to catch. Found by injecting one and watching the
    # guard pass.
    pattern = re.compile(
        r"def (\w+_repository)\([^)]*\)[^:]*:\s*(?:\"\"\".*?\"\"\")?(.*?)(?=\ndef |\nclass |\Z)", re.S)
    for match in pattern.finditer(SOURCE):
        name, body = match.group(1), match.group(2)
        if "DynamoDocumentRepository(" not in body:
            continue
        if "mode_scoped=True" not in body:
            found.add(name)
    return found


class TheCensusTests(unittest.TestCase):
    def test_every_mode_agnostic_repository_is_accounted_for(self):
        """The guard. A new repository with no mode must be classified here — as setup, as scoped-on-read,
        or as a known gap — rather than quietly becoming the fifth instance of this bug."""
        classified = SETUP_AND_IDENTITY | set(SCOPED_AT_READ_TIME) | KNOWN_GAP
        unclassified = mode_agnostic_repositories() - classified
        self.assertEqual(unclassified, set(),
                         f"These repositories are not mode-scoped and nobody has said why: {sorted(unclassified)}. "
                         "Decide: mode-agnostic by nature, scoped where it is read, or a gap to record.")

    def test_the_census_does_not_list_repositories_that_no_longer_exist(self):
        """A stale entry is how a census stops describing the code."""
        actual = mode_agnostic_repositories()
        for name in SETUP_AND_IDENTITY | set(SCOPED_AT_READ_TIME) | KNOWN_GAP:
            with self.subTest(repository=name):
                self.assertIn(name, actual,
                              f"{name} is listed here but is now mode-scoped (or gone) — remove the entry.")


class TheReadTimeScopingIsRealTests(unittest.TestCase):
    def test_each_scoped_at_read_handler_still_has_its_filter(self):
        """Naming the handler is not evidence; this checks the function is actually there, because a
        refactor that drops it would otherwise leave this file asserting a fiction."""
        for repository, (handler, helper) in SCOPED_AT_READ_TIME.items():
            with self.subTest(repository=repository):
                source = (ROOT / "src" / handler).read_text(encoding="utf-8")
                self.assertIn(f"def {helper}(", source)
                self.assertIn("resolve_stripe_mode(event)", source)


if __name__ == "__main__":
    unittest.main()
