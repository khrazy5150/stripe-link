"""The canonical must follow the slug the Site says NOW, not the one it said a second ago.

Publishing is almost always triggered BY a write that just changed what it reads. Attaching a page or
setting a homepage saves the Site and then re-puts the page to fire the publish stream -- so an
eventually-consistent query can hand the publisher the Site as it was before the move. The page then
renders with the slug it used to have, and `canonical_path` is derived from that slug.

Measured on a live store, 2026-10-30: the homepage artifact written at 08:57:05 -- AFTER the move --
declared `canonical: https://shop.automizepro.com/amazing-gift-ideas`, a URL that 404s, on a page that
was `index,follow`. It usually won the race, which is what made it nasty: intermittent, and the page
looks right unless you read the canonical.
"""

import pathlib
import unittest

from stripe_link.domain.sites import find_site_for_page, site_for_page

ROOT = pathlib.Path(__file__).resolve().parents[1]

STALE = {"site_id": "site_1", "pages": {"/amazing-gift-ideas": {"page_id": "page_X", "page_type": "landing"}}}
FRESH = {"site_id": "site_1", "pages": {"/": {"page_id": "page_X", "page_type": "homepage"}}}


class LaggingRepository:
    """A replica that has not caught up: the eventually-consistent read still serves the old Site."""

    def __init__(self):
        self.calls = []

    def list_for_tenant(self, tenant_id, *, consistent=False):
        self.calls.append(consistent)
        return [FRESH if consistent else STALE]


class TheLookupCanDemandTheLatestTests(unittest.TestCase):
    def test_the_default_can_be_stale(self):
        """Not a bug in itself -- it is half the cost and no browser-facing listing needs the guarantee.
        This pins the behaviour the publish path had to opt out of."""
        repo = LaggingRepository()
        site = site_for_page(repo, "t1", "page_X")
        self.assertEqual(list(site["pages"]), ["/amazing-gift-ideas"])
        self.assertEqual(repo.calls, [False])

    def test_asking_for_consistency_gets_the_move(self):
        repo = LaggingRepository()
        site = site_for_page(repo, "t1", "page_X", consistent=True)
        self.assertEqual(list(site["pages"]), ["/"])
        self.assertEqual(repo.calls, [True])

    def test_the_best_effort_wrapper_threads_it_too(self):
        repo = LaggingRepository()
        site = find_site_for_page(repo, "t1", "page_X", consistent=True)
        self.assertEqual(list(site["pages"]), ["/"])

    def test_a_repository_without_the_flag_still_resolves(self):
        """A double (or an older repository) whose list_for_tenant predates `consistent`. The lookup
        matters more than the guarantee: losing the Site entirely would publish the page with its
        interim identity and no Organization graph."""

        class Old:
            def list_for_tenant(self, tenant_id):
                return [STALE]

        site = find_site_for_page(Old(), "t1", "page_X", consistent=True)
        self.assertIsNotNone(site)
        self.assertEqual(list(site["pages"]), ["/amazing-gift-ideas"])


class TheCanonicalFollowsTheSiteSlugTests(unittest.TestCase):
    """The derivation itself was always right -- `canonical_path` is "" for a page at "/". What was wrong
    was the Site it read. This pins both halves so neither can drift back."""

    SOURCE = (ROOT / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")

    def test_publish_demands_the_latest_site(self):
        self.assertIn(
            "find_site_for_page(sites_repository, tenant_id, seo_identity_page_id, consistent=True)",
            self.SOURCE)

    def test_a_page_at_the_root_canonicalises_to_the_origin(self):
        self.assertIn('canonical_path = "" if page_site_slug in ("", "/") else page_site_slug.lstrip("/")',
                      self.SOURCE)


class TheConsistentReadIsOptInTests(unittest.TestCase):
    """Every other caller keeps the eventually-consistent read: it is half the cost, it need not be served
    by the partition leader, and a browser-facing listing has nothing to gain from the guarantee."""

    SOURCE = (ROOT / "src" / "stripe_link" / "repositories" / "documents.py").read_text(encoding="utf-8")

    def test_the_default_is_unchanged(self):
        self.assertIn("def list_for_tenant(self, tenant_id: str, *, consistent: bool = False)", self.SOURCE)

    def test_the_flag_reaches_dynamodb_only_when_asked(self):
        self.assertIn('**({"ConsistentRead": True} if consistent else {}),', self.SOURCE)

    def test_it_is_the_base_table_so_the_read_is_available(self):
        """A GSI cannot serve a consistent read. This query is on PK/SK."""
        block = self.SOURCE.split("def list_for_tenant", 1)[1].split("def list_page_for_tenant", 1)[0]
        self.assertIn('Key("PK").eq(f"TENANT#{tenant_id}")', block)
        self.assertNotIn("IndexName", block)
