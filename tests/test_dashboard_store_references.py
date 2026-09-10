"""Every `*Store` a component uses must be declared in that component.

Reported 2026-09-10: editing a product failed with `ReferenceError: productStore is not defined`.
Products.vue declares `const store = useProductsStore()` but one call site said `productStore.fetchFull(row)`
-- the name Offers.vue uses. It shipped on 2026-09-01 and edit-a-product was broken for NINE DAYS.

Nothing caught it because nothing could. Vite does not resolve identifiers inside a function body, so the
build succeeded; the error only exists when the handler runs; and the dashboard has no ESLint config, so
`no-undef` -- which is exactly the rule for this -- was never run.

This is a narrow stand-in for that rule, not a replacement. `*Store` is a strong convention here, which
makes the check reliable, but a real linter would catch the whole class rather than the one shape that
has bitten so far. Adding ESLint is the better fix and is recorded in plans/TODO.md.
"""
import pathlib
import re
import unittest

COMPONENTS = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"


class StoreReferenceTests(unittest.TestCase):
    def test_the_scan_finds_components_to_check(self):
        # Guards the guard: a path change that matched no files would make the assertion below vacuous.
        self.assertGreaterEqual(len(list(COMPONENTS.rglob("*.vue"))), 10)

    def test_every_store_reference_is_declared_in_its_component(self):
        offenders = []
        for component in sorted(COMPONENTS.rglob("*.vue")):
            text = component.read_text(encoding="utf-8")
            used = set(re.findall(r"\b(\w+Store)\s*\.", text))
            declared = set(re.findall(r"\b(?:const|let|var)\s+(\w+Store)\s*=", text))
            for name in sorted(used - declared):
                offenders.append(f"{component.name}: {name}")
        self.assertEqual(
            offenders, [],
            "these reference a store the component never declares, which is a ReferenceError the moment "
            "the code runs: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
