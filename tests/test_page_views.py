"""The zero-config view counter: unique visitors per published page per day.

Its job is narrow on purpose. A tenant who configures GA4 or a Meta pixel gets sessions, sources and
funnels from a product built for that; this answers "is anyone looking at my page" for a tenant who
configures nothing, which was the reason the legacy app had it.
"""
import unittest

from handlers.page_view import handler as track
from stripe_link.domain.page_views import (
    counter_key,
    day_bucket,
    dedupe_item,
    is_trackable_page_id,
    visitor_key,
)
from stripe_link.runtime.html import render_view_beacon


class VisitorKeyTests(unittest.TestCase):
    def test_the_same_visitor_dedupes_within_a_day(self):
        args = {"ip": "1.2.3.4", "user_agent": "UA", "salt": "s", "day": "20260909"}
        self.assertEqual(visitor_key(**args), visitor_key(**args))

    def test_the_key_cannot_be_correlated_across_days(self):
        base = {"ip": "1.2.3.4", "user_agent": "UA", "salt": "s"}
        self.assertNotEqual(visitor_key(**base, day="20260909"), visitor_key(**base, day="20260910"))

    def test_the_salt_makes_an_ip_untestable(self):
        # Unsalted, anyone holding the table could hash a suspected IP and check whether it appears --
        # the legacy implementation's one real weakness.
        base = {"ip": "1.2.3.4", "user_agent": "UA", "day": "20260909"}
        self.assertNotEqual(visitor_key(**base, salt="a"), visitor_key(**base, salt="b"))

    def test_a_first_party_id_beats_the_ip_heuristic(self):
        # Same person, different network: the explicit id keeps them one visitor.
        a = visitor_key(ip="1.2.3.4", user_agent="UA", explicit_id="abc", salt="s", day="d")
        b = visitor_key(ip="9.9.9.9", user_agent="Other", explicit_id="abc", salt="s", day="d")
        self.assertEqual(a, b)


class PublicEndpointTests(unittest.TestCase):
    class Repo:
        def __init__(self, claim=True):
            self.claim = claim
            self.claims, self.increments = [], []

        def claim_view(self, item):
            self.claims.append(item)
            return self.claim

        def increment_total(self, key, now):
            self.increments.append(key)

    def _call(self, params, repo, headers=None):
        return track({"httpMethod": "POST", "queryStringParameters": params,
                      "headers": headers or {}}, None, repository=repo, now=1789000000)

    def test_a_first_view_counts(self):
        repo = self.Repo(claim=True)
        response = self._call({"p": "page_abc123"}, repo)
        self.assertEqual(response["statusCode"], 204)
        self.assertEqual(repo.increments, [counter_key("page_abc123")])

    def test_a_repeat_view_the_same_day_does_not(self):
        repo = self.Repo(claim=False)
        self._call({"p": "page_abc123"}, repo)
        self.assertEqual(repo.increments, [])

    def test_a_malformed_page_id_never_reaches_the_store(self):
        # The endpoint is public, so nothing the caller sends may become a partition key unchecked.
        for bad in ("../evil", "PAGEVIEWS#x", "", "offer_123", "page_" + "x" * 200):
            repo = self.Repo()
            self._call({"p": bad}, repo)
            self.assertEqual(repo.claims, [], bad)

    def test_a_storage_failure_is_invisible_to_the_visitor(self):
        class Broken:
            def claim_view(self, item):
                raise RuntimeError("table gone")
        self.assertEqual(self._call({"p": "page_abc123"}, Broken())["statusCode"], 204)

    def test_it_never_returns_a_body(self):
        # A tracker must not report whether a page exists or whether the view was counted.
        for repo in (self.Repo(claim=True), self.Repo(claim=False)):
            self.assertEqual(self._call({"p": "page_abc123"}, repo)["body"], "")


class DedupeRowTests(unittest.TestCase):
    def test_the_row_expires_but_the_total_does_not(self):
        item = dedupe_item("page_abc", day_bucket(1789000000), "v1", 1789000000)
        self.assertGreater(item["ttl"], item["created_at"])
        self.assertNotIn("ttl", counter_key("page_abc"))

    def test_page_ids_are_shape_checked(self):
        self.assertTrue(is_trackable_page_id("page_abc123"))
        self.assertFalse(is_trackable_page_id("page_a/b"))


class BeaconEmissionTests(unittest.TestCase):
    PAGE = {"page_id": "page_abc"}
    API = "https://api.example.com/prod"

    def test_only_the_published_artifact_carries_the_tracker(self):
        # The gate is the artifact KIND, not a runtime check: preview and test artifacts do not skip
        # counting, they have no tracker in them. A tenant editing their own page cannot inflate it.
        self.assertIn("/t/view", render_view_beacon(self.PAGE, "published", self.API))
        for kind in ("preview", "test", ""):
            self.assertEqual(render_view_beacon(self.PAGE, kind, self.API), "", kind)

    def test_nothing_is_emitted_without_somewhere_to_send_it(self):
        self.assertEqual(render_view_beacon(self.PAGE, "published", ""), "")
        self.assertEqual(render_view_beacon({}, "published", self.API), "")

    def test_the_page_id_is_json_escaped_into_the_script(self):
        markup = render_view_beacon({"page_id": 'page_a"x'}, "published", self.API)
        self.assertNotIn('"page_a"x"', markup)


if __name__ == "__main__":
    unittest.main()
