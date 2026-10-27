"""Collection layouts: grid, masonry, listicle (plans/ROUNDUP_PAGES.md §3, P1).

`Collection.presentation` held exactly one key — `heading` — and every collection rendered as the same
uniform grid. A Roundup needs an ordered single column, and the old dot-net front page's masonry is worth
having back as a browsing layout, so `layout` joins `heading` on the same object and travels the same road
to the renderer.

The invariant these tests exist to protect is CRAWLABILITY. The grid's cards are the internal links that
make the catalog hierarchy work, and a layout is only a container: whatever the arrangement, every item
with a slug must still come out as a real `<a href>`. A layout that quietly stopped emitting anchors would
look perfect on screen and cost the Site its internal linking.
"""

import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_collection
from stripe_link.runtime import html
from stripe_link.runtime.publishing import resolve_category_grids

OFFERS = {
    "o1": {"offer_id": "o1", "name": "Desk Lamp",
           "presentation": {"headline": "Compact Desk Lamp", "hero_image_url": "https://img/lamp.jpg"}},
    "o2": {"offer_id": "o2", "name": "Travel Organizer",
           "presentation": {"headline": "Travel Organizer"}},
}
ITEMS = [{"offer_id": "o1", "slug": "/desk-lamp"}, {"offer_id": "o2", "slug": "/organizer"}]
COLLECTION_BASE = {"schema_version": 1, "document_type": "collection", "tenant_id": "t1",
                   "collection_id": "col_1", "site_id": "site_1", "name": "Gift picks", "rule": "manual"}


def _render(layout=None, items=None):
    html._RENDER_STATE["home_url"] = "https://shop.example.com"
    section = {"type": "catalog_grid", "id": "s1", "heading": "Gift picks",
               "items": ITEMS if items is None else items}
    if layout is not None:
        section["layout"] = layout
    return html.render_catalog_grid(section, OFFERS, {}, {})


class LayoutValidationTests(unittest.TestCase):
    def test_the_three_layouts_are_accepted(self):
        for layout in ("grid", "masonry", "listicle"):
            doc = dict(COLLECTION_BASE, presentation={"layout": layout})
            validate_collection(doc)   # must not raise

    def test_absent_is_allowed_so_every_existing_collection_still_validates(self):
        validate_collection(dict(COLLECTION_BASE, presentation={"heading": "Gift picks"}))
        validate_collection(dict(COLLECTION_BASE))

    def test_an_unknown_layout_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_collection(dict(COLLECTION_BASE, presentation={"layout": "carousel"}))


class LayoutReachesTheSectionTests(unittest.TestCase):
    """Layout travels the same road as `heading`, with the same precedence."""

    SITE = {"pages": {"/desk-lamp": {"page_id": "p1", "offer_id": "o1"},
                      "/organizer": {"page_id": "p2", "offer_id": "o2"}}}

    def _resolve(self, collection_presentation, section_extra=None):
        page = {"sections": [dict({"type": "catalog_grid", "collection_id": "col_1"}, **(section_extra or {}))]}
        collection = {"rule": "manual", "members": ["p1", "p2"], "presentation": collection_presentation}
        resolve_category_grids(page, self.SITE, {"col_1": collection})
        return page["sections"][0]

    def test_the_collection_decides_how_its_members_are_arranged(self):
        self.assertEqual(self._resolve({"layout": "listicle"})["layout"], "listicle")

    def test_the_section_wins_when_it_says_anything(self):
        section = self._resolve({"layout": "listicle"}, {"layout": "grid"})
        self.assertEqual(section["layout"], "grid")

    def test_silence_on_both_leaves_it_unset(self):
        # Unset renders as `grid` — the renderer owns the default, so nothing has to write one in.
        self.assertNotIn("layout", self._resolve({"heading": "Gift picks"}))


class EveryLayoutStaysCrawlableTests(unittest.TestCase):
    """THE INVARIANT. A layout is a container; it must never change whether an item is a link.

    These cards are the internal links that make the catalog hierarchy work. A layout that rendered
    beautiful unlinked tiles would look finished and quietly cost the Site its linking.
    """

    def test_all_three_layouts_emit_one_anchor_per_item(self):
        for layout in ("grid", "masonry", "listicle"):
            self.assertEqual(_render(layout).count('<a class="sl-catalog-card"'), 2, layout)

    def test_the_hrefs_are_the_site_slugs_in_every_layout(self):
        for layout in ("grid", "masonry", "listicle"):
            markup = _render(layout)
            self.assertIn("/desk-lamp", markup, layout)
            self.assertIn("/organizer", markup, layout)

    def test_an_item_with_no_slug_is_an_unlinked_tile_not_a_dead_link(self):
        items = [{"offer_id": "o1", "slug": ""}]
        for layout in ("grid", "masonry", "listicle"):
            markup = _render(layout, items=items)
            self.assertIn('<div class="sl-catalog-card"', markup, layout)
            self.assertNotIn("<a class=", markup, layout)


class LayoutMarkupTests(unittest.TestCase):
    def test_grid_is_the_default_when_nothing_says_otherwise(self):
        self.assertIn('data-layout="grid"', _render(None))

    def test_an_unknown_layout_falls_back_to_grid_rather_than_rendering_nothing(self):
        """Validation refuses a bad value on the way in, so reaching the renderer means something
        bypassed it — a hand-edited document, an older artifact. Falling back beats a blank section."""
        self.assertIn('data-layout="grid"', _render("bogus"))

    def test_the_listicle_puts_its_order_in_the_markup(self):
        """A real <ol>, for the same reason `render_numbered_list` uses one: the sequence is announced by
        assistive technology, and the visible number is a CSS counter carrying no content of its own."""
        markup = _render("listicle")
        self.assertIn('<ol class="sl-catalog-list">', markup)
        self.assertEqual(markup.count('<li class="sl-catalog-row">'), 2)
        self.assertIn("counter-increment:sl-catalog", "".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES))

    def test_grid_and_masonry_do_not_claim_an_order(self):
        for layout in ("grid", "masonry"):
            markup = _render(layout)
            self.assertNotIn("<ol", markup, layout)
            self.assertIn(f'class="sl-catalog-cards sl-catalog-{layout}"', markup, layout)

    def test_the_section_still_carries_its_original_classes_and_ids(self):
        # Existing CSS and the builder both key off these; a layout must add, never replace.
        markup = _render("masonry")
        self.assertIn('class="sl-catalog-grid sl-layout-masonry"', markup)
        self.assertIn('data-section-id="s1"', markup)
        self.assertIn('data-section-type="catalog_grid"', markup)


class MasonryCssTests(unittest.TestCase):
    """Ported from the old dot-net front page: pure CSS multi-column, no JS."""

    CSS = ""

    @classmethod
    def setUpClass(cls):
        cls.CSS = "".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)

    def test_it_is_multi_column_at_five_across(self):
        self.assertIn("column-count:5", self.CSS)

    def test_tiles_do_not_split_across_columns(self):
        self.assertIn("break-inside:avoid", self.CSS)

    def test_it_steps_down_to_a_single_column_on_a_phone(self):
        for width in ("1180px", "900px", "650px", "420px"):
            self.assertIn(f"max-width:{width}", self.CSS, width)

    def test_the_square_crop_is_dropped_so_heights_can_vary(self):
        """Variable tile heights ARE the layout. Forcing every image square would produce a uniform grid
        with extra steps."""
        self.assertIn(".sl-catalog-masonry .sl-catalog-card img{aspect-ratio:auto}", self.CSS)

    def test_the_hover_lift_respects_reduced_motion(self):
        self.assertIn("prefers-reduced-motion:reduce", self.CSS)
