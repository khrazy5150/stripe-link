"""A page that is reachable is not thereby authorized to take money (plans/COMMERCE_ELIGIBILITY.md).

The rule itself is three lookups. What these tests are really protecting are its two safety properties, both
of which are easy to lose in a later refactor and neither of which announces its own failure:

- **An unreadable Sites table must never read as "attached to nothing".** `find_site_for_page` swallows
  exceptions and returns None, which for publishing is right and here is catastrophic: a missing IAM grant
  would look exactly like the hole, so Phase 1 would report a flood of false positives and Phase 2 would
  refuse every legitimate checkout on the platform. Hence `site_for_page` (strict) and the LOOKUP_FAILED
  verdict.
- **A detached A/B variant must stay eligible.** The visitor is on the control's URL; the CTA carries the
  variant's own page_id. Making "attached to a Site" the test would silently break the conversion arm of
  every experiment.
"""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from stripe_link.domain import commerce_eligibility as ce


class FakeSites:
    def __init__(self, sites):
        self.sites = sites
        self.calls = 0

    def list_for_tenant(self, tenant_id):
        self.calls += 1
        return list(self.sites)


class BrokenSites:
    """What a missing DynamoDBReadPolicy actually looks like at the point of use."""

    def __init__(self):
        self.calls = 0

    def list_for_tenant(self, tenant_id):
        self.calls += 1
        raise RuntimeError("AccessDeniedException: User is not authorized to perform dynamodb:Query")


class FakeExperiments:
    def __init__(self, experiments):
        self.experiments = experiments
        self.calls = 0

    def list_for_tenant(self, tenant_id):
        self.calls += 1
        return list(self.experiments)


class BrokenExperiments:
    def list_for_tenant(self, tenant_id):
        raise RuntimeError("AccessDeniedException")


def site(site_id, *page_ids):
    return {"site_id": site_id, "pages": {f"/p{i}": {"page_id": pid} for i, pid in enumerate(page_ids)}}


def running_experiment(control, variant):
    # `variants` is a LIST of variant documents, matching what experiments_repository stores.
    return {
        "experiment_id": "exp_1", "status": "running", "control_page_id": control,
        "variants": [
            {"page_id": control, "key": "control", "split": 50},
            {"page_id": variant, "key": "b", "split": 50},
        ],
    }


class EvaluateTests(unittest.TestCase):
    def test_page_on_a_site_is_eligible(self):
        verdict = ce.evaluate(
            tenant_id="t1", page_id="page_a", sites_repo=FakeSites([site("site_1", "page_a")]))
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["reason"], ce.ATTACHED)
        self.assertEqual(verdict["site_id"], "site_1")

    def test_the_ordinary_case_never_reads_the_experiments_table(self):
        # Cost, not correctness: this runs on every checkout the platform takes. An attached page is answered
        # by the Sites read alone, so the money path pays ONE extra read, not two.
        experiments = FakeExperiments([])
        ce.evaluate(
            tenant_id="t1", page_id="page_a", sites_repo=FakeSites([site("site_1", "page_a")]),
            experiments_repo=experiments)
        self.assertEqual(experiments.calls, 0)

    def test_page_on_no_site_is_not_eligible(self):
        verdict = ce.evaluate(
            tenant_id="t1", page_id="page_orphan", sites_repo=FakeSites([site("site_1", "page_a")]))
        self.assertFalse(verdict["eligible"])
        self.assertEqual(verdict["reason"], ce.NOT_ATTACHED)

    def test_detached_variant_of_an_attached_control_is_eligible(self):
        # The constraint that shapes the whole rule. `page_v` is on no Site; it stands for `page_a`, which is.
        verdict = ce.evaluate(
            tenant_id="t1", page_id="page_v", sites_repo=FakeSites([site("site_1", "page_a")]),
            experiments_repo=FakeExperiments([running_experiment("page_a", "page_v")]))
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["reason"], ce.VARIANT_OF_ATTACHED)
        self.assertEqual(verdict["identity_page_id"], "page_a")

    def test_variant_of_a_control_that_is_itself_detached_is_not_eligible(self):
        verdict = ce.evaluate(
            tenant_id="t1", page_id="page_v", sites_repo=FakeSites([site("site_1", "page_other")]),
            experiments_repo=FakeExperiments([running_experiment("page_a", "page_v")]))
        self.assertFalse(verdict["eligible"])
        self.assertEqual(verdict["reason"], ce.NOT_ATTACHED)
        self.assertEqual(verdict["identity_page_id"], "page_a")

    def test_an_unreadable_sites_table_is_undecided_not_ineligible(self):
        broken = BrokenSites()
        verdict = ce.evaluate(tenant_id="t1", page_id="page_a", sites_repo=broken)
        self.assertEqual(verdict["reason"], ce.LOOKUP_FAILED)
        self.assertTrue(verdict["eligible"])
        self.assertIn("AccessDenied", verdict["detail"])
        self.assertEqual(broken.calls, 1)

    def test_an_unreadable_experiments_table_is_undecided_not_ineligible(self):
        # The subtle one. The page is on no Site, so the verdict hinges entirely on whether it is a variant —
        # and a failed experiments read means we do not know, not that it stands for nothing.
        verdict = ce.evaluate(
            tenant_id="t1", page_id="page_v", sites_repo=FakeSites([site("site_1", "page_a")]),
            experiments_repo=BrokenExperiments())
        self.assertEqual(verdict["reason"], ce.LOOKUP_FAILED)
        self.assertTrue(verdict["eligible"])

    def test_no_sites_table_configured_is_undecided(self):
        verdict = ce.evaluate(tenant_id="t1", page_id="page_a", sites_repo=None)
        self.assertEqual(verdict["reason"], ce.NO_SITES_TABLE)
        self.assertTrue(verdict["eligible"])

    def test_no_page_context_is_not_this_rules_business(self):
        sites = FakeSites([])
        verdict = ce.evaluate(tenant_id="t1", page_id="", sites_repo=sites)
        self.assertEqual(verdict["reason"], ce.NO_PAGE)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(sites.calls, 0)


class EnforcementModeTests(unittest.TestCase):
    def test_default_is_observe(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ELIGIBILITY_ENFORCEMENT", None)
            self.assertEqual(ce.enforcement(), ce.OBSERVE)

    def test_an_unrecognised_value_is_observe_never_enforce(self):
        # Enforcement is the one behaviour that must require saying so exactly. A typo ("enforced", "on",
        # "true") must not start refusing checkouts.
        for value in ("enforced", "true", "on", "1", "ENFORCE ME", ""):
            with mock.patch.dict(os.environ, {"ELIGIBILITY_ENFORCEMENT": value}):
                self.assertEqual(ce.enforcement(), ce.OBSERVE, value)

    def test_enforce_is_case_insensitive_and_trimmed(self):
        with mock.patch.dict(os.environ, {"ELIGIBILITY_ENFORCEMENT": "  ENFORCE "}):
            self.assertEqual(ce.enforcement(), ce.ENFORCE)


class GuardTests(unittest.TestCase):
    def _guard(self, enforcement, **kwargs):
        with mock.patch.dict(os.environ, {"ELIGIBILITY_ENFORCEMENT": enforcement}):
            out = io.StringIO()
            with redirect_stdout(out):
                verdict = ce.guard(path="checkout", tenant_id="t1", stripe_mode="test", **kwargs)
            return verdict, out.getvalue()

    def test_observe_records_the_hole_and_still_allows_it(self):
        verdict, logged = self._guard(
            ce.OBSERVE, page_id="page_orphan", sites_repo=FakeSites([site("site_1", "page_a")]))
        self.assertFalse(verdict["refuse"])
        record = json.loads(logged)["commerce_eligibility"]
        self.assertEqual(record["verdict"], ce.NOT_ATTACHED)
        self.assertFalse(record["enforced"], "observe must record without refusing")
        self.assertFalse(record["undecided"])
        self.assertEqual(record["page_id"], "page_orphan")
        self.assertEqual(record["path"], "checkout")

    def test_observe_does_not_log_the_ordinary_case(self):
        # Every checkout the platform takes would otherwise write a CloudWatch line saying "normal".
        _, logged = self._guard(
            ce.OBSERVE, page_id="page_a", sites_repo=FakeSites([site("site_1", "page_a")]))
        self.assertEqual(logged, "")

    def test_undecided_is_logged_distinctly_from_the_hole(self):
        # Phase 1 is a measurement. If a broken grant were counted as a detached page, the measurement would
        # say "enforce is safe" for exactly the wrong reason.
        verdict, logged = self._guard(ce.OBSERVE, page_id="page_a", sites_repo=BrokenSites())
        self.assertFalse(verdict["refuse"])
        record = json.loads(logged)["commerce_eligibility"]
        self.assertEqual(record["verdict"], ce.LOOKUP_FAILED)
        self.assertTrue(record["undecided"])
        self.assertIn("AccessDenied", record["detail"])

    def test_enforce_refuses_a_definite_verdict(self):
        verdict, logged = self._guard(
            ce.ENFORCE, page_id="page_orphan", sites_repo=FakeSites([site("site_1", "page_a")]))
        self.assertTrue(verdict["refuse"])
        self.assertTrue(json.loads(logged)["commerce_eligibility"]["enforced"])

    def test_enforce_still_allows_an_undecided_verdict(self):
        # Fail open on infrastructure, closed only on a definite answer. A throttle or a revoked grant must
        # not take the platform's checkout down.
        verdict, _ = self._guard(ce.ENFORCE, page_id="page_a", sites_repo=BrokenSites())
        self.assertFalse(verdict["refuse"])

    def test_enforce_allows_a_detached_variant(self):
        verdict, _ = self._guard(
            ce.ENFORCE, page_id="page_v", sites_repo=FakeSites([site("site_1", "page_a")]),
            experiments_repo=FakeExperiments([running_experiment("page_a", "page_v")]))
        self.assertFalse(verdict["refuse"])

    def test_off_reads_nothing_at_all(self):
        # The kill switch has to remove the COST, not just the refusal.
        sites = FakeSites([])
        verdict, logged = self._guard(ce.OFF, page_id="page_orphan", sites_repo=sites)
        self.assertFalse(verdict["refuse"])
        self.assertEqual(sites.calls, 0)
        self.assertNotIn("commerce_eligibility", logged)


class StrictSiteLookupTests(unittest.TestCase):
    """`site_for_page` raises where `find_site_for_page` swallows — the split this rule depends on."""

    def test_strict_lookup_raises(self):
        from stripe_link.domain.sites import site_for_page

        with self.assertRaises(RuntimeError):
            site_for_page(BrokenSites(), "t1", "page_a")

    def test_best_effort_lookup_still_swallows(self):
        from stripe_link.domain.sites import find_site_for_page

        self.assertIsNone(find_site_for_page(BrokenSites(), "t1", "page_a"))

    def test_both_agree_when_the_table_reads(self):
        from stripe_link.domain.sites import find_site_for_page, site_for_page

        sites = FakeSites([site("site_1", "page_a")])
        self.assertEqual(
            site_for_page(sites, "t1", "page_a"), find_site_for_page(sites, "t1", "page_a"))


if __name__ == "__main__":
    unittest.main()


class CheckoutWiringTests(unittest.TestCase):
    """The rule reaching the two handlers that have a page context.

    Wiring is worth its own tests because the interesting failure is silent in both directions: a guard that
    is never called reports a clean Phase 1 and proves nothing, and a guard called with the wrong repo refuses
    real sales the moment enforcement flips.
    """

    def setUp(self):
        from tests.test_checkout_handler import (
            FakeCipher, FakeRepository, FakeStripeKeysRepository, load_fixture)
        from stripe_link.domain.fees import clear_config_cache

        clear_config_cache()
        self.addCleanup(clear_config_cache)
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.FakeRepository = FakeRepository
        self.FakeCipher = FakeCipher
        self.FakeStripeKeysRepository = FakeStripeKeysRepository
        self.requests = []

    def opener(self, request, timeout=20):
        from tests.test_checkout_handler import FakeResponse

        self.requests.append(request)
        return FakeResponse()

    def _checkout(self, enforcement, sites, *, method="GET"):
        from handlers.checkout import handler

        pages = self.FakeRepository(
            "page_id", [{"tenant_id": "tenant_demo", "page_id": "page_orphan", "status": "published"}])
        with mock.patch.dict(os.environ, {"ELIGIBILITY_ENFORCEMENT": enforcement}):
            out = io.StringIO()
            with redirect_stdout(out):
                response = handler(
                    {"httpMethod": method, "queryStringParameters": {
                        "clientID": "tenant_demo", "offer": "offer_simple_coffee", "page_id": "page_orphan",
                        "product_id": "prod_simple_coffee", "price_id": "price_simple_coffee",
                        "success_url": "https://pages.example.com/thanks",
                        "cancel_url": "https://pages.example.com/buy"}},
                    None,
                    offers_repo=self.FakeRepository("offer_id", [self.offer]),
                    products_repo=self.FakeRepository("product_id", [self.product]),
                    stripe_repo=self.FakeStripeKeysRepository(),
                    tenant_repo=self.FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
                    pages_repo=pages,
                    sites_repo=sites,
                    secret_cipher=self.FakeCipher(),
                    opener=self.opener,
                )
        return response, out.getvalue()

    def test_observe_lets_a_detached_page_take_money_and_says_so(self):
        response, logged = self._checkout(ce.OBSERVE, FakeSites([site("site_1", "page_other")]))
        self.assertEqual(response["statusCode"], 303)  # GET redirects the browser to Stripe
        self.assertEqual(len(self.requests), 1, "the Stripe session must still be created")
        record = json.loads(logged.splitlines()[-1])["commerce_eligibility"]
        self.assertEqual(record["verdict"], ce.NOT_ATTACHED)
        self.assertEqual(record["path"], "checkout")
        self.assertFalse(record["enforced"])

    def test_observe_is_silent_for_an_attached_page(self):
        response, logged = self._checkout(ce.OBSERVE, FakeSites([site("site_1", "page_orphan")]))
        self.assertEqual(response["statusCode"], 303)
        # Other measurements share stdout (the api_auth phase-1 line), so assert on OUR namespace.
        self.assertNotIn("commerce_eligibility", logged)

    def test_enforce_refuses_a_detached_page_before_reaching_stripe(self):
        response, _ = self._checkout(ce.ENFORCE, FakeSites([site("site_1", "page_other")]))
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(self.requests, [], "no Stripe call may be made for a refused checkout")
        # GET is the CTA's own href — a browser lands here — so the refusal is the branded page, not JSON.
        self.assertEqual(response["headers"]["Content-Type"], "text/html; charset=utf-8")

    def test_enforce_refusal_on_post_is_json(self):
        import json as _json

        response, _ = self._checkout(ce.ENFORCE, FakeSites([site("site_1", "page_other")]), method="POST")
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(_json.loads(response["body"])["error"], "page_not_eligible")

    def test_cart_checkout_is_wired_to_the_same_rule(self):
        import json as _json

        from handlers.cart_checkout import handler as cart_handler

        cart = {
            "tenant_id": "tenant_demo", "cart_id": "cart_1", "offer_id": "offer_simple_coffee",
            "line_items": [{"product_id": "prod_simple_coffee", "price_id": "price_simple_coffee",
                            "quantity": 1}],
        }
        pages = self.FakeRepository(
            "page_id", [{"tenant_id": "tenant_demo", "page_id": "page_orphan", "status": "published"}])
        with mock.patch.dict(os.environ, {"ELIGIBILITY_ENFORCEMENT": ce.ENFORCE}):
            out = io.StringIO()
            with redirect_stdout(out):
                response = cart_handler(
                    {"httpMethod": "POST", "body": _json.dumps({
                        "tenant_id": "tenant_demo", "cart_id": "cart_1", "page_id": "page_orphan",
                        "success_url": "https://pages.example.com/thanks",
                        "cancel_url": "https://pages.example.com/buy"})},
                    None,
                    carts_repo=self.FakeRepository("cart_id", [cart]),
                    offers_repo=self.FakeRepository("offer_id", [self.offer]),
                    products_repo=self.FakeRepository("product_id", [self.product]),
                    stripe_repo=self.FakeStripeKeysRepository(),
                    tenant_repo=self.FakeRepository("tenant_id", [{"tenant_id": "tenant_demo"}]),
                    pages_repo=pages,
                    sites_repo=FakeSites([site("site_1", "page_other")]),
                    secret_cipher=self.FakeCipher(),
                    opener=self.opener,
                )
        self.assertEqual(response["statusCode"], 403)
        self.assertIn("page_not_eligible", response["body"])
        self.assertEqual(self.requests, [])
        self.assertIn('"path": "cart_checkout"', out.getvalue())
