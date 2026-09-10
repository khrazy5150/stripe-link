"""A lead-gen offer composes as a LEAD page, not a checkout page with the price hidden.

plans/SOCIAL_MEDIA_PAGES.md §2a. The first attempt hung this on `offer_type: social_media` and was
unreachable: offer_type is DERIVED, and no offer SHAPE can express "this page sells nothing". The switch
is `product_intent`, which the Offer already carries and which the builder already reads.
"""
import pathlib
import re
import unittest

from stripe_link.domain.composition import allowed_ctas, compose_page, composition_key, is_section_visible
from stripe_link.domain.opportunities import derived_offer_type

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def _offer(**overrides):
    offer = {"offer_id": "off_1", "items": [{"product_id": "p1"}], "presentation": {}}
    offer.update(overrides)
    return offer


class CompositionKeyTests(unittest.TestCase):
    def test_a_lead_gen_offer_gets_its_own_composition(self):
        self.assertEqual(composition_key(_offer(product_intent="lead_gen")), "lead_gen")

    def test_a_transactional_offer_is_unchanged(self):
        self.assertEqual(composition_key(_offer(product_intent="transaction")), "single")
        self.assertEqual(composition_key(_offer()), "single")

    def test_pricing_shape_is_still_answered_separately(self):
        """derived_offer_type answers "how does this offer PRICE", and four places in the renderer branch
        on it for carousel and minicart behaviour. Intent is a different question, so folding them together
        would silently change those four."""
        lead = _offer(product_intent="lead_gen", offer_type="listicle")
        self.assertEqual(composition_key(lead), "lead_gen")
        self.assertEqual(derived_offer_type(lead), "listicle")


class LeadGenSectionsTests(unittest.TestCase):
    def test_the_purchase_spine_is_gone(self):
        # Not a guard against bad data -- a lead-gen offer cannot carry purchasable items in the first
        # place: validation forbids `checkout` and discounts on one, and the builder stamps intent from
        # the selected products, so intents cannot mix in a single offer. This states the composition
        # POSITIVELY, so the Page Sections panel recommends the right set instead of offering a price
        # selector that would render empty.
        for key in ("offer_price_selector", "refund_policy", "trust_badges"):
            self.assertFalse(is_section_visible("lead_gen", key), key)

    def test_the_cta_stays_because_it_IS_the_capture_form(self):
        # render_lead_capture_form is reached through checkout_cta; removing it would remove the form.
        self.assertTrue(is_section_visible("lead_gen", "checkout_cta"))

    def test_the_page_cannot_transact(self):
        self.assertNotIn("buy", allowed_ctas("lead_gen"))
        self.assertIn("email_capture", allowed_ctas("lead_gen"))
        self.assertIn("buy", allowed_ctas("single"))   # unchanged

    def test_identity_and_link_elements_render(self):
        for key in ("social_links", "link_cards", "seller_profile"):
            self.assertTrue(is_section_visible("lead_gen", key), key)

    def test_end_to_end_a_lead_gen_page_drops_the_price_selector(self):
        page = {"sections": [
            {"type": "hero", "id": "h"},
            {"type": "offer_price_selector", "id": "ops"},
            {"type": "social_links", "id": "sl"},
            {"type": "link_cards", "id": "lc", "items": []},
            {"type": "checkout_cta", "id": "cta"},
        ]}
        types = [s["type"] for s in compose_page(_offer(product_intent="lead_gen"), page)]
        self.assertNotIn("offer_price_selector", types)
        self.assertIn("checkout_cta", types)
        self.assertIn("social_links", types)


class BuilderParityTests(unittest.TestCase):
    def test_the_builder_switches_on_the_same_signal(self):
        """Preview and published must agree about what a lead-gen page contains. Both read the same
        composition_rules.json, but each derives the KEY itself -- so the two derivations are pinned."""
        match = re.search(r'function deriveOfferType\(offer\) \{(.*?)\n\}', BUILDER, re.S)
        self.assertIsNotNone(match, "deriveOfferType not found")
        body = match.group(1)
        self.assertIn('product_intent === "lead_gen"', body)
        self.assertIn('return "lead_gen"', body)
        # and it must come FIRST -- a stored offer_type must not win over intent.
        self.assertLess(body.index('product_intent'), body.index('offer?.offer_type'))


if __name__ == "__main__":
    unittest.main()


class IntentsCannotMixTests(unittest.TestCase):
    """The constraint the composition rests on, pinned so it cannot quietly relax.

    If a lead-gen offer could ever carry checkout or a discount, the composition above would be papering
    over a data problem instead of describing a page.
    """

    def test_a_lead_gen_offer_must_not_carry_checkout(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
        import json as _json
        import pathlib as _pathlib
        fixture = (_pathlib.Path(__file__).resolve().parents[1]
                   / "schemas" / "examples" / "offer-simple-coffee.json")
        offer = _json.loads(fixture.read_text(encoding="utf-8"))
        offer["product_intent"] = "lead_gen"
        with self.assertRaisesRegex(DocumentValidationError, "must not include checkout"):
            validate_offer_document(offer)
