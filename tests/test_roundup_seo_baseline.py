"""What a Roundup publishes when its goal says it is a search page (plans/ROUNDUP_PAGES.md).

The goal axis decides, and that is the point: `search_seo` unions in `structured_data`, the breadcrumb
and the prose/FAQ seeds, and every other goal composes exactly as it did. Nothing here forces SEO onto a
Roundup built for ads. What these tests pin is that CHOOSING the goal produces a baseline that does not
contradict the page -- found by auditing a real published Roundup, which came out with a `Product` node
claiming a price it never showed, a meta description reading "Browse 2 products.", the same heading twice
per entry, an outline its own checker rejected, and no dimensions on the one image every entry has.
"""

import copy
import json
import pathlib
import re
import unittest

from stripe_link.runtime.html import (
    _as_sentence,
    crop_url_dims,
    document_description,
    heading_outline_warnings,
    product_json_ld,
    render_page,
    responsive_img,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "schemas" / "examples" / name).read_text(encoding="utf-8"))


def _entry_offer(offer_id, name, headline=""):
    offer = fixture("offer-simple-coffee.json")
    offer.update({"offer_id": offer_id, "name": name})
    offer["presentation"] = {"headline": headline,
                             "hero_image_url": f"https://images.example.com/{offer_id}.webp"}
    offer["items"] = [{"product_id": f"prod_{offer_id}",
                       "selectable_prices": [{"price_id": f"price_{offer_id}", "quantity": 1,
                                              "label": "One"}],
                       "default_price_id": f"price_{offer_id}"}]
    return offer


def _product(product_id, name, category, description, price_id, selling_point=None):
    product = fixture("product-simple-coffee.json")
    product.update({"product_id": product_id, "name": name, "product_category": category,
                    "description": description})
    product["prices"] = [dict(product["prices"][0], price_id=price_id)]
    product["default_price_id"] = price_id
    if selling_point:
        product["selling_point"] = selling_point
    return product


ROUNDUP_OFFER = fixture("offer-simple-coffee.json")
ROUNDUP_OFFER.update({"offer_id": "o_round", "name": "Amazing Gift Ideas",
                      "product_intent": "lead_gen", "lead_capture_action": "roundup"})
ROUNDUP_OFFER["presentation"] = {"headline": "2 Amazing Gift Ideas for 2026",
                                 "subheadline": "These make great gifts!"}

PRODUCTS = {
    "prod_simple_coffee": _product("prod_simple_coffee", "Amazing Gift Ideas", "other",
                                   "A gift guide.", "price_simple_coffee"),
    "prod_o1": _product("prod_o1", "Security Mini Cam", "electronics",
                        "Protect your home with this easy camera.", "price_o1",
                        "See what happens on your property in your absence"),
    "prod_o2": _product("prod_o2", "Digital Marketing 101", "digital_download",
                        "Your sales will increase.", "price_o2"),
}


def roundup_page(goal="search_seo", heading=None):
    sections = [
        {"id": "brand", "type": "brand_label"},
        {"id": "hero", "type": "hero", "headline": "2 Amazing Gift Ideas for 2026",
         "subheadline": "These make great gifts!"},
        {"id": "grid", "type": "catalog_grid", "layout": "editorial",
         "items": [{"offer_id": "o1", "slug": "/security-mini-cam"},
                   {"offer_id": "o2", "slug": "/digital-marketing-101"}]},
        {"id": "sd", "type": "structured_data"},
    ]
    if heading is not None:
        sections[2]["heading"] = heading
    page = {"page_id": "pg1", "tenant_id": "tenant_demo", "offer_id": "o_round",
            "name": "Amazing Gift Ideas", "sections": sections}
    if goal:
        page["goal"] = goal
    return page


SITE = {"site_id": "s1",
        "organization": {"name": "Poliaxis Nutrition", "description": "Supplements and gifts."}}


def render(goal="search_seo", heading=None, headlines=("", ""), site=SITE):
    offers = {"o1": _entry_offer("o1", "Security Mini Cam", headlines[0]),
              "o2": _entry_offer("o2", "Digital Marketing 101", headlines[1]),
              "o_round": ROUNDUP_OFFER}
    return render_page(
        roundup_page(goal, heading), ROUNDUP_OFFER, copy.deepcopy(PRODUCTS), offers_by_id=offers,
        canonical_url="https://shop.example.com/amazing-gift-ideas", indexable=True,
        home_url="https://shop.example.com", site=site,
    )


def ld_blocks(html):
    out = []
    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        raw = match.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
        out.append(json.loads(raw))
    return out


def outline(html):
    body = html.split("<body>", 1)[-1]
    return [(int(level), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip())
            for level, text in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", body, re.S)]


class APageThatSellsNothingClaimsNoPriceTests(unittest.TestCase):
    """A Roundup published `Product` markup with `offers.price` and `availability: InStock`.

    Its composition excludes checkout_cta, offer_price_selector, price_highlight and product_details --
    "a price on the listing would be a second claim about money that can disagree with the one on the
    offer page" -- and then said exactly that second claim in the head, where nobody looks. The offer
    still carries items and prices, so `product_json_ld` found one and published it.
    """

    def test_a_roundup_emits_no_product_node(self):
        types = [block.get("@type") for block in ld_blocks(render())]
        self.assertNotIn("Product", types)

    def test_the_markup_it_does_emit_describes_the_list(self):
        """Dropping Product must not leave the page with nothing to say. CollectionPage/ItemList is what
        a roundup IS, and it was already being emitted beside the contradictory node."""
        types = [block.get("@type") for block in ld_blocks(render())]
        self.assertIn("CollectionPage", types)
        self.assertIn("BreadcrumbList", types)

    def test_the_whole_baseline_is_what_a_roundup_should_say(self):
        """The SEO goal's complete output: who publishes it, the site it belongs to, the list it IS, and
        where it sits. Four nodes that agree with each other and with the page -- and no fifth one
        claiming a sale. Pinned as a SET so a node added later has to be considered rather than noticed."""
        self.assertEqual([block.get("@type") for block in ld_blocks(render())],
                         ["Organization", "WebSite", "CollectionPage", "BreadcrumbList"])

    def test_every_lead_shape_is_covered_not_just_the_roundup(self):
        """None of them sell on the page they are on, so none may claim a price.

        Driven off LEAD_COMPOSITIONS rather than a list typed here, for two reasons: a name typed by
        hand that is not a real action falls through to DEFAULT_LEAD_COMPOSITION and the assertion
        passes without testing the shape it names, and a lead action added later is covered the day it
        is added instead of the day someone remembers this file.
        """
        from stripe_link.domain.composition import LEAD_COMPOSITIONS
        for action in LEAD_COMPOSITIONS:
            with self.subTest(action=action):
                offer = dict(ROUNDUP_OFFER, product_intent="lead_gen", lead_capture_action=action)
                self.assertEqual(product_json_ld({}, offer, PRODUCTS, {}), "")

    def test_a_transacting_page_still_emits_it(self):
        """The gate is the composition, not the absence of a price -- a checkout page must keep its
        Product markup, which is most of what this function exists for."""
        offer = fixture("offer-creatine-standard.json")
        product = fixture("product-creatine-gummies.json")
        markup = product_json_ld(fixture("page-creatine-standard.json"), offer,
                                 {product["product_id"]: product}, {})
        self.assertIn('"@type":"Product"', markup.replace(" ", ""))

    def test_a_tip_jar_is_not_caught_by_this(self):
        """It TAKES MONEY, so its markup should say so -- and it states a range rather than a price,
        which is the honest form. `is_lead_composition` is false for it, deliberately."""
        from stripe_link.domain.composition import is_lead_composition
        self.assertFalse(is_lead_composition({"product_intent": "tip_jar"}))


class TheDescriptionReadsTheHeadlineOnThePageTests(unittest.TestCase):
    """Every Roundup published "Browse 2 products." while its own h1 read "2 Amazing Gift Ideas for 2026".

    `is_offerless_page` is true for anything carrying a `catalog_grid` and every Roundup has one, so the
    description was built by `offerless_description` -- which looked for a `brand_hero`. A Roundup
    composes the ordinary `hero`, whose tagline field is `subheadline`, so both values came back empty
    and only the item count survived. The words were on the page; the function could not see them.
    """

    def test_the_hero_headline_leads(self):
        description = document_description(roundup_page(), ROUNDUP_OFFER, PRODUCTS)
        self.assertTrue(description.startswith("2 Amazing Gift Ideas for 2026"), description)

    def test_the_subheadline_is_the_tagline(self):
        self.assertIn("These make great gifts!",
                      document_description(roundup_page(), ROUNDUP_OFFER, PRODUCTS))

    def test_it_no_longer_collapses_to_the_count(self):
        self.assertNotEqual(document_description(roundup_page(), ROUNDUP_OFFER, PRODUCTS),
                            "Browse 2 products.")

    def test_a_storefronts_brand_hero_still_works(self):
        """The other hero. This function's original caller must be untouched by teaching it a second
        section type -- a storefront has no `hero` and must still read its `brand_hero`."""
        page = {"page_id": "p", "sections": [
            {"id": "h", "type": "brand_hero", "headline": "Probe Store", "tagline": "Good things"},
            {"id": "g", "type": "catalog_grid", "items": [{"offer_id": "o1", "slug": "/a"}]},
        ]}
        self.assertIn("Probe Store", document_description(page, {}, {}))
        self.assertIn("Good things", document_description(page, {}, {}))

    def test_the_tenants_own_description_still_wins(self):
        page = dict(roundup_page(), seo={"description": "My own words."})
        self.assertEqual(document_description(page, ROUNDUP_OFFER, PRODUCTS), "My own words.")


class TheDescriptionUsesTheHeadlinesOwnResolverTests(unittest.TestCase):
    """The first fix for "Browse N products." read the hero SECTION and shipped unchanged.

    A live Roundup on a custom domain still published "Browse 3 products." after it, because the hero
    section on that page is EMPTY -- the tenant never typed a headline there, so the h1 came from
    `offer.presentation` through `hero_copy`'s fallback. The fix had been written against a page built
    the other way and tested against a fixture built the same way, so it looked right and changed
    nothing where it mattered. Sharing `hero_copy` is what makes the description and the h1 incapable
    of disagreeing, which is the property actually wanted.
    """

    EMPTY_HERO = {"page_id": "p", "sections": [
        {"id": "hero", "type": "hero"},
        {"id": "g", "type": "catalog_grid",
         "items": [{"offer_id": "a", "slug": "/x"}, {"offer_id": "b", "slug": "/y"},
                   {"offer_id": "c", "slug": "/z"}]},
    ]}
    OFFER = {"offer_id": "o", "name": "Amazing Gift Ideas", "product_intent": "lead_gen",
             "lead_capture_action": "roundup",
             "presentation": {"headline": "Amazing Gift Ideas",
                              "subheadline": "These make great gifts!"}}

    def test_an_untouched_hero_reads_the_offer(self):
        self.assertEqual(document_description(self.EMPTY_HERO, self.OFFER, {}),
                         "Amazing Gift Ideas — These make great gifts! Browse 3 products.")

    def test_it_no_longer_collapses_to_the_count(self):
        self.assertNotEqual(document_description(self.EMPTY_HERO, self.OFFER, {}),
                            "Browse 3 products.")

    def test_a_token_reached_through_the_fallback_is_expanded(self):
        """`expand_roundup_titles` rewrites the hero SECTION at publish, so a headline reached through
        the offer never passed through it. Without expanding here the description would publish a
        literal "{count}" -- a regression this fix would otherwise have introduced on its own."""
        offer = dict(self.OFFER, presentation={"headline": "{count} Amazing Gift Ideas for {year}",
                                               "subheadline": "These make great gifts!"})
        description = document_description(self.EMPTY_HERO, offer, {})
        self.assertNotIn("{count}", description)
        self.assertNotIn("{year}", description)
        self.assertTrue(description.startswith("3 Amazing Gift Ideas for "), description)

    def test_the_pages_own_words_still_outrank_the_offer(self):
        """`hero_copy` is "the page's own words, else the offer's" and that order has to survive."""
        page = copy.deepcopy(self.EMPTY_HERO)
        page["sections"][0].update({"headline": "My Own Headline", "subheadline": "My own tagline."})
        self.assertEqual(document_description(page, self.OFFER, {}),
                         "My Own Headline — My own tagline. Browse 3 products.")

    def test_a_storefront_is_untouched(self):
        """A `brand_hero` has no offer behind it and its tagline field is `tagline`, so it keeps the
        plain section read rather than going through hero_copy."""
        page = {"page_id": "s", "sections": [
            {"id": "h", "type": "brand_hero", "headline": "Probe Store", "tagline": "Good things"},
            {"id": "g", "type": "catalog_grid", "items": [{"offer_id": "a", "slug": "/x"}]},
        ]}
        self.assertEqual(document_description(page, {}, {}), "Probe Store — Good things. Browse 1 product.")


class OneFullStopTests(unittest.TestCase):
    """"These make great gifts!" came out as "great gifts!." -- the segments appended "." and only a
    trailing period was stripped first. A Roundup's subheadline is marketing copy, so the mark it ends
    with is usually not a period."""

    def test_an_exclamation_is_kept_and_not_doubled(self):
        self.assertEqual(_as_sentence("These make great gifts!"), "These make great gifts!")

    def test_a_question_mark_is_kept(self):
        self.assertEqual(_as_sentence("Looking for a gift?"), "Looking for a gift?")

    def test_a_plain_fragment_gains_one(self):
        """`mark in "!?"` is TRUE for the empty string -- every Python substring test is -- so the first
        cut of this silently returned the fragment unpunctuated."""
        self.assertEqual(_as_sentence("Widgets from Probe Store"), "Widgets from Probe Store.")

    def test_an_existing_period_is_not_doubled(self):
        self.assertEqual(_as_sentence("Already done."), "Already done.")

    def test_an_ellipsis_collapses_to_one(self):
        self.assertEqual(_as_sentence("Trailing..."), "Trailing.")

    def test_nothing_in_nothing_out(self):
        self.assertEqual(_as_sentence("   "), "")
        self.assertEqual(_as_sentence(None), "")


class TheOutlineIsOneHeadingPerEntryTests(unittest.TestCase):
    """The published page read h1, then h3 h3 h3 h3 -- the same product name twice per entry, under an
    outline that skipped a level. `heading_outline_warnings` flagged the renderer's own output.

    Two causes. The card title was a fixed <h3> on the reasoning that it sits under the grid's section
    heading, which is OPTIONAL and which a Roundup leaves empty; and the prose and panel headlines take
    different defaults that both fall back to the product name when the entry's offer has no headline.
    """

    def test_the_renderers_own_checker_passes(self):
        self.assertEqual(heading_outline_warnings(render()), [])

    def test_a_headless_grid_puts_its_entries_at_h2(self):
        levels = [level for level, _ in outline(render())]
        self.assertEqual(levels[0], 1)
        self.assertEqual(levels[1:], [2, 2])

    def test_a_grid_with_a_heading_keeps_its_entries_under_it(self):
        """The old fixed level was right for THIS case, which is why it survived: h1, the grid's h2, then
        h3 entries. It has to stay right."""
        levels = [level for level, _ in outline(render(heading="Our picks"))]
        self.assertEqual(levels, [1, 2, 3, 3])
        self.assertEqual(heading_outline_warnings(render(heading="Our picks")), [])

    def test_the_product_name_is_not_printed_twice(self):
        names = [text for _, text in outline(render())]
        self.assertEqual(len(names), len(set(names)), names)

    def test_a_distinct_offer_headline_brings_the_panel_heading_back(self):
        """The two are meant to differ -- a sales line above, the product name in the ribbon. When they
        do, both are kept, and the panel sits one level under the title rather than beside it."""
        html = render(headlines=("Homeowners Are Trading In Their Doorbell Cams",
                                 "Watch Your Sales Improve"))
        self.assertEqual([level for level, _ in outline(html)], [1, 2, 3, 2, 3])
        self.assertIn("Security Mini Cam", html)
        self.assertEqual(heading_outline_warnings(html), [])

    def test_the_panel_drops_its_heading_not_the_prose_one(self):
        """The prose title carries the rank badge -- `.sl-catalog-title::before` is the counter -- so
        dropping that one would cost the number the whole layout is built around."""
        html = render()
        self.assertIn('class="sl-catalog-title"', html)
        self.assertNotIn('class="sl-ribbon-headline"', html)


class TheListIsMachineReadableTests(unittest.TestCase):
    """ItemList was already emitted for a catalog_grid; what it needed was the `structured_data` section,
    which only the SEO goal unions in. Nothing new was built for this -- these tests say so, so that a
    change to `collection_json_ld` cannot quietly stop covering the shape that most needs it."""

    def test_the_entries_are_an_itemlist(self):
        collection = next(b for b in ld_blocks(render()) if b.get("@type") == "CollectionPage")
        item_list = collection["mainEntity"]
        self.assertEqual(item_list["@type"], "ItemList")
        self.assertEqual(item_list["numberOfItems"], 2)

    def test_each_entry_carries_its_position_and_url(self):
        collection = next(b for b in ld_blocks(render()) if b.get("@type") == "CollectionPage")
        items = collection["mainEntity"]["itemListElement"]
        self.assertEqual([i["position"] for i in items], [1, 2])
        self.assertEqual([i["url"] for i in items],
                         ["https://shop.example.com/security-mini-cam",
                          "https://shop.example.com/digital-marketing-101"])

    def test_another_goal_gets_none_of_it(self):
        """THE GOAL DECIDES. A Roundup built for ads composes as it always did -- no structured_data
        section, so no JSON-LD. Forcing the SEO mechanics onto every Roundup is the thing this is not."""
        for goal in ("paid_ads", "minimal", ""):
            with self.subTest(goal=goal):
                page = roundup_page(goal)
                page["sections"] = [s for s in page["sections"] if s["type"] != "structured_data"]
                offers = {"o1": _entry_offer("o1", "Security Mini Cam"),
                          "o2": _entry_offer("o2", "Digital Marketing 101"), "o_round": ROUNDUP_OFFER}
                html = render_page(page, ROUNDUP_OFFER, copy.deepcopy(PRODUCTS), offers_by_id=offers,
                                   canonical_url="https://shop.example.com/x", indexable=True,
                                   home_url="https://shop.example.com")
                self.assertEqual(ld_blocks(html), [])


class ACropStatesItsOwnSizeTests(unittest.TestCase):
    """An entry's picture is cropped to a square, and a crop published with no width/height.

    `rendition_base` matches the fixed rendition names (small/medium/large/...), not
    `custom_<w>x<h>_<suffix>.<ext>`, so a cropped URL fell through to a full-URL sidecar lookup that
    nothing writes. The processor puts the output size in the filename
    (image-processing/src/onDemandResize.js), so no sidecar is needed to read it.
    """

    CROP = "https://images.juniorbay.com/products/0ZbA4VDDJ0i/custom_1600x1600_3767eef420.webp"

    def test_the_dimensions_come_off_the_filename(self):
        self.assertEqual(crop_url_dims(self.CROP), (1600, 1600))

    def test_a_non_square_crop_too(self):
        self.assertEqual(
            crop_url_dims("https://img.example.com/a/custom_1200x628_ab12.jpg"), (1200, 628))

    def test_a_plain_rendition_is_not_one(self):
        self.assertIsNone(crop_url_dims("https://img.example.com/a/medium.webp"))

    def test_an_arbitrary_url_is_not_one(self):
        self.assertIsNone(crop_url_dims("https://example.com/photo.png"))
        self.assertIsNone(crop_url_dims(""))
        self.assertIsNone(crop_url_dims(None))

    def test_a_zero_dimension_is_refused(self):
        """0x0 would emit width="0", which reserves nothing and tells a crawler something false."""
        self.assertIsNone(crop_url_dims("https://img.example.com/a/custom_0x0_z.webp"))

    def test_the_tag_carries_them(self):
        tag = responsive_img(self.CROP, "Security Mini Cam", sizes="22rem")
        self.assertIn('width="1600"', tag)
        self.assertIn('height="1600"', tag)

    def test_an_explicit_override_still_wins(self):
        tag = responsive_img(self.CROP, "Security Mini Cam", sizes="22rem", dims=(800, 450))
        self.assertIn('width="800"', tag)
        self.assertIn('height="450"', tag)
