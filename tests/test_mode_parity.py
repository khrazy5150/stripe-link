"""Nothing may rely on the Stripe mode's fail-safe default.

`resolve_stripe_mode` falls back to `test` when no mode arrives, deliberately: a caller who forgets one
must never mutate live data. The cost of that safety is that **an omission works in test and breaks in
live** — the single mechanism that makes a green test suite non-predictive about live, and the cause of
the funnel defect on 2026-10-08, where a buyer who had just paid was returned to the landing page
because `/post-checkout/next` arrived with no mode and looked for the page under `PAGE#test#…`.

Two guards here:

1. **Every API call the published island makes carries a mode.** Scoped per call block, because the mode
   travels in the query string for a GET and in the JSON body for a POST — a line-level check reports
   `/upsell/charge` as missing one and is simply wrong. That mistake was made twice while writing this.

2. **The same request resolves the same way in both modes.** A scenario run with `mode=live` and
   `mode=test` must differ only in which mode-scoped store it addresses, never in which branch it takes.
"""
import json
import pathlib
import re
import unittest

from stripe_link.common import resolve_stripe_mode
from stripe_link.runtime.html import render_page

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_fixture(name):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rendered_island():
    product = load_fixture("product-creatine-gummies.json")
    offer = load_fixture("offer-creatine-standard.json")
    page = load_fixture("page-creatine-standard.json")
    page["post_checkout"] = {"thank_you_page": {"page_id": "page_ty"}}
    return render_page(page, offer, {"prod_creatine_gummies": product},
                       api_base_url="https://api-dev.example.com")


# Endpoints that read or write mode-scoped documents. A call to one of these without a mode resolves to
# `test` and silently addresses the wrong store.
MODE_SCOPED_ENDPOINTS = ("/upsell/session", "/upsell/charge", "/cart", "post-checkout/next", "/checkout")

# How far past the call site the mode may appear: a POST body is written over several lines.
BLOCK_LINES = 10


def calls_without_a_mode(html):
    """Every mode-scoped API call in the island whose surrounding block names no mode."""
    lines = html.replace('"', "'").splitlines()
    offenders = []
    for index, line in enumerate(lines):
        if not any(endpoint in line for endpoint in MODE_SCOPED_ENDPOINTS):
            continue
        if not ("fetch(" in line or "assign(" in line or "Url =" in line or "return `" in line):
            continue
        block = "\n".join(lines[max(0, index - BLOCK_LINES):index + BLOCK_LINES])
        if not re.search(r"\bmode\b\s*[:=]|set\('mode'", block):
            offenders.append(line.strip()[:120])
    return offenders


class TheIslandAlwaysNamesItsMode(unittest.TestCase):
    def test_no_mode_scoped_call_omits_it(self):
        offenders = calls_without_a_mode(rendered_island())
        self.assertEqual(offenders, [], "these calls resolve to TEST in a live buyer's browser:\n  " +
                         "\n  ".join(offenders))

    def test_the_guard_itself_detects_a_missing_mode(self):
        """A guard that cannot fail is not a guard — this one was written wrong twice."""
        html = rendered_island().replace("set('mode', cta.dataset.checkoutMode || 'test');", "")
        html = html.replace('set("mode", cta.dataset.checkoutMode || "test");', "")
        self.assertNotEqual(calls_without_a_mode(html), [],
                            "stripping a mode must make this test fail")


class OmissionResolvesToTestAndThatIsTheHazard(unittest.TestCase):
    """Pinned so the behaviour is a decision rather than an accident. If this ever changes, every call
    site that relies on the default has to be revisited."""

    def test_an_absent_mode_is_test(self):
        self.assertEqual(resolve_stripe_mode({"queryStringParameters": {}}), "test")

    def test_an_explicit_live_mode_survives_every_carrier(self):
        for event in (
            {"queryStringParameters": {"mode": "live"}},
            {"headers": {"X-Stripe-Mode": "live"}},
            {"body": json.dumps({"mode": "live"})},
        ):
            self.assertEqual(resolve_stripe_mode(event), "live", event)

    def test_case_and_whitespace_are_tolerated(self):
        for ok in ("LIVE", "live ", " Live"):
            self.assertEqual(resolve_stripe_mode({"queryStringParameters": {"mode": ok}}), "live", ok)

    def test_an_unknown_mode_is_not_treated_as_live(self):
        for bogus in ("production", "prod", "1", "true"):
            self.assertEqual(resolve_stripe_mode({"queryStringParameters": {"mode": bogus}}), "test",
                             f"{bogus!r} must not be read as live")


class TheSameRequestBranchesTheSameWayInBothModes(unittest.TestCase):
    """A scenario must differ between modes only in WHICH store it addresses."""

    def _post_checkout(self, mode):
        from handlers.post_checkout import handler
        from tests.fakes import FakeDocumentRepository

        repo = FakeDocumentRepository("page_id")
        repo.put({"tenant_id": "t_1", "page_id": "page_entry", "status": "published",
                  "post_checkout": {"thank_you_page": {"page_id": "page_ty"}}})
        return handler(
            {"httpMethod": "GET", "pathParameters": {"page_id": "page_entry"},
             "queryStringParameters": {"tenant_id": "t_1", "outcome": "accept", "mode": mode}},
            None, repository=repo, pages_domain="pages.example.com",
        )

    def test_live_and_test_take_the_same_branch(self):
        live, test = self._post_checkout("live"), self._post_checkout("test")
        self.assertEqual(live["statusCode"], test["statusCode"],
                         "the same request must not succeed in one mode and fail in the other")

    def test_the_only_difference_is_which_store_is_addressed(self):
        """Live artifacts keep the root key and test ones are namespaced under `test/`
        (STRIPE_MODE_DECOUPLING P5). That prefix is the ONLY thing the mode may change here -- the page
        it routes to must be identical, which is what the funnel defect got wrong."""
        live = self._post_checkout("live")["headers"]["Location"].split("?")[0]
        test = self._post_checkout("test")["headers"]["Location"].split("?")[0]
        self.assertNotEqual(live, test, "the two modes must not share a storage location")
        self.assertEqual(test, live.replace("/page_entry__thank_you", "/test/page_entry__thank_you"),
                         "the mode may namespace the artifact and change nothing else")
        self.assertTrue(live.endswith("/page_entry__thank_you/index.html"))
