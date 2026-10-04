"""The page's JavaScript is built as a list of Python strings. Nothing checks that it parses.

Every element script in `runtime/html.py` is assembled line by line in Python and inlined into a published
artifact. A stray bracket there is not a test failure or a deploy failure -- it is a silent one: the page
renders, the script throws on load, and the element simply never appears. This file has already been
burned twice by the gap between the source and the published page (the cart selector that matched nothing,
the CTA href built once at load), both found by reading the artifact rather than the code.

So: render it and hand it to a parser. `node --check` if node is here, and `esprima`-free otherwise --
skipped rather than faked, because a check that cannot run must say so.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import stripe_link.runtime.html as html_module

NODE = shutil.which("node")


def _script_body(rendered):
    body = re.sub(r"^.*?<script[^>]*>", "", rendered, count=1, flags=re.S)
    return re.sub(r"</script>\s*$", "", body, flags=re.S)


@unittest.skipIf(NODE is None, "node is not installed; cannot parse the emitted JavaScript")
class TheEmittedJavaScriptParsesTests(unittest.TestCase):
    def _check(self, source, label):
        self.assertTrue(source.strip(), f"{label} rendered nothing to check")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(source)
            path = handle.name
        try:
            result = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, f"{label} is not valid JavaScript:\n{result.stderr}")

    def test_the_shipping_selector_parses(self):
        html_module._RENDER_SHIPPING["_active"] = True
        try:
            self._check(_script_body(html_module.render_shipping_selector_script()),
                        "render_shipping_selector_script")
        finally:
            html_module._RENDER_SHIPPING.pop("_active", None)


class TheCountryDropdownIsReadableTests(unittest.TestCase):
    """A catch-all zone expands to 233 entries. Two countries could wear their ISO codes; 233 cannot --
    "AD / AE / AF" is not a list anyone can shop from."""

    def setUp(self):
        html_module._RENDER_SHIPPING["_active"] = True
        self.addCleanup(html_module._RENDER_SHIPPING.pop, "_active", None)
        self.js = _script_body(html_module.render_shipping_selector_script())

    def test_options_are_labelled_with_country_names(self):
        self.assertIn("Intl.DisplayNames", self.js)
        self.assertIn("nameOf(code)", self.js)

    def test_a_name_lookup_that_throws_falls_back_to_the_code(self):
        # `Intl.DisplayNames` is absent on older browsers and throws on a bad tag. A dropdown of blanks
        # would be worse than a dropdown of codes.
        self.assertIn("catch (e) { return code; }", self.js)

    def test_the_tenants_own_destinations_come_first(self):
        # Their order is a statement about where they mainly sell; burying the United States between
        # Ukraine and Uruguay throws it away.
        self.assertIn("data.primary_countries", self.js)
        self.assertLess(self.js.index("primary.forEach(add)"), self.js.index("rest.forEach(add)"))

    def test_the_rest_are_sorted_by_the_name_actually_shown(self):
        # Sorted client-side because the server has codes and no locale.
        self.assertIn("nameOf(a).localeCompare(nameOf(b))", self.js)

    def test_the_two_groups_are_separated(self):
        self.assertIn("sep.disabled = true", self.js)
