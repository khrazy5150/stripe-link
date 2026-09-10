"""The tenant's saved avatar is the default for every page they build.

`user_profile.profile_images` was validated (max 10) and written by NOTHING -- no handler, no UI -- so
"use your saved image" had nothing behind it. The Profile screen now produces it and the builder consumes
it, on checkout pages and link pages alike.

These are source-level pins rather than behavioural tests: the dashboard has no JS test runner (see the
ESLint item in TODO.md), so this asserts the wiring exists at all -- which is the failure mode that has
actually happened here, twice, with fields that had no producer.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
PROFILE_VUE = (ROOT / "components" / "Profile.vue").read_text(encoding="utf-8")
PROFILE_STORE = (ROOT / "stores" / "profile.js").read_text(encoding="utf-8")
BUILDER = (ROOT / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class ProducerTests(unittest.TestCase):
    def test_the_profile_screen_can_now_write_profile_images(self):
        # The whole point: the field had no producer, which is why "use your saved image" was empty.
        self.assertIn("doc.profile_images = { images: profileImages.value }", PROFILE_VUE)

    def test_removing_the_avatar_clears_the_field_rather_than_storing_an_empty_list(self):
        self.assertIn("delete doc.profile_images", PROFILE_VUE)

    def test_the_store_exposes_it_to_every_screen(self):
        self.assertIn("profileImages", PROFILE_STORE)
        self.assertIn("profile_images", PROFILE_STORE)


class BuilderDefaultTests(unittest.TestCase):
    def test_a_new_page_starts_with_the_saved_avatar(self):
        self.assertIn("builder.avatar_url = profileStore.profileImages[0]?.url", BUILDER)

    def test_the_default_is_applied_only_when_the_page_has_none(self):
        # An uploaded page avatar is an override and must survive.
        match = re.search(r"if \(!builder\.avatar_url\) builder\.avatar_url = profileStore", BUILDER)
        self.assertIsNotNone(match, "the default must be guarded on the page having no avatar")

    def test_the_default_is_NOT_applied_when_reopening_an_existing_page(self):
        """On an existing page an empty avatar_url is a DECISION -- the tenant pressed Remove. Defaulting
        there would silently undo it every time they reopened the builder, which is the same
        'looks-applied-but-isn't' shape that cost a day on section removal."""
        applied_at = BUILDER.index("builder.avatar_url = profileStore.profileImages[0]?.url")
        wizard_at = BUILDER.index("function startBuilderFromWizard")
        populate_at = BUILDER.index("function populateBuilderFromPage")
        self.assertGreater(applied_at, wizard_at)
        self.assertNotIn("profileStore.profileImages",
                         BUILDER[populate_at:populate_at + 4000])


if __name__ == "__main__":
    unittest.main()
