"""The resolver hands the edge an experiment DEFINITION, and never an assignment.

plans/AB_TESTING.md A1. The Worker caches resolve responses for 60 seconds
(`Cache-Control: public, max-age=60`), so an assignment made here would give every visitor in that window
the same variant — a time-bucketed split rather than a random one, which on low traffic hands one variant
nearly everything. The server therefore says what the experiment IS (identical for everyone, so caching is
correct) and the edge says who gets which.

`origin_url` stays the CONTROL's, so a Worker that does not understand `experiment` still serves the
control page: the backend can ship before the edge, and a Worker rollback degrades to "no experiment"
rather than to a broken page.
"""
import json
import unittest

from stripe_link.domain.experiments import experiment_route_block, running_experiment_for


def _experiment(**over):
    base = {
        "experiment_id": "exp_1", "tenant_id": "t1", "status": "running",
        "control_page_id": "page_A", "cookie_name": "jb_ab_exp_1",
        "variants": [{"page_id": "page_A", "weight": 50}, {"page_id": "page_B", "weight": 50}],
    }
    base.update(over)
    return base


def _url(page_id):
    return f"https://cdn.example/{page_id}/index.html"


class RunningOnlyTests(unittest.TestCase):
    def test_a_running_experiment_on_the_control_page_is_found(self):
        self.assertEqual(running_experiment_for("page_A", [_experiment()])["experiment_id"], "exp_1")

    def test_every_other_status_serves_the_control(self):
        """Draft, paused and completed need no edge behaviour: the URL already serves the control."""
        for status in ("draft", "paused", "completed"):
            with self.subTest(status=status):
                self.assertIsNone(running_experiment_for("page_A", [_experiment(status=status)]))

    def test_it_matches_on_the_CONTROL_page_not_a_variant(self):
        """The control is the page with a route — the one a visitor actually asks for. A variant has no
        route while the experiment runs, which is what keeps it out of the index."""
        self.assertIsNone(running_experiment_for("page_B", [_experiment()]))

    def test_an_unrelated_page_is_unaffected(self):
        self.assertIsNone(running_experiment_for("page_Z", [_experiment()]))

    def test_no_experiments_at_all(self):
        self.assertIsNone(running_experiment_for("page_A", []))
        self.assertIsNone(running_experiment_for("page_A", None))
        self.assertIsNone(running_experiment_for("", [_experiment()]))


class DefinitionForTheEdgeTests(unittest.TestCase):
    def test_the_block_carries_what_the_edge_needs_and_no_assignment(self):
        block = experiment_route_block(_experiment(), _url)
        self.assertEqual(set(block), {"experiment_id", "cookie_name", "variants"})
        # No chosen variant, no roll, nothing per-visitor.
        self.assertNotIn("assigned", json.dumps(block))
        self.assertEqual([v["page_id"] for v in block["variants"]], ["page_A", "page_B"])

    def test_each_variant_carries_its_own_artifact_url(self):
        block = experiment_route_block(_experiment(), _url)
        self.assertEqual(block["variants"][1]["origin_url"], "https://cdn.example/page_B/index.html")

    def test_the_cookie_is_named_per_experiment(self):
        """Two experiments running at once on different pages must not overwrite each other's pin."""
        first = experiment_route_block(_experiment(), _url)["cookie_name"]
        second = experiment_route_block(_experiment(experiment_id="exp_2", cookie_name=""), _url)["cookie_name"]
        self.assertNotEqual(first, second)
        self.assertEqual(second, "jb_ab_exp_2")

    def test_a_variant_whose_artifact_is_missing_is_dropped(self):
        """The edge would proxy a 404 to a real visitor. Losing one arm of a test beats serving nobody."""
        block = experiment_route_block(_experiment(), lambda p: "" if p == "page_B" else _url(p))
        self.assertEqual([v["page_id"] for v in block["variants"]], ["page_A"])

    def test_weights_are_normalised_so_the_edge_need_not_validate(self):
        block = experiment_route_block(
            _experiment(variants=[{"page_id": "page_A", "weight": "40"},
                                  {"page_id": "page_B", "weight": -5},
                                  {"page_id": "page_C", "weight": None}]), _url)
        self.assertEqual([v["weight"] for v in block["variants"]], [40, 0, 0])

    def test_all_zero_weights_produce_nothing_so_the_control_keeps_serving(self):
        block = experiment_route_block(
            _experiment(variants=[{"page_id": "page_A", "weight": 0}, {"page_id": "page_B", "weight": 0}]), _url)
        self.assertEqual(block, {})

    def test_a_variant_with_no_page_is_skipped(self):
        block = experiment_route_block(
            _experiment(variants=[{"page_id": "", "weight": 50}, {"page_id": "page_B", "weight": 50}]), _url)
        self.assertEqual([v["page_id"] for v in block["variants"]], ["page_B"])


class ResolverWiringTests(unittest.TestCase):
    import pathlib as _pathlib

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    RESOLVE = (ROOT / "src/handlers/custom_domains_resolve.py").read_text(encoding="utf-8")

    def test_the_control_stays_the_default_origin(self):
        """A Worker that does not understand `experiment` must still serve the control, so the backend can
        ship first and a Worker rollback degrades to no experiment rather than a broken page."""
        block = self.RESOLVE.split('route = {"type": "origin_url", "origin_url": origin_url}', 1)[1][:900]
        self.assertIn('route["experiment"] = experiment_block', block)
        self.assertNotIn('route["origin_url"] =', block)

    def test_an_experiment_lookup_can_never_break_serving(self):
        """A resolve that 500s would take a tenant's whole site down over an A/B test."""
        helper = self.RESOLVE.split("def _experiment_for_page", 1)[1][:1200]
        self.assertIn("except Exception", helper)
        self.assertIn("return {}", helper)

    def test_crawl_files_are_never_experimented_on(self):
        # robots.txt and sitemap.xml belong to the site, not a page; varying them per visitor is incoherent.
        self.assertIn('page_id_under_test, price_context_under_test = "", ""', self.RESOLVE)

    def test_the_resolver_is_granted_the_table_it_now_reads(self):
        template = (self.ROOT / "template.yaml").read_text(encoding="utf-8")
        import re
        block = re.search(r"^  CustomDomainsResolveFunction:\n((?:    .*\n|\n)*)", template, re.M).group(1)
        self.assertIn("TableName: !Ref ExperimentsTable", block)
        # Read-only: view counts are pinged separately by the Worker, so this must not be Crud.
        self.assertNotIn("DynamoDBCrudPolicy:\n            TableName: !Ref ExperimentsTable", block)


if __name__ == "__main__":
    unittest.main()
