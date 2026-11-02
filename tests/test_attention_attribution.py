"""A2 — attribution (plans/ATTENTION_PRIMITIVE.md §8).

`?src=` on a published page names the POST that sent a visitor. The click is counted in the page-views
table; the MONEY lands on the order, carried through Stripe metadata because that is the only channel
surviving the hop to a hosted checkout and back. GMV per post is then a join on one string.

Built before the campaign engine on the plan's own instruction — it makes hand-posted content measurable,
and retrofitting it afterwards would leave a hole in exactly the data that justifies the tier.
"""

import json
import unittest

from handlers.checkout import build_checkout_payload
from handlers.page_view import handler as view_handler
from stripe_link.domain.page_views import (
    MAX_SOURCE_LENGTH,
    source_counter_key,
    source_counter_partition,
    source_dedupe_item,
    source_slug,
)
from stripe_link.runtime.html import render_view_beacon

PAGE = {"page_id": "page_abc123", "tenant_id": "t1"}


class TheSlug(unittest.TestCase):
    """The ONE place tenant text reaches a key, which is why the character set is an allow-list."""

    def test_it_is_readable_back(self):
        """Not hashed, unlike `link_id`: this IS the tenant's own label and has to appear on a report.
        "ig-reel-nov-03" is the answer they are looking for."""
        self.assertEqual(source_slug("IG-Reel-Nov-03"), "ig-reel-nov-03")
        self.assertEqual(source_slug(" tiktok_01 "), "tiktok_01")

    def test_path_and_key_characters_cannot_survive(self):
        for hostile in ("bad/../slug", "a#b", "x y", "drop table", "../../etc"):
            with self.subTest(hostile=hostile):
                cleaned = source_slug(hostile)
                for ch in "/#. ":
                    self.assertNotIn(ch, cleaned)

    def test_it_is_length_capped(self):
        self.assertEqual(len(source_slug("x" * 500)), MAX_SOURCE_LENGTH)

    def test_rubbish_is_empty_not_an_error(self):
        for junk in (None, "", 7, [], {}):
            with self.subTest(junk=junk):
                self.assertIsInstance(source_slug(junk), str)

    def test_the_key_carries_the_slug_and_the_page(self):
        self.assertEqual(source_counter_key("page_1", "ig-reel"),
                         {"PK": "PAGESOURCES#page_1", "SK": "SOURCE#ig-reel"})
        self.assertEqual(source_counter_partition("page_1"), "PAGESOURCES#page_1")

    def test_every_source_of_a_page_shares_one_partition(self):
        """So the dashboard reads them all in ONE query instead of a lookup per source — the same trick
        the link counters use."""
        keys = [source_counter_key("page_1", s)["PK"] for s in ("a", "b", "c")]
        self.assertEqual(len(set(keys)), 1)

    def test_the_dedupe_is_per_page_source_visitor_and_day(self):
        """Unique ARRIVALS, not raw hits, so every number on the page stays an answer about people and a
        rate computed from any two of them means something."""
        item = source_dedupe_item("page_1", "ig-reel", "2026-11-01", "v1", 1_793_000_000)
        self.assertEqual(item["PK"], "PAGESOURCEHIT#page_1#2026-11-01")
        self.assertEqual(item["SK"], "SOURCE#ig-reel#VISITOR#v1")
        self.assertGreater(item["ttl"], item["created_at"])


class Repo:
    def __init__(self, claim=True):
        self.claim = claim
        self.views = 0
        self.sources = []
        self.links = []

    def claim_view(self, item):
        self.claimed = item
        return self.claim

    def increment_total(self, _key, _now):
        self.views += 1

    def increment_source_total(self, key, _now):
        self.sources.append(key["SK"])

    def increment_link_total(self, key, _now):
        self.links.append(key["SK"])


def beacon(**params):
    return {"httpMethod": "GET",
            "queryStringParameters": {"p": PAGE["page_id"], "v": "visitor1", **params},
            "headers": {}}


class Ingestion(unittest.TestCase):
    def test_a_source_arrival_counts_the_view_AND_the_source(self):
        """Not an alternative to a view, unlike `l` — it is the same arrival on a second axis. A visitor
        who followed a Reel is one view and one arrival from that post."""
        repo = Repo()
        response = view_handler(beacon(s="ig-reel"), None, repository=repo, now=1_793_000_000)
        self.assertEqual(response["statusCode"], 204)
        self.assertEqual(repo.views, 1)
        self.assertEqual(repo.sources, ["SOURCE#ig-reel"])

    def test_no_source_still_counts_the_view(self):
        repo = Repo()
        view_handler(beacon(), None, repository=repo, now=1)
        self.assertEqual((repo.views, repo.sources), (1, []))

    def test_a_mistyped_slug_never_costs_the_page_view(self):
        """Losing a view because a tenant mistyped a campaign label would be the analytics equivalent of
        refusing the page."""
        repo = Repo()
        view_handler(beacon(s="///"), None, repository=repo, now=1)
        self.assertEqual(repo.views, 1)
        self.assertEqual(repo.sources, [])

    def test_a_link_click_is_still_exclusive(self):
        """`l` means they LEFT. That is a different event, and a source on it must not also count an
        arrival — they arrived earlier."""
        repo = Repo()
        view_handler(beacon(l="a" * 16, s="ig-reel"), None, repository=repo, now=1)
        self.assertEqual(repo.views, 0)
        self.assertEqual(repo.sources, [])
        self.assertEqual(len(repo.links), 1)

    def test_a_repeat_arrival_in_the_same_day_is_not_counted_twice(self):
        repo = Repo(claim=False)
        view_handler(beacon(s="ig-reel"), None, repository=repo, now=1)
        self.assertEqual((repo.views, repo.sources), (0, []))

    def test_an_unreadable_counter_is_silent_to_the_visitor(self):
        class Exploding(Repo):
            def claim_view(self, item):
                raise RuntimeError("dynamo is unhappy")

        response = view_handler(beacon(s="ig-reel"), None, repository=Exploding(), now=1)
        self.assertEqual(response["statusCode"], 204)


class ThePublishedPage(unittest.TestCase):
    def script(self, kind="published"):
        return render_view_beacon(PAGE, kind, "https://api.test")

    def test_it_captures_and_beacons_the_source(self):
        text = self.script()
        self.assertIn("get('src')", text)
        self.assertIn("'&s=' + encodeURIComponent(s)", text)

    def test_first_touch_wins(self):
        """A visitor who arrives from a Reel and later returns by bookmark is still credited to the Reel.
        Overwriting on each visit would reassign the sale to whatever they touched last, which is the
        attribution mistake that makes a channel look worthless."""
        self.assertIn("if (q && !held)", self.script())

    def test_the_source_outlives_the_url(self):
        """They arrive on the Reel's link, browse, and check out from a page whose address no longer
        carries it — so it is held in storage, not read from `location` at checkout time."""
        text = self.script()
        self.assertIn("sl_src_", text)
        self.assertIn("window.__jbSrc", text)

    def test_it_expires(self):
        self.assertIn("2592000000", self.script())  # 30 days

    def test_the_key_is_namespaced_per_tenant(self):
        """Link-in-bio serving puts many tenants on ONE origin, where a bare key would share a visitor's
        source across unrelated stores."""
        self.assertIn("'sl_src_' + \"t1\"", self.script())

    def test_a_preview_artifact_carries_no_tracker_at_all(self):
        for kind in ("preview", "test", ""):
            with self.subTest(kind=kind):
                self.assertEqual(self.script(kind), "")


class ThroughCheckout(unittest.TestCase):
    def payload(self, **kwargs):
        return build_checkout_payload(
            tenant_id="t1", offer={"offer_id": "o1", "stripe_mode": "test"},
            products_by_id={}, resolved={"line_items": []},
            success_url="https://x.test/s", cancel_url="https://x.test/c", **kwargs)

    def test_the_source_rides_stripe_metadata(self):
        """The only channel that survives the hop to a hosted page and back through the webhook — which
        is why attribution needs no session store of its own. `cart_id` already proves the path."""
        self.assertEqual(self.payload(attribution_source="ig-reel")["metadata[src]"], "ig-reel")

    def test_it_is_sanitised_server_side_too(self):
        """The page that sends this is a static artifact anyone can POST in place of, and the value
        reaches a stored document."""
        self.assertEqual(self.payload(attribution_source="IG/../Reel")["metadata[src]"], "igreel")

    def test_no_source_writes_no_key(self):
        """An order with no attribution is one nobody tracked. An empty string in the column would be
        indistinguishable from a post whose slug failed to arrive."""
        self.assertNotIn("metadata[src]", self.payload())
        self.assertNotIn("metadata[src]", self.payload(attribution_source="///"))


class OntoTheOrder(unittest.TestCase):
    """Inside `attribution`, beside `page_id` — the page is WHERE they converted, the source is WHAT
    brought them to it. One change there covers checkout, subscription renewal and upsell."""

    def attribution(self, **metadata):
        from handlers.stripe_webhook import attribution_from_metadata
        return attribution_from_metadata({"page_id": "p1", **metadata})

    def test_the_source_lands_beside_the_page(self):
        row = self.attribution(src="ig-reel")
        self.assertEqual(row["source"], "ig-reel")
        self.assertEqual(row["page_id"], "p1")

    def test_an_untracked_order_carries_an_empty_source(self):
        """Empty rather than absent HERE, because the block is a fixed shape every order has — the
        distinction that matters is made by the fold, which skips a blank."""
        self.assertEqual(self.attribution()["source"], "")


class TheMoneyFold(unittest.TestCase):
    """The same fold `summarize_by_page` does, keyed on the post, so the two cannot disagree about what a
    conversion is."""

    ORDERS = [
        {"status": "paid", "amount_total": 4999, "attribution": {"source": "ig-reel", "page_id": "p1"}},
        {"status": "paid", "amount_total": 2500, "attribution": {"source": "ig-reel", "page_id": "p1"}},
        {"status": "pending", "amount_total": 9999, "attribution": {"source": "ig-reel", "page_id": "p1"}},
        {"status": "paid", "amount_total": 1000, "attribution": {"source": "tiktok", "page_id": "p2"}},
        {"status": "paid", "amount_total": 700, "attribution": {"page_id": "p1"}},
    ]

    def test_only_paid_orders_count(self):
        from stripe_link.domain.page_analytics import summarize_by_source
        self.assertEqual(summarize_by_source(self.ORDERS)["ig-reel"],
                         {"conversions": 2, "revenue_cents": 7499})

    def test_a_page_id_narrows_it(self):
        from stripe_link.domain.page_analytics import summarize_by_source
        self.assertEqual(sorted(summarize_by_source(self.ORDERS, "p1")), ["ig-reel"])
        self.assertEqual(sorted(summarize_by_source(self.ORDERS, "p2")), ["tiktok"])

    def test_an_untracked_order_is_skipped_not_bucketed_as_blank(self):
        from stripe_link.domain.page_analytics import summarize_by_source
        self.assertNotIn("", summarize_by_source(self.ORDERS))

    def test_a_malformed_amount_does_not_cost_the_report(self):
        from stripe_link.domain.page_analytics import summarize_by_source
        rows = summarize_by_source([{"status": "paid", "amount_total": "oops",
                                     "attribution": {"source": "x"}}])
        self.assertEqual(rows["x"], {"conversions": 1, "revenue_cents": 0})


class TheReportRows(unittest.TestCase):
    def rows(self, arrivals, money):
        from stripe_link.domain.page_analytics import attribution_rows
        return attribution_rows(arrivals, money)

    def test_attention_without_sales_is_the_most_useful_row(self):
        """The post that got attention and sold nothing is the whole point of measuring, so the report is
        the UNION of both sides rather than the intersection."""
        rows = self.rows({"tiktok": 15}, {})
        self.assertEqual(rows[0]["source"], "tiktok")
        self.assertEqual(rows[0]["arrivals"], 15)
        self.assertEqual(rows[0]["conversions"], 0)

    def test_sales_without_arrivals_are_not_dropped(self):
        """Real: the visitor arrived before the tracker shipped, or cleared their storage. Dropping the
        row would quietly understate revenue."""
        rows = self.rows({}, {"old-post": {"conversions": 1, "revenue_cents": 5000}})
        self.assertEqual(rows[0]["revenue_cents"], 5000)
        self.assertNotIn("arrivals", rows[0])

    def test_unmeasured_is_not_zero(self):
        """"Nobody came" and "we were not measuring" must stay distinguishable, exactly as
        `attach_summaries` keeps views absent rather than 0."""
        rows = self.rows({"a": 0}, {"b": {"conversions": 1, "revenue_cents": 10}})
        by_source = {r["source"]: r for r in rows}
        self.assertEqual(by_source["a"]["arrivals"], 0)
        self.assertNotIn("arrivals", by_source["b"])

    def test_it_sorts_by_money_then_attention(self):
        rows = self.rows({"a": 1, "b": 99, "c": 5},
                         {"a": {"conversions": 1, "revenue_cents": 9000}})
        self.assertEqual([r["source"] for r in rows], ["a", "b", "c"])

    def test_nothing_measured_is_an_empty_report(self):
        self.assertEqual(self.rows({}, {}), [])
        self.assertEqual(self.rows(None, None), [])


if __name__ == "__main__":
    unittest.main()
