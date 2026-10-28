"""A product's gallery in the hero, and what a hero slide STANDS FOR.

Two things that were tangled together. The hero carousel does double duty -- it is a product's photo
gallery on a single-item offer, and a product SWITCHER on a multi-item one -- and the island told them
apart by counting: the settled slide's ordinal was read as the conversion-target index.

That only worked because the renderer threw a single product's gallery away whenever the offer had tiers,
so the counts could never differ. Restoring the gallery breaks the assumption, so the mapping is now
DECLARED on each slide instead of inferred from its position.
"""

import unittest

from stripe_link.runtime.html import (
    offer_uses_grouped_item_media,
    render_hero_media,
    render_page_interactions_script,
)

IMAGES = [f"https://cdn.example.com/{n}.jpg" for n in range(1, 7)]


def product(product_id="p1", images=None, name="Security Mini Cam"):
    # Real prices: a listicle slide is DROPPED when its item has no resolvable single-unit price, so a
    # price-less fixture would silently assert against an empty carousel.
    return {"product_id": product_id, "name": name,
            "images": images if images is not None else IMAGES,
            "default_price_id": f"price_{product_id}",
            "prices": [{"price_id": f"price_{product_id}", "unit_amount": 2995, "currency": "usd"}]}


def offer(items):
    return {"offer_id": "o1", "name": "Offer", "items": items}


def one_item(selectable=0):
    item = {"product_id": "p1", "price_id": "price_1"}
    if selectable:
        item["selectable_prices"] = [{"price_id": f"price_{i}"} for i in range(1, selectable + 1)]
    return offer([item])


def hero(offer_doc, products, section=None):
    return render_hero_media(section or {"id": "hero-media"}, offer_doc,
                             {p["product_id"]: p for p in products}, {})


def slide_indices(html):
    import re

    return [int(value) for value in re.findall(r'sl-hero-slide" data-conv-index="(\d+)"', html)]


class TheGalleryComesBackTests(unittest.TestCase):
    """A single product shows all of its photos, tiers or no tiers."""

    def test_a_plain_single_product_shows_every_image(self):
        self.assertEqual(len(slide_indices(hero(one_item(), [product()]))), 6)

    def test_tiers_no_longer_collapse_the_gallery(self):
        """THE BUG. A product sold as a 1-pack and a 4-pack is still ONE product with one conversion
        target, but `any(selectable_prices)` treated it as a multi-product offer and kept only the first
        image -- on exactly the offers most likely to have a real gallery. The builder meanwhile listed
        all six as AUTO rows, so it promised a carousel the page never built."""
        self.assertEqual(len(slide_indices(hero(one_item(selectable=2), [product()]))), 6)

    def test_the_gate_now_means_what_its_name_says(self):
        self.assertFalse(offer_uses_grouped_item_media(one_item()))
        self.assertFalse(offer_uses_grouped_item_media(one_item(selectable=3)))
        self.assertTrue(offer_uses_grouped_item_media(
            offer([{"product_id": "p1", "price_id": "price_p1"},
                   {"product_id": "p2", "price_id": "price_p2"}])))

    def test_several_products_still_get_one_slide_each(self):
        """UNCHANGED, and it must be: the tier blocks and the BNPL island read the slide index as the item
        index, so a second photo of product one would otherwise push product two's slide out of place.

        Two landing items DERIVE as a listicle (`landing_presentation`: N opportunities -> carousel), so
        this is the listicle branch -- the one the whole index coupling was built for -- rather than the
        grouped-media fallback, which a stored `offer_type` is now the only way to reach."""
        two = offer([{"product_id": "p1", "price_id": "price_p1"},
                     {"product_id": "p2", "price_id": "price_p2"}])
        html = hero(two, [product("p1"), product("p2", images=["https://cdn.example.com/b.jpg"])])
        self.assertEqual(len(slide_indices(html)), 2)

    def test_an_explicit_list_still_wins(self):
        """The tenant's own media list overrides the product's -- unchanged, and it is why the AUTO rows
        are now hidden in the builder as soon as anything is stored."""
        section = {"id": "hero-media", "images": ["https://cdn.example.com/own.jpg"]}
        html = hero(one_item(selectable=2), [product()], section)
        self.assertIn("own.jpg", html)
        self.assertEqual(len(slide_indices(html)), 1)


class WhatASlideStandsForTests(unittest.TestCase):
    """The mapping is declared per slide, so slide COUNT and target COUNT may now differ safely."""

    def test_a_gallery_declares_one_target_for_every_slide(self):
        """Swiping between photos of the same product must not look like switching product. If these were
        ordinals, slide two would re-price the BNPL island against the second TIER CARD -- it indexes
        `.sl-price-option` by this number -- and would hide a listicle's tier block outright."""
        self.assertEqual(slide_indices(hero(one_item(selectable=2), [product()])), [0, 0, 0, 0, 0, 0])

    def test_a_switcher_declares_the_item_index(self):
        two = offer([{"product_id": "p1", "price_id": "price_p1"},
                     {"product_id": "p2", "price_id": "price_p2"}])
        html = hero(two, [product("p1"), product("p2", images=["https://cdn.example.com/b.jpg"])])
        self.assertEqual(slide_indices(html), [0, 1])

    def test_every_slide_carries_the_attribute(self):
        """A slide with none falls back to its ordinal, which is right for a page published before this
        existed and wrong for anything rendered now -- so nothing rendered now may omit it."""
        html = hero(one_item(), [product()])
        self.assertEqual(html.count("sl-hero-slide"), html.count("data-conv-index"))


class TheIslandReadsTheDeclarationTests(unittest.TestCase):
    SCRIPT = ""

    @classmethod
    def setUpClass(cls):
        page = {"sections": [{"id": "h", "type": "hero_media",
                              "images": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"]}]}
        cls.SCRIPT = render_page_interactions_script(page)

    def test_it_prefers_the_declared_index(self):
        self.assertIn("dataset.convIndex", self.SCRIPT)

    def test_it_falls_back_to_the_ordinal(self):
        self.assertIn("slideIndex", self.SCRIPT)

    def test_the_emit_is_range_checked_too(self):
        """`applyTarget` already returned early for an out-of-range index, but the emit beside it did not,
        so every listener was told to switch to a target that does not exist. On a listicle that hides the
        tier block and leaves the Add button with nothing to read."""
        self.assertIn("index < convTargets.length", self.SCRIPT)
