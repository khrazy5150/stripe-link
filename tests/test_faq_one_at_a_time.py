"""An FAQ opens one question at a time.

Author, 2026-10-15: *"if one accordion is open, and the customer clicks another, all other accordions are
closed and only the one that was clicked is opened."* Checked by default.

Done with a shared `name` on `<details>`, which is the native exclusive accordion: the browser closes the
siblings, the toggle still closes the open one, and the keyboard behaviour is its own. A JS version would
re-implement all of that and only work once the script had run. A browser without it keeps today's
behaviour -- every panel independent -- which is a degradation nobody can be harmed by.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.documents import DocumentValidationError, validate_page_document  # noqa: E402
from stripe_link.runtime.html import render_faq  # noqa: E402

ITEMS = [{"question": "How long?", "answer": "Eight hours."},
         {"question": "Is there a replay?", "answer": "Yes."}]
BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class TheRenderedAccordionTests(unittest.TestCase):
    def test_absent_means_ON(self):
        """So a page gains the behaviour on its next publish rather than needing every FAQ re-edited."""
        markup = render_faq({"id": "faq", "items": ITEMS})
        self.assertEqual(markup.count('<details name="faq-faq">'), 2)

    def test_explicitly_on(self):
        markup = render_faq({"id": "faq", "items": ITEMS, "one_at_a_time": True})
        self.assertEqual(markup.count('<details name="faq-faq">'), 2)

    def test_turning_it_off_restores_independent_panels(self):
        markup = render_faq({"id": "faq", "items": ITEMS, "one_at_a_time": False})
        self.assertEqual(markup.count("<details>"), 2)
        self.assertNotIn("name=", markup)

    def test_every_question_shares_ONE_name(self):
        """The grouping is what makes it exclusive. Two different names would be two accordions."""
        markup = render_faq({"id": "faq", "items": ITEMS + [{"question": "Cost?", "answer": "Low."}]})
        names = {line.split('name="')[1].split('"')[0] for line in markup.splitlines() if "<details name=" in line}
        self.assertEqual(len(names), 1)

    def test_the_group_is_scoped_to_the_section(self):
        """Two FAQ blocks on one page must not fight over the same group."""
        first = render_faq({"id": "faq-a", "items": ITEMS})
        second = render_faq({"id": "faq-b", "items": ITEMS})
        self.assertIn('name="faq-faq-a"', first)
        self.assertIn('name="faq-faq-b"', second)

    def test_the_name_is_escaped(self):
        self.assertNotIn('name="faq-"><script>', render_faq({"id": '"><script>', "items": ITEMS}))

    def test_no_javascript_was_added(self):
        """The browser does this. If a <script> ever appears here, the native behaviour was abandoned."""
        self.assertNotIn("<script", render_faq({"id": "faq", "items": ITEMS}))


class TheStoredSectionTests(unittest.TestCase):
    def page(self, **faq):
        return {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
                "page_id": "p1", "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                "sections": [{"type": "faq", "id": "faq", "items": ITEMS, **faq}]}

    def test_both_values_validate(self):
        for value in (True, False):
            with self.subTest(value=value):
                validate_page_document(self.page(one_at_a_time=value))

    def test_absent_validates(self):
        validate_page_document(self.page())

    def test_a_non_boolean_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self.page(one_at_a_time="yes"))


class TheBuilderTests(unittest.TestCase):
    def test_a_new_faq_starts_with_it_on(self):
        new_element = BUILDER.split('if (type === "faq") return', 1)[1].split(";", 1)[0]
        self.assertIn("one_at_a_time: true", new_element)

    def test_it_is_stored_only_when_turned_OFF(self):
        """Writing `true` would freeze every page against a future change of default, and writing it on
        save is how a page stops tracking the baseline."""
        save = BUILDER.split('if (element.type === "faq") {', 1)[1].split("\n  }", 1)[0]
        self.assertIn('element.one_at_a_time === false ? { one_at_a_time: false } : {}', save)

    def test_loading_treats_absent_as_on(self):
        load = BUILDER.split('} else if (section.type === "faq") {', 1)[1].split("\n    }", 1)[0]
        self.assertIn("one_at_a_time: section.one_at_a_time !== false", load)

    def test_the_checkbox_exists(self):
        self.assertIn("Open one question at a time", BUILDER)


if __name__ == "__main__":
    unittest.main()
