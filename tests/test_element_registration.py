"""Every tenant-addable element must be registered in ALL the places the builder needs it.

The bug this exists to prevent, found in review on 2026-09-02: `price_highlight` was added to the element
catalog, the renderer, the dispatch table, the builder's `newElement` defaults and its editor — but NOT to
`elementSection`, the element→section serializer. So a tenant could add it, edit it and save the page, and
the section was silently discarded on the way to the document. Nothing errored; it simply never appeared.

That is the shape this codebase keeps producing: several places that must agree, with nothing forcing them
to. A catalog entry is the source of truth here, so the client registrations are checked against it.
"""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")

ADDABLE = sorted(key for key, spec in RULES["elements"].items() if spec.get("ui") == "add")


class AddableElementRegistrationTests(unittest.TestCase):
    def test_there_are_addable_elements_to_check(self):
        # Guards the guard: a selector typo here would make every assertion below vacuous.
        self.assertGreaterEqual(len(ADDABLE), 5, ADDABLE)

    def test_each_has_a_builder_editor_or_default(self):
        for element in ADDABLE:
            with self.subTest(element=element):
                self.assertIn(f'type === "{element}"', BUILDER,
                              f"{element} has no newElement default or editor branch")

    def test_each_serializes_to_a_section(self):
        """elementSection turns builder state into the saved document. Missing here means the tenant's
        section is dropped on save with no error — the price_highlight bug."""
        for element in ADDABLE:
            with self.subTest(element=element):
                self.assertIn(f'element.type === "{element}"', BUILDER,
                              f"{element} is missing from elementSection — it would be dropped on save")

    def test_each_round_trips_back_into_the_builder(self):
        """elementsFromPage rebuilds the editable list when an existing page is opened. Missing here means
        the section survives in the document but vanishes from the form the next time it is edited."""
        for element in ADDABLE:
            with self.subTest(element=element):
                self.assertIn(f'section.type === "{element}"', BUILDER,
                              f"{element} is missing from elementsFromPage — it would vanish on re-edit")

    def test_each_has_a_renderer_registered(self):
        registry = re.search(r"SECTION_REGISTRY: dict\[str, dict\[str, Any\]\] = \{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(registry, "SECTION_REGISTRY not found")
        for element in ADDABLE:
            with self.subTest(element=element):
                self.assertIn(f'"{element}"', registry.group(1),
                              f"{element} has no entry in SECTION_REGISTRY — it would render as nothing")

    def test_each_has_a_baseline_order_slot(self):
        # Already asserted elsewhere for all placeable elements; repeated here so an addable element is
        # checked by this file too, which is the one a new element's author will read.
        for element in ADDABLE:
            with self.subTest(element=element):
                self.assertIn(element, RULES["default_order"])


if __name__ == "__main__":
    unittest.main()


class SectionOrderKeyTests(unittest.TestCase):
    """A section's order key is its TYPE, unless the type is repeatable — then it is the element id.

    The bug this exists to prevent, found 2026-09-02 from a builder screenshot: two sites keyed elements
    by raw `element.id` while every reader keyed them by `sectionOrderKey`. For a NON-repeatable element
    (author_bio, faq, price_highlight) those differ, so the row-dedupe matched nothing and each one grew a
    second, phantom row that sorted somewhere the real section did not — the form and the live preview
    disagreed about where the section was. Same shape as the class above: two places that must agree.
    """

    def _body(self, name):
        start = BUILDER.index(f"{name}")
        return BUILDER[start:start + 1200]

    def test_element_rows_dedupe_by_order_key_not_id(self):
        # contentRows() appends a row for any element the composed sections did not already emit. The
        # identity test must be the ORDER KEY; element.id only equals it for repeatable types.
        self.assertNotIn("row.key === element.id", BUILDER)

    def test_section_order_is_written_with_order_keys(self):
        # Every assignment to builder.section_order must carry keys, never raw element ids.
        for match in re.finditer(r"builder\.section_order = (.+)", BUILDER):
            self.assertNotRegex(
                match.group(1), r"\belement\.id\b",
                "section_order must be written with sectionOrderKey(element), not element.id",
            )

    def test_repeatable_types_are_the_only_id_keyed_ones(self):
        # Guards the premise: if nothing were repeatable, keying by type would be trivially correct and
        # the assertions above would be testing nothing.
        repeatable = sorted(k for k, spec in RULES["elements"].items() if spec.get("repeatable"))
        self.assertTrue(repeatable)
        self.assertNotIn("author_bio", repeatable)
