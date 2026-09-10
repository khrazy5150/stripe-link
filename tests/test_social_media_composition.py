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
            self.assertFalse(is_section_visible("social_media", key), key)

    def test_identity_and_links_are_present(self):
        # seller_profile / social_links / catalog_grid are UNGOVERNED, so they render whenever the page
        # carries them -- this asserts the composer does not accidentally start gating them.
        for key in ("seller_profile", "social_links", "catalog_grid"):
            self.assertTrue(is_section_visible("social_media", key), key)
        for key in ("brand_label", "hero_media", "hero", "legal_footer"):
            self.assertTrue(is_section_visible("social_media", key), key)

    def test_the_page_cannot_convert(self):
        # Empty by design: a CTA here would contradict the cardinality guardrail. Every other offer_type
        # offers at least "buy".
        self.assertEqual(allowed_ctas("social_media"), [])
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
        markup = self._render(self.ORG)
        self.assertIn(">GitHub<", markup)
        self.assertIn(">Instagram<", markup)

    def test_nothing_renders_without_links(self):
        self.assertEqual(self._render({}), "")
        self.assertEqual(self._render({"same_as": []}), "")


if __name__ == "__main__":
    unittest.main()
