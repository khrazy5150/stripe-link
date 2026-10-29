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
        self.assertIn("sl-catalog-cta", markup)
        self.assertIn("See Compact Desk Lamp", markup)

    def test_the_eyebrow_still_has_no_default(self):
        """The button is NAVIGATION -- the row goes to that page and it says so. An eyebrow is a CLAIM
        ("Supplies are limited"), and this plan has never put one of those in a tenant's mouth."""
        self.assertNotIn("sl-catalog-eyebrow", self._render())

    def test_the_button_is_named_from_the_offer_not_the_entry_headline(self):
        """A tenant writing an editorial headline would otherwise get a button reading
        "See Homeowners Are Trading in Their Doorbell Cams for This"."""
        markup = self._render(entry_headline={"pg1": "Homeowners Are Trading in Their Doorbell Cams"})
        self.assertIn("See Compact Desk Lamp", markup)

    def test_the_compact_row_gains_no_button(self):
        """The two layouts must stay visibly different, which is the whole reason this was reported."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        markup = html.render_catalog_grid(
            {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY]},
            OFFERS, {}, {})
        self.assertNotIn("sl-catalog-cta", markup)

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
        self.assertIn('<span class="sl-catalog-cta">', markup)
        self.assertEqual(markup.count("<a "), 1)

    def test_the_extras_are_editorial_only(self):
        """Offering a field in the builder that the chosen layout would not render is how a tenant comes
        to distrust the form. The compact row has nowhere to put an eyebrow or a button."""
        html._RENDER_STATE["home_url"] = "https://shop.example.com"
        section = {"type": "catalog_grid", "id": "s1", "layout": "listicle", "items": [self.ENTRY],
                   "entry_eyebrow": {"pg1": "Supplies are limited"}, "entry_cta": {"pg1": "Shop now"}}
        markup = html.render_catalog_grid(section, OFFERS, {}, {})
        self.assertNotIn("Supplies are limited", markup)
        self.assertNotIn("sl-catalog-cta", markup)

    def test_both_ordered_layouts_read_the_same_per_entry_pitch(self):
        """entry_copy predates this and belongs to BOTH; switching layout to compare must not lose it."""
        for layout in ("listicle", "editorial"):
            html._RENDER_STATE["home_url"] = "https://shop.example.com"
            markup = html.render_catalog_grid(
                {"type": "catalog_grid", "id": "s1", "layout": layout, "items": [self.ENTRY],
                 "entry_copy": {"pg1": "Why this one made the list"}}, OFFERS, {}, {})
            self.assertIn("Why this one made the list", markup, layout)


class EditorialBorrowsTheRibbonTests(unittest.TestCase):
    """The proportions are the page ribbon's, deliberately.

    The author built his mock-up out of page ribbons and content blocks. The first cut of this layout
    guessed its own smaller numbers -- an 18rem image, a 2.2rem headline -- and he reported, twice, that
    the layout "looks the same": it read as a row with a button rather than an entry that argues.

    Borrowing the element he pointed at is both closer to what he drew and one less set of magic numbers
    to keep in step, so these tests assert the two stay equal rather than merely asserting values.
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

    def test_the_eyebrow_is_the_ribbon_eyebrow(self):
        ribbon = self._rule(".sl-ribbon-eyebrow")
        entry = self._rule(".sl-catalog-eyebrow")
        for part in ("font-size:1.3rem", "letter-spacing:0.08em", "text-transform:uppercase"):
            self.assertIn(part, ribbon, part)
            self.assertIn(part, entry, part)

    def test_the_image_column_is_the_ribbon_image_column(self):
        self.assertIn("minmax(0,22rem)", self._rule(".sl-page-ribbon.is-image_left"))
        self.assertIn("minmax(0,22rem)", self._rule(".sl-layout-editorial .sl-catalog-row .sl-catalog-card"))

    def test_the_image_fills_its_column_rather_than_naming_a_width(self):
        """Two numbers for one measurement is how a column and the thing inside it come to disagree."""
        self.assertIn("width:100%", self._rule(".sl-layout-editorial .sl-catalog-row .sl-catalog-card img"))

    def test_the_panel_matches_the_ribbon_and_beats_the_compact_row(self):
        card = self._rule(".sl-layout-editorial .sl-catalog-row .sl-catalog-card")
        self.assertIn("padding:3.2rem", card)
        self.assertIn("border-radius:1.4rem", card)
        # The compact row must stay compact, or the two layouts collapse into one again.
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
