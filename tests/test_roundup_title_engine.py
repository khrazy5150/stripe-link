"""The counted headline (plans/ROUNDUP_PAGES.md §4, P4).

`{count} {plural noun} {hook}` is a proven headline pattern most small merchants do not know, and handing
it over with the number kept true is the point of the feature. The page it is modelled on says
"29 Insanely Cool Gifts" above a list of more than sixty: the number was typed once, in October, and the
author kept adding products.

So the number is not decoration. If it can drift it is worse than no number at all, because a count is
the kind of claim a reader trusts without checking.
"""

import unittest

from stripe_link.domain.composition import RULES, expand_title_tokens, has_title_tokens
from stripe_link.runtime.publishing import expand_roundup_titles, roundup_item_count

MANUAL = {"c_manual": {"rule": "manual"}}
ALL_RULE = {"c_all": {"rule": "all"}}


def grid(collection_id, item_count):
    return {"type": "catalog_grid", "collection_id": collection_id,
            "items": [{"offer_id": f"o{i}", "slug": f"/p{i}"} for i in range(item_count)]}


def page(collection_id="c_manual", item_count=3, title="{count} gift ideas for your mom",
         headline="{count} gift ideas for your mom"):
    return {"seo": {"title": title},
            "sections": [{"type": "hero", "headline": headline}, grid(collection_id, item_count)]}


class ExpansionTests(unittest.TestCase):
    def _expand(self, text, count, year=2026):
        return expand_title_tokens(text, count=count, year=year)

    def test_the_number_is_printed_when_there_is_more_than_one(self):
        self.assertEqual(self._expand("{count} gift ideas for your mom", 13),
                         "13 gift ideas for your mom")

    def test_one_item_drops_the_number_entirely(self):
        """"1 gift ideas for your mom" is fatal to the format, and no automatic singularisation is
        attempted: the tenant typed the plural and English does not let us un-type it."""
        self.assertEqual(self._expand("{count} gift ideas for your mom", 1),
                         "Gift ideas for your mom")

    def test_dropping_it_re_capitalises_only_when_it_led_the_line(self):
        self.assertEqual(self._expand("Our {count} best picks", 1), "Our best picks")
        self.assertEqual(self._expand("Our {count} best picks", 7), "Our 7 best picks")

    def test_an_unknown_count_degrades_to_no_number_rather_than_a_literal_token(self):
        """Publishing "{count} gift ideas" to a live page would be worse than any wrong number."""
        for count in (None, 0):
            self.assertEqual(self._expand("{count} gift ideas for your mom", count),
                             "Gift ideas for your mom", count)

    def test_the_year_is_maintained_for_the_same_reason_the_count_is(self):
        """A hand-typed year goes stale exactly the way a hand-typed count does, and worse: a year in the
        past reads as an abandoned page."""
        self.assertEqual(self._expand("{count} gadgets you'll love in {year}", 25),
                         "25 gadgets you'll love in 2026")

    def test_untokenised_copy_is_returned_untouched(self):
        self.assertEqual(self._expand("Gifts for every budget", 9), "Gifts for every budget")

    def test_the_token_check_is_what_marks_a_headline_as_counted(self):
        self.assertTrue(has_title_tokens("{count} gifts"))
        self.assertTrue(has_title_tokens("Gifts for {year}"))
        self.assertFalse(has_title_tokens("Gifts for every budget"))
        self.assertFalse(has_title_tokens(""))


class CountingTests(unittest.TestCase):
    def test_it_counts_what_the_page_will_actually_show(self):
        """Counted from the RESOLVED items, after members not published on the Site have been dropped, so
        the headline can never claim more than the page renders."""
        self.assertEqual(roundup_item_count(page(item_count=13), MANUAL), 13)

    def test_only_manual_collections_are_counted(self):
        """An `all` collection's membership moves when a PAGE publishes — a direction nothing re-renders
        from — so a number printed for it would go quietly wrong."""
        self.assertIsNone(roundup_item_count(page("c_all", 13), ALL_RULE))

    def test_a_page_with_no_grid_has_nothing_to_count(self):
        self.assertIsNone(roundup_item_count({"sections": [{"type": "hero"}]}, MANUAL))

    def test_several_manual_grids_sum(self):
        multi = {"sections": [grid("c_manual", 4), grid("c_manual", 5)]}
        self.assertEqual(roundup_item_count(multi, MANUAL), 9)


class AllFourSurfacesAgreeTests(unittest.TestCase):
    """The count must land everywhere or nowhere.

    `seo.title` feeds the `<title>`, `og:title` (the title up to the brand separator) and the
    `CollectionPage` name; the hero's `headline` IS the h1. A number that updated in three of the four
    would leave the page contradicting itself — the exact failure this feature exists to prevent, just
    moved inside one document.
    """

    def test_the_title_and_the_h1_get_the_same_number(self):
        doc = page(item_count=13)
        expand_roundup_titles(doc, MANUAL, year=2026)
        self.assertEqual(doc["seo"]["title"], "13 gift ideas for your mom")
        self.assertEqual(doc["sections"][0]["headline"], "13 gift ideas for your mom")

    def test_a_subheadline_is_expanded_too(self):
        doc = page()
        doc["sections"][0]["subheadline"] = "All under $60, picked in {year}"
        expand_roundup_titles(doc, MANUAL, year=2026)
        self.assertEqual(doc["sections"][0]["subheadline"], "All under $60, picked in 2026")

    def test_untokenised_pages_are_not_touched(self):
        doc = page(title="Gift ideas", headline="Gift ideas for your mom")
        before = (doc["seo"]["title"], doc["sections"][0]["headline"])
        expand_roundup_titles(doc, MANUAL, year=2026)
        self.assertEqual((doc["seo"]["title"], doc["sections"][0]["headline"]), before)

    def test_an_all_rule_page_still_publishes_clean_copy(self):
        """No count available, so the number is dropped — never left as a literal token on a live page."""
        doc = page("c_all", 13)
        expand_roundup_titles(doc, ALL_RULE, year=2026)
        self.assertEqual(doc["seo"]["title"], "Gift ideas for your mom")
        self.assertNotIn("{count}", doc["sections"][0]["headline"])

    def test_a_page_with_no_seo_block_does_not_explode(self):
        doc = {"sections": [{"type": "hero", "headline": "{count} gifts"}, grid("c_manual", 4)]}
        expand_roundup_titles(doc, MANUAL, year=2026)
        self.assertEqual(doc["sections"][0]["headline"], "4 gifts")


class HeadlinePatternTests(unittest.TestCase):
    """The patterns offered in the builder are STRUCTURES, not finished claims.

    The page this feature copies opens entries with lines like "you absolutely have to have". Shipping
    that as pre-filled copy would put our words in a tenant's mouth, and the claims are where their
    liability starts. We give the shape; they write the hook.
    """

    PATTERNS = RULES["roundup_headlines"]

    def test_every_pattern_is_counted(self):
        for pattern in self.PATTERNS:
            self.assertIn("{count}", pattern, pattern)

    def test_every_pattern_expands_without_leaving_a_token(self):
        for pattern in self.PATTERNS:
            for count in (1, 13, None):
                out = expand_title_tokens(pattern, count=count, year=2026)
                self.assertNotIn("{count}", out, (pattern, count))
                self.assertNotIn("{year}", out, (pattern, count))

    def test_a_single_item_never_reads_as_one_something(self):
        for pattern in self.PATTERNS:
            self.assertNotIn("1 ", expand_title_tokens(pattern, count=1, year=2026), pattern)

    def test_none_of_them_makes_a_claim_on_the_tenants_behalf(self):
        """`{things}` and `{audience}` are the tenant's words. A pattern that shipped an adjective would
        be us writing their copy."""
        for pattern in self.PATTERNS:
            lowered = pattern.lower()
            for word in ("insane", "amazing", "must-have", "absolutely", "incredible", "best-selling"):
                self.assertNotIn(word, lowered, pattern)
