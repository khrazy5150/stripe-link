"""The host tables have a review date. This is what makes it mean something.

plans/CREATOR_LINK_POLICY.md §7: "Staleness is the failure mode. X's policy CHANGED -- it did not always
permit this. A host table that encodes platform policy silently goes wrong." The doc asks for two things: a
`reviewed` date on each table, and *"a test that FAILS when that date is older than a year. Surfacing beats
remembering."* The dates were stamped on 2026-09-11; this is the half that surfaces them.

The failure it guards is specific and has happened here before: a table of third-party policy claims ages
without anyone noticing, and the product keeps acting on facts that stopped being true. An adult warning that
no longer fires, or a host that is no longer safe to link, both look exactly like working software.
"""
import datetime as dt
import unittest

from stripe_link.domain.social_links import (
    ADULT_HOSTS, ADULT_HOSTS_REVIEWED, CREATOR_LINKABLE_HOSTS,
    PLATFORM_LINKABLE_HOSTS, PLATFORM_LINKABLE_REVIEWED,
)

# A year. Long enough not to nag, short enough that a platform's policy shift is caught in the same year it
# happens. The doc picked it; this only spells it.
MAX_AGE = dt.timedelta(days=365)
TABLES = {
    "ADULT_HOSTS": ADULT_HOSTS_REVIEWED,
    "PLATFORM_LINKABLE_HOSTS": PLATFORM_LINKABLE_REVIEWED,
}


class ReviewDateTests(unittest.TestCase):
    def test_every_policy_table_is_stamped_with_a_parsable_date(self):
        for name, stamped in TABLES.items():
            with self.subTest(table=name):
                dt.date.fromisoformat(stamped)   # raises if it is not a real ISO date

    def test_no_table_has_gone_a_year_without_review(self):
        """When this fails, RE-CHECK the claims -- do not just bump the date.

        Each entry carries its reason in the table precisely so a reviewer can verify the claim rather than
        re-derive the decision. Bumping the date without reading the reasons converts this test into a
        reminder to lie.
        """
        today = dt.date.today()
        stale = {
            name: (today - dt.date.fromisoformat(stamped)).days
            for name, stamped in TABLES.items()
            if today - dt.date.fromisoformat(stamped) > MAX_AGE
        }
        self.assertEqual(
            stale, {},
            "Host policy tables are overdue for review (days since): "
            f"{stale}. Re-verify each host's reason in plans/CREATOR_LINK_POLICY.md §5c, then update the "
            "reviewed date.",
        )

    def test_a_reason_travels_with_every_adult_host(self):
        # §7: "Every host entry carries its reason in the table, so a reviewer can re-check the claim rather
        # than re-derive the decision." A bare set would make review guesswork.
        for host, reason in ADULT_HOSTS.items():
            with self.subTest(host=host):
                self.assertTrue(str(reason).strip(), f"{host} has no reason recorded")

    def test_the_creator_list_is_a_superset_question_not_a_duplicate(self):
        """§2: the two rules must not be conflated. Linkability is not identity."""
        self.assertTrue(set(CREATOR_LINKABLE_HOSTS) <= set(PLATFORM_LINKABLE_HOSTS))
        # An adult host may be LINKED (with a warning) and must never be an identity claim.
        from stripe_link.domain.social_links import SAME_AS_HOSTS

        self.assertFalse(set(ADULT_HOSTS) & set(SAME_AS_HOSTS),
                         "an adult host is being offered as a sameAs identity claim")


if __name__ == "__main__":
    unittest.main()
