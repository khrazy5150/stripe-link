"""Slice 2: the §A.7 field floor, the resolvers, and the generation schema.

Every claim case below is a sentence a real model really produced on 2026-09-27 against a brief that
did not license it. They are regression tests for measured failures, not invented ones.
"""

import json
import unittest

from stripe_link.domain.ai_floor import (CLAIM_CLASSES, FLOOR_SECTIONS, assert_within_floor,
                                         claim_violations, floor_reason, generatable_sections,
                                         may_generate_section, section_violations)
from stripe_link.domain.ai_resolvers import (AI, CATEGORY_PRESETS, EXPLICIT, RULES, TENANT,
                                             resolution_log, resolve_brand, resolve_goal,
                                             resolve_preset, resolve_sections)
from stripe_link.domain.ai_schema import (SECTION_SHAPES, describe_vocabulary,
                                          generatable_with_shape, page_sections_schema)
from stripe_link.domain.documents import SUPPORTED_THEME_PRESETS

BRIEF = ("5g creatine monohydrate per serving; 60 gummies per tub; third-party lab tested; "
         "made in the USA; ships free in the US; 30-day money-back guarantee.")


def sect(text, kind="subheadline"):
    return [{"id": "s", "type": kind, "text": text}]


class StructuralFloorTests(unittest.TestCase):
    def test_policy_and_legal_sections_are_never_generatable(self):
        for kind in ("refund_policy", "legal_footer"):
            with self.subTest(kind=kind):
                self.assertFalse(may_generate_section(kind))
                self.assertTrue(floor_reason(kind))

    def test_money_sections_are_never_generatable(self):
        for kind in ("checkout_cta", "offer_price_selector", "price_highlight", "coupon"):
            with self.subTest(kind=kind):
                self.assertFalse(may_generate_section(kind))

    def test_fabricable_social_proof_is_floored(self):
        # A generated testimonial is a fabricated review however it is labelled, a rating is a number
        # someone can check, and a logo wall asserts who a business's customers are.
        for kind in ("testimonials", "rating", "client_marquee", "trust_badges"):
            with self.subTest(kind=kind):
                self.assertFalse(may_generate_section(kind))

    def test_anything_carrying_a_url_or_asset_is_floored(self):
        for kind in ("hero_media", "video", "social_links", "link_cards", "before_after"):
            with self.subTest(kind=kind):
                self.assertFalse(may_generate_section(kind))

    def test_plain_copy_stays_generatable(self):
        for kind in ("headline", "subheadline", "faq", "bragging_points", "content_block"):
            with self.subTest(kind=kind):
                self.assertTrue(may_generate_section(kind))

    def test_every_floored_section_records_why(self):
        for kind, reason in FLOOR_SECTIONS.items():
            with self.subTest(kind=kind):
                self.assertTrue(reason.strip(), f"{kind} is floored with no reason given")

    def test_unknown_section_types_are_dropped_not_passed_through(self):
        # Page.schema.json accepts any `type` string and renders nothing for one the catalog does not
        # know, so a passthrough would validate and produce a blank page.
        self.assertEqual(generatable_sections(["headline", "not_a_real_section"]), ["headline"])

    def test_a_floored_section_in_the_output_is_caught_even_though_the_schema_excludes_it(self):
        found = section_violations([{"id": "x", "type": "refund_policy"}])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["claim_class"], "forbidden_section")


class GroundednessTests(unittest.TestCase):
    """A claim in a governed class must be traceable to the brief -- not absent from the page."""

    def test_an_invented_cancellation_term_is_caught(self):
        # Two of four models volunteered this from a brief that never mentioned cancellation.
        found = claim_violations(sect("Yes. No lock-in, no fees. Cancel or pause whenever."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "cancellation")

    def test_an_invented_dosage_is_caught_by_its_number(self):
        # The brief gave "5g per serving, 60 per tub" and never said how many gummies make a serving.
        found = claim_violations(sect("One gummy daily. No mixing."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "dosage")
        self.assertIn("1", found[0]["reason"])

    def test_an_invented_unit_is_caught_even_without_a_number(self):
        # "per serving" and "per gummy" are different products.
        found = claim_violations(sect("5g of creatine monohydrate per gummy."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "dosage")

    def test_an_efficacy_claim_is_caught(self):
        found = claim_violations(sect("You'll notice improved strength and muscle endurance."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "efficacy")

    def test_a_longer_guarantee_than_the_brief_gives_is_caught(self):
        found = claim_violations(sect("We offer a 90-day money-back guarantee."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "guarantee")
        self.assertIn("90", found[0]["reason"])

    def test_an_invented_delivery_window_is_caught(self):
        found = claim_violations(sect("Ships free in the US within 2 days."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "shipping")

    def test_an_invented_certification_is_caught(self):
        found = claim_violations(sect("FDA approved and certified organic."), BRIEF)
        self.assertEqual(found[0]["claim_class"], "certification")

    # ---- and the other half: grounded claims must SURVIVE ---------------------------------------
    def test_a_guarantee_the_brief_gives_is_allowed(self):
        self.assertEqual(claim_violations(sect("You have 30 days to decide. Then a full refund."), BRIEF), [])

    def test_a_shipping_promise_the_brief_gives_is_allowed(self):
        self.assertEqual(claim_violations(sect("Ships free in the US."), BRIEF), [])

    def test_a_number_the_brief_gives_is_allowed(self):
        self.assertEqual(claim_violations(sect("Each tub holds 60 gummies."), BRIEF), [])

    def test_a_neighbouring_sentence_does_not_lend_its_number(self):
        # "You have 30 days to decide." must not license "a 60-day guarantee" in the next sentence.
        found = claim_violations(sect("You have 30 days to decide. We offer a 60-day guarantee."), BRIEF)
        self.assertTrue(found)
        self.assertIn("60", found[0]["reason"])

    def test_plain_copy_with_no_governed_claim_passes(self):
        self.assertEqual(claim_violations(sect("Creatine without the powder or the shaker."), BRIEF), [])

    def test_claims_inside_faq_items_are_reached(self):
        # Every invented term measured on 2026-09-27 landed in a FAQ answer, because the question
        # format invites a policy statement.
        sections = [{"id": "f", "type": "faq",
                     "items": [{"question": "Can I cancel?", "answer": "Yes, cancel anytime, no contract."}]}]
        found = claim_violations(sections, BRIEF)
        self.assertEqual(found[0]["path"], "items[0].answer")

    def test_an_empty_brief_licenses_nothing(self):
        self.assertTrue(claim_violations(sect("30-day money-back guarantee."), ""))

    def test_every_claim_class_declares_both_halves(self):
        for key, spec in CLAIM_CLASSES.items():
            with self.subTest(key=key):
                self.assertTrue(spec["triggers"], f"{key} detects nothing")
                self.assertTrue(spec["evidence"], f"{key} can never be grounded")
                self.assertTrue(spec["label"])


class ValidatorTests(unittest.TestCase):
    def test_it_raises_so_the_repair_loop_re_prompts(self):
        # Raising rather than stripping: a silently deleted section leaves a gap nobody asked for,
        # while a repair round usually gets a grounded sentence back.
        with self.assertRaises(ValueError) as caught:
            assert_within_floor({"sections": sect("Cancel anytime, no fees.")}, BRIEF)
        self.assertIn("cancellation", str(caught.exception))

    def test_the_complaint_tells_the_model_what_to_do(self):
        with self.assertRaises(ValueError) as caught:
            assert_within_floor({"sections": sect("You'll notice results in 2 weeks.")}, BRIEF)
        self.assertIn("state only what the brief gives you", str(caught.exception).lower())

    def test_clean_output_passes_silently(self):
        assert_within_floor({"sections": sect("Creatine in a gummy. 60 per tub.")}, BRIEF)

    def test_it_survives_junk(self):
        for value in ({}, {"sections": None}, {"sections": ["not a dict"]}, None):
            with self.subTest(value=value):
                assert_within_floor(value, BRIEF)


class ResolverTests(unittest.TestCase):
    def test_the_precedence_chain_holds_in_order(self):
        both = dict(requested="fire-sale", tenant_preset="midnight-luxe", category="supplement",
                    supported=SUPPORTED_THEME_PRESETS)
        self.assertEqual(resolve_preset(**both)["source"], EXPLICIT)
        self.assertEqual(resolve_preset(**{**both, "requested": ""})["source"], TENANT)
        self.assertEqual(resolve_preset(**{**both, "requested": "", "tenant_preset": ""})["source"], AI)

    def test_a_tenants_existing_preset_beats_the_category_suggestion(self):
        # Their other pages look like that; a generated page that does not match their own site is a
        # worse answer than an imperfect palette.
        out = resolve_preset(tenant_preset="midnight-luxe", category="supplement",
                             supported=SUPPORTED_THEME_PRESETS)
        self.assertEqual(out["value"], "midnight-luxe")

    def test_the_ai_gets_a_shortlist_not_an_open_choice(self):
        out = resolve_preset(category="supplement", supported=SUPPORTED_THEME_PRESETS)
        self.assertEqual(out["source"], AI)
        self.assertGreater(len(out["shortlist"]), 1)
        self.assertLessEqual(len(out["shortlist"]), 4)

    def test_an_unsupported_preset_is_ignored_rather_than_emitted(self):
        out = resolve_preset(requested="not-a-preset", category="supplement",
                             supported=SUPPORTED_THEME_PRESETS)
        self.assertNotEqual(out["value"], "not-a-preset")

    def test_every_curated_preset_actually_exists(self):
        for category, presets in CATEGORY_PRESETS.items():
            for preset in presets:
                with self.subTest(category=category, preset=preset):
                    self.assertIn(preset, SUPPORTED_THEME_PRESETS)

    def test_sections_come_from_the_composer_minus_the_floor(self):
        out = resolve_sections(offer_type="single")
        self.assertIn("headline", out["value"])
        for floored in ("refund_policy", "testimonials", "checkout_cta"):
            self.assertNotIn(floored, out["value"])

    def test_a_request_can_narrow_but_never_add_a_floored_section(self):
        out = resolve_sections(offer_type="single",
                               requested=["headline", "refund_policy", "testimonials"])
        self.assertEqual(out["value"], ["headline"])
        self.assertEqual(out["refused"], ["refund_policy", "testimonials"])

    def test_a_request_for_nothing_available_falls_back_rather_than_emptying_the_page(self):
        out = resolve_sections(offer_type="single", requested=["refund_policy"])
        self.assertEqual(out["source"], RULES)
        self.assertTrue(out["value"])

    def test_a_brand_is_resolved_never_invented(self):
        self.assertEqual(resolve_brand(business_name="Poliaxis")["value"], "Poliaxis")
        self.assertEqual(resolve_brand(product_brand="Poliaxis")["source"], RULES)
        self.assertEqual(resolve_brand()["value"], "")   # asserts nothing rather than guessing

    def test_an_unsupported_goal_is_dropped(self):
        self.assertEqual(resolve_goal(requested="not-a-goal")["value"], "")

    def test_every_decision_explains_itself(self):
        decisions = {"preset": resolve_preset(category="tech", supported=SUPPORTED_THEME_PRESETS),
                     "brand": resolve_brand(business_name="X")}
        for line in resolution_log(decisions):
            self.assertRegex(line, r"^\w+=.+\((explicit|tenant|rules|ai)\): .+")


class GenerationSchemaTests(unittest.TestCase):
    def setUp(self):
        self.allowed = resolve_sections(offer_type="single")["value"]
        self.schema = page_sections_schema(self.allowed)

    def _walk(self, node, path="$"):
        problems = []
        if isinstance(node, dict):
            if node.get("type") == "object":
                if node.get("additionalProperties") is not False:
                    problems.append(f"{path} leaves additionalProperties open")
                if sorted(node.get("required", [])) != sorted(node.get("properties", {})):
                    problems.append(f"{path} required != properties")
            for key, value in node.items():
                problems += self._walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                problems += self._walk(value, f"{path}[{index}]")
        return problems

    def test_it_satisfies_strict_structured_output(self):
        self.assertEqual(self._walk(self.schema), [])

    def test_it_avoids_the_keywords_strict_mode_rejects(self):
        # minItems above 1 is refused outright, and oneOf is not accepted -- both measured against
        # real Bedrock on 2026-09-27.
        serialized = json.dumps(self.schema)
        self.assertNotIn("minItems", serialized)
        self.assertNotIn("oneOf", serialized)

    def test_the_union_is_discriminable_by_a_single_valued_enum(self):
        # So a model choosing the faq branch cannot then emit a headline's fields.
        for branch in self.schema["properties"]["sections"]["items"]["anyOf"]:
            with self.subTest(branch=branch["properties"]["type"]["enum"][0]):
                self.assertEqual(len(branch["properties"]["type"]["enum"]), 1)

    def test_no_floored_section_can_appear_in_the_schema(self):
        names = {b["properties"]["type"]["enum"][0]
                 for b in self.schema["properties"]["sections"]["items"]["anyOf"]}
        self.assertFalse(names & set(FLOOR_SECTIONS))

    def test_a_section_with_no_known_shape_is_excluded(self):
        # An un-modelled section would reach the page as an empty shell.
        self.assertNotIn("catalog_grid", generatable_with_shape(["catalog_grid", "headline"]))

    def test_it_refuses_to_build_an_empty_contract(self):
        with self.assertRaises(ValueError):
            page_sections_schema(["refund_policy", "testimonials"])

    def test_cardinality_is_stated_in_the_prompt_since_the_schema_cannot_carry_it(self):
        text = describe_vocabulary(self.allowed)
        self.assertIn("at least four", text)
        self.assertIn("at most once", text)

    def test_every_modelled_shape_is_a_section_the_ai_may_write(self):
        for name in SECTION_SHAPES:
            with self.subTest(name=name):
                self.assertTrue(may_generate_section(name))
