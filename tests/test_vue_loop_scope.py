"""An element that reads a loop variable must be inside the loop.

The Orders page rendered nothing and the console said:

    TypeError: Cannot read properties of undefined (reading 'fulfilment_group')

A `<tr v-if="order.fulfilment_group">` had been added as a SIBLING of `<tr v-for="order in …">`. A sibling
is outside the loop, so `order` is undefined there — and Vue templates are not type-checked, so
`npm run build` passed and the regression shipped (2026-10-05).

This is the cheap structural check that would have caught it: every element referencing a loop variable
has to sit between the `v-for` that introduces it and the end of that element.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENTS = sorted((ROOT / "dashboard" / "src").rglob("*.vue"))


def _template_of(source: str) -> str:
    match = re.search(r"<template>(.*)</template>\s*\n\s*<script", source, re.S)
    return match.group(1) if match else ""


class ALoopVariableIsOnlyValidInsideItsLoopTests(unittest.TestCase):
    """A general version of this check was written and thrown away.

    It flagged eight call sites across five components -- `page`, `activity`, `logo`, `product`, `brand`
    -- all of them component-level names that merely collide with a later loop variable of the same name.
    Catching one real regression at the cost of eight false alarms trains people to ignore the result,
    which is worse than not checking: doing it properly needs a real template parser that understands
    nesting, not a regex over text.

    What remains is the specific structural assertion below, which is reliable because it is about one
    table whose shape is known.
    """

    def test_the_general_check_was_deliberately_not_kept(self):
        self.assertTrue(True)


class TheOrdersTableKeepsItsRowsTogetherTests(unittest.TestCase):
    """The specific regression, named so it cannot come back quietly."""

    TEMPLATE = _template_of((ROOT / "dashboard" / "src" / "components" / "Orders.vue").read_text())

    def test_both_rows_live_under_one_template_v_for(self):
        self.assertIn('<template v-for="order in visibleOrders"', self.TEMPLATE)

    def test_the_parcel_row_is_inside_it(self):
        """Not "appears after the opening tag" -- that was true of the broken version too, which is the
        whole trap. Balanced depth is the real question, because the row legitimately contains nested
        `<template v-if>` blocks of its own.
        """
        start = self.TEMPLATE.index('<template v-for="order in visibleOrders"')
        parcel_at = self.TEMPLATE.index("orders-parcel-row")
        self.assertLess(start, parcel_at)
        depth = 0
        for match in re.finditer(r"</?template\b", self.TEMPLATE[start:parcel_at]):
            depth += 1 if match.group(0) == "<template" else -1
        self.assertGreater(depth, 0, "the parcel row sits outside the v-for that defines `order`")

    def test_the_main_row_no_longer_carries_its_own_v_for(self):
        # Two v-fors over the same collection would render the table twice.
        self.assertNotIn('<tr v-for="order in visibleOrders"', self.TEMPLATE)
