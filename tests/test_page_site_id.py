"""The page→Site reverse edge (plans/SITE_AS_BUSINESS_IDENTITY.md §3.1).

`Site.pages` stays the source of truth. `page.site_id` is the reverse edge, written only by the Site save
path, so a consumer can answer "whose business is this page?" in one read instead of scanning every Site —
which is what `review_invites._tenant_organization` does today, badly, by taking the first Site it finds.

Three properties carry it, and each is one mistake away from an email naming the wrong business:

1. **Absent is legal.** An unattached page is a draft with no address yet. Requiring `site_id` would make
   page creation fail until a Site existed.
2. **Only the DIFFERENCE is written.** A Site saved for an unrelated reason must not rewrite every page it
   routes — that is N chances to collide with a tenant editing one of them, for no change at all.
3. **Detach CLEARS it.** Leaving the old id would have the page answer "whose business is this?" with a
   Site that no longer routes it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from handlers.sites import _reconcile_page_site_ids  # noqa: E402
from stripe_link.domain.documents import DocumentValidationError, validate_page_document  # noqa: E402

PAGE = {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1", "page_id": "p1",
        "name": "P", "offer_id": "o1", "route": {"slug": "p"}, "sections": [{"type": "hero", "id": "h"}]}


class TheValidatorTests(unittest.TestCase):
    def test_a_page_with_NO_site_is_valid(self):
        """An unattached draft. Requiring it would break page creation before any Site exists."""
        validate_page_document(dict(PAGE))

    def test_a_well_formed_site_id_is_accepted(self):
        validate_page_document({**PAGE, "site_id": "site_rWLjyL57Pn5Gk5"})

    def test_a_malformed_site_id_is_REFUSED(self):
        """It is a key into another table; a typo here resolves to no Site and the page silently loses its
        business identity."""
        for bad in ("nonsense", "site_", "site_ab!", "  ", "SITE_abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(DocumentValidationError):
                    validate_page_document({**PAGE, "site_id": bad})


class FakePages:
    """Records every write so the tests can assert on WHICH pages were touched, not just the end state."""

    def __init__(self):
        self.calls = []
        self.fail = False

    def set_site_id(self, tenant_id, page_id, site_id):
        if self.fail:
            raise RuntimeError("throttled")
        self.calls.append((tenant_id, page_id, site_id))
        return True


def site(*page_ids, site_id="site_abc", tenant_id="t1"):
    return {"tenant_id": tenant_id, "site_id": site_id,
            "pages": {f"/{p}": {"page_id": p} for p in page_ids}}


class ReconcileTests(unittest.TestCase):
    def test_a_page_that_JOINED_is_stamped(self):
        pages = FakePages()
        _reconcile_page_site_ids(site("p1"), before_page_ids=set(), pages_repo=pages)
        self.assertEqual(pages.calls, [("t1", "p1", "site_abc")])

    def test_a_page_that_LEFT_is_cleared(self):
        """Not reassigned — a detached page belongs to no Site."""
        pages = FakePages()
        _reconcile_page_site_ids(site(), before_page_ids={"p1"}, pages_repo=pages)
        self.assertEqual(pages.calls, [("t1", "p1", "")])

    def test_ONLY_THE_DIFFERENCE_is_written(self):
        """The property that keeps this cheap and safe: a Site saved for an unrelated reason must not
        rewrite every page it routes."""
        pages = FakePages()
        _reconcile_page_site_ids(site("p1", "p2", "p3"), before_page_ids={"p1", "p2"}, pages_repo=pages)
        self.assertEqual(pages.calls, [("t1", "p3", "site_abc")])

    def test_an_unchanged_route_map_writes_NOTHING(self):
        pages = FakePages()
        _reconcile_page_site_ids(site("p1", "p2"), before_page_ids={"p1", "p2"}, pages_repo=pages)
        self.assertEqual(pages.calls, [])

    def test_a_swap_both_clears_and_stamps(self):
        pages = FakePages()
        _reconcile_page_site_ids(site("p2"), before_page_ids={"p1"}, pages_repo=pages)
        self.assertEqual(sorted(pages.calls), [("t1", "p1", ""), ("t1", "p2", "site_abc")])

    def test_a_site_with_no_id_or_tenant_does_nothing(self):
        """Rather than stamping an empty key onto every page it lists."""
        pages = FakePages()
        _reconcile_page_site_ids({"pages": {"/p": {"page_id": "p1"}}}, before_page_ids=set(),
                                 pages_repo=pages)
        _reconcile_page_site_ids(None, before_page_ids={"p1"}, pages_repo=pages)
        self.assertEqual(pages.calls, [])

    def test_a_WRITE_FAILURE_does_not_raise(self):
        """The route map is already persisted and the tenant has seen the save succeed. Raising here would
        undo a success; the backfill repairs a stale edge."""
        pages = FakePages()
        pages.fail = True
        _reconcile_page_site_ids(site("p1"), before_page_ids=set(), pages_repo=pages)  # must not raise

    def test_entries_with_no_page_id_are_ignored(self):
        pages = FakePages()
        bad = {"tenant_id": "t1", "site_id": "site_abc", "pages": {"/a": {}, "/b": {"page_id": ""}}}
        _reconcile_page_site_ids(bad, before_page_ids=set(), pages_repo=pages)
        self.assertEqual(pages.calls, [])


class TheWritePathIsTheChokePointTests(unittest.TestCase):
    """Stamping at each attach point would be three chances to miss one."""

    def test_every_caller_passes_the_MODE(self):
        """A page lives at SITE#<mode>#..., so a reconcile against the default mode would stamp the wrong
        partition — set_homepage in live mode writing to the test-mode page."""
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers" / "sites.py").read_text()
        calls = [line for line in src.splitlines() if "_save_site_pages(repository, site" in line
                 and "def " not in line]
        self.assertTrue(calls)
        for line in calls:
            with self.subTest(line=line.strip()):
                self.assertIn("mode=mode", line)

    def test_the_reconcile_runs_from_the_single_save_path(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers" / "sites.py").read_text()
        saver = src.split("def _save_site_pages(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_reconcile_page_site_ids(", saver)


if __name__ == "__main__":
    unittest.main()


class TheResolverShortcutTests(unittest.TestCase):
    """`site_for_page` already existed and scanned Site.pages — it is EXTENDED, not replaced, so every
    caller keeps working and `Site.pages` stays the authority."""

    class Repo:
        def __init__(self):
            self.scans = 0

        def get(self, _tenant, site_id):
            return {"site_id": site_id, "via": "direct"} if site_id == "site_ok" else None

        def list_for_tenant(self, _tenant, **_kw):
            self.scans += 1
            return [{"site_id": "site_scan", "via": "scan", "pages": {"/a": {"page_id": "p1"}}}]

    def test_the_reverse_edge_avoids_the_scan(self):
        from stripe_link.domain.sites import site_for_page

        repo = self.Repo()
        found = site_for_page(repo, "t1", "p1", page={"site_id": "site_ok"})
        self.assertEqual(found["via"], "direct")
        self.assertEqual(repo.scans, 0)

    def test_a_DANGLING_edge_falls_back_to_the_scan(self):
        """A stale site_id must not be able to detach a page a Site still routes."""
        from stripe_link.domain.sites import site_for_page

        repo = self.Repo()
        found = site_for_page(repo, "t1", "p1", page={"site_id": "site_deleted"})
        self.assertEqual(found["via"], "scan")
        self.assertEqual(repo.scans, 1)

    def test_a_caller_with_no_page_document_is_unchanged(self):
        from stripe_link.domain.sites import site_for_page

        repo = self.Repo()
        self.assertEqual(site_for_page(repo, "t1", "p1")["via"], "scan")

    def test_a_failing_shortcut_does_not_raise(self):
        from stripe_link.domain.sites import site_for_page

        class Broken(self.Repo):
            def get(self, *_a):
                raise RuntimeError("throttled")

        repo = Broken()
        self.assertEqual(site_for_page(repo, "t1", "p1", page={"site_id": "site_ok"})["via"], "scan")

    def test_find_site_for_page_threads_the_hint(self):
        from stripe_link.domain.sites import find_site_for_page

        repo = self.Repo()
        self.assertEqual(find_site_for_page(repo, "t1", "p1", page={"site_id": "site_ok"})["via"], "direct")
        self.assertEqual(repo.scans, 0)
