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
