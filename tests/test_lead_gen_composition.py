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
        # Four shapes now, chosen by the ACTION. An offer that says lead_gen without naming one still must
        # not get a checkout page, so the capture shape is the safe default -- it is the only one that
        # keeps a form, so nothing the tenant typed is lost.
        self.assertEqual(composition_key(_offer(product_intent="lead_gen")), "lead_capture")
        for action, expected in (("capture_email", "lead_capture"), ("capture_phone", "lead_capture"),
                                 ("capture_email_phone", "lead_capture"), ("call_number", "lead_call"),
                                 ("external_url", "lead_bridge"), ("social_redirect", "lead_social")):
            self.assertEqual(
                composition_key(_offer(product_intent="lead_gen", lead_capture_action=action)),
                expected, action)

    def test_a_transactional_offer_is_unchanged(self):
        self.assertEqual(composition_key(_offer(product_intent="transaction")), "single")
        self.assertEqual(composition_key(_offer()), "single")

    def test_pricing_shape_is_still_answered_separately(self):
        """derived_offer_type answers "how does this offer PRICE", and four places in the renderer branch
        on it for carousel and minicart behaviour. Intent is a different question, so folding them together
        would silently change those four."""
        lead = _offer(product_intent="lead_gen", offer_type="listicle")
        self.assertEqual(composition_key(lead), "lead_capture")
        self.assertEqual(derived_offer_type(lead), "listicle")


class LeadGenSectionsTests(unittest.TestCase):
    def test_the_purchase_spine_is_gone(self):
        # Not a guard against bad data -- a lead-gen offer cannot carry purchasable items in the first
        # place: validation forbids `checkout` and discounts on one, and the builder stamps intent from
        # the selected products, so intents cannot mix in a single offer. This states the composition
        # POSITIVELY, so the Page Sections panel recommends the right set instead of offering a price
        # selector that would render empty.
        for key in ("offer_price_selector", "refund_policy", "trust_badges"):
            self.assertFalse(is_section_visible("lead_capture", key), key)

    def test_the_cta_stays_because_it_IS_the_capture_form(self):
        # render_lead_capture_form is reached through checkout_cta; removing it would remove the form.
        self.assertTrue(is_section_visible("lead_capture", "checkout_cta"))

    def test_the_page_cannot_transact(self):
        self.assertNotIn("buy", allowed_ctas("lead_capture"))
        self.assertIn("email_capture", allowed_ctas("lead_capture"))
        self.assertIn("buy", allowed_ctas("single"))   # unchanged

    def test_identity_and_link_elements_render(self):
        for key in ("social_links", "link_cards", "seller_profile"):
            self.assertTrue(is_section_visible("lead_capture", key), key)

    def test_end_to_end_a_lead_gen_page_drops_the_price_selector(self):
        page = {"sections": [
            {"type": "hero", "id": "h"},
            {"type": "offer_price_selector", "id": "ops"},
            {"type": "social_links", "id": "sl"},
            {"type": "link_cards", "id": "lc", "items": []},
            {"type": "checkout_cta", "id": "cta"},
        ]}
        types = [s["type"] for s in compose_page(_offer(product_intent="lead_gen", lead_capture_action="capture_email"), page)]
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
        # Asks offerIntent(), the ONE derivation -- it used to read offer.product_intent directly, which
        # disagreed with the CTA's derivation whenever the intent came from the product.
        self.assertIn('offerIntent(offer) === "lead_gen"', body)
        self.assertIn("LEAD_COMPOSITIONS[action]", body)
        # No longer returns a literal "lead_gen": the ACTION picks one of four shapes, with the capture
        # page as the fallback so an offer that names no action still never gets a checkout page.
        self.assertIn('|| "lead_capture"', body)
        # and it must come FIRST -- a stored offer_type must not win over intent.
        self.assertLess(body.index('offerIntent'), body.index('offer?.offer_type'))


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


class GoalCannotResurrectTransactionalSectionsTests(unittest.TestCase):
    """Reported 2026-09-10 with a real saved document: a capture-email page carrying trust badges and a
    refund policy, composition.overrides empty.

    The cause was the GOAL axis, not the offer_type. It is union-only by design -- goals ADD sections and
    can never subtract -- and the paid_ads pack turns on trust_badges and refund_policy. That is right for a
    paid-traffic CHECKOUT page, where cold traffic needs reassurance, and incoherent on a page that takes no
    money. So a composition can now declare sections IMPOSSIBLE, and that outranks both the goal union and a
    tenant override: it is a statement about what the page is, not a preference.
    """

    def test_the_paid_ads_goal_does_not_put_trust_badges_on_a_lead_page(self):
        for key in ("trust_badges", "refund_policy"):
            self.assertFalse(is_section_visible("lead_capture", key, {}, "paid_ads"), key)

    def test_an_override_cannot_resurrect_them_either(self):
        for key in ("trust_badges", "refund_policy"):
            self.assertFalse(
                is_section_visible("lead_capture", key, {key: {"enabled": True}}, "paid_ads"), key)

    def test_the_goal_still_works_for_everything_it_should(self):
        # The exclusion is narrow: a lead page still gets its CTA and hero from the composition, and a
        # goal can still union in anything not excluded.
        self.assertTrue(is_section_visible("lead_capture", "checkout_cta", {}, "paid_ads"))
        self.assertTrue(is_section_visible("lead_capture", "hero", {}, "paid_ads"))

    def test_transactional_pages_are_untouched(self):
        # The paid_ads pack must go on doing its job where it makes sense.
        for offer_type in ("single", "bundle", "listicle"):
            self.assertTrue(is_section_visible(offer_type, "trust_badges", {}, "paid_ads"), offer_type)
            self.assertTrue(is_section_visible(offer_type, "refund_policy", {}, "paid_ads"), offer_type)

    def test_the_builder_applies_the_same_exclusion(self):
        """Preview and published must agree. Both read composition_rules.json, but each implements the
        visibility logic itself -- so the exclusion has to exist on both sides."""
        import pathlib
        composer = (pathlib.Path(__file__).resolve().parents[1]
                    / "dashboard" / "src" / "composables" / "pageComposer.js").read_text(encoding="utf-8")
        self.assertIn("excludedSections", composer)
        self.assertIn("if (excludedSections(offerType).has(key)) return false;", composer)


class SocialPageSkipsTheGoalTests(unittest.TestCase):
    """The link-in-bio page is the ONE lead shape with no goal question to answer.

    Its traffic is always a tap from a bio field, and every pack seeds the wrong thing for it -- ad_landing
    seeds a content block and an FAQ, social_proof seeds testimonials and a rating. On a link hub those are
    noise.

    The other three KEEP the step, and the reasoning is recorded because it was nearly dropped for all of
    them: paid traffic to lead-capture pages is a large category (Meta has a "Leads" objective, Google has
    lead-form extensions), and after the exclusion the packs still contribute useful SEEDS there.
    """

    def _builder(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def test_the_goal_step_is_skipped_for_a_social_page(self):
        builder = self._builder()
        self.assertIn('product?.lead_capture?.action === "social_redirect"', builder)
        self.assertIn('form.goal = "minimal"', builder)

    def test_it_skips_rather_than_pre_answering(self):
        # An option nobody should change is a question that should not be asked.
        self.assertIn("wizardStep.value = 3;", self._builder())

    def test_the_step_counter_has_no_hole_in_it(self):
        # Without this a Social Page read "Step 2 of 5" then "Step 4 of 5", which looks like a lost step.
        self.assertIn("wizardSkipsGoal", self._builder())

    def test_minimal_really_does_nothing(self):
        # The forced goal has to be inert, or skipping the question would quietly choose content for them.
        from stripe_link.domain.composition import goal_packs, goal_sections
        self.assertEqual(goal_packs("minimal"), [])
        self.assertEqual(goal_sections("minimal"), set())


class OpenFormIsRetiredTests(unittest.TestCase):
    """`open_form` is gone, not deferred.

    Its required `form_id` was read by nothing and it fell through to a generic email CTA, so it looked
    like a feature and behaved like a dead branch. It was blocked on a form builder that does not exist,
    and plans/FORM_BUILDER.md §8 had already concluded it should be retired rather than implemented.
    Verified before removal: ZERO products used it in dev or prod, so it left no data behind.
    """

    def test_the_action_is_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_product_document
        import json
        import pathlib
        fixture = next((pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples").glob("product-*.json"))
        product = json.loads(fixture.read_text(encoding="utf-8"))
        product["product_intent"] = "lead_gen"
        product["lead_capture"] = {"action": "open_form", "title": "T", "description": "D",
                                   "target": {"type": "form", "form_id": "form_1"}}
        with self.assertRaises(DocumentValidationError):
            validate_product_document(product)

    def test_the_surviving_actions_still_validate(self):
        from stripe_link.domain.documents import validate_product_document
        import json
        import pathlib
        fixture = next((pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples").glob("product-*.json"))
        for action, target in (("call_number", {"type": "phone", "value": "+12065550100"}),
                               ("external_url", {"type": "url", "value": "https://example.com"}),
                               ("social_redirect", {"type": "social", "value": "https://instagram.com/x",
                                                    "platform": "instagram"})):
            product = json.loads(fixture.read_text(encoding="utf-8"))
            product["product_intent"] = "lead_gen"
            product["lead_capture"] = {"action": action, "title": "T", "description": "D", "target": target}
            validate_product_document(product)   # must not raise

    def test_no_code_still_offers_it(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders = []
        for path in list((root / "src").rglob("*.py")) + list((root / "dashboard" / "src").rglob("*.vue")) \
                + list((root / "dashboard" / "src").rglob("*.js")) + [root / "schemas" / "Product.schema.json"]:
            text = path.read_text(encoding="utf-8")
            for line in text.split("\n"):
                if "open_form" in line and not line.lstrip().startswith(("#", "//", "*")):
                    offenders.append(f"{path.name}: {line.strip()[:70]}")
        self.assertEqual(offenders, [], "open_form is retired but still referenced: " + str(offenders))
