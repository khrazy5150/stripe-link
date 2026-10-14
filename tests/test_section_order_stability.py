"""A dragged order has to survive closing the page.

Reported 2026-10-14: "Drag and drop positioning looks different in the preview pane than what it looks
like when you go to the link. Once the page is closed, the order falls back to whatever it was originally."

The cause: `elementsFromPage` minted a fresh `localId("el")` for EVERY element it rebuilt, throwing away
the id the document had saved. `sectionOrderKey` keys a REPEATABLE type by its id, so `section_order`
still named ids that no longer existed — nothing matched, and the page reverted to the baseline order.

Non-repeatable elements key by TYPE and never noticed, which is why this survived: it could only be seen
on a page carrying content blocks, ribbons or (now) info cards and dates.
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
COMPOSER = (ROOT / "dashboard" / "src" / "composables" / "pageComposer.js").read_text(encoding="utf-8")
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
REPEATABLE = sorted(k for k, v in RULES["elements"].items() if v.get("repeatable"))


def hydrate_body():
    start = BUILDER.index("function elementsFromPage(sections) {")
    return BUILDER[start:BUILDER.index("\n}\n", start)]


def serialize_body():
    start = BUILDER.index("function elementSection(element) {")
    return BUILDER[start:start + 9000]


class ThePremise(unittest.TestCase):
    def test_a_repeatable_type_is_keyed_by_its_id(self):
        """If this stops being true the rest of this file is testing nothing."""
        self.assertIn("spec.repeatable && section?.id ? section.id : type", COMPOSER)

    def test_there_are_repeatable_types_to_protect(self):
        self.assertGreaterEqual(len(REPEATABLE), 3, REPEATABLE)


class HydrationKeepsTheSavedId(unittest.TestCase):
    def test_no_element_is_rebuilt_with_a_fresh_id(self):
        body = hydrate_body()
        self.assertNotIn('id: localId("el")', body,
                         "a regenerated id orphans every order key that names it")
        self.assertIn("const keepId = (section) =>", body)

    def test_every_push_uses_the_keeper(self):
        body = hydrate_body()
        pushes = re.findall(r"elements\.push\(\{ id: ([^,]+),", body)
        self.assertTrue(pushes)
        for expression in set(pushes):
            with self.subTest(expression=expression):
                self.assertEqual(expression.strip(), "keepId(section)")

    def test_a_fresh_id_is_still_minted_for_a_NEW_element(self):
        """The fix must not take the id away from an element the tenant just added."""
        self.assertIn('const base = { id: localId("el"), type };', BUILDER)

    def test_duplicates_fall_back_rather_than_colliding(self):
        """A legacy content_block section holding several blocks becomes several elements; they cannot all
        answer to the section's one id."""
        body = hydrate_body()
        self.assertIn("seen.has(id)", body)
        self.assertIn("seen.add(id)", body)


class SerialisationWritesItBack(unittest.TestCase):
    """Keeping the id on the way in is only half of it: a repeatable section that saves without one gets
    keyed by TYPE, and two of them would collapse onto a single order slot."""

    def test_every_repeatable_addable_type_writes_its_id(self):
        body = serialize_body()
        for element in REPEATABLE:
            marker = f'element.type === "{element}"'
            if marker not in body:
                continue   # not builder-addable (catalog_grid is generated for storefront pages)
            with self.subTest(element=element):
                chunk = body[body.index(marker):body.index(marker) + 900]
                self.assertIn("id: element.id", chunk)


if __name__ == "__main__":
    unittest.main()
