"""A/B testing is available in TEST mode, so an experiment can be proved without live money.

A departure from the original design, which offered the screen only in live. The constraint behind that
choice no longer holds: test-mode Stripe transactions make a full experiment provable end to end, and
test-mode pages are noindex regardless (`publishing.py` forces NOINDEX_ROBOTS when page_mode == "test"), so
a sandbox experiment carries no SEO risk at all.
"""
import json
import pathlib
import unittest

from handlers.experiments import handler as experiments_handler
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]


class MenuTests(unittest.TestCase):
    MENU = (ROOT / "dashboard/src/config/menu.js").read_text(encoding="utf-8")

    def test_ab_testing_is_offered_in_both_environments(self):
        block = self.MENU.split("abTesting: {", 1)[1].split("},", 1)[0]
        self.assertIn('environments: ["test", "live"]', block)

    def test_it_is_still_enabled(self):
        block = self.MENU.split("abTesting: {", 1)[1].split("},", 1)[0]
        self.assertIn("enabled: true", block)


class ModeStampTests(unittest.TestCase):
    """Isolation is structural (the repo bakes mode into the SK), so this stamp is for READING: without it
    a dumped experiment cannot say which mode it belongs to, which is the question asked when something
    looks wrong."""

    def setUp(self):
        self.experiments = FakeDocumentRepository("experiment_id")
        self.routes = FakeDocumentRepository("short_code")

    def _create(self, query=None):
        return json.loads(experiments_handler(
            {"httpMethod": "POST", "queryStringParameters": {"tenant_id": "t1", **(query or {})},
             "body": json.dumps({
                 "name": "Test", "control_page_id": "page_a",
                 "variants": [{"page_id": "page_a", "weight": 50}, {"page_id": "page_b", "weight": 50}],
             })},
            None, repository=self.experiments, routes=self.routes,
            now_fn=lambda: 1781230000, id_fn=lambda: "exp_1", code_fn=lambda: "code123ABCd",
        )["body"])["experiment"]

    def test_a_test_mode_experiment_says_so(self):
        self.assertEqual(self._create({"mode": "test"})["stripe_mode"], "test")

    def test_a_live_mode_experiment_says_so(self):
        self.assertEqual(self._create({"mode": "live"})["stripe_mode"], "live")

    def test_an_unspecified_mode_is_test_not_live(self):
        # Defaulting the other way would stamp a live label on a sandbox experiment.
        self.assertEqual(self._create()["stripe_mode"], "test")
