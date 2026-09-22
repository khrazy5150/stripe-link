"""A variant's artifact carries the TESTED page's identity, not its own (plans/AB_TESTING.md A2/A7).

The shape that matters is an UNATTACHED variant, because that is the only shape the product allows: a
variant must have no public address of its own while it is tested (Option A). That is exactly what broke
the first implementation -- the Site was resolved from the variant's own page_id, found nothing, and every
downstream substitution operated on `site = None`. The artifact fell back to its interim identity: a
canonical pointing at the raw artifact URL and, in prod, noindex on the page being tested.

Caught in QA on dev 2026-09-21, where test-mode noindex hid half of it. These tests publish in PROD mode
on a verified custom domain so both halves are visible.
"""
import copy
import unittest
from unittest.mock import patch

from stripe_link.runtime.publishing import publish_page_document

from tests.test_page_publishing import FakeRepository, FakeS3Client, FakeSitesRepository, load_fixture

CONTROL_ID = "page_control"
VARIANT_ID = "page_simple_coffee"  # the fixture's own id, so the fixture publishes as the VARIANT


class FakeExperiments:
    def __init__(self, experiments):
        self.experiments = experiments

    def list_for_tenant(self, tenant_id):
        return list(self.experiments)


def _experiment(status="running"):
    return {
        "tenant_id": "tenant_demo", "experiment_id": "exp_1", "status": status,
        "control_page_id": CONTROL_ID,
        "variants": [{"page_id": CONTROL_ID, "weight": 50}, {"page_id": VARIANT_ID, "weight": 50}],
    }


class VariantIdentityTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-simple-coffee.json")
        self.page["stripe_mode"] = "live"
        self.page["status"] = "published"
        self.page.setdefault("sections", []).append({
            "id": "about", "type": "content_block",
            "blocks": [{"title": "About", "text": " ".join(["freshly roasted single origin beans"] * 30)}],
        })
        self.s3 = FakeS3Client()
        # The CONTROL holds the slug. The variant is attached to nothing, which is the required shape.
        self.site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com",
                        "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "pages": {"/offer": {"page_id": CONTROL_ID, "page_type": "landing"}},
        }

    def _publish(self, experiments_repo):
        with patch("stripe_link.runtime.publishing.submit_indexnow", return_value=True):
            publish_page_document(
                copy.deepcopy(self.page),
                offers_repository=FakeRepository("offer_id", [load_fixture("offer-simple-coffee.json")]),
                products_repository=FakeRepository("product_id", [load_fixture("product-simple-coffee.json")]),
                sites_repository=FakeSitesRepository([copy.deepcopy(self.site)]),
                experiments_repository=experiments_repo,
                s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        return [p for p in self.s3.puts if p["Key"] == f"{VARIANT_ID}/index.html"][0]["Body"].decode()

    def test_the_canonical_is_the_TESTED_url_not_the_artifact_url(self):
        html = self._publish(FakeExperiments([_experiment()]))
        self.assertIn('<link rel="canonical" href="https://shop.example.com/offer">', html)
        self.assertNotIn("pages.example.com", html.split("</head>")[0])

    def test_it_inherits_the_tested_pages_INDEXABILITY(self):
        # The half that test mode hid on dev. Without the Site, on_custom_domain is false and this bakes
        # noindex -- served behind the tested URL, that de-indexes the page the test exists to improve.
        html = self._publish(FakeExperiments([_experiment()]))
        self.assertIn('content="index,follow', html)

    def test_an_unattached_page_that_is_NOT_a_variant_keeps_its_interim_identity(self):
        # The control for the two above: identical publish, no running experiment. Proves the difference is
        # the experiment and not the fixture.
        html = self._publish(FakeExperiments([]))
        self.assertNotIn('<link rel="canonical" href="https://shop.example.com/offer">', html)
        self.assertIn("noindex", html)

    def test_a_paused_experiment_does_not_lend_its_identity(self):
        html = self._publish(FakeExperiments([_experiment(status="paused")]))
        self.assertNotIn('<link rel="canonical" href="https://shop.example.com/offer">', html)

    def test_no_experiments_repository_at_all_is_the_old_behaviour(self):
        html = self._publish(None)
        self.assertNotIn('<link rel="canonical" href="https://shop.example.com/offer">', html)
