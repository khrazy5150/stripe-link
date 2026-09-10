"""The store avatar is resolved BY REFERENCE, so changing it updates every page that never overrode it.

A person's picture changes over time, and a published page should show the current one. Copying the URL
onto each page at build time -- the first implementation -- froze each page at whatever the avatar was the
day it was made, which is the opposite of what a profile picture is for.

It lives on the TENANT profile rather than the user profile, for the reasons load_tenant_preferences already
gives about the store's font: pages carry no owner, publish runs from a stream holding only the page, and
the avatar is a property of the STORE customers see rather than of a staff login.
"""
import json
import pathlib
import unittest

from handlers.tenant_avatar import handler as avatar_handler
from stripe_link.runtime import html as html_module
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
PREFERENCES = (ROOT / "components" / "Preferences.vue").read_text(encoding="utf-8")
PROFILE_VUE = (ROOT / "components" / "Profile.vue").read_text(encoding="utf-8")
BUILDER = (ROOT / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def _hero(**overrides):
    section = {"type": "hero_media", "images": ["https://img.example/hero.jpg"]}
    section.update(overrides)
    return section


class ResolutionTests(unittest.TestCase):
    def tearDown(self):
        html_module._RENDER_PREFERENCES.clear()

    def _render(self, section, store_avatar=""):
        html_module._RENDER_PREFERENCES.clear()
        if store_avatar:
            html_module._RENDER_PREFERENCES["avatar_url"] = store_avatar
        return html_module.render_hero_media(section, {}, {})

    def test_a_page_with_no_avatar_inherits_the_store_one(self):
        self.assertIn("store.jpg", self._render(_hero(), store_avatar="https://img.example/store.jpg"))

    def test_a_page_upload_overrides_it_for_that_page_only(self):
        markup = self._render(_hero(avatar_url="https://img.example/page.jpg"),
                              store_avatar="https://img.example/store.jpg")
        self.assertIn("page.jpg", markup)
        self.assertNotIn("store.jpg", markup)

    def test_no_avatar_anywhere_renders_none(self):
        self.assertNotIn("sl-avatar", self._render(_hero()))

    def test_the_reserved_overhang_follows_the_RESOLVED_avatar(self):
        # has-avatar reserves the gap the overlay hangs into. An inherited avatar overhangs just as much as
        # an uploaded one, so keying it on the page's own field would leave the overlay clipped.
        self.assertIn("has-avatar", self._render(_hero(), store_avatar="https://img.example/store.jpg"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeDocumentRepository("tenant_id")
        self.repo.put({"schema_version": "2026-05-29", "document_type": "tenant_profile",
                       "tenant_id": "t1", "owner": {"first_name": "A", "last_name": "B",
                                                    "email": "a@b.c"}})

    def _call(self, method, body=None):
        event = {"httpMethod": method, "queryStringParameters": {"tenant_id": "t1"}}
        if body is not None:
            event["body"] = json.dumps(body)
        return avatar_handler(event, None, repository=self.repo)

    def test_setting_and_reading_it_back(self):
        self._call("PUT", {"avatar_url": "https://img.example/a.jpg"})
        self.assertEqual(json.loads(self._call("GET")["body"])["avatar_url"],
                         "https://img.example/a.jpg")

    def test_clearing_removes_the_field_rather_than_storing_an_empty_string(self):
        self._call("PUT", {"avatar_url": "https://img.example/a.jpg"})
        self._call("PUT", {"avatar_url": ""})
        self.assertNotIn("avatar_url", self.repo.get("t1", "t1"))

    def test_an_http_url_is_refused(self):
        # It renders on the tenant's own pages; http:// would make every one of them mixed-content, which
        # browsers block silently.
        response = self._call("PUT", {"avatar_url": "http://img.example/a.jpg"})
        self.assertEqual(response["statusCode"], 400)


class WiringTests(unittest.TestCase):
    def test_the_builder_never_copies_the_store_avatar_onto_a_page(self):
        # The whole point of the reference: copying would freeze the page at today's picture.
        self.assertNotIn("builder.avatar_url = profileStore", BUILDER)
        self.assertIn("effectiveAvatarUrl", BUILDER)

    def test_it_is_a_STORE_setting_not_a_personal_one(self):
        # Two people editing one store must not put different faces on its pages.
        self.assertIn("Store Avatar", PREFERENCES)
        self.assertNotIn("Avatar</h2>", PROFILE_VUE)


if __name__ == "__main__":
    unittest.main()
