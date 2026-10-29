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

import pathlib
import re
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


class TheRowIsOneGridTests(unittest.TestCase):
    """A listicle row is a three-column grid: number, image, words. The CHILD COUNT has to match.

    Reported 2026-10-28 against a live Roundup. The card put its title, pitch and price in as three
    separate grid children, so a row carrying an image held five items for three columns and wrapped: the
    title sat beside the image while the pitch and the price dropped onto a second line under the number,
    and a long title ran outside the card.

    Nothing caught it because every existing test asked whether the ANCHOR and the ORDER were right, and
    both were. The markup was correct and the layout was wrong, which is the same way the masonry column
    order is easy to miss.
    """

    def _card(self, layout="listicle"):
        markup = _render(layout)
        return markup.split('<a class="sl-catalog-card"', 1)[1].split("</a>", 1)[0]

    def test_the_words_are_one_child_not_three(self):
        card = self._card()
        self.assertEqual(card.count('<div class="sl-catalog-body">'), 1)

    def test_the_card_has_exactly_the_children_the_columns_expect(self):
        """Image + body. The number is a ::before, so three grid items for three columns. A new paragraph
        added outside the body would break the row again, and this is what says so."""
        card = self._card()
        top_level = re.findall(r'\n        <(\w+)', card)
        self.assertEqual(top_level, ["img", "div"], card)

    def test_the_title_and_price_moved_INSIDE_the_body(self):
        card = self._card()
        body = card.split('<div class="sl-catalog-body">', 1)[1]
        self.assertIn("sl-catalog-title", body)

    def test_every_layout_carries_the_same_card_content(self):
        """The property the wrapper was added to every layout to keep: a layout is a container, and two
        layouts rendering different DATA is the drift this renderer exists to prevent."""
        bodies = {layout: self._card(layout).count('<div class="sl-catalog-body">')
                  for layout in ("grid", "masonry", "listicle")}
        self.assertEqual(set(bodies.values()), {1}, bodies)

    def test_the_body_cannot_be_pushed_out_of_its_column(self):
        css = "\n".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn("min-width:0", css.split(".sl-catalog-body{", 1)[1].split("}", 1)[0])

    def test_the_row_aligns_to_the_top_of_the_words(self):
        css = "\n".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        row = css.split(".sl-catalog-row .sl-catalog-card{", 1)[1].split("}", 1)[0]
        self.assertIn("align-items:start", row)


class EditorialLayoutTests(unittest.TestCase):
    """The Roundup's real shape: the same ordered sequence, given room to ARGUE.

    The author built it by hand out of content blocks and page ribbons to show what it should look like,
    and then asked for it to be generated. It is a LAYOUT rather than generated elements, and the reasons
    are concrete: `page_ribbon` caps at two per page, generated elements would not grow when a product
    joins the Collection, and `{count}` counts the GRID — so a hand-assembled page would carry a number
    that stops matching the list, which is the exact failure the counted headline exists to prevent.
    """

    ENTRY = {"offer_id": "o1", "slug": "/desk-lamp", "page_id": "pg1"}

    def _render(self, **overrides):
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "layout": "editorial", "items": [self.ENTRY]}
        section.update(overrides)
        return html.render_catalog_grid(section, OFFERS, {}, {})

    def test_it_is_a_valid_collection_layout(self):
        validate_collection({**COLLECTION_BASE, "members": ["p1"],
                             "presentation": {"layout": "editorial"}})

    def test_it_keeps_the_order_in_the_markup(self):
        """Still an <ol>. The sequence is the whole point of a ranked roundup, and an editorial entry does
        not get to be less crawlable or less announceable than a compact one."""
        markup = self._render()
        self.assertIn("<ol class=\"sl-catalog-list\">", markup)
        self.assertIn('<li class="sl-catalog-row">', markup)

    def test_it_scopes_its_styling_off_the_section_rather_than_a_second_class(self):
        self.assertIn('class="sl-catalog-grid sl-layout-editorial"', self._render())

    def test_a_bare_entry_still_gets_its_button(self):
        """THE BUG. The first cut defaulted nothing, so an editorial entry with no fields filled rendered
        the same four things a compact row does -- image, title, pitch, price -- only bigger. The author
        set the layout, saw no button, and reported "no change in layout". The fancy layout has to BE
        fancy before anyone writes a word: the formula is that the software fills the data in and the
        tenant edits the wording."""
        markup = self._render()
        self.assertIn("sl-ribbon-cta", markup)
        self.assertIn("Shop Now", markup)

    def test_the_eyebrow_defaults_to_nothing_when_there_is_no_product_to_read(self):
        """It defaults to the product's CATEGORY, which is the tenant's own data. With no product resolved
        there is nothing to say, and an empty eyebrow element is not rendered at all -- the earlier rule
        that an eyebrow must never be invented still holds, it is just no longer invented FROM NOTHING."""
        self.assertNotIn("sl-ribbon-eyebrow", self._render())

    def test_the_button_label_is_fixed_rather_than_built_from_a_name(self):
        """It used to read "See {offer name}", which got unreadable the moment the name was long -- and a
        tenant writing an editorial headline risked "See Homeowners Are Trading in Their Doorbell Cams for
        This". Every button on a Roundup does the same thing, so every button may say the same thing."""
        markup = self._render(entry_headline={"pg1": "Homeowners Are Trading in Their Doorbell Cams"})
        self.assertIn('<span class="sl-ribbon-cta">Shop Now</span>', markup)
        self.assertNotIn("See Homeowners", markup)
        self.assertNotIn("See Compact Desk Lamp", markup)

    def test_the_compact_row_gains_no_button(self):
        """The two layouts must stay visibly different, which is the whole reason this was reported."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        markup = html.render_catalog_grid(
            {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY]},
            OFFERS, {}, {})
        self.assertNotIn("sl-ribbon-cta", markup)

    def test_the_tenants_words_win_where_they_wrote_them(self):
        markup = self._render(entry_eyebrow={"pg1": "Supplies are limited"},
                              entry_headline={"pg1": "Homeowners Are Switching"},
                              entry_cta={"pg1": "Shop the mini cam"})
        self.assertIn("Supplies are limited", markup)
        self.assertIn("Homeowners Are Switching", markup)
        self.assertIn("Shop the mini cam", markup)

    def test_a_blank_override_falls_back_rather_than_blanking_the_entry(self):
        markup = self._render(entry_headline={"pg1": "   "})
        self.assertIn("Compact Desk Lamp", markup)

    def test_the_button_is_a_span_not_a_nested_anchor(self):
        """The card IS the link. An <a> inside an <a> is invalid markup that browsers silently un-nest,
        which would lift the button out of the card and break the row."""
        markup = self._render(entry_cta={"pg1": "Shop now"})
        self.assertIn('<span class="sl-ribbon-cta">', markup)
        self.assertEqual(markup.count("<a "), 1)

    def test_the_extras_are_editorial_only(self):
        """Offering a field in the builder that the chosen layout would not render is how a tenant comes
        to distrust the form. The compact row has nowhere to put an eyebrow or a button."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY],
                   "entry_eyebrow": {"pg1": "Supplies are limited"}, "entry_cta": {"pg1": "Shop now"}}
        markup = html.render_catalog_grid(section, OFFERS, {}, {})
        self.assertNotIn("Supplies are limited", markup)
        self.assertNotIn("sl-ribbon-cta", markup)

    def test_both_ordered_layouts_read_the_same_per_entry_pitch(self):
        """entry_copy predates this and belongs to BOTH; switching layout to compare must not lose it."""
        for layout in ("listicle", "editorial"):
            html._RENDER_STATE["home_url"] = "https://shop.example.com"
            markup = html.render_catalog_grid(
                {"type": "catalog_grid", "id": "s1", "layout": layout, "items": [self.ENTRY],
                 "entry_copy": {"pg1": "Why this one made the list"}}, OFFERS, {}, {})
            self.assertIn("Why this one made the list", markup, layout)


class TheEntryIsFilledFromTheProductTests(unittest.TestCase):
    """Every editorial box now starts from the product behind the entry.

    The first cut defaulted only the headline, arguing that an eyebrow and a button label are CLAIMS the
    tenant must write. That argument was wrong about where the words come from: a category and a product
    name are the tenant's own data, typed once on the product, and making them retype it on every page
    that lists the product is the self-service form this builder exists to replace. The author named the
    formula directly -- "the software will fill in the data first, and the tenant can modify the wording."

    The one thing still not invented is a REASON. `selling_point` is a field the tenant fills in, and when
    it is empty the entry falls back to "Available now": a fact about stock that claims nothing about the
    product. That is the whole of what we may say in a seller's voice unasked.
    """

    ENTRY = {"offer_id": "o3", "slug": "/mini-cam", "page_id": "pg3"}
    OFFER = {"o3": {"offer_id": "o3", "name": "Mini Cam Offer",
                    "items": [{"product_id": "pr1", "price_id": "pc1"}],
                    "presentation": {"headline": "Homeowners Are Trading In Their Doorbell Cams",
                                     "subheadline": "Protect your home and your loved ones."}}}
    PRODUCT = {"pr1": {"name": "Security Mini Cam", "product_category": "home_security",
                       "description": "4pcs Mini Wireless Security Camera, 2.4GHz WiFi, night vision.",
                       "selling_point": "Catches what a doorbell cam misses, indoors and at night.",
                       "images": ["https://img/cam.jpg"]}}

    def _render(self, products=None, **overrides):
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "layout": "editorial", "items": [self.ENTRY]}
        section.update(overrides)
        return html.render_catalog_grid(section, self.OFFER,
                                        self.PRODUCT if products is None else products, {})

    def test_the_eyebrow_is_the_products_category(self):
        self.assertIn('<p class="sl-ribbon-eyebrow">home security</p>', self._render())

    def test_a_stored_category_key_is_humanised(self):
        """Categories are stored either as a typed label ("Electronics") or as a key
        ("dietary_supplement"). The second must not publish with its underscores showing."""
        self.assertNotIn("home_security", self._render())

    def test_the_headline_is_the_PRODUCTS_name_not_the_offers_sales_line(self):
        """An offer headline is a sales line; an entry in a ranked list is announcing which product this
        is. Reading `presentation.headline` here would title entry 1 "Homeowners Are Trading In Their
        Doorbell Cams", which says nothing about what is being ranked."""
        markup = self._render()
        self.assertIn("Security Mini Cam</h3>", markup)
        # Title-cased on the way out ("In" -> "in"), so assert the form that actually publishes.
        self.assertNotIn("Homeowners Are Trading in Their Doorbell Cams</h3>", markup)

    def test_the_supporting_line_is_the_products_selling_point(self):
        self.assertIn('<p class="sl-ribbon-body">Catches what a doorbell cam misses, indoors and at night.</p>',
                      self._render())

    def test_a_product_with_no_selling_point_gets_the_bland_fallback(self):
        bare = {"pr1": {"name": "Security Mini Cam", "product_category": "home_security"}}
        self.assertIn('<p class="sl-ribbon-body">Available now</p>', self._render(products=bare))

    def test_the_pitch_prefers_the_pages_own_subheadline_over_the_description(self):
        """Unchanged ladder, and deliberately so: a description is often pasted from a supplier and
        written for a marketplace listing, while the subheadline is the pitch for THIS page."""
        markup = self._render()
        self.assertIn("Protect your home and your loved ones.", markup)
        self.assertNotIn("4pcs Mini Wireless Security Camera", markup)

    def test_the_description_is_the_last_resort_for_the_pitch(self):
        offer = {"o3": {**self.OFFER["o3"], "presentation": {"headline": "Mini Cam"}}}
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        markup = html.render_catalog_grid(
            {"type": "catalog_grid", "id": "s1", "layout": "editorial", "items": [self.ENTRY]},
            offer, self.PRODUCT, {})
        self.assertIn("4pcs Mini Wireless Security Camera", markup)

    def test_the_tenants_words_beat_the_products_everywhere(self):
        """The defaults are a STARTING POINT. A value written in the builder is the whole reason these
        are editable boxes rather than a fixed rendering of the product."""
        markup = self._render(entry_eyebrow={"pg3": "Supplies are limited"},
                              entry_headline={"pg3": "The One We Keep Recommending"},
                              entry_copy={"pg3": "Why this one made the list"},
                              entry_support={"pg3": "Runs for a year on one charge"},
                              entry_cta={"pg3": "See the mini cam"})
        for written in ("Supplies are limited", "The One We Keep Recommending", "Why this one made the list",
                        "Runs for a year on one charge", "See the mini cam"):
            self.assertIn(written, markup, written)
        self.assertNotIn("home security", markup)
        self.assertNotIn("Shop Now", markup)

    def test_the_compact_row_gains_none_of_it(self):
        """The two ordered layouts must stay visibly different -- that difference is what was reported
        missing in the first place. A compact row has nowhere to put a supporting line or a button."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        markup = html.render_catalog_grid(
            {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY]},
            self.OFFER, self.PRODUCT, {})
        for absent in ("sl-ribbon-body", "sl-ribbon-cta", "sl-ribbon-eyebrow", "Available now"):
            self.assertNotIn(absent, markup, absent)

    def test_an_offer_with_no_product_still_renders_an_entry(self):
        """Nothing in the ladder may become required. A Roundup can list a page whose product was
        archived, and the entry must still be a link rather than a hole in the list."""
        markup = self._render(products={})
        self.assertIn('<a class="sl-catalog-card"', markup)
        self.assertIn("Homeowners Are Trading in Their Doorbell Cams", markup)  # the offer's own, as before
        self.assertIn("Available now", markup)


class TheNumberIsABadgeBesideTheHeadlineTests(unittest.TestCase):
    """The author asked for "a circle number (similar to how the numbered list shows it) ... next to the
    headline". It was a bare numeral on its own line above the title, which reads as a stray figure
    rather than as a rank.

    The counter is incremented by the ROW and drawn by the TITLE. That works because a CSS counter is
    visible to a descendant, and it is what puts the badge on the heading's own line so the two wrap
    together instead of stacking.
    """

    CSS = "\n".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)

    def test_the_row_still_increments_the_counter(self):
        self.assertIn(".sl-catalog-row{counter-increment:sl-catalog", self.CSS)

    def test_the_card_no_longer_draws_it(self):
        rule = self.CSS.split(".sl-layout-editorial .sl-catalog-row .sl-catalog-card::before{", 1)[1].split("}", 1)[0]
        self.assertEqual(rule, "content:none")

    def test_the_title_draws_it_as_a_circle(self):
        rule = self.CSS.split(".sl-layout-editorial .sl-catalog-title::before{", 1)[1].split("}", 1)[0]
        self.assertIn("content:counter(sl-catalog)", rule)
        self.assertIn("border-radius:50%", rule)
        self.assertIn("inline-grid", rule)  # inline, so it sits ON the heading line

    def test_it_borrows_the_numbered_lists_own_badge(self):
        """Same element the author pointed at. Two hand-tuned circles that drift apart is the failure
        mode; the numbers here must look like the numbers there."""
        badge = self.CSS.split(".sl-numbered-item::before{", 1)[1].split("}", 1)[0]
        mine = self.CSS.split(".sl-layout-editorial .sl-catalog-title::before{", 1)[1].split("}", 1)[0]
        for shared in ("width:3.6rem", "height:3.6rem", "border-radius:50%",
                       "background:var(--sl-badge-bg,var(--sl-accent))",
                       "color:var(--sl-badge-ink,#fff)", "font-size:1.8rem"):
            self.assertIn(shared, badge, shared)
            self.assertIn(shared, mine, shared)

    def test_a_rule_separates_one_entry_from_the_next(self):
        """"Add a dividing line", which the author ticked by hand on every content block in his mock-up.
        Intrinsic to the layout rather than a tick of its own: an entry that is prose plus a panel needs a
        boundary, or the next headline reads as part of the panel above it."""
        rule = self.CSS.split(".sl-layout-editorial .sl-catalog-row + .sl-catalog-row{", 1)[1].split("}", 1)[0]
        self.assertIn("border-top:1px solid var(--sl-content-border)", rule)

    def test_the_rule_never_lands_above_the_first_entry(self):
        """`+` and not `:not(:first-child)` for a reason worth stating: a line above entry 1 would read as
        a separator from the page heading, which is not what it separates."""
        self.assertNotIn(".sl-layout-editorial .sl-catalog-row:first-child", self.CSS)

    def test_the_divider_uses_the_same_token_the_content_block_does(self):
        divided = self.CSS.split(".sl-content-blocks--divided .sl-content-block{", 1)[1].split("}", 1)[0]
        self.assertIn("var(--sl-content-border)", divided)


class TheBuilderShowsWhatWouldPublishTests(unittest.TestCase):
    """The defaults are written INTO the editor's boxes, not shown as placeholders.

    The author asked for exactly this: "Prefill all of these and make them editable for tenants to
    change." A placeholder cannot be edited into -- it vanishes the moment anything is typed and there is
    no way to keep part of it -- so prefilling is what makes "modify the wording" a real option.

    The renderer keeps its own copy of the ladder regardless, because an entry added to the Collection
    after the modal was last open has never been through the dashboard's seeder. Two copies of one rule is
    a drift risk, so these tests pin them to each other.

    Source assertions, because this is Vue. The behaviour they stand for is opening the grid editor.
    """

    BUILDER = (pathlib.Path(__file__).resolve().parents[1]
               / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
    COMPOSER = (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "composables" / "pageComposer.js").read_text(encoding="utf-8")

    def _defaults(self):
        return self.BUILDER.split("function roundupEntryDefaults(page)", 1)[1].split("\n}", 1)[0]

    def test_the_boxes_are_filled_when_the_grid_editor_opens(self):
        self.assertIn('if (row?.editor === "catalog_grid") seedRoundupEntryCopy();', self.BUILDER)

    def test_an_entry_the_tenant_has_touched_is_never_reseeded(self):
        """What keeps this a starting point rather than a default that keeps reasserting itself. Without
        it, a tenant who deletes an eyebrow finds it back the next time they open the modal."""
        block = self.BUILDER.split("function seedRoundupEntryCopy()", 1)[1].split("\n}", 1)[0]
        self.assertIn("if (ROUNDUP_ENTRY_FIELDS.some(authored)) continue;", block)

    def test_it_seeds_every_box_the_renderer_reads(self):
        fields = self.BUILDER.split("const ROUNDUP_ENTRY_FIELDS = [", 1)[1].split("]", 1)[0]
        for field in ("entry_copy", "entry_eyebrow", "entry_headline", "entry_support", "entry_cta"):
            self.assertIn(f'"{field}"', fields, field)

    def test_every_seeded_box_is_also_saved(self):
        """A field the seeder fills and the composer drops is a value the tenant edits and then loses."""
        block = self.COMPOSER.split("export function catalogGridSection(state)", 1)[1].split("\n}", 1)[0]
        for field in ("entry_copy", "entry_eyebrow", "entry_headline", "entry_support", "entry_cta"):
            self.assertIn(f"{field}: authored(grid.{field})", block, field)

    def test_every_saved_box_is_read_back(self):
        """Write-only fields are lost on reload, which reads as the builder discarding the tenant's work."""
        block = self.COMPOSER.split("export function offerlessState(page)", 1)[1].split("\n  },", 1)[0]
        for field in ("entry_copy", "entry_eyebrow", "entry_headline", "entry_support", "entry_cta"):
            self.assertIn(f"{field}: {{ ...(grid.{field} || {{}}) }}", block, field)

    def test_the_dashboards_ladder_matches_the_renderers(self):
        """The four values both sides derive. Spelled out here so that changing one and not the other
        fails a test rather than publishing something the tenant never saw in the form."""
        defaults = self._defaults()
        self.assertIn("presentation.subheadline || product.description", defaults)
        self.assertIn("product.product_category", defaults)
        self.assertIn("product.name || presentation.headline", defaults)
        self.assertIn('product.selling_point || "Available now"', defaults)
        self.assertIn('entry_cta: "Shop Now"', defaults)

    def test_the_renderer_holds_the_same_four(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        block = source.split("def render_catalog_grid(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('product.get("product_category") or ""', block)
        self.assertIn('product.get("name") or ""', block)
        self.assertIn('product.get("selling_point") or ""', block)
        self.assertIn('"Available now"', block)
        self.assertIn('or "Shop Now"', block)

    def test_the_supporting_box_is_offered_in_the_form(self):
        self.assertIn("builder.catalog_grid.entry_support[entry.page_id]", self.BUILDER)


class TheEntryIsProseThenAPanelTests(unittest.TestCase):
    """What the author actually drew, after two cuts that missed it.

    He assembled the shape by hand as a CONTENT BLOCK followed by a PAGE RIBBON, and said so plainly on
    the third try: "the headline and body of a content block pre-filled before the page ribbon is shown.
    This gives the tenant the opportunity to modify the headline and the paragraph before presenting a
    call to action."

    Folding all of it into one ribbon-shaped row -- cut two -- reads as a product tile however generously
    it is spaced, because the prose has nowhere to be. The prose is what a Roundup is FOR; the panel is
    the call to action it earns.
    """

    ENTRY = {"offer_id": "o1", "slug": "/desk-lamp", "page_id": "pg1"}
    # A COMPLETE offer, unlike the module fixture: an entry only grows a pitch when it has a subheadline
    # to fall back to, and only grows a price when the offer resolves to one. Asserting where those land
    # needs them to exist.
    PRICED = {"o1": {"offer_id": "o1", "name": "Desk Lamp",
                     "presentation": {"headline": "Compact Desk Lamp",
                                      "subheadline": "Warm light, no glare, folds flat.",
                                      "hero_image_url": "https://img/lamp.jpg"},
                     "items": [{"product_id": "p1", "price_id": "pr1"}]}}
    PRODUCTS = {"p1": {"product_id": "p1", "name": "Desk Lamp",
                       "images": ["https://img/lamp.jpg"],
                       "default_price_id": "pr1",
                       "prices": [{"price_id": "pr1", "unit_amount": 4200, "currency": "usd"}]}}

    def _entry(self, **overrides):
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "layout": "editorial", "items": [self.ENTRY]}
        section.update(overrides)
        markup = html.render_catalog_grid(section, self.PRICED, self.PRODUCTS, {})
        return markup.split('<a class="sl-catalog-card"', 1)[1].split("</a>", 1)[0]

    def test_the_prose_comes_before_the_panel(self):
        entry = self._entry()
        self.assertLess(entry.index("sl-catalog-title"), entry.index("sl-page-ribbon"))
        self.assertLess(entry.index("sl-catalog-pitch"), entry.index("sl-page-ribbon"))

    def test_the_image_moved_INSIDE_the_panel(self):
        """In the compact row the image is a sibling of the words. Here it belongs to the call to action."""
        entry = self._entry()
        panel = entry.split('<div class="sl-page-ribbon is-image_left">', 1)[1]
        self.assertIn("<img", panel)
        self.assertNotIn("<img", entry.split('<div class="sl-page-ribbon is-image_left">', 1)[0])

    def test_the_call_to_action_sits_with_the_image_not_with_the_prose(self):
        """Asserted as "not in the prose half" rather than "price is in the panel": the price only
        renders when `resolve_offer` succeeds, and a fixture that fails to resolve would make this pass
        for the wrong reason. The structural claim is where things land, not whether all of them exist."""
        entry = self._entry()
        prose, panel = entry.split('<div class="sl-page-ribbon is-image_left">', 1)
        self.assertIn("sl-ribbon-cta", panel)
        for belongs_below in ("sl-ribbon-cta", "sl-catalog-price", "sl-ribbon-eyebrow"):
            self.assertNotIn(belongs_below, prose, belongs_below)

    def test_the_headline_and_paragraph_are_the_tenants_to_rewrite(self):
        """The whole reason for the split: these are PRE-FILLED, then edited."""
        entry = self._entry(entry_headline={"pg1": "Homeowners Are Switching"},
                            entry_copy={"pg1": "Because now you can set one up in three minutes."})
        self.assertIn("Homeowners Are Switching", entry)
        self.assertIn("Because now you can set one up in three minutes.", entry)

    def test_both_are_pre_filled_when_the_tenant_writes_nothing(self):
        """This fixture's product is named "Desk Lamp" while the offer heads its landing page with
        "Compact Desk Lamp" -- which is why the headline reads the product. An offer headline is a sales
        line; an entry in a ranked list is saying which product this is."""
        entry = self._entry()
        self.assertIn("Desk Lamp", entry)                  # headline <- the PRODUCT's name
        self.assertIn("sl-ribbon-cta", entry)             # button   <- "Shop Now"

    def test_the_compact_row_keeps_its_old_shape(self):
        """Two layouts, and the quiet one must not inherit the loud one's structure."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        markup = html.render_catalog_grid(
            {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY]},
            OFFERS, {}, {})
        self.assertNotIn("sl-page-ribbon", markup)
        row = markup.split('<a class="sl-catalog-card"', 1)[1].split("</a>", 1)[0]
        self.assertLess(row.index("<img"), row.index("sl-catalog-body"))


def _render_editorial_entry():
    """One editorial entry with a product behind it, for the markup assertions below."""
    html._RENDER_STATE["home_url"] = "https://shop.example.com"
    offers = {"o9": {"offer_id": "o9", "name": "Mini Cam", "items": [{"product_id": "p9", "price_id": "pc9"}],
                     "presentation": {"headline": "Mini Cam", "subheadline": "Protect your home."}}}
    products = {"p9": {"name": "Security Mini Cam", "product_category": "Electronics",
                       "images": ["https://img/cam.jpg"], "selling_point": "Sees what a doorbell cam misses."}}
    return html.render_catalog_grid(
        {"type": "catalog_grid", "id": "s1", "layout": "editorial",
         "items": [{"offer_id": "o9", "slug": "/cam", "page_id": "pg9"}]}, offers, products, {})


class EditorialUsesTheRibbonItselfTests(unittest.TestCase):
    """The panel IS a page ribbon -- the element, not a copy of its numbers.

    Three cuts of this got progressively closer and all three were re-implementations. The last one
    hand-rolled a `.sl-catalog-panel` carrying the ribbon's grid, gap, padding, radius and background
    typed out again, and tests here asserted those values matched. They did. The duplicate still shipped
    a bug, because a copy is defined by what it leaves out: it never set `color`, so every word in the
    panel inherited the card's surrounding <a> and published in the browser's VISITED-LINK purple.

    The author's report named the cause exactly -- "you're NOT using the same elements as the Page
    Ribbon ... it seems like you re-invented the wheel instead of reusing the existing elements."

    So these tests no longer check that two sets of numbers agree. They check that there is only one set.
    """

    CSS = "\n".join(html.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)

    def _rule(self, selector):
        return self.CSS.split(selector + "{", 1)[1].split("}", 1)[0]

    def test_the_headline_is_the_ribbon_headline(self):
        ribbon = self._rule(".sl-ribbon-headline")
        entry = self._rule(".sl-layout-editorial .sl-catalog-title")
        for part in ("font-size:clamp(2rem,4vw,2.8rem)", "line-height:1.2"):
            self.assertIn(part, ribbon, part)
            self.assertIn(part, entry, part)

    def test_the_body_copy_is_the_ribbon_body(self):
        ribbon = self._rule(".sl-ribbon-body")
        entry = self._rule(".sl-layout-editorial .sl-catalog-pitch")
        for part in ("font-size:1.6rem", "line-height:1.55", "opacity:0.85"):
            self.assertIn(part, ribbon, part)
            self.assertIn(part, entry, part)

    def test_the_panel_carries_the_ribbons_own_classes(self):
        """The whole fix, asserted on the markup: the entry opts into `.sl-page-ribbon` rather than
        naming a private class that has to be kept in step with it by hand."""
        markup = _render_editorial_entry()
        self.assertIn('<div class="sl-page-ribbon is-image_left">', markup)
        for part in ("sl-ribbon-media", "sl-ribbon-copy", "sl-ribbon-eyebrow", "sl-ribbon-body",
                     "sl-ribbon-cta"):
            self.assertIn(part, markup, part)

    def test_the_duplicate_is_gone_rather_than_merely_unused(self):
        """A dead copy left in the stylesheet is the next person's source of truth."""
        self.assertNotIn("sl-catalog-panel", self.CSS)
        self.assertNotIn("sl-catalog-eyebrow", self.CSS)
        self.assertNotIn("sl-catalog-support", self.CSS)
        self.assertNotIn("sl-catalog-cta", self.CSS)

    def test_THE_BUG_the_panel_sets_a_colour(self):
        """What the duplicate omitted and what the element supplies.

        The panel lives inside the card's <a>, so any text in it that does not state a colour inherits
        the anchor's -- which the browser paints visited-purple on a page the visitor has been to. This
        is the one property that made the difference visible on a real page, so it gets its own test."""
        self.assertIn("color:var(--sl-section-ink,var(--sl-card-text,var(--sl-text)))",
                      self._rule(".sl-page-ribbon"))

    def test_no_text_in_the_panel_floats_without_one(self):
        """Nothing inside may re-introduce the hole by overriding the inherited colour with nothing. The
        ribbon's copy classes deliberately state no colour of their own -- they take the panel's."""
        for selector in (".sl-ribbon-eyebrow", ".sl-ribbon-body"):
            self.assertNotIn("color:", self._rule(selector), selector)

    def test_the_button_takes_the_accent_safe_ink(self):
        """`.sl-ribbon-cta` derives its ink from the section accent so a tenant cannot colour the button
        into invisibility. The hand-rolled copy used a fixed gradient and `--sl-cta-text` instead, which
        is a second answer to a question the ribbon had already answered."""
        rule = self._rule(".sl-ribbon-cta")
        self.assertIn("var(--sl-section-accent-ink,var(--sl-badge-ink,#fff))", rule)

    def test_the_image_column_is_the_ribbons_because_it_IS_the_ribbons(self):
        self.assertIn("minmax(0,22rem)", self._rule(".sl-page-ribbon.is-image_left"))

    def test_the_responsive_collapse_is_inherited_not_restated(self):
        """The ribbon already collapses to one column at 700px. The duplicate restated that at 650px --
        two breakpoints for one element, which is how a page comes to look broken at 680px."""
        self.assertNotIn("@media (max-width:650px){.sl-page-ribbon", self.CSS)
        self.assertIn(".sl-page-ribbon.is-image_left,.sl-page-ribbon.is-compact{grid-template-columns:minmax(0,1fr)}",
                      self.CSS)

    def test_what_is_NOT_inherited_is_stated_once_and_scoped_to_a_row(self):
        """Three genuine differences, and each is a thing the ribbon cannot know from inside a ranked
        list: the panel follows prose rather than standing alone, its images must match each other down
        the list, and the whole row is one link so the hover lift belongs to the panel."""
        rule = self._rule(".sl-catalog-row .sl-page-ribbon")
        self.assertIn("margin-top:1.6rem", rule)
        self.assertIn("transition:", rule)
        square = ".sl-catalog-row .sl-ribbon-media:not(.sl-cropped) img"
        self.assertIn("aspect-ratio:1/1", self._rule(square))
        self.assertIn("transform:translateY(-2px)",
                      self._rule(".sl-layout-editorial a.sl-catalog-card:hover .sl-page-ribbon"))

    def test_only_the_PANEL_is_tinted(self):
        """The prose sits on the page, not in a box. A card around the headline and paragraph is what made
        the first two cuts read as a product tile however generously they were spaced."""
        card = self._rule(".sl-layout-editorial .sl-catalog-row .sl-catalog-card")
        self.assertIn("background:transparent", card)
        self.assertIn("border:0", card)
        panel = self._rule(".sl-page-ribbon")
        self.assertIn("border-radius:1.4rem", panel)
        self.assertIn("background:var(--sl-section-bg,var(--sl-card))", panel)

    def test_the_compact_row_stays_compact(self):
        """Or the two layouts collapse into one again, which is the whole complaint."""
        self.assertIn("12rem", self._rule(".sl-catalog-row .sl-catalog-card"))

    def test_editorial_outranks_the_compact_row(self):
        """Three classes beat two, so the editorial rules win wherever they overlap. Asserted because the
        whole bug was 'the layout looks the same' and a specificity slip reproduces it exactly."""
        compact = ".sl-catalog-row .sl-catalog-card"
        editorial = ".sl-layout-editorial .sl-catalog-row .sl-catalog-card"
        self.assertEqual(editorial.count("."), compact.count(".") + 1)


class TheCountTickTests(unittest.TestCase):
    """The tick writes the TOKEN, so there is no second piece of state to disagree with the headline.

    Author: type "Amazing Gift Ideas", tick both, publish "2 Amazing Gift Ideas for 2026". Source
    assertions, because this is Vue — the behaviour they stand for is that the checkbox is checked exactly
    when the token is present.
    """

    BUILDER = (pathlib.Path(__file__).resolve().parents[1]
               / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def test_the_checkbox_state_is_derived_from_the_headline(self):
        self.assertIn("get: () => COUNT_TOKEN.test(builder.headline", self.BUILDER)
        self.assertIn("get: () => YEAR_TOKEN.test(builder.headline", self.BUILDER)

    def test_ticking_inserts_and_unticking_removes(self):
        block = self.BUILDER.split("const headlineCountsItems", 1)[1].split("});", 1)[0]
        self.assertIn("`{count} ${text}`", block)
        self.assertIn('replace(/\\{count\\}\\s*/gi, "")', block)

    def test_removing_the_year_takes_its_connector_with_it(self):
        """"...you'll love in {year}" must not leave a dangling "in"."""
        block = self.BUILDER.split("const headlineShowsYear", 1)[1].split("});", 1)[0]
        self.assertIn("(?:for|in)", block)

    def test_the_tokens_are_matched_case_INSENSITIVELY(self):
        """The builder title-cases headlines as they are typed and turned `{count}` into `{Count}`, which
        the expander's lowercase pattern no longer matched -- so a live page published the literal token.
        Both halves are fixed: the caser leaves placeholders alone, and the server tolerates the ones
        already stored, so those pages heal on their next publish without anyone retyping."""
        from stripe_link.domain.composition import expand_title_tokens, has_title_tokens

        stored = "{Count} Amazing Gifts Ideas for {Year}"
        self.assertTrue(has_title_tokens(stored))
        self.assertEqual(expand_title_tokens(stored, count=2, year=2026),
                         "2 Amazing Gifts Ideas for 2026")

    def test_the_title_caser_leaves_a_placeholder_alone(self):
        caser = (pathlib.Path(__file__).resolve().parents[1]
                 / "dashboard" / "src" / "utils" / "titleCase.js").read_text(encoding="utf-8")
        self.assertIn("PLACEHOLDER_TOKEN", caser)
        self.assertIn("if (PLACEHOLDER_TOKEN.test(word)) return word;", caser)

    def test_a_new_roundup_starts_editorial(self):
        self.assertIn('presentation: { layout: "editorial" }', self.BUILDER)


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


class PerEntryPitchTests(unittest.TestCase):
    """The paragraph beside each entry (plans/ROUNDUP_PAGES.md open question 2, resolved).

    Optional, with a fallback, because "very little design" is the goal: a tenant who writes nothing still
    gets a working page. Keyed by PAGE rather than offer, because the tenant picked a page and two pages
    can serve the same offer -- a seasonal variant, a second language -- and the pitch belongs to the page.
    """

    OFFERS = {
        "o1": {"offer_id": "o1", "name": "Lamp",
               "presentation": {"headline": "Desk Lamp", "subheadline": "Folds flat, charges by USB."},
               "items": [{"product_id": "pr1"}]},
        "o2": {"offer_id": "o2", "name": "Bag", "presentation": {"headline": "Travel Bag"},
               "items": [{"product_id": "pr2"}]},
    }
    PRODUCTS = {"pr1": {"product_id": "pr1", "description": "Product one description."},
                "pr2": {"product_id": "pr2", "description": "Product two description."}}
    ITEMS = [{"offer_id": "o1", "slug": "/lamp", "page_id": "p1"},
             {"offer_id": "o2", "slug": "/bag", "page_id": "p2"}]

    def _pitches(self, layout="listicle", entry_copy=None):
        import re
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "items": self.ITEMS, "layout": layout,
                   "entry_copy": entry_copy or {}}
        markup = html.render_catalog_grid(section, self.OFFERS, self.PRODUCTS, {})
        return re.findall(r'sl-catalog-pitch">([^<]*)', markup)

    def test_authored_copy_wins(self):
        self.assertEqual(self._pitches(entry_copy={"p1": "The one my desk needed.", "p2": "Fits a laptop."}),
                         ["The one my desk needed.", "Fits a laptop."])

    def test_writing_nothing_falls_back_to_the_pages_own_words(self):
        """Offer subheadline, then the product description — the same ladder `hero_copy` climbs, so an
        entry reads the way its own page's hero does."""
        self.assertEqual(self._pitches(),
                         ["Folds flat, charges by USB.", "Product two description."])

    def test_one_authored_entry_does_not_suppress_the_others_fallback(self):
        self.assertEqual(self._pitches(entry_copy={"p1": "Authored."}),
                         ["Authored.", "Product two description."])

    def test_the_card_layouts_carry_no_pitch(self):
        """A card is a glance and a row is a read. Grid and masonry are unchanged by this."""
        for layout in ("grid", "masonry"):
            self.assertEqual(self._pitches(layout=layout), [], layout)

    def test_copy_is_keyed_by_page_not_offer(self):
        # Keyed by offer_id, this would match and render. It must not.
        self.assertEqual(self._pitches(entry_copy={"o1": "Wrong key."})[0],
                         "Folds flat, charges by USB.")

    def test_the_pitch_is_escaped(self):
        self.assertEqual(self._pitches(entry_copy={"p1": "Under <$60> & tidy"})[0],
                         "Under &lt;$60&gt; &amp; tidy")
