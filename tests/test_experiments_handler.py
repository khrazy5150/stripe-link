import json
import pathlib
import os
import unittest
from unittest.mock import patch

from handlers.experiments import handler as experiments_handler
from handlers.experiments_resolve import handler as resolve_handler
from tests.fakes import FakeDocumentRepository


def event(method, *, tenant_id=None, body=None, experiment_id=None, action=None, query=None, headers=None):
    params = dict(query or {})
    if tenant_id:
        params["tenant_id"] = tenant_id
    evt = {"httpMethod": method, "queryStringParameters": params}
    if body is not None:
        evt["body"] = json.dumps(body)
    if experiment_id is not None:
        evt["pathParameters"] = {"experiment_id": experiment_id}
        resource = "/experiments/{experiment_id}"
        if action:
            resource = f"{resource}/{action}"
        evt["resource"] = resource
    if headers is not None:
        evt["headers"] = headers
    return evt


def variant(page_id, weight, label=None):
    payload = {"page_id": page_id, "weight": weight}
    if label:
        payload["label"] = label
    return payload


class ExperimentsCrudTests(unittest.TestCase):
    def setUp(self):
        self.experiments = FakeDocumentRepository("experiment_id")
        self.routes = FakeDocumentRepository("short_code")
        self.pages = FakeDocumentRepository("page_id")
        self.orders = FakeDocumentRepository("order_id")

    def create(self, body=None, exp_id="exp_1", code="code123ABCd"):
        body = body or {
            "name": "Hero CTA Test",
            "control_page_id": "page_control",
            "variants": [variant("page_control", 50, "Control"), variant("page_b", 50, "Variant A")],
        }
        return experiments_handler(
            event("POST", tenant_id="tenant_demo", body=body),
            None,
            repository=self.experiments,
            routes=self.routes,
            now_fn=lambda: 1781230000,
            id_fn=lambda: exp_id,
            code_fn=lambda: code,
        )

    def test_create_no_longer_allocates_a_short_url_or_route(self):
        """A short code would be a second way into the experiment, entered by different traffic than the
        page's own URL -- and a link a tenant could copy that no longer assigns anyone
        (plans/AB_TESTING.md A1c)."""
        with patch.dict(os.environ, {"SHORT_URL_HOST": "go.jbay.uk"}, clear=False):
            response = self.create()
        self.assertEqual(response["statusCode"], 201)
        experiment = json.loads(response["body"])["experiment"]
        self.assertEqual(experiment["status"], "draft")
        self.assertNotIn("short_url", experiment)
        self.assertNotIn("short_code", experiment)
        self.assertEqual(experiment["cookie_name"], "jb_ab_exp_1")
        keys = sorted(v["key"] for v in experiment["variants"])
        self.assertEqual(keys, ["control", "variant_a"])
        # and nothing was written to the routes table
        self.assertIsNone(self.routes.find_by_id("code123ABCd"))

    def test_create_requires_control_among_variants(self):
        response = self.create(body={
            "name": "Bad",
            "control_page_id": "page_missing",
            "variants": [variant("page_a", 50), variant("page_b", 50)],
        })
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_experiment")
        # the pre-allocated route is rolled back on validation failure
        self.assertEqual(json.loads(experiments_handler(
            event("GET", tenant_id="tenant_demo"), None, repository=self.experiments, routes=self.routes,
        )["body"])["count"], 0)

    def test_start_requires_weights_total_100(self):
        self.create(body={
            "name": "Test",
            "control_page_id": "page_control",
            "variants": [variant("page_control", 40), variant("page_b", 40)],
        })
        response = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages,
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_weights")

    def test_start_requires_published_pages(self):
        self.create()
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_control", "status": "published"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_b", "status": "draft"})
        response = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages,
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "variant_not_published")

    def test_start_succeeds_when_valid(self):
        self.create()
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_control", "status": "published"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_b", "status": "published"})
        response = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages, now_fn=lambda: 1781240000,
        )
        self.assertEqual(response["statusCode"], 200)
        experiment = json.loads(response["body"])["experiment"]
        self.assertEqual(experiment["status"], "running")
        self.assertEqual(experiment["started_at"], 1781240000)

    def test_pause_and_complete(self):
        self.create()
        paused = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="pause"),
            None, repository=self.experiments,
        )
        self.assertEqual(json.loads(paused["body"])["experiment"]["status"], "paused")

        completed = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="complete",
                  body={"winner_page_id": "page_b"}),
            None, repository=self.experiments,
        )
        experiment = json.loads(completed["body"])["experiment"]
        self.assertEqual(experiment["status"], "completed")
        self.assertEqual(experiment["winner_page_id"], "page_b")

    def test_complete_rejects_unknown_winner(self):
        self.create()
        response = experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="complete",
                  body={"winner_page_id": "page_x"}),
            None, repository=self.experiments,
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_winner")

    def test_get_computes_results_from_orders_and_views(self):
        self.create()
        self.experiments.increment_view("tenant_demo", "exp_1", "page_control")
        self.experiments.increment_view("tenant_demo", "exp_1", "page_control")
        self.experiments.increment_view("tenant_demo", "exp_1", "page_b")
        self.orders.put({"tenant_id": "tenant_demo", "order_id": "o1", "status": "paid",
                         "amount_total": 5000, "attribution": {"page_id": "page_b"}})
        self.orders.put({"tenant_id": "tenant_demo", "order_id": "o2", "status": "open",
                         "amount_total": 9999, "attribution": {"page_id": "page_b"}})
        response = experiments_handler(
            event("GET", tenant_id="tenant_demo", experiment_id="exp_1"),
            None, repository=self.experiments, orders=self.orders,
        )
        results = {r["page_id"]: r for r in json.loads(response["body"])["results"]}
        self.assertEqual(results["page_control"]["views"], 2)
        self.assertEqual(results["page_control"]["conversions"], 0)
        self.assertEqual(results["page_b"]["views"], 1)
        self.assertEqual(results["page_b"]["conversions"], 1)  # only the paid order counts
        self.assertEqual(results["page_b"]["revenue"], 5000)
        self.assertEqual(results["page_b"]["conversion_rate"], 1.0)

    def test_delete_removes_experiment_and_route(self):
        self.create()
        response = experiments_handler(
            event("DELETE", tenant_id="tenant_demo", experiment_id="exp_1"),
            None, repository=self.experiments, routes=self.routes,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertIsNone(self.experiments.get("tenant_demo", "exp_1"))
        self.assertIsNone(self.routes.find_by_id("code123ABCd"))


class ExperimentsResolveTests(unittest.TestCase):
    """The short-code resolver is DISABLED, not dismantled (plans/AB_TESTING.md A1c).

    Assignment moved to the edge, on the page's own URL, because entering only through go.jbay.uk/{code}
    biases the experiment: organic traffic to the real URL never enters it. Answering here as well would be
    a SECOND assignment path with its own roll and its own cookie, and that drift is invisible until the
    numbers look wrong.

    The endpoint answers 410. Its assignment LOGIC is kept and still exercised directly below, because the
    edge implements the same rules and these cases are the record of what those rules are.
    """

    def _resolve(self, **params):
        from handlers import experiments_resolve
        return experiments_resolve.handler(
            {"httpMethod": "GET", "pathParameters": {"experiment_id": "exp_1"}, "headers": {}},
            None, repository=None, **params)

    def test_the_endpoint_is_gone_not_broken(self):
        response = self._resolve()
        self.assertEqual(response["statusCode"], 410)
        self.assertIn("page's own URL", json.loads(response["body"])["message"])

    def test_the_flag_is_off_and_says_why(self):
        from stripe_link.domain import experiments
        self.assertFalse(experiments.SHORT_CODE_ENTRY_ENABLED)
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src/stripe_link/domain/experiments.py").read_text(encoding="utf-8")
        self.assertIn("two live assignment paths", source)


class ExperimentAssignmentRulesTests(unittest.TestCase):
    """The rules themselves, still true and still tested -- the edge implements the same ones."""

    VARIANTS = [{"page_id": "page_control", "weight": 50}, {"page_id": "page_b", "weight": 50}]

    def _experiment(self, status="running", winner=None):
        return {"status": status, "control_page_id": "page_control", "winner_page_id": winner,
                "variants": self.VARIANTS}

    def test_first_bucket_is_the_control(self):
        from handlers.experiments_resolve import choose_page
        page_id, counted = choose_page(self._experiment(), "", lambda upper: 0)
        self.assertEqual((page_id, counted), ("page_control", True))

    def test_past_the_first_weight_is_the_variant(self):
        from handlers.experiments_resolve import choose_page
        self.assertEqual(choose_page(self._experiment(), "", lambda upper: 75)[0], "page_b")

    def test_a_pin_wins_over_a_fresh_roll(self):
        from handlers.experiments_resolve import choose_page
        self.assertEqual(choose_page(self._experiment(), "page_b", lambda upper: 0)[0], "page_b")

    def test_paused_serves_the_control_and_counts_nothing(self):
        from handlers.experiments_resolve import choose_page
        self.assertEqual(choose_page(self._experiment(status="paused"), "", lambda upper: 75),
                         ("page_control", False))

    def test_completed_sends_everyone_to_the_winner(self):
        from handlers.experiments_resolve import choose_page
        self.assertEqual(choose_page(self._experiment(status="completed", winner="page_b"), "",
                                     lambda upper: 0), ("page_b", False))


