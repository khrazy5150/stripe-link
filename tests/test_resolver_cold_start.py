"""The custom-domain resolver is on the hot path of every custom domain, and its cold start was 419ms of
imports it did not use.

Measured 2026-10-25, with the Worker caching resolve responses for only 60 seconds: on a quiet domain
nearly every view paid a cold start, and the resolver Lambda was the largest single hop in a page view
(~0.24s) — larger than fetching the page itself.

Two causes, both the same mistake in different places: a cheap thing imported from an expensive module.

  runtime.publishing   383ms / 205 modules, imported for `public_url` — three lines of string formatting
  urllib.request       131ms /  66 modules, imported at the top of custom_domains, whose pure helpers
                       (normalize_domain, route_target, …) never make an HTTP call

This guards both. It is a budget, not a benchmark: it asserts the heavy modules are not reachable from
the resolver's import graph at all, which is a fact about structure rather than about how fast the
machine running the tests happens to be.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modules_after_importing(module: str) -> set[str]:
    """Import in a FRESH interpreter — in-process the answer depends on what earlier tests imported."""
    code = (
        "import sys; sys.path.insert(0, 'src');"
        f"import {module};"
        "print('\\n'.join(sorted(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=ROOT, timeout=120)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return set(out.stdout.split())


class ResolverImportBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = _modules_after_importing("handlers.custom_domains_resolve")

    def test_the_publish_pipeline_is_not_dragged_in(self):
        """`public_url` lives in runtime.artifacts now. Importing it from runtime.publishing pulled in
        documents, composition, funnels, reviews and upsell pages — a pipeline this handler never runs."""
        self.assertNotIn("stripe_link.runtime.publishing", self.loaded)
        for module in ("stripe_link.domain.funnels", "stripe_link.domain.opportunities",
                       "stripe_link.runtime.upsell_pages", "stripe_link.domain.bnpl"):
            self.assertNotIn(module, self.loaded, module)

    def test_the_http_stack_is_not_dragged_in(self):
        """custom_domains imports urllib lazily. Its pure helpers are what the resolver uses, and none of
        them open a socket — paying for email, http.client and ssl to format a hostname is the tax."""
        for module in ("urllib.request", "http.client", "ssl", "email"):
            self.assertNotIn(module, self.loaded, module)

    def test_boto3_still_waits_until_a_table_is_touched(self):
        # The pattern the rest of this fix copies; it was already right and must stay right.
        self.assertNotIn("boto3", self.loaded)

    def test_it_still_imports_what_it_genuinely_needs(self):
        # A budget that passed by breaking the handler would be worse than no budget.
        for module in ("stripe_link.domain.custom_domains", "stripe_link.runtime.artifacts",
                       "stripe_link.repositories.documents"):
            self.assertIn(module, self.loaded, module)

    def test_the_graph_stays_small(self):
        """157 modules before, 89 after. The ceiling is deliberately loose — this catches a regression in
        kind (someone importing a pipeline), not a module or two of honest growth."""
        self.assertLess(len(self.loaded), 120, f"resolver now imports {len(self.loaded)} modules")


class PublicUrlTests(unittest.TestCase):
    def test_both_import_paths_are_the_same_function(self):
        # publishing re-exports it, so the move cost no caller anything.
        from stripe_link.runtime.artifacts import public_url as from_artifacts
        from stripe_link.runtime.publishing import public_url as from_publishing
        self.assertIs(from_publishing, from_artifacts)

    def test_it_still_formats_what_it_always_did(self):
        from stripe_link.runtime.artifacts import public_url
        self.assertEqual(public_url("d1.cloudfront.net", "page_x/index.html"),
                         "https://d1.cloudfront.net/page_x/index.html")
        self.assertEqual(public_url("d1.cloudfront.net/", "page_x/index.html"),
                         "https://d1.cloudfront.net/page_x/index.html")
        self.assertEqual(public_url("", "page_x/index.html"), "")


if __name__ == "__main__":
    unittest.main()
