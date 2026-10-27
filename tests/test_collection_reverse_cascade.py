"""Changing a Collection must re-render the pages that embed it (plans/ROUNDUP_PAGES.md §5, P2).

The cascade ran one way only. `cascade_publish_collection_drafts` fires when the EMBEDDING PAGE publishes
and publishes that page's draft members; nothing at all happened when the Collection itself changed —
`handlers/collections.py` had no publish path. So a tenant who added three products in February left every
already-published artifact exactly as it was in October: the same grid, and the same count above it.

That is the precise bug the Roundup feature exists to fix, so shipping a counted headline without this
would have reproduced it with our own machinery. Artifacts are pre-rendered and served from the CDN, so
there is no render-time escape hatch — something has to re-put the page.
"""

import json
import unittest

from handlers.collections import handler, pages_embedding_collection
from tests.fakes import FakeDocumentRepository


class RecordingPages(FakeDocumentRepository):
    """A pages repo that remembers what was re-put, and can be told to fail on one page.

    Asserting on the WRITE rather than on a patched helper is the point: re-putting the page document is
    what fires the publish stream, so the write IS the re-render. A test that mocked the helper would
    still pass if the write stopped happening.
    """

    def __init__(self):
        super().__init__("page_id")
        self.written = []
        self.explode_on = ""

    def put(self, document):
        page_id = str(document.get("page_id") or "")
        if page_id and page_id == self.explode_on:
            raise RuntimeError("stream unavailable")
        if page_id in {str(d.get("page_id")) for (_t, _k), d in self.documents.items()}:
            self.written.append(page_id)
        return super().put(document)

TENANT = "tenant_demo"


def collection_doc(**overrides):
    doc = {"tenant_id": TENANT, "site_id": "site_x", "name": "Gift picks", "rule": "manual",
           "members": ["page_a"], "presentation": {"heading": "Gift picks"}}
    doc.update(overrides)
    return doc


def page_doc(page_id, collection_id=None, status="published", extra_sections=()):
    sections = list(extra_sections)
    if collection_id:
        sections.append({"type": "catalog_grid", "id": "grid", "collection_id": collection_id})
    return {"tenant_id": TENANT, "page_id": page_id, "status": status, "sections": sections,
            "updated_at": 1000}


class FinderTests(unittest.TestCase):
    """`pages_embedding_collection` — who goes stale when a Collection changes."""

    def _repo(self):
        repo = FakeDocumentRepository("page_id")
        repo.put(page_doc("p_published", "coll_1"))
        repo.put(page_doc("p_draft", "coll_1", status="draft"))
        repo.put(page_doc("p_other", "coll_2"))
        repo.put(page_doc("p_nogrid", None))
        repo.put(page_doc("p_mixed", "coll_1", extra_sections=[{"type": "hero"}]))
        return repo

    def test_it_finds_every_published_embedder(self):
        self.assertEqual(sorted(pages_embedding_collection(self._repo(), TENANT, "coll_1")),
                         ["p_mixed", "p_published"])

    def test_drafts_are_skipped(self):
        """A draft has no artifact to go stale, and it resolves the collection fresh whenever it does
        publish. Re-putting one spends a write to change nothing a visitor can see."""
        self.assertNotIn("p_draft", pages_embedding_collection(self._repo(), TENANT, "coll_1"))

    def test_a_different_collection_is_not_swept_up(self):
        self.assertEqual(pages_embedding_collection(self._repo(), TENANT, "coll_2"), ["p_other"])

    def test_an_unknown_collection_finds_nothing(self):
        self.assertEqual(pages_embedding_collection(self._repo(), TENANT, "coll_nope"), [])

    def test_a_blank_id_never_matches_everything(self):
        # Sections without a collection_id read as "" — a blank query must not sweep up every inline grid.
        repo = self._repo()
        repo.put(page_doc("p_inline", None, extra_sections=[{"type": "catalog_grid", "scope": "all"}]))
        self.assertEqual(pages_embedding_collection(repo, TENANT, ""), [])


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self.collections = FakeDocumentRepository("collection_id")
        self.pages = RecordingPages()

    def _post(self, doc):
        return handler({"httpMethod": "POST", "body": json.dumps(doc)}, None,
                       repository=self.collections, pages_repo=self.pages)

    def _delete(self, collection_id):
        return handler({"httpMethod": "DELETE", "pathParameters": {"collection_id": collection_id},
                        "queryStringParameters": {"tenant_id": TENANT}}, None,
                       repository=self.collections, pages_repo=self.pages)

    def _with_embedders(self, *page_ids):
        created = json.loads(self._post(collection_doc())["body"])["collection"]
        for page_id in page_ids:
            self.pages.put(page_doc(page_id, created["collection_id"]))
        self.pages.written.clear()
        return created

    def test_editing_a_collection_re_renders_its_readers(self):
        created = self._with_embedders("p1", "p2")
        response = self._post(dict(created, members=["page_a", "page_b", "page_c"]))
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(sorted(self.pages.written), ["p1", "p2"])
        self.assertEqual(sorted(json.loads(response["body"])["republished"]), ["p1", "p2"])

    def test_the_re_put_carries_a_fresh_timestamp(self):
        """The write IS the re-render: a MODIFY on the page document fires the publish stream. Re-putting
        it unchanged would still fire, but a stale `updated_at` would misreport when the page last
        changed to everything downstream that reads it."""
        created = self._with_embedders("p1")
        before = self.pages.get(TENANT, "p1")["updated_at"]
        self._post(created)
        self.assertGreater(self.pages.get(TENANT, "p1")["updated_at"], before)

    def test_deleting_a_collection_re_renders_them_too(self):
        """A deleted Collection leaves its readers rendering a grid that resolves to nothing. They need
        the re-render at least as much as an edited one — the page is now wrong, not merely stale."""
        created = self._with_embedders("p1")
        response = self._delete(created["collection_id"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.pages.written, ["p1"])

    def test_drafts_are_left_alone(self):
        created = json.loads(self._post(collection_doc())["body"])["collection"]
        self.pages.put(page_doc("p_draft", created["collection_id"], status="draft"))
        self.pages.written.clear()
        self._post(created)
        self.assertEqual(self.pages.written, [])

    def test_a_collection_nobody_embeds_re_renders_nothing(self):
        self.pages.put(page_doc("p_elsewhere", "coll_other"))
        self.pages.written.clear()
        self._post(collection_doc())
        self.assertEqual(self.pages.written, [])

    def test_an_invalid_collection_re_renders_nothing(self):
        """The put comes first; a page must never be re-published from a version that failed to save."""
        self.pages.put(page_doc("p1", "coll_x"))
        self.pages.written.clear()
        response = self._post(collection_doc(name=""))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(self.pages.written, [])


class BestEffortTests(unittest.TestCase):
    """The edit is already saved. Discovering and re-rendering its readers must never undo that."""

    def setUp(self):
        self.collections = FakeDocumentRepository("collection_id")
        self.pages = RecordingPages()

    def _post(self, doc, pages_repo=None):
        return handler({"httpMethod": "POST", "body": json.dumps(doc)}, None,
                       repository=self.collections, pages_repo=pages_repo or self.pages)

    def test_one_failing_page_does_not_stop_the_others(self):
        created = json.loads(self._post(collection_doc())["body"])["collection"]
        for page_id in ("p1", "p_bad", "p3"):
            self.pages.put(page_doc(page_id, created["collection_id"]))
        self.pages.written.clear()
        self.pages.explode_on = "p_bad"

        response = self._post(created)

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(sorted(self.pages.written), ["p1", "p3"])
        self.assertEqual(sorted(json.loads(response["body"])["republished"]), ["p1", "p3"])

    def test_a_failed_lookup_still_saves_the_collection(self):
        class Exploding:
            def list_for_tenant(self, _tenant):
                raise RuntimeError("table unavailable")

        response = self._post(collection_doc(), pages_repo=Exploding())

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"])["republished"], [])
        self.assertEqual(len(self.collections.documents), 1)
