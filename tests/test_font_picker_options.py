"""The builder's font picker must offer exactly what the service can serve.

`SERVABLE_FAMILIES` is an ALLOW-LIST, not a wish list: a family the service cannot serve produces a
stylesheet request that 404s, which is worse than shipping no webfont at all. The picker is a second copy
of that list living in the dashboard, and the dashboard cannot import Python — so the two are pinned here
instead. Adding a family to one side and not the other is the failure this test exists to catch.

It also pins the picker to the roles the resolver actually honours as page-level overrides, so a role typo
cannot silently write a key `resolve_families` never reads.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.domain.fonts import OPTIONAL_ROLES, ROLES, SERVABLE_FAMILIES, SYSTEM, resolve_families

BUILDER = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components" / "LandingPages.vue"
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples" / "page-creatine-standard.json"


def _page_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _js_array(name: str) -> str:
    source = BUILDER.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = \[(.*?)\];", source, re.S)
    assert match, f"{name} not found in {BUILDER.name}"
    return match.group(1)


class FontPickerOptionTests(unittest.TestCase):
    def test_the_picker_offers_exactly_the_servable_families(self):
        offered = set(re.findall(r'"([^"]+)"', _js_array("builderFontFamilies")))
        self.assertEqual(
            offered, SERVABLE_FAMILIES,
            "the builder's font list and SERVABLE_FAMILIES have drifted; a family in only one of them is "
            "either unofferable or unservable",
        )

    def test_every_offered_role_is_one_the_resolver_reads_from_the_page(self):
        roles = set(re.findall(r'key:\s*"(\w+)"', _js_array("builderFontRoles")))
        self.assertTrue(roles)
        self.assertLessEqual(roles, set(ROLES) | set(OPTIONAL_ROLES))

    def test_the_shape_the_picker_writes_both_validates_and_resolves(self):
        """The two halves of the contract, checked together.

        `resolve_families` reads a bare family string perfectly well, so exercising only the resolver said
        the picker worked while `validate_page_document` — which runs FIRST, on every save — rejected it
        with "Page theme.fonts.body must be an object". Anything that claims the picker is correct has to
        pass through both.
        """
        for family in ["Poppins", SYSTEM]:
            with self.subTest(family=family):
                page = _page_fixture()
                page.setdefault("theme", {})["fonts"] = {
                    "heading": {"family": family}, "body": {"family": family},
                }
                validate_page_document(page)   # raises if the shape is wrong
                self.assertEqual(resolve_families(page)["heading"], family)

    def test_a_bare_family_string_is_rejected_which_is_why_the_picker_writes_an_object(self):
        page = _page_fixture()
        page.setdefault("theme", {})["fonts"] = {"body": "Poppins"}
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page)

    def test_the_picker_never_assigns_a_bare_string(self):
        body = re.search(r"function setFontFamily\(role, value\) \{(.*?)\n\}", BUILDER.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(body)
        self.assertNotIn("] = family", body.group(1), "setFontFamily must assign { family }, not a string")

    def test_the_system_sentinel_is_spelled_the_way_the_resolver_reads_it(self):
        # "no webfont" is a real choice that must beat the preset, and it only does so if the value the
        # picker writes is the exact sentinel is_system() compares against.
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn(f'<option value="{SYSTEM}">', source)


if __name__ == "__main__":
    unittest.main()
