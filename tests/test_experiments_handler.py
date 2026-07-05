import json
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

    def test_create_allocates_short_url_and_route(self):
        with patch.dict(os.environ, {"SHORT_URL_HOST": "go.jbay.uk"}, clear=False):
            response = self.create()
        self.assertEqual(response["statusCode"], 201)
        experiment = json.loads(response["body"])["experiment"]
        self.assertEqual(experiment["status"], "draft")
        self.assertEqual(experiment["short_url"], "https://go.jbay.uk/code123ABCd")
        self.assertEqual(experiment["cookie_name"], "jb_ab_exp_1")
        keys = sorted(v["key"] for v in experiment["variants"])
        self.assertEqual(keys, ["control", "variant_a"])
        # a matching experiment route was created
        route = self.routes.find_by_id("code123ABCd")
        self.assertEqual(route["target_type"], "experiment")
        self.assertEqual(route["target_experiment_id"], "exp_1")

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
    def setUp(self):
        self.experiments = FakeDocumentRepository("experiment_id")

    def seed(self, status="running", winner=None):
        self.experiments.put({
            "tenant_id": "tenant_demo",
            "experiment_id": "exp_1",
            "document_type": "experiment",
            "status": status,
            "control_page_id": "page_control",
            "winner_page_id": winner,
            "cookie_name": "jb_ab_exp_1",
            "variants": [
                {"key": "control", "page_id": "page_control", "weight": 50},
                {"key": "variant_a", "page_id": "page_b", "weight": 50},
            ],
            "stats": {"views_by_page": {}},
        })

    def resolve(self, headers=None, choose_fn=None):
        return resolve_handler(
            event("GET", experiment_id="exp_1", headers=headers),
            None,
            repository=self.experiments,
            pages_domain="pages.example.com",
            choose_fn=choose_fn or (lambda upper: 0),
        )

    def test_running_assigns_by_weight_and_sets_cookie(self):
        self.seed()
        response = self.resolve(choose_fn=lambda upper: 0)  # first bucket -> control
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], "https://pages.example.com/page_control/index.html")
        self.assertIn("jb_ab_exp_1=page_control", response["headers"]["Set-Cookie"])
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["stats"]["views_by_page"]["page_control"], 1)

    def test_weighted_choice_second_bucket(self):
        self.seed()
        response = self.resolve(choose_fn=lambda upper: 75)  # past control's 50 -> variant
        self.assertEqual(response["headers"]["Location"], "https://pages.example.com/page_b/index.html")

    def test_sticky_cookie_pins_variant(self):
        self.seed()
        response = self.resolve(headers={"Cookie": "jb_ab_exp_1=page_b"}, choose_fn=lambda upper: 0)
        self.assertEqual(response["headers"]["Location"], "https://pages.example.com/page_b/index.html")

    def test_paused_falls_back_to_control_without_counting(self):
        self.seed(status="paused")
        response = self.resolve()
        self.assertEqual(response["headers"]["Location"], "https://pages.example.com/page_control/index.html")
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["stats"]["views_by_page"], {})

    def test_completed_routes_to_winner(self):
        self.seed(status="completed", winner="page_b")
        response = self.resolve()
        self.assertEqual(response["headers"]["Location"], "https://pages.example.com/page_b/index.html")

    def test_unknown_experiment_404(self):
        response = resolve_handler(
            event("GET", experiment_id="missing"),
            None, repository=self.experiments, pages_domain="pages.example.com",
        )
        self.assertEqual(response["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
