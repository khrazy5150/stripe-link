"""The page a shopper meets while a store is shut for the Sabbath, and the resolver that serves it.

The closure is decided on the LIVE PAGE path (`custom_domains_resolve`) -- the one Lambda every live
request already passes through -- and the Cloudflare Worker proxies whatever URL it is handed, so no edge
code changes. These tests pin that split: the resolver decides, the page only renders.
"""
import datetime
import json
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from handlers import sabbath_closed
from stripe_link.domain.sabbath import SabbathClosedError
from stripe_link.runtime.platform_pages import (format_reopen, render_platform_page,
                                                render_sabbath_closed)

DENVER = ZoneInfo("America/Denver")
REOPEN = datetime.datetime(2026, 11, 7, 18, 12, 27, tzinfo=DENVER)


class TheSharedShellTests(unittest.TestCase):
    """Ported from stripe-cart's paywall template -- the page a shopper already meets when a merchant's
    billing lapses. Same design, so a closure does not read as a second, unfamiliar failure."""

    def test_every_placeholder_is_filled(self):
        html = render_platform_page(headline="x", subtitle="y")
        self.assertNotIn("__", html)

    def test_the_billing_copy_is_gone(self):
        """"Secured by Stripe / Cancel anytime" and "One step away" were written for the paywall. A
        shopper told the shop is shut for the day does not need reassuring about card encryption."""
        html = render_sabbath_closed(reopen_at=REOPEN, timezone_name="America/Denver")
        for leftover in ("Secured by Stripe", "256-bit encryption", "Cancel anytime", "One step away"):
            self.assertNotIn(leftover, html)

    def test_the_brand_shell_survived_the_port(self):
        html = render_sabbath_closed(reopen_at=REOPEN, timezone_name="America/Denver")
        for kept in ("#ff8309", "Junior ", "card-accent", "trust-badge"):
            self.assertIn(kept, html)

    def test_the_headline_keeps_its_accent_word(self):
        html = render_sabbath_closed(reopen_at=REOPEN, timezone_name="America/Denver")
        self.assertIn("<em>Sabbath.</em>", html)

    def test_the_subtitle_is_escaped(self):
        html = render_platform_page(headline="h", subtitle="<script>alert(1)</script>")
        self.assertNotIn("<script>", html)

    def test_the_store_name_is_escaped(self):
        html = render_sabbath_closed(reopen_at=REOPEN, timezone_name="UTC",
                                     store_name="<script>alert(1)</script>")
        self.assertNotIn("<script>alert", html)

    def test_no_robots_meta(self):
        """A noindex on a 503 is a contradictory signal that can cost a tenant the ranking of a page that
        is merely shut until sundown. The 503 alone says "come back"."""
        self.assertNotIn("noindex", render_sabbath_closed(reopen_at=REOPEN, timezone_name="UTC"))


class TheReopeningMomentTests(unittest.TestCase):
    def test_it_is_said_in_the_STORE_timezone(self):
        """The shopkeeper reopens at sundown where the SHOP is. A visitor two zones away reading their own
        clock would arrive at the wrong hour, which is why the zone is named on the page."""
        self.assertEqual(format_reopen(REOPEN, "America/Denver"), "Saturday at 6:12 pm")

    def test_the_same_instant_reads_differently_elsewhere(self):
        self.assertNotEqual(format_reopen(REOPEN, "America/Denver"),
                            format_reopen(REOPEN, "Europe/London"))

    def test_an_unknown_zone_falls_back_without_crashing(self):
        self.assertIn("at", format_reopen(REOPEN, "Mars/Olympus_Mons"))

    def test_the_zone_is_named_on_the_page(self):
        html = render_sabbath_closed(reopen_at=REOPEN, timezone_name="America/Denver")
        self.assertIn("America/Denver", html)

    def test_no_reopening_time_DROPS_the_sentence_rather_than_inventing_one(self):
        """THE ONE THAT MATTERS here. A wrong reopening time is worse than none: a shopper who comes back
        and finds the shop still shut has been told something false by us."""
        html = render_sabbath_closed(reopen_at=None, timezone_name="UTC")
        self.assertNotIn("Orders reopen", html)
        self.assertIn("Nothing has been charged", html)


def event(**params):
    return {"httpMethod": "GET", "queryStringParameters": params or None}


class ThePageHandlerTests(unittest.TestCase):
    def test_it_answers_503_so_a_crawler_keeps_the_url(self):
        """200 would invite Google to index "we are closed" as the product page; 404/403 would invite it
        to drop the URL. 503 means "the page is fine, come back"."""
        response = sabbath_closed.handler(event(until=REOPEN.isoformat(), tz="America/Denver"), None)
        self.assertEqual(response["statusCode"], 503)
        self.assertIn("text/html", response["headers"]["Content-Type"])

    def test_retry_after_is_present_and_sane(self):
        response = sabbath_closed.handler(event(until=REOPEN.isoformat(), tz="America/Denver"), None)
        self.assertTrue(0 < int(response["headers"]["Retry-After"]) <= 86400)

    def test_a_reopening_time_far_in_the_past_still_yields_a_sane_retry_after(self):
        past = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
        self.assertGreater(int(sabbath_closed.handler(event(until=past), None)["headers"]["Retry-After"]), 0)

    def test_an_absurd_reopening_time_is_clamped(self):
        far = datetime.datetime(2222, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
        self.assertEqual(sabbath_closed.handler(event(until=far), None)["headers"]["Retry-After"], "86400")

    def test_a_broken_until_still_renders_a_page(self):
        """The query string is DISPLAY data. Nothing acts on it, so nothing may break on it."""
        response = sabbath_closed.handler(event(until="not-a-date", tz="UTC"), None)
        self.assertEqual(response["statusCode"], 503)
        self.assertNotIn("Orders reopen", response["body"])

    def test_no_parameters_at_all_still_renders(self):
        response = sabbath_closed.handler({"httpMethod": "GET"}, None)
        self.assertEqual(response["statusCode"], 503)
        self.assertIn("Sabbath", response["body"])

    def test_a_naive_timestamp_is_read_as_utc(self):
        response = sabbath_closed.handler(event(until="2026-11-07T18:12:27", tz="UTC"), None)
        self.assertIn("Orders reopen", response["body"])

    def test_head_gets_the_headers_without_a_body(self):
        response = sabbath_closed.handler({"httpMethod": "HEAD"}, None)
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(response["body"], "")
        self.assertIn("Retry-After", response["headers"])

    def test_it_reads_no_table(self):
        """It renders; it does not decide. One implementation of the window, in the resolver."""
        import inspect

        source = inspect.getsource(sabbath_closed)
        for forbidden in ("_repository(", "boto3", "closure_for_site", "assert_open"):
            self.assertNotIn(forbidden, source)


class TheResolverServesItTests(unittest.TestCase):
    """The closure is decided here so the Cloudflare Worker needs no change: it already proxies whatever
    `origin_url` names."""

    def _resolve(self, closure, api_base="https://api.test"):
        from handlers import custom_domains_resolve as resolver

        record = {"tenant_id": "t1", "site_id": "s1", "status": "active",
                  "target_page_id": "page_1", "domain": "shop.test",
                  "routes": {"/": {"kind": "page", "page_id": "page_1"}}}
        index_repo = mock.Mock()
        index_repo.find_by_id.return_value = record
        with mock.patch.object(resolver, "closure_for_site", return_value=closure), \
             mock.patch.dict("os.environ", {"PUBLIC_API_BASE_URL": api_base}, clear=False):
            response = resolver.handler(
                {"httpMethod": "GET", "queryStringParameters": {"host": "shop.test", "path": "/"}},
                None, index_repo=index_repo, pages_domain="d123.cloudfront.net",
                experiments_repo=mock.Mock(**{"query.return_value": []}))
        return response, json.loads(response["body"])

    def _closure(self):
        return SabbathClosedError(resume_at=REOPEN, timezone_name="America/Denver")

    def test_an_open_store_serves_its_published_artifact(self):
        _response, body = self._resolve(None)
        self.assertIn("cloudfront.net", body["route"]["origin_url"])

    def test_a_closed_store_is_pointed_at_the_closed_page(self):
        _response, body = self._resolve(self._closure())
        self.assertIn("/sabbath/closed", body["route"]["origin_url"])
        self.assertEqual(body["route"]["type"], "origin_url")

    def test_the_reopening_moment_travels_to_the_page(self):
        _response, body = self._resolve(self._closure())
        self.assertIn("America%2FDenver", body["route"]["origin_url"])
        self.assertIn("until=", body["route"]["origin_url"])

    def test_the_closed_route_is_NOT_marked_noindex(self):
        """503 + Retry-After already tells a crawler to come back. noindex on top risks dropping a URL
        that is merely shut until sundown."""
        _response, body = self._resolve(self._closure())
        self.assertNotIn("noindex", body["route"])

    def test_with_no_api_base_the_store_keeps_serving(self):
        """Failing open. A shop that stayed open through its Sabbath has a setting that did not work; a
        shop that went blank has lost the week's trade."""
        _response, body = self._resolve(self._closure(), api_base="")
        self.assertIn("cloudfront.net", body["route"]["origin_url"])


class TheGateFailsOpenTests(unittest.TestCase):
    def test_any_failure_leaves_the_store_serving(self):
        from stripe_link.sabbath_site import closure_for_site

        with mock.patch("stripe_link.sabbath_site.tenant_settings", side_effect=RuntimeError("boom")):
            self.assertIsNone(closure_for_site("t1", "s1"))

    def test_the_setting_short_circuits_before_any_other_read(self):
        """This runs on the live store path. A tenant who has not enabled the Sabbath must pay one keyed
        lookup and nothing else -- no Site read, no profile read, no solar maths."""
        from stripe_link import sabbath_site

        with mock.patch.object(sabbath_site, "tenant_settings", return_value={}), \
             mock.patch.object(sabbath_site, "site_organization_by_id") as site_read:
            self.assertIsNone(sabbath_site.closure_for_site("t1", "s1"))
        site_read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
