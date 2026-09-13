"""The link-in-bio identity header: a centred avatar, the creator's name, and a slogan.

Built 2026-09-13 from the linkcloud/Lola Greiner reference the author supplied: hero image, avatar overlapping
its BOTTOM CENTRE, name, one-line slogan, then the social row. Three additions, and the through-line is that
not every tenant is a business -- most creators are promoting themselves, so the brand mark has to be
optional and a person's name has to be able to take its place.
"""
import pathlib
import unittest

from stripe_link.domain.documents import (
    HERO_TAGLINE_MAX_LENGTH,
    DocumentValidationError,
    validate_page_document,
)
from stripe_link.runtime import html as html_module

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def _page(**hero):
    return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
            "name": "P", "offer_id": "o1", "route": {"slug": "p"},
            "sections": [{"id": "hm", "type": "hero_media", **hero}]}


class PlacementTests(unittest.TestCase):
    def test_bottom_centre_is_a_placement(self):
        self.assertIn("overlay_bottom", html_module.AVATAR_PLACEMENTS)
        self.assertEqual(html_module.avatar_placement({"avatar_placement": "overlay_bottom"}), "overlay_bottom")
        validate_page_document(_page(avatar_placement="overlay_bottom"))

    def test_it_overhangs_like_the_bottom_left_one(self):
        # Same edge, same overhang, so it reuses .has-avatar -- the class that reserves the room the circle
        # hangs into. Without it the avatar collides with whatever follows the hero.
        html_module._RENDER_PREFERENCES.clear()
        html_module._RENDER_PREFERENCES["avatar_url"] = "https://img.example/a.webp"
        try:
            markup = html_module.render_hero_media(
                {"id": "hm", "images": ["https://img.example/h.webp"], "avatar_placement": "overlay_bottom"},
                {}, {})
        finally:
            html_module._RENDER_PREFERENCES.clear()
        self.assertIn("has-avatar", markup)
        self.assertNotIn("has-avatar-top", markup)
        self.assertIn("sl-avatar--overlay_bottom", markup)

    def test_the_css_centres_it(self):
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-avatar-wrap.sl-avatar--overlay_bottom{left:50%;transform:translateX(-50%)}", css)


class IdentityBlockTests(unittest.TestCase):
    def setUp(self):
        html_module._RENDER_PREFERENCES.clear()

    def tearDown(self):
        html_module._RENDER_PREFERENCES.clear()

    def test_nothing_renders_unless_it_is_switched_on(self):
        # Opt-in: most pages are selling something and want the product's headline, not a person's name.
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        self.assertEqual(html_module.render_hero_identity({"tagline": "be kind"}), [])

    def test_the_name_is_derived_never_stored(self):
        # Same rule as the avatar and the brand label: renaming yourself updates every page, instead of
        # leaving each one frozen at whatever was true the day it was made.
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        markup = "\n".join(html_module.render_hero_identity({"show_identity": True}))
        self.assertIn("Lola Greiner", markup)
        # ...and the builder writes only the switch and the slogan into the section -- never the name itself.
        written = BUILDER.split("show_identity: builder.show_identity", 1)[1].split("});", 1)[0]
        for frozen in ("display_name", "owner_name", "identity_name"):
            self.assertNotIn(frozen, written, frozen)

    def test_it_falls_back_to_the_signup_name(self):
        # display_name is copied in at publish from the owner's user profile. A tenant that has not published
        # since that shipped has only the signup-time owner block, and a name is better than a blank.
        html_module._RENDER_PREFERENCES["owner"] = {"first_name": "Keith", "last_name": "De Costa"}
        self.assertEqual(html_module.tenant_display_name(), "Keith De Costa")

    def test_the_copied_name_wins_over_the_signup_one(self):
        # Because the signup block is never updated: profile.py edits the USER profile and does not touch it.
        html_module._RENDER_PREFERENCES["owner"] = {"first_name": "Keith", "last_name": "De Costa"}
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        self.assertEqual(html_module.tenant_display_name(), "Lola Greiner")

    def test_the_slogan_is_the_pages_own(self):
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        markup = "\n".join(html_module.render_hero_identity({"show_identity": True, "tagline": "be kind"}))
        self.assertIn("be kind", markup)

    def test_the_name_is_not_a_second_h1(self):
        # The brand mark already carries the page's H1 on a link hub; a heading here would give it two, which
        # is exactly what plans/SEMANTIC_HTML.md exists to prevent.
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        markup = "\n".join(html_module.render_hero_identity({"show_identity": True, "tagline": "be kind"}))
        self.assertNotIn("<h1", markup)
        self.assertNotIn("<h2", markup)


class TaglineCapTests(unittest.TestCase):
    def test_one_cap_not_two(self):
        # Two constants that must agree is how a value ends up enforced at 40 in one place and 60 in another,
        # with the renderer clipping a string the validator accepted.
        self.assertIs(html_module.TAGLINE_MAX_LENGTH, HERO_TAGLINE_MAX_LENGTH)
        self.assertIn(f"const HERO_TAGLINE_MAX = {HERO_TAGLINE_MAX_LENGTH};", BUILDER)

    def test_a_long_slogan_is_refused(self):
        validate_page_document(_page(tagline="x" * HERO_TAGLINE_MAX_LENGTH))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(_page(tagline="x" * (HERO_TAGLINE_MAX_LENGTH + 1)))

    def test_it_can_never_wrap(self):
        # The cap makes wrapping rare; this makes it impossible, including for a value saved before the cap.
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        tagline = [line for line in css.splitlines() if "sl-hero-identity-tagline" in line][0]
        self.assertIn("white-space:nowrap", tagline)
        self.assertIn("text-overflow:ellipsis", tagline)


class BuilderTests(unittest.TestCase):
    def test_hiding_the_brand_uses_the_existing_override(self):
        # Not a second way to switch brand_label off. Two mechanisms for one state is how they come to
        # disagree -- the Page Sections panel and this switch now describe the same override.
        block = BUILDER.split("const brandLabelHidden = computed(", 1)[1][:400]
        self.assertIn('isSectionEnabled("brand_label")', block)
        self.assertIn('toggleSection("brand_label"', block)

    def test_the_hide_switch_is_not_inverted_against_its_label(self):
        # A switch labelled "hide" that must be turned OFF to hide is a puzzle.
        block = BUILDER.split("const brandLabelHidden = computed(", 1)[1][:400]
        self.assertIn('get: () => !isSectionEnabled("brand_label")', block)

    def test_the_slogan_input_is_capped_and_counts_down(self):
        self.assertIn(':maxlength="HERO_TAGLINE_MAX"', BUILDER)
        self.assertIn("characters left", BUILDER)

    def test_the_slogan_only_appears_once_the_block_is_on(self):
        self.assertIn('v-if="builder.show_identity" class="offer-field"', BUILDER)


if __name__ == "__main__":
    unittest.main()


class LayoutTests(unittest.TestCase):
    """The identity block is a SIBLING of the hero section, not a child of it.

    Reported 2026-09-13: with the name and slogan on, they rendered BEHIND the avatar and the avatar lost its
    bottom-centre position. Both from one cause. The avatar is absolutely positioned against .sl-hero-media,
    and .has-avatar reserves the room it overhangs into with a margin BELOW that section -- so a block placed
    INSIDE the section rendered into the figure's flow (under the image, behind the avatar) and grew the
    section, which moved the avatar's `bottom` anchor down with it.
    """

    def setUp(self):
        html_module._RENDER_PREFERENCES.clear()
        html_module._RENDER_PREFERENCES.update(
            {"avatar_url": "https://img.example/a.webp", "display_name": "Lola Greiner"})

    def tearDown(self):
        html_module._RENDER_PREFERENCES.clear()

    def _media(self, **extra):
        return html_module.render_hero_media(
            {"id": "hm", "images": ["https://img.example/h.webp"],
             "avatar_placement": "overlay_bottom", "show_identity": True, **extra}, {}, {})

    def test_it_renders_outside_the_hero_section(self):
        markup = self._media(tagline="be kind")
        self.assertGreater(markup.index("sl-hero-identity"), markup.index("</section>"))

    def test_the_avatar_still_anchors_to_the_hero(self):
        # The avatar stays INSIDE the section -- it is positioned against it. Only the identity block moved.
        markup = self._media(tagline="be kind")
        self.assertLess(markup.index("sl-avatar-wrap"), markup.index("</section>"))

    def test_the_overhang_is_still_reserved(self):
        self.assertIn("has-avatar", self._media())

    def test_a_carousel_hero_places_it_the_same_way(self):
        # Two branches build the hero, and the bug would have been fixed in one of them.
        markup = html_module.render_hero_media(
            {"id": "hm", "images": ["https://img.example/a.webp", "https://img.example/b.webp"],
             "avatar_placement": "overlay_bottom", "show_identity": True}, {}, {})
        self.assertGreater(markup.index("sl-hero-identity"), markup.index("</section>"))


class HeadingOwnerTests(unittest.TestCase):
    """Exactly one H1, decided in one place.

    Reported 2026-09-13: hiding the brand name produced a page-health warning ("no main heading") on a page
    type where the tenant had done nothing wrong. The brand mark had been carrying the H1; hiding it left the
    page with none, while the visible heading -- the creator's name -- was a <p>.

    The candidates render in different places and none can see the others, so render_page decides and each
    reads the verdict.
    """

    def tearDown(self):
        html_module._RENDER_STATE.pop("h1_owner", None)
        html_module._RENDER_PREFERENCES.clear()

    def test_the_name_takes_the_h1_when_the_brand_is_hidden(self):
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        html_module._RENDER_STATE["h1_owner"] = "identity"
        markup = "\n".join(html_module.render_hero_identity({"show_identity": True}))
        self.assertIn("<h1 class=\"sl-hero-identity-name\">Lola Greiner</h1>", markup)

    def test_it_stays_a_paragraph_when_something_else_owns_the_heading(self):
        html_module._RENDER_PREFERENCES["display_name"] = "Lola Greiner"
        for owner in ("hero", "brand_label", ""):
            html_module._RENDER_STATE["h1_owner"] = owner
            markup = "\n".join(html_module.render_hero_identity({"show_identity": True}))
            self.assertIn("<p class=\"sl-hero-identity-name\">", markup, owner)

    def test_the_styling_does_not_depend_on_the_tag(self):
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-hero-identity-name,h1.sl-hero-identity-name{", css)

    def test_a_page_with_the_brand_hidden_and_a_name_has_exactly_one_h1(self):
        import re

        page = {"page_id": "p1", "tenant_id": "t", "name": "My Links", "route": {"slug": "x"},
                "sections": [{"id": "hm", "type": "hero_media", "images": ["https://img.example/h.webp"],
                              "avatar_placement": "overlay_bottom", "show_identity": True},
                             {"id": "lf", "type": "legal_footer"}],
                "composition": {"overrides": {"brand_label": {"enabled": False}}}}
        offer = {"offer_id": "o", "status": "active", "items": [{"product_id": "p", "price_id": "pr"}],
                 "presentation": {}, "product_intent": "lead_gen", "lead_capture_action": "social_redirect"}
        products = {"p": {"product_id": "p", "name": "My Links", "default_price_id": "pr",
                          "prices": [{"price_id": "pr", "unit_amount": 0, "currency": "usd"}]}}
        html = html_module.render_page(
            page, offer, products, checkout_url="https://c", api_base_url="https://a",
            preferences={"avatar_url": "https://img.example/a.webp", "display_name": "Lola Greiner"},
            kind="published")
        body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
        self.assertEqual(re.findall(r"<h1[^>]*>(.*?)</h1>", body, re.S), ["Lola Greiner"])
        # ...and therefore no page-health warning for the tenant to puzzle over.
        self.assertEqual(html_module.heading_outline_warnings(html), [])


class BrandSuppressionTests(unittest.TestCase):
    """Hiding the brand has to hide it EVERYWHERE, not move it.

    Reported 2026-09-13: switching the brand off -- from the Hero editor or from Page Sections, either way --
    made the store name reappear at the top of the page in a different style.

    It was the storefront site header. Its rule was "if the page composes its own brand mark, drop mine, so
    there are not two". Sound, until you notice brand_label is in EVERY composition, so `not in body_sections`
    means the tenant TURNED IT OFF -- and the rule then read that as "this page has no brand mark" and
    helpfully supplied one. The switch did not remove the brand; it relocated it.

    The header's brand exists for pages that own no mark at all -- an offer-less storefront or category page.
    So the question it asks is now whether the page OWNS a brand mark, not whether one is currently visible.
    """

    SITE = {"site_id": "s", "hosting": {"type": "platform", "platform_hostname": "poliaxis.jbay.uk"},
            "organization": {"name": "Poliaxis Nutrition"}, "pages": {"/links": {"page_id": "p1"}}}
    OFFER = {"offer_id": "o", "status": "active", "items": [{"product_id": "p", "price_id": "pr"}],
             "presentation": {}, "product_intent": "lead_gen", "lead_capture_action": "social_redirect"}
    PRODUCTS = {"p": {"product_id": "p", "name": "My Links", "default_price_id": "pr",
                      "prices": [{"price_id": "pr", "unit_amount": 0, "currency": "usd"}]}}

    def _body(self, *, hidden):
        import re

        page = {"page_id": "p1", "tenant_id": "t", "name": "My Links", "route": {"slug": "x"},
                "sections": [{"id": "brand", "type": "brand_label"},
                             {"id": "hm", "type": "hero_media", "images": ["https://img.example/h.webp"]},
                             {"id": "lf", "type": "legal_footer"}]}
        if hidden:
            page["composition"] = {"overrides": {"brand_label": {"enabled": False}}}
        html = html_module.render_page(
            page, self.OFFER, self.PRODUCTS, checkout_url="https://c", api_base_url="https://a",
            site=self.SITE, home_url="https://poliaxis.jbay.uk/",
            preferences={"avatar_url": "https://img.example/a.webp"}, kind="published")
        body = html.split("<body>", 1)[-1].split("</body>", 1)[0]
        return re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)

    def test_hiding_the_brand_removes_it_from_the_page_entirely(self):
        body = self._body(hidden=True)
        self.assertNotIn("Poliaxis Nutrition", body)
        self.assertNotIn('data-section-type="brand_label"', body)

    def test_showing_it_still_renders_exactly_one(self):
        body = self._body(hidden=False)
        self.assertIn('data-section-type="brand_label"', body)
        self.assertEqual(body.count("Poliaxis Nutrition"), 1)

    def test_the_header_never_supplies_a_brand_the_page_owns(self):
        # Either way, the header carries the menu alone -- the mark is the page's job.
        for hidden in (True, False):
            self.assertNotIn('<a class="sl-brand" href="/">', self._body(hidden=hidden), hidden)

    def test_a_page_with_no_brand_mark_still_gets_the_header_brand(self):
        # The case the header's brand exists for: an offer-less storefront or category page owns no mark.
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG["name"] = "Poliaxis Nutrition"
        html_module._RENDER_STATE["home_url"] = "https://poliaxis.jbay.uk/"
        html_module._RENDER_STATE["page_type"] = "category"
        try:
            self.assertIn("Poliaxis Nutrition", html_module.render_site_header(has_brand_mark=False))
            self.assertNotIn("Poliaxis Nutrition", html_module.render_site_header(has_brand_mark=True))
        finally:
            html_module._RENDER_ORG.clear()
            html_module._RENDER_STATE["home_url"] = ""
            html_module._RENDER_STATE["page_type"] = ""
