"""The Site chosen in step 1 of the create wizard actually gets used.

Author, 2026-09-17: "Why can't the software auto-attach the page to the selected site in Step 1 when it was
selected? All pages must be attached to a Site anyway, which is the point of Step 1." The workaround they had
been living with: save the page, leave the builder, find it in the list, kebab menu, Attach a Site, go back.

It HAD been built -- in savePage(), the wizard's own save. Nothing had called savePage() since auto-save
moved the builder onto saveBuilderPageWithStatus(), so the orphaned copy kept the behaviour looking present
in the source while it could never run. The same failure this codebase keeps producing: two things that must
agree, with nothing forcing them to.
"""
import pathlib
import re
import unittest

BUILDER = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"
           / "LandingPages.vue").read_text(encoding="utf-8")


def _function(name):
    """The body of a top-level function, to the start of the next one."""
    start = BUILDER.index(f"function {name}(")
    rest = BUILDER[start:]
    end = rest.find("\nfunction ", 1)
    other = rest.find("\nasync function ", 1)
    if other != -1 and (end == -1 or other < end):
        end = other
    return rest[:end if end != -1 else len(rest)]


class AttachOnFirstSaveTests(unittest.TestCase):
    def test_the_save_the_builder_actually_calls_honours_the_choice(self):
        body = _function("saveBuilderPageWithStatus")
        self.assertIn("pendingSiteAttach", body)
        self.assertIn("attachCreatedPageToSite(", body)

    def test_it_asks_whether_this_is_the_first_save_BEFORE_saving(self):
        """The save is what stops it being the first one.

        `builderExistingPageId` is assigned from the response, so reading it after the POST would say "not
        the first save" every time and the attach would never fire.
        """
        body = _function("saveBuilderPageWithStatus")
        first = body.index("const firstSave")
        post = body.index('apiRequest("/pages"')
        self.assertLess(first, post)
        self.assertIn("firstSave && pendingSiteAttach.value", body)

    def test_it_attaches_once_and_forgets(self):
        # Left set, a later save would re-attach a page the tenant may since have moved.
        body = _function("saveBuilderPageWithStatus")
        self.assertIn('pendingSiteAttach.value = ""', body)

    def test_a_failure_surfaces_where_the_builder_can_show_it(self):
        # The helper defaulted to `wizardError`, which the builder does not render -- the attach would fail
        # silently and the tenant would find out by publishing an unattached page.
        self.assertIn("errorRef = wizardError", BUILDER)
        self.assertIn('attachCreatedPageToSite(saved, siteId, "offer", undefined, error)', BUILDER)


class NoOrphanedCopyTests(unittest.TestCase):
    def test_the_wizards_dead_save_is_gone(self):
        """It was the ONLY caller of the attach, and nothing called it.

        Worse than dead: reading it says the feature works. Deleted rather than wired up, because the
        builder's save is the one that runs.
        """
        self.assertNotIn("async function savePage(", BUILDER)

    def test_exactly_one_place_acts_on_the_pending_choice(self):
        """Two consumers is how the live one drifts from the one people read -- which is this whole bug.

        Clearing it in resetWizard does not count: that discards the choice, it does not honour it.
        """
        # Counted on the CHOICE being acted on, not on the call's literal text -- the helper's own parameter
        # is named siteId too, so matching that counted the definition as a second consumer.
        self.assertEqual(BUILDER.count("firstSave && pendingSiteAttach.value"), 1)
        self.assertEqual(BUILDER.count("const siteId = pendingSiteAttach.value;"), 1)


class NoticeTests(unittest.TestCase):
    def test_the_not_attached_notice_is_silent_while_an_attach_is_pending(self):
        """A notice needs an action the tenant must take.

        They answered this in step 1; until the first save there is no page_id to attach and nothing they
        could do. Telling them anyway is what taught them to distrust the panel.
        """
        computed = BUILDER.split("const previewNeedsSite = computed(", 1)[1].split(");", 1)[0]
        self.assertIn("!pendingSiteAttach.value", computed)

    def test_it_still_fires_for_a_page_with_no_site_at_all(self):
        computed = BUILDER.split("const previewNeedsSite = computed(", 1)[1].split(");", 1)[0]
        self.assertIn("!siteByPageId.value[builder.page_id]", computed)
        self.assertIn("builderOfferType.value === \"lead_social\"", computed)


if __name__ == "__main__":
    unittest.main()


class StaleSiteAfterAttachTests(unittest.TestCase):
    """Nothing between the attach and the end of the save may write a Site document it read BEFORE it.

    Reported 2026-09-17, the "not attached to a Site" notice reappearing right after a successful create. The
    username save, added the same day, took the Site as an argument -- captured a line above the attach, which
    rewrites that Site's `pages` map server-side. Saving the snapshot posted the pre-attach map back and
    un-attached the page that had just been attached.

    The shape is the one this codebase keeps producing: a value read before the write that invalidates it. The
    fix is that the function takes an ID and reads the document itself, so there is no window to be stale in.
    """

    def test_the_username_save_takes_an_id_not_a_document(self):
        self.assertIn("async function saveCreatorUsername(siteId)", BUILDER)
        self.assertIn("await saveCreatorUsername(siteId)", BUILDER)

    def test_it_reads_the_site_after_the_attach_not_before(self):
        body = _function("saveCreatorUsername")
        self.assertIn("sitesStore.sites.find((entry) => entry.site_id === siteId)", body)

    def test_the_save_block_holds_no_site_document_across_the_attach(self):
        """Only the NAME is carried over, which the attach cannot change."""
        block = BUILDER.split("if (firstSave && pendingSiteAttach.value) {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("const siteName =", block)
        self.assertNotIn("const site =", block)
