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


class ExperimentsFixture:
    """Repos + a create() helper, shared by the suites below.

    Deliberately not a TestCase and deliberately not inherited FROM the CRUD suite: subclassing that would
    re-run every CRUD test against each suite's own setUp, which is both wasteful and misleading when one
    of them fails.
    """

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


class ExperimentShapeIsFrozenOnceStartedTests(ExperimentsFixture, unittest.TestCase):
    """Changing the control mid-flight is not an edit; it is a different experiment.

    Assignment is matched on `control_page_id`, so swapping it moves the entry point to another URL, while
    `stats.views_by_page` is one cumulative untimestamped map -- counts from both regimes land in the same
    counters with nothing recording which is which.
    """

    def _start(self):
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_control", "status": "published"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_b", "status": "published"})
        return experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages, now_fn=lambda: 1781240000,
        )

    def _update(self, body):
        return experiments_handler(
            event("PUT", tenant_id="tenant_demo", experiment_id="exp_1", body=body),
            None, repository=self.experiments, now_fn=lambda: 1781250000,
        )

    def test_a_draft_that_never_started_stays_editable(self):
        self.create()
        response = self._update({"control_page_id": "page_b"})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["experiment"]["control_page_id"], "page_b")

    def test_the_control_cannot_change_once_started(self):
        self.create()
        self._start()
        response = self._update({"control_page_id": "page_b"})
        self.assertEqual(json.loads(response["body"])["error"], "experiment_started")
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["control_page_id"], "page_control")

    def test_it_stays_frozen_while_paused(self):
        # Pausing does not make data already collected compatible with a different control.
        self.create()
        self._start()
        experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="pause"),
            None, repository=self.experiments, now_fn=lambda: 1781245000,
        )
        self.assertEqual(json.loads(self._update({"control_page_id": "page_b"})["body"])["error"],
                         "experiment_started")

    def test_variants_cannot_change_once_started(self):
        self.create()
        self._start()
        response = self._update({"variants": [variant("page_control", 80), variant("page_b", 20)]})
        self.assertEqual(json.loads(response["body"])["error"], "experiment_started")

    def test_renaming_is_still_allowed_once_started(self):
        self.create()
        self._start()
        response = self._update({"name": "Hero CTA Test v2"})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["experiment"]["name"], "Hero CTA Test v2")

    def test_resending_the_same_shape_is_not_an_error(self):
        # Weights arrive as Decimal from storage and int from a request body; a naive comparison would
        # report "changed" and block a plain rename that happens to echo the variants back.
        self.create()
        self._start()
        stored = self.experiments.get("tenant_demo", "exp_1")
        from decimal import Decimal
        stored["variants"] = [dict(v, weight=Decimal(str(v["weight"]))) for v in stored["variants"]]
        self.experiments.put(stored)
        response = self._update({
            "name": "Renamed",
            "variants": [variant("page_control", 50, "Control"), variant("page_b", 50, "Variant A")],
        })
        self.assertEqual(response["statusCode"], 200)

    def test_starting_clears_counters_from_a_previous_run(self):
        # Otherwise "stop, edit, restart" both contaminates results and routes around the freeze above.
        self.create()
        self._start()
        stale = self.experiments.get("tenant_demo", "exp_1")
        stale["stats"] = {"views_by_page": {"page_control": 400, "page_b": 380}}
        self.experiments.put(stale)
        experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="pause"),
            None, repository=self.experiments, now_fn=lambda: 1781246000,
        )
        self._start()
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["stats"]["views_by_page"], {})


class VariantsMayNotHaveTheirOwnUrlTests(ExperimentsFixture, unittest.TestCase):
    """Option A: a variant is an alternative rendering of the page under test, not a second public page."""

    def setUp(self):
        super().setUp()
        self.sites = FakeDocumentRepository("site_id")
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_control", "status": "published"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_b", "status": "published"})

    def _start(self):
        return experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages, sites=self.sites,
            now_fn=lambda: 1781240000,
        )

    def _site_with(self, pages):
        self.sites.put({"tenant_id": "tenant_demo", "site_id": "site_1", "pages": pages})

    def test_a_start_is_refused_when_a_variant_is_attached(self):
        self.create()
        self._site_with({"/offer": {"page_id": "page_control"}, "/offer-b": {"page_id": "page_b"}})
        response = self._start()
        self.assertEqual(json.loads(response["body"])["error"], "variant_attached")
        self.assertIn("/offer-b", json.loads(response["body"])["message"])
        self.assertNotEqual(self.experiments.get("tenant_demo", "exp_1").get("status"), "running")

    def test_the_control_being_attached_is_normal_and_required(self):
        self.create()
        self._site_with({"/offer": {"page_id": "page_control"}})
        self.assertEqual(self._start()["statusCode"], 200)

    def test_an_unattached_variant_starts_fine(self):
        self.create()
        self._site_with({"/offer": {"page_id": "page_control"}})
        self.assertEqual(self._start()["statusCode"], 200)

    def test_the_check_fails_open_when_sites_cannot_be_read(self):
        # Two other layers already cover this; refusing to start over an unreadable table would be worse.
        class Exploding:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("sites table is unavailable")
        self.create()
        self.sites = Exploding()
        self.assertEqual(self._start()["statusCode"], 200)


class PromotionMovesTheRouteTests(ExperimentsFixture, unittest.TestCase):
    """A5: the route is the durable identity; the page behind it is swappable."""

    def setUp(self):
        super().setUp()
        self.sites = FakeDocumentRepository("site_id")
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_control", "status": "published"})
        self.pages.put({"tenant_id": "tenant_demo", "page_id": "page_b", "status": "published"})
        self.sites.put({
            "tenant_id": "tenant_demo", "site_id": "site_1",
            "pages": {"/offer": {"page_id": "page_control", "page_type": "landing",
                                 "label": "Offer", "enabled": True, "offer_id": "offer_old"}},
        })
        self.create()
        experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="start"),
            None, repository=self.experiments, pages=self.pages, sites=self.sites,
            now_fn=lambda: 1781240000,
        )

    def _complete(self, winner, sites=None):
        return experiments_handler(
            event("POST", tenant_id="tenant_demo", experiment_id="exp_1", action="complete",
                  body={"winner_page_id": winner}),
            None, repository=self.experiments, sites=self.sites if sites is None else sites,
            now_fn=lambda: 1781250000,
        )

    def _pages(self):
        return self.sites.get("tenant_demo", "site_1")["pages"]

    def test_the_winning_variant_takes_the_tested_slug(self):
        self.assertEqual(self._complete("page_b")["statusCode"], 200)
        self.assertEqual(self._pages()["/offer"]["page_id"], "page_b")

    def test_THE_LOSER_IS_NOT_GIVEN_A_URL_OF_ITS_OWN(self):
        # The distinction from _attach_page_to_site, whose contract is to displace the previous occupant to
        # its own slug so it stays reachable. Here that would hand the loser a public URL as it lost.
        self._complete("page_b")
        routed = {entry.get("page_id") for entry in self._pages().values() if isinstance(entry, dict)}
        self.assertNotIn("page_control", routed)
        self.assertEqual(len(self._pages()), 1)

    def test_slug_level_fields_survive_and_page_level_ones_do_not(self):
        self._complete("page_b")
        entry = self._pages()["/offer"]
        self.assertEqual(entry["page_type"], "landing")   # describes the address
        self.assertEqual(entry["label"], "Offer")
        self.assertTrue(entry["enabled"])
        self.assertNotIn("offer_id", entry)               # described the loser

    def test_the_control_winning_moves_nothing(self):
        self._complete("page_control")
        self.assertEqual(self._pages()["/offer"]["page_id"], "page_control")
        stored = self.experiments.get("tenant_demo", "exp_1")
        self.assertEqual(stored["promotion"]["status"], "not_needed")

    def test_the_outcome_is_recorded_on_the_experiment(self):
        self._complete("page_b")
        promotion = self.experiments.get("tenant_demo", "exp_1")["promotion"]
        self.assertEqual(promotion, {"status": "moved", "slug": "/offer"})

    def test_a_failed_move_does_not_complete_the_experiment(self):
        # Completing is what stops assignment. Recording it after a failed move would revert the tested URL
        # to the LOSER while telling the tenant the winner is live.
        class Exploding:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("sites table is unavailable")
        response = self._complete("page_b", sites=Exploding())
        self.assertEqual(json.loads(response["body"])["error"], "promotion_failed")
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["status"], "running")

    def test_an_unrouted_control_is_not_an_error(self):
        self.sites.put({"tenant_id": "tenant_demo", "site_id": "site_1", "pages": {}})
        self.assertEqual(self._complete("page_b")["statusCode"], 200)
        self.assertEqual(self.experiments.get("tenant_demo", "exp_1")["promotion"]["status"], "no_route")


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


