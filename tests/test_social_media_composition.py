"""The link-in-bio composition: an identity page with the conversion spine deliberately absent.

plans/SOCIAL_MEDIA_PAGES.md §2 — this is a COMPOSITION, not a new page type or a second renderer. What
makes it different from every existing offer_type is a subtraction: no price selector, no checkout CTA,
no refund policy, because the page has nothing to sell of its own. Its cards each resolve their own offer.
"""
import json
import pathlib
import unittest

from stripe_link.domain.composition import allowed_ctas, is_section_visible
from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.runtime import html as html_module


FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples" / "offer-simple-coffee.json"


def _offer(**overrides):
    """A valid offer minus its items — the shape the exemption is about."""
    offer = json.loads(FIXTURE.read_text(encoding="utf-8"))
    offer.pop("items", None)
    offer.pop("offer_type", None)
    offer.update(overrides)
    return offer


class SocialMediaCompositionTests(unittest.TestCase):
    def test_the_conversion_spine_is_absent(self):
        for key in ("offer_price_selector", "checkout_cta", "refund_policy", "trust_badges"):
            self.assertFalse(is_section_visible("lead_social", key), key)

    def test_identity_and_links_are_present(self):
        # seller_profile / social_links / catalog_grid are UNGOVERNED, so they render whenever the page
        # carries them -- this asserts the composer does not accidentally start gating them.
        for key in ("seller_profile", "social_links", "catalog_grid"):
            self.assertTrue(is_section_visible("lead_social", key), key)
        for key in ("brand_label", "hero_media", "legal_footer"):
            self.assertTrue(is_section_visible("lead_social", key), key)

    def test_the_offer_headline_block_is_absent(self):
        """`hero` renders the OFFER's headline and subheadline. On a link hub the identity header does that
        job -- brand name, avatar, then the links -- and an offer headline repeated above it is noise. This
        is also what produced "Capture Email" as both brand and headline on the page reported 2026-09-10."""
        self.assertFalse(is_section_visible("lead_social", "hero"))
        # The capture page KEEPS it: a squeeze page is nothing without a promise at the top.
        self.assertTrue(is_section_visible("lead_capture", "hero"))

    def test_the_page_cannot_convert(self):
        # Empty by design: a CTA here would contradict the cardinality guardrail. Every other offer_type
        # offers at least "buy".
        self.assertEqual(allowed_ctas("lead_social"), [])
        self.assertIn("buy", allowed_ctas("single"))

    def test_the_existing_offer_types_are_untouched(self):
        for offer_type in ("single", "bundle", "listicle"):
            self.assertTrue(is_section_visible(offer_type, "checkout_cta"), offer_type)


class SocialMediaOfferValidationTests(unittest.TestCase):
    def test_a_social_media_offer_needs_no_items(self):
        # A zero-primary-offer page has no conversion, so requiring an item would mean inventing one --
        # a $0 phantom product in the tenant's catalogue, or borrowing a real offer the page is not about
        # and emitting false Product markup. Both rejected 2026-09-09.
        validate_offer_document(_offer(offer_type="social_media"))

    def test_every_other_offer_type_still_requires_items(self):
        for offer_type in ("single", "bundle", "listicle"):
            with self.assertRaises(DocumentValidationError, msg=offer_type):
                validate_offer_document(_offer(offer_type=offer_type))

    def test_an_offer_with_no_type_at_all_still_requires_items(self):
        # The exemption keys off the EXPLICIT type. An offer that simply omits offer_type must not slip
        # through it -- that would make the empty-offer case reachable by accident.
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(_offer())

    def test_a_social_media_offer_may_still_carry_items(self):
        # Not forbidden, just not required -- and items that ARE present are still validated.
        with self.assertRaises(DocumentValidationError):
            validate_offer_document(_offer(offer_type="social_media", items=[{"product_id": ""}]))


class SocialLinksElementTests(unittest.TestCase):
    ORG = {"same_as": [
        {"url": "https://github.com/acme", "verification": {"state": "verified"}},
        {"url": "https://instagram.com/acme", "verification": {"state": "unverifiable"}},
        {"url": "https://x.com/acme", "verification": {"state": "failed"}},
    ]}

    def _render(self, org):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(org)
        return html_module.render_social_links({"id": "s1"})

    def test_display_is_not_gated_on_verification(self):
        # The point of the two-tier model. Instagram and TikTok can never be confirmed, and they are the
        # platforms this page exists to be linked FROM -- gating display would empty the row of exactly
        # the links that matter.
        markup = self._render(self.ORG)
        for host in ("github.com/acme", "instagram.com/acme", "x.com/acme"):
            self.assertIn(host, markup)

    def test_every_link_is_nofollow_ugc(self):
        markup = self._render(self.ORG)
        self.assertEqual(markup.count('rel="nofollow ugc noopener"'), 3)
        self.assertNotIn('rel="noopener"', markup.replace('rel="nofollow ugc noopener"', ""))

    def test_links_are_labelled_by_network(self):
        # The row shows BRAND GLYPHS now (plans/LEAD_GEN_PAGES.md §8) -- a visitor scanning a link hub finds
        # the YouTube mark faster than the word among nine other words. The network name is still carried,
        # because a glyph nobody can see is not a label: aria-label names the link, and the svg is
        # aria-hidden so a screen reader announces the network once instead of twice.
        markup = self._render(self.ORG)
        self.assertIn('aria-label="GitHub"', markup)
        self.assertIn('aria-label="Instagram"', markup)
        self.assertEqual(markup.count('aria-hidden="true"'), 3)
        self.assertEqual(markup.count("<svg "), 3)

    def test_a_network_with_no_mark_gets_a_globe(self):
        # A tenant can paste any host. It used to be spelled out, which put a wide text pill in a row of 44px
        # circles; now it gets a globe and the HOST goes on the link's name, where a screen reader and a hover
        # still find it. The link works -- we just do not recognise where it goes.
        markup = self._render({"same_as": [{"url": "https://example.org/acme"}]})
        self.assertIn('aria-label="example.org"', markup)
        self.assertIn("sl-social-glyph", markup)
        self.assertIn("<svg ", markup)
        self.assertNotIn("sl-social-worded", markup)

    def test_every_tile_in_a_row_is_the_same_shape(self):
        # The point of the globe fallback: one unrecognised host used to widen the row and break its rhythm.
        markup = self._render({"same_as": [
            {"url": "https://youtube.com/@acme"},
            {"url": "https://example.org/acme"},
        ]})
        self.assertEqual(markup.count("sl-social-glyph"), 2)
        self.assertEqual(markup.count("<svg "), 2)
        self.assertNotIn("sl-social-worded", markup)
        # Both are 44px tall so a mixed row sits on one baseline, and both clear the WCAG 2.5.8 target
        # minimum -- this page is tapped on a phone, from a bio link, which is its entire traffic source.
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn("min-height:44px", css)
        self.assertIn(".sl-social-row a.sl-social-glyph{width:44px;height:44px", css)

    def test_nothing_renders_without_links(self):
        self.assertEqual(self._render({}), "")
        self.assertEqual(self._render({"same_as": []}), "")


if __name__ == "__main__":
    unittest.main()


class LinkCardsElementTests(unittest.TestCase):
    """External destinations, and the §7 trust boundary that governs them.

    Kept separate from catalog_grid deliberately: catalog_grid's links must be FOLLOWABLE (it exists to
    build the crawlable subfolder hierarchy), these must be nofollow ugc. One element holding both would
    be a conditional someone eventually inverts without knowing why it was there.
    """

    SECTION = {"id": "lc", "items": [
        {"url": "https://github.com/acme", "label": "Our code"},
        {"url": "https://www.amazon.com/shops/acme", "label": "Amazon storefront"},
    ]}

    def _render(self, *, on_custom_domain):
        html_module._RENDER_STATE["home_url"] = "https://shop.example.com/" if on_custom_domain else ""
        html_module._RENDER_STATE["own_domain"] = on_custom_domain
        return html_module.render_link_cards(self.SECTION)

    def test_any_destination_is_linkable_on_the_tenants_own_domain(self):
        markup = self._render(on_custom_domain=True)
        self.assertEqual(markup.count('rel="nofollow ugc noopener"'), 2)
        self.assertIn("amazon.com/shops/acme", markup)

    def test_a_shared_platform_host_only_links_allowlisted_destinations(self):
        # The reason is the URL bar, not SEO: noindex does nothing about a human tapping a phishing link
        # on scammer.jbay.uk, which is a blocklist problem for OUR domain and every tenant on it.
        markup = self._render(on_custom_domain=False)
        self.assertEqual(markup.count('rel="nofollow ugc noopener"'), 1)
        self.assertIn('href="https://github.com/acme"', markup)
        self.assertNotIn('href="https://www.amazon.com/shops/acme"', markup)

    def test_a_blocked_destination_is_shown_unlinked_rather_than_dropped(self):
        # A card that silently vanishes tells the tenant nothing about why.
        markup = self._render(on_custom_domain=False)
        self.assertIn("Amazon Storefront", markup)
        self.assertIn('<div class="sl-catalog-card sl-link-card">', markup)

    def test_links_are_never_followable(self):
        for on_domain in (True, False):
            markup = self._render(on_custom_domain=on_domain)
            self.assertNotIn('rel="noopener"', markup.replace('rel="nofollow ugc noopener"', ""))

    def test_the_element_cannot_convert(self):
        # No offer_id, no price, no resolve_offer -- it is visitor navigation, not catalog.
        markup = self._render(on_custom_domain=True)
        for forbidden in ("checkout", "sl-catalog-price", "data-offer-id", "add-to-cart"):
            self.assertNotIn(forbidden, markup)

    def test_incomplete_items_are_skipped(self):
        html_module._RENDER_STATE["home_url"] = "https://shop.example.com/"
        html_module._RENDER_STATE["own_domain"] = True
        markup = html_module.render_link_cards({"id": "lc", "items": [
            {"url": "https://github.com/acme"},          # no label
            {"label": "No destination"},                  # no url
        ]})
        self.assertEqual(markup, "")


class LinkCardGridTests(unittest.TestCase):
    """A partial last row must look deliberate, not left over.

    catalog_grid uses auto-fill, which packs from the left -- so a creator with ONE link had it pinned
    against the left edge with two columns of dead space beside it. Reported 2026-09-10.

    The rules are written on nth-child(3n+1) rather than on the total count, because the same complaint
    reappears at four cards: the fourth strands exactly the way the first did.
    """

    def _styles(self) -> str:
        import re
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        return "\n".join(re.findall(r'"(\s*\.sl-link-cards[^"]*)"', source))

    def test_link_cards_do_not_inherit_the_auto_fill_grid(self):
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", self._styles())

    def test_a_lone_card_in_a_row_is_centred(self):
        # Applies to one card, and to the fourth of four, and the seventh of seven.
        self.assertIn(":nth-child(3n+1):last-child{grid-column:2}", self._styles())

    def test_a_pair_in_a_row_spreads_to_the_outer_columns(self):
        styles = self._styles()
        self.assertIn(":nth-child(3n+1):nth-last-child(2){grid-column:1}", styles)
        self.assertIn(":nth-child(3n+1):nth-last-child(2)+*{grid-column:3}", styles)

    def test_the_phone_layout_is_two_columns_with_a_full_width_orphan(self):
        # Effectively all of this traffic is a thumb arriving from an app's bio field, so the phone case
        # is the one that matters most -- and three columns of cards on a phone is unreadable.
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        media = [line for line in source.split("\n") if "max-width: 700px" in line]
        self.assertTrue(media)
        self.assertIn("repeat(2,minmax(0,1fr))", media[0])
        self.assertIn(":nth-child(2n+1):last-child{grid-column:1/-1}", media[0])

    def test_long_text_is_clamped_by_LINES_not_characters(self):
        """The card is constrained in pixels, and the tenant picks the font.

        A maxlength would be a proxy for the wrong thing: Comic Relief at 40 characters is a different
        width from Lato at 40. Clamping is font-agnostic by construction -- a heavier face fits fewer
        words into the same two lines and the card is identical either way.
        """
        styles = self._styles()
        self.assertIn("-webkit-line-clamp:2", styles)   # headline
        self.assertIn("-webkit-line-clamp:3", styles)   # description
        # NOT single-line: a phone card is ~146px, so nowrap would cut a headline at ~16 characters.
        self.assertNotIn("white-space:nowrap", styles)
        # A pasted URL has no break opportunity, so clamping alone would still widen the card.
        self.assertIn("overflow-wrap:anywhere", styles)

    def test_clamping_never_costs_the_text(self):
        # Visual only: the full string stays in the DOM and in title=, so a screen reader and a hover
        # both still get it.
        import stripe_link.runtime.html as html_mod
        html_mod._RENDER_STATE["home_url"] = "https://shop.example.com/"
        html_mod._RENDER_STATE["own_domain"] = True
        label = "My Amazon Storefront With A Very Long Name Indeed"
        markup = html_mod.render_link_cards({"id": "lc", "items": [
            {"url": "https://amazon.com/x", "label": label, "description": "Long note here"}]})
        self.assertIn(f'title="{label}"', markup)
        self.assertIn('title="Long note here"', markup)
