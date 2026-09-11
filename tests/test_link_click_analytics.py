"""Per-link click counts: "link-in-bio pages live or die on click data" (SOCIAL_MEDIA_PAGES.md §11).

Rides the view rail rather than building a second one -- same table, same endpoint, same abuse posture. That
is why this was worth waiting for: when §11 was written there was no first-party analytics rail at all, so
per-link clicks would have been the first one and would have had to invent the public-write abuse story from
scratch.
"""
import pathlib
import unittest

from stripe_link.domain.page_views import (
    clicks_by_url,
    is_trackable_link_id,
    link_counter_key,
    link_dedupe_item,
    link_id,
    page_link_urls,
)
from stripe_link.runtime import html as html_module

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

ORG = {"same_as": [{"url": "https://github.com/acme"}, {"url": "https://instagram.com/acme"}]}


class LinkIdTests(unittest.TestCase):
    def test_the_id_follows_the_url_not_the_position(self):
        # Position looked simpler and is wrong: reordering a hub -- which creators do constantly -- would
        # silently reassign every link's history to its new neighbour, and the numbers would keep looking
        # plausible. This is the property that makes the counts trustworthy over time.
        first = link_id("https://instagram.com/acme")
        self.assertEqual(first, link_id("https://instagram.com/acme"))
        self.assertNotEqual(first, link_id("https://instagram.com/other"))

    def test_whitespace_does_not_fork_a_counter(self):
        self.assertEqual(link_id("  https://x.com/a  "), link_id("https://x.com/a"))

    def test_the_id_is_shaped_for_a_public_endpoint(self):
        # The caller supplies it, so it must be checkable before it reaches a key.
        self.assertTrue(is_trackable_link_id(link_id("https://x.com/a")))
        for bad in ("", "short", "../../etc", "g" * 16, link_id("https://x.com/a") + "0"):
            self.assertFalse(is_trackable_link_id(bad), bad)


class CountingUnitTests(unittest.TestCase):
    def test_clicks_are_deduped_the_same_way_views_are(self):
        # A decision about UNITS, not caution. Views count unique visitors; if clicks counted raw taps the
        # two numbers would be in different units, so "8 views, 11 Instagram clicks" would be a true sentence
        # that reads as broken, and any click-through rate computed from them would be nonsense.
        item = link_dedupe_item("page_1", link_id("https://x.com/a"), "20260911", "vis1", 1_700_000_000)
        self.assertIn("VISITOR#vis1", item["SK"])
        self.assertIn("20260911", item["PK"])
        self.assertGreater(item["ttl"], item["created_at"])  # dedupe rows expire; the total does not

    def test_every_link_of_a_page_shares_one_partition(self):
        # So the dashboard reads them in ONE query instead of a lookup per link.
        a = link_counter_key("page_1", link_id("https://x.com/a"))
        b = link_counter_key("page_1", link_id("https://x.com/b"))
        self.assertEqual(a["PK"], b["PK"])
        self.assertNotEqual(a["SK"], b["SK"])

    def test_the_total_carries_no_ttl(self):
        self.assertNotIn("ttl", link_counter_key("page_1", link_id("https://x.com/a")))


class ResolutionTests(unittest.TestCase):
    PAGE = {"sections": [
        {"type": "social_links"},
        {"type": "link_cards", "items": [{"url": "https://substack.com/@acme", "label": "Newsletter"}]},
    ]}

    def test_inherited_profiles_are_resolved_too(self):
        # The section is inheriting, so its URLs are not in the page document at all. Reading the page alone
        # would have labelled only the cards and left the profile clicks as unexplained numbers.
        self.assertEqual(page_link_urls(self.PAGE, ORG),
                         ["https://github.com/acme", "https://instagram.com/acme",
                          "https://substack.com/@acme"])

    def test_page_local_links_override_exactly_as_they_render(self):
        page = {"sections": [{"type": "social_links", "items": [{"url": "https://onlyfans.com/acme"}]}]}
        self.assertEqual(page_link_urls(page, ORG), ["https://onlyfans.com/acme"])

    def test_a_url_listed_twice_is_one_counter(self):
        page = {"sections": [{"type": "link_cards", "items": [
            {"url": "https://x.com/a"}, {"url": "https://x.com/a"}]}]}
        self.assertEqual(page_link_urls(page, {}), ["https://x.com/a"])

    def test_counts_come_back_keyed_by_url(self):
        # The id is a hash WE own. The dashboard should never have to reproduce it to read its own numbers,
        # which is also what keeps the hash a single implementation.
        totals = {link_id("https://substack.com/@acme"): 7}
        clicks = clicks_by_url(self.PAGE, totals, ORG)
        self.assertEqual(clicks["https://substack.com/@acme"], 7)

    def test_a_link_nobody_clicked_reports_zero_not_nothing(self):
        # "Nobody has clicked this" is a real answer; an absent key renders as blank and reads as broken.
        clicks = clicks_by_url(self.PAGE, {}, ORG)
        self.assertEqual(clicks["https://github.com/acme"], 0)


class BeaconTests(unittest.TestCase):
    PAGE = {"page_id": "page_abc"}

    def test_nothing_is_emitted_outside_a_published_artifact(self):
        # The gate is the artifact KIND, not a runtime check, so a tenant editing their own hub all afternoon
        # cannot inflate their own numbers -- the page they are looking at has no tracker in it.
        for kind in ("preview", "", "draft"):
            self.assertEqual(html_module.render_link_click_beacon(self.PAGE, kind, "https://api.example"), "")

    def test_it_listens_once_rather_than_per_link(self):
        script = html_module.render_link_click_beacon(self.PAGE, "published", "https://api.example")
        self.assertEqual(script.count("addEventListener"), 1)
        self.assertIn("[data-sl-link]", script)

    def test_it_fires_on_pointerdown_not_click(self):
        # A tap that opens a new tab often unloads or backgrounds the page before a click handler's beacon is
        # flushed, so counting on click under-reports on exactly the platform this page exists for.
        script = html_module.render_link_click_beacon(self.PAGE, "published", "https://api.example")
        self.assertIn("'pointerdown'", script)
        self.assertNotIn("'click'", script)

    def test_it_is_a_beacon_and_not_a_redirector(self):
        # A /go/{page}/{link} hop would count perfectly and turn the shared platform host into an open
        # redirect, which is the abuse surface §7 exists to prevent. The honest cost is a lossy count.
        script = html_module.render_link_click_beacon(self.PAGE, "published", "https://api.example")
        self.assertIn("sendBeacon", script)
        self.assertNotIn("/go/", script)

    def test_rendered_links_carry_their_id(self):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(ORG)
        markup = html_module.render_social_links({"id": "s1"})
        self.assertIn(f'data-sl-link="{link_id("https://github.com/acme")}"', markup)

    def test_link_cards_carry_theirs_too(self):
        html_module._RENDER_STATE["home_url"] = "https://acme.com"
        try:
            markup = html_module.render_link_cards(
                {"id": "lc", "items": [{"url": "https://substack.com/@acme", "label": "Newsletter"}]})
        finally:
            html_module._RENDER_STATE.pop("home_url", None)
        self.assertIn(f'data-sl-link="{link_id("https://substack.com/@acme")}"', markup)


class DashboardTests(unittest.TestCase):
    def test_counts_are_fetched_lazily_when_a_page_is_opened(self):
        # Not attached to the listing: it is one query per page, so the listing would pay for it on every row
        # while only a link hub has anything to show.
        self.assertIn("async function loadLinkClicks(", BUILDER)
        self.assertIn("loadLinkClicks(page.page_id);", BUILDER)

    def test_a_failed_fetch_never_blocks_editing(self):
        block = BUILDER.split("async function loadLinkClicks(", 1)[1][:600]
        self.assertIn("catch", block)
        self.assertIn("linkClicks.value = {};", block)


if __name__ == "__main__":
    unittest.main()
