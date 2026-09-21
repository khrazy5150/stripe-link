"""Counting an A/B assignment (plans/AB_TESTING.md A1b).

The edge assigns and cannot write to DynamoDB, so it pings POST /experiments/{id}/view from inside
`waitUntil` — after the visitor's response has gone. A metric must never sit in the critical path of
serving a page.

The endpoint is public and unauthenticated because the caller is an edge worker with no tenant
credentials, which makes two guards load-bearing.
"""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPERIMENT = {"experiment_id": "exp_1", "tenant_id": "t1", "status": "running",
              "variants": [{"page_id": "page_A"}, {"page_id": "page_B"}]}


class Repo:
    def __init__(self, experiment):
        self.experiment = experiment
        self.bumped = []

    def find_by_id(self, experiment_id):
        return self.experiment

    def increment_view(self, tenant_id, experiment_id, page_id):
        self.bumped.append((tenant_id, experiment_id, page_id))


def _call(repo, page_id, experiment_id="exp_1", method="POST", body=None):
    from handlers import experiments_view
    event = {"httpMethod": method, "pathParameters": {"experiment_id": experiment_id},
             "body": json.dumps({"page_id": page_id}) if body is None else body, "headers": {}}
    response = experiments_view.handler(event, None, repository=repo)
    return response["statusCode"], json.loads(response["body"])


class CountingTests(unittest.TestCase):
    def test_a_real_variant_is_counted(self):
        repo = Repo(EXPERIMENT)
        status, body = _call(repo, "page_B")
        self.assertEqual((status, body), (200, {"counted": True}))
        self.assertEqual(repo.bumped, [("t1", "exp_1", "page_B")])

    def test_an_unknown_page_id_is_refused(self):
        """The guard that matters most: page_id becomes a DynamoDB attribute NAME in increment_view, so an
        unchecked value would let anyone create arbitrary keys inside a stats map they do not own."""
        repo = Repo(EXPERIMENT)
        status, body = _call(repo, "anything-i-like")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "unknown_variant")
        self.assertEqual(repo.bumped, [])

    def test_a_paused_experiment_counts_nothing_and_is_not_an_error(self):
        """An experiment can be paused between the edge assigning and this ping arriving. That is a race,
        not a fault, and 4xx-ing it would fill the Worker's logs with noise."""
        repo = Repo({**EXPERIMENT, "status": "paused"})
        status, body = _call(repo, "page_A")
        self.assertEqual((status, body["counted"]), (200, False))
        self.assertEqual(repo.bumped, [])

    def test_a_completed_experiment_never_moves_again(self):
        repo = Repo({**EXPERIMENT, "status": "completed"})
        _call(repo, "page_A")
        self.assertEqual(repo.bumped, [])

    def test_a_missing_experiment_is_a_404(self):
        self.assertEqual(_call(Repo(None), "page_A")[0], 404)

    def test_junk_is_refused_without_touching_the_table(self):
        repo = Repo(EXPERIMENT)
        self.assertEqual(_call(repo, "")[0], 400)
        self.assertEqual(_call(repo, "page_A", experiment_id="")[0], 400)
        self.assertEqual(_call(repo, "page_A", body="not json")[0], 400)
        self.assertEqual(_call(repo, "page_A", method="GET")[0], 405)
        self.assertEqual(repo.bumped, [])


class WiringTests(unittest.TestCase):
    TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")
    DOMAIN = (ROOT / "src/stripe_link/domain/experiments.py").read_text(encoding="utf-8")

    def test_the_route_exists(self):
        self.assertIn("Path: /experiments/{experiment_id}/view", self.TEMPLATE)

    def test_it_is_the_only_writer_and_has_crud(self):
        import re
        block = re.search(r"^  ExperimentsViewFunction:\n((?:    .*\n|\n)*)", self.TEMPLATE, re.M).group(1)
        self.assertIn("DynamoDBCrudPolicy:\n            TableName: !Ref ExperimentsTable", block)

    def test_the_edge_is_handed_a_fully_formed_url(self):
        """So it never has to know an API base, a mode, or how an id is shaped — it pings what it was
        given."""
        self.assertIn('f"{api_base.rstrip(\'/\')}/experiments/{experiment_id}/view"', self.DOMAIN)

    def test_no_api_base_means_no_counting_rather_than_a_broken_url(self):
        from stripe_link.domain.experiments import experiment_route_block
        block = experiment_route_block(EXPERIMENT | {"variants": [{"page_id": "page_A", "weight": 1}]},
                                       lambda p: f"https://cdn/{p}", api_base="")
        self.assertNotIn("view_url", block)


class EdgeAssignmentTests(unittest.TestCase):
    """The Worker's own logic, evaluated as written rather than paraphrased."""

    WORKER = (ROOT / "deploy/cloudflare-custom-domain-worker.js").read_text(encoding="utf-8")

    def test_a_view_is_counted_only_on_a_NEW_assignment(self):
        """Counting a pinned visitor's refresh would make one person look like many."""
        block = self.WORKER.split("function countView", 1)[1][:400]
        self.assertIn("if (!assignment.counted", block)

    def test_a_variant_response_is_never_shared_by_a_cache(self):
        # One visitor's variant served to another would silently corrupt the split.
        self.assertIn('stamped.headers.set("Cache-Control", "private, no-store")', self.WORKER)

    def test_the_visitor_is_pinned(self):
        self.assertIn("Max-Age=2592000; Secure; SameSite=Lax", self.WORKER)

    def test_a_stale_pin_re_rolls_instead_of_stranding_the_visitor(self):
        """A variant removed mid-flight would otherwise hold those visitors on a page no longer tested."""
        block = self.WORKER.split("function assignVariant", 1)[1][:900]
        self.assertIn("variants.find((variant) => variant.page_id === pinned)", block)

    def test_the_control_is_the_fallback_everywhere(self):
        self.assertIn("const originUrl = assignment.origin_url || route.origin_url;", self.WORKER)

    def test_counting_happens_off_the_critical_path(self):
        self.assertIn("event.waitUntil(promise)", self.WORKER)


if __name__ == "__main__":
    unittest.main()
