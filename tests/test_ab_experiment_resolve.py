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

from stripe_link.domain.experiments import (
    experiment_route_block,
    running_experiment_for,
    variant_of_running_experiment,
)
from handlers.custom_domains_resolve import handler as resolve_handler
from tests.fakes import FakeDocumentRepository


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
        """A resolve that 500s would take a tenant's whole site down over an A/B test.

        Exercised rather than grepped: the guarantee is "the page still serves when the experiments table
        does not", and only running it can show that.
        """
        class ExplodingExperiments:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("experiments table is unavailable")

        index = FakeDocumentRepository("domain")
        index.put({"tenant_id": "t1", "domain": "shop.example.com", "status": "active",
                   "target_page_id": "page_A"})
        response = resolve_handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com"}},
            None, index_repo=index, pages_domain="pages.example.com",
            experiments_repo=ExplodingExperiments(),
        )

        self.assertEqual(response["statusCode"], 200)
        route = json.loads(response["body"])["route"]
        self.assertEqual(route["origin_url"], "https://pages.example.com/page_A/index.html")
        self.assertNotIn("experiment", route)
        # and it must not guess "noindex" out of an error, either
        self.assertNotIn("noindex", route)

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


class VariantAsItsOwnResourceTests(unittest.TestCase):
    """The indexing question, which is NOT the assignment question.

    An experiment runs at the control's URL: same address, no redirect, only the origin artifact varies. So
    that URL keeps the ranking signals the test exists to improve. The risk is a variant someone attached to
    a public slug of its own -- a second URL serving near-identical content.
    """

    def test_a_variant_attached_to_its_own_slug_is_found(self):
        self.assertEqual(
            variant_of_running_experiment("page_B", [_experiment()])["experiment_id"], "exp_1")

    def test_THE_CONTROL_IS_NOT_A_VARIANT(self):
        # The control is listed in `variants` too (key "control"), so excluding it is not incidental: this is
        # the single assertion standing between an A/B test and deindexing the page it was meant to improve.
        self.assertIsNone(variant_of_running_experiment("page_A", [_experiment()]))

    def test_only_a_running_experiment_counts(self):
        for status in ("draft", "paused", "completed", ""):
            with self.subTest(status=status):
                self.assertIsNone(variant_of_running_experiment("page_B", [_experiment(status=status)]))

    def test_an_unrelated_page_is_unaffected(self):
        self.assertIsNone(variant_of_running_experiment("page_Z", [_experiment()]))

    def test_empty_inputs(self):
        self.assertIsNone(variant_of_running_experiment("page_B", []))
        self.assertIsNone(variant_of_running_experiment("page_B", None))
        self.assertIsNone(variant_of_running_experiment("", [_experiment()]))


class IndexingThroughTheResolverTests(unittest.TestCase):
    """End-to-end: what the edge is actually told, on a CUSTOM domain (where indexing is real)."""

    def setUp(self):
        self.index = FakeDocumentRepository("domain")
        self.experiments = FakeDocumentRepository("experiment_id")
        self.experiments.put({
            "tenant_id": "t1", "experiment_id": "exp_1", "status": "running",
            "control_page_id": "page_A", "cookie_name": "jb_ab_exp_1",
            "variants": [{"page_id": "page_A", "weight": 50}, {"page_id": "page_B", "weight": 50}],
        })
        self.index.put({
            "tenant_id": "t1", "domain": "shop.example.com", "status": "active",
            "target_page_id": "page_A",
            "routes": {
                "/offer": {"page_id": "page_A", "page_type": "landing", "enabled": True},
                "/offer-b": {"page_id": "page_B", "page_type": "landing", "enabled": True},
            },
        })

    def _route(self, path):
        response = resolve_handler(
            {"httpMethod": "GET", "queryStringParameters": {"host": "shop.example.com", "path": path}},
            None, index_repo=self.index, pages_domain="pages.example.com",
            experiments_repo=self.experiments,
        )
        self.assertEqual(response["statusCode"], 200)
        return json.loads(response["body"])["route"]

    def test_the_tested_url_is_never_made_noindex(self):
        # The whole point of the cookie/same-URL design. If this ever flips, an experiment silently drops the
        # tenant's ranking page out of Google for as long as it runs.
        route = self._route("/offer")
        self.assertNotIn("noindex", route)

    def test_the_tested_url_still_gets_its_experiment(self):
        self.assertEqual(self._route("/offer")["experiment"]["experiment_id"], "exp_1")

    def test_a_variant_at_its_OWN_url_is_noindex(self):
        self.assertTrue(self._route("/offer-b")["noindex"])

    def test_a_variant_at_its_own_url_is_not_itself_an_experiment_entry(self):
        # Assignment happens on the control's URL only; two entry points would roll and pin separately.
        self.assertNotIn("experiment", self._route("/offer-b"))

    def test_nothing_is_noindex_once_the_experiment_stops(self):
        stopped = self.experiments.get("t1", "exp_1")
        stopped["status"] = "completed"
        self.experiments.put(stopped)
        self.assertNotIn("noindex", self._route("/offer-b"))
        self.assertNotIn("noindex", self._route("/offer"))


class VariantArtifactIdentityTests(unittest.TestCase):
    """A2: a variant artifact carries the TESTED page's identity, because the edge serves it behind that
    page's URL. Both alternatives break something (plans/AB_TESTING.md):

    * its OWN identity while attached  -> canonical points at its own slug, so serving it at the control's
      URL asks Google to move the tested page's ranking signals to the variant's URL.
    * its OWN identity while unattached -> on_custom_domain false -> bakes noindex, so serving it at the
      control's URL de-indexes the page the test exists to improve.
    """

    def setUp(self):
        self.experiments = FakeDocumentRepository("experiment_id")
        self.experiments.put({
            "tenant_id": "t1", "experiment_id": "exp_1", "status": "running",
            "control_page_id": "page_A",
            "variants": [{"page_id": "page_A", "weight": 50}, {"page_id": "page_B", "weight": 50}],
        })

    def _identity(self, page_id, repo=None):
        from stripe_link.runtime.publishing import identity_page_id
        return identity_page_id("t1", page_id, self.experiments if repo is None else repo)

    def test_a_variant_takes_the_control_pages_identity(self):
        self.assertEqual(self._identity("page_B"), "page_A")

    def test_the_control_keeps_its_own(self):
        self.assertEqual(self._identity("page_A"), "page_A")

    def test_an_unrelated_page_keeps_its_own(self):
        self.assertEqual(self._identity("page_Z"), "page_Z")

    def test_a_stopped_experiment_releases_the_variant(self):
        stopped = self.experiments.get("t1", "exp_1")
        stopped["status"] = "completed"
        self.experiments.put(stopped)
        self.assertEqual(self._identity("page_B"), "page_B")

    def test_no_repository_is_the_old_behaviour(self):
        # Environments without the table (or a test that injects nothing) publish exactly as they did before.
        from stripe_link.runtime.publishing import identity_page_id
        self.assertEqual(identity_page_id("t1", "page_B", None), "page_B")

    def test_publishing_never_fails_over_an_ab_lookup(self):
        class Exploding:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("experiments table is unavailable")
        self.assertEqual(self._identity("page_B", repo=Exploding()), "page_B")
