"""Attaching a page to a Site must re-render it.

Measured on a real page 2026-09-11, which is the only way this was ever going to be found:

    page saved        21:12:45
    artifact written  21:12:50   <- published here, page NOT yet attached
    site updated      21:13:14   <- attached 24 seconds LATER

Attaching writes the SITE, never the page. The publish stream watches the PAGES table, so it never fires
again and the artifact keeps whatever identity it was rendered with. For most page types that is a degraded
page -- no store name, no Organization graph. For a link-in-bio page it is an EMPTY page, because
`social_links` renders the Site's profiles and there were none at render time. Nothing ever re-renders it, so
it stays empty until the tenant happens to re-save, which is exactly what made this look intermittent.

Third instance of the same shape. `SOCIAL_MEDIA_PAGES.md` P3 records the first two: first-verify of a custom
domain already re-published (canonical/robots are baked in at publish), and domain DISCONNECT was found
missing for the same reason and fixed. Attach/detach is the same hole in the same wall.
"""
import unittest

from handlers import sites as sites_handler


class FakeSites:
    def __init__(self, site):
        self.site = site

    def get(self, tenant_id, site_id):
        return dict(self.site) if site_id == self.site["site_id"] else None

    def put(self, site):
        self.site = site
        return site

    def list_for_tenant(self, tenant_id):
        # _assert_pages_unassigned checks the tenant's OTHER Sites for the same page_id.
        return [dict(self.site)]


class FakePages:
    def __init__(self, pages):
        self.pages = {p["page_id"]: p for p in pages}
        self.puts = []

    def get(self, tenant_id, page_id):
        page = self.pages.get(page_id)
        return dict(page) if page else None

    def put(self, page):
        self.puts.append(page)
        self.pages[page["page_id"]] = page
        return page


def _event(body=None, params=None):
    # tenant_id travels in the body/query, not the JWT claims (see common.tenant_id_from_event).
    import json
    return {
        "body": json.dumps({"tenant_id": "tenant_1", **(body or {})}),
        "queryStringParameters": {"tenant_id": "tenant_1", **(params or {})},
    }


class AttachTests(unittest.TestCase):
    def setUp(self):
        # A full, valid Site: _save_site_pages re-validates the document before writing it. Shape taken from
        # tests/test_document_validation.py, which is where the canonical one lives.
        self.site = {
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_1",
            "tenant_id": "tenant_1", "environment": "live", "name": "Poliaxis", "status": "active",
            "hosting": {"type": "platform", "platform_hostname": "poliaxis.jbay.uk", "custom_domain": None},
            "organization": {"name": "Poliaxis", "entity_type": "OnlineStore"},
            "indexing": {"eligibility": "blocked"},
            "pages": {}, "created_at": 1, "updated_at": 1,
        }
        self.pages = FakePages([{"tenant_id": "tenant_1", "page_id": "page_1",
                                 "name": "My Links", "updated_at": 1}])

    def test_attaching_re_renders_the_page(self):
        response = sites_handler.attach_page(
            _event({"page_id": "page_1", "slug": "/links"}), FakeSites(self.site), "site_1",
            pages_repo=self.pages)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual([p["page_id"] for p in self.pages.puts], ["page_1"])

    def test_the_re_put_actually_changes_the_document(self):
        # The publish stream fires on a MODIFY. Re-putting an IDENTICAL item is not a modification, so the
        # bumped timestamp is not cosmetic -- it is the whole mechanism.
        sites_handler.attach_page(
            _event({"page_id": "page_1", "slug": "/links"}), FakeSites(self.site), "site_1",
            pages_repo=self.pages)
        self.assertGreater(self.pages.puts[0]["updated_at"], 1)

    def test_detaching_re_renders_it_too(self):
        # The mirror. A detached page must stop claiming an identity it no longer has -- the same reasoning
        # that made domain DISCONNECT re-publish once first-verify already did.
        site = {**self.site, "pages": {"/links": {"page_id": "page_1", "page_type": "landing"}}}
        response = sites_handler.detach_page(
            _event(params={"page_id": "page_1"}), FakeSites(site), "site_1", pages_repo=self.pages)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual([p["page_id"] for p in self.pages.puts], ["page_1"])

    def test_a_failed_attach_re_renders_nothing(self):
        # Re-rendering a page whose attach was rejected would publish an identity it does not have.
        response = sites_handler.attach_page(
            _event({"page_id": "page_1", "slug": "/"}), FakeSites(self.site), "site_1",
            pages_repo=self.pages)
        self.assertNotEqual(response["statusCode"], 200)
        self.assertEqual(self.pages.puts, [])

    def test_a_re_render_failure_never_fails_the_attach(self):
        # Best-effort, like every other re-publish here. The attach is the tenant's action and it succeeded;
        # losing the re-render costs them a stale artifact, losing the attach costs them the operation.
        class Broken(FakePages):
            def put(self, page):
                raise RuntimeError("dynamo is unhappy")

        response = sites_handler.attach_page(
            _event({"page_id": "page_1", "slug": "/links"}), FakeSites(self.site), "site_1",
            pages_repo=Broken([{"tenant_id": "tenant_1", "page_id": "page_1", "updated_at": 1}]))
        self.assertEqual(response["statusCode"], 200)


class SharedImplementationTests(unittest.TestCase):
    def test_the_bulk_republish_uses_the_same_helper(self):
        # _republish_site_pages (custom-domain verify/disconnect) and the attach path must not drift into two
        # ideas of what "re-render this page" means.
        import inspect
        source = inspect.getsource(sites_handler._republish_site_pages)
        self.assertIn("_republish_page(", source)


if __name__ == "__main__":
    unittest.main()
