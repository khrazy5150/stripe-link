"""Element contracts: what each element is FOR, and the checks that enforce it.

Every case here comes from a page a real model really produced on 2026-09-27 — six bragging-point
cards of prose, from a brief that asked "what do you want people to know". The generator read the
questionnaire's shape as the semantics: desirable things, therefore bragging points.

The contracts teach the boundary and the checks enforce it, and only the second is reliable. A future
model may be persuaded differently; a value with no digit in it fails either way.
"""

import json
import unittest

from stripe_link.domain.ai_elements import (MAX_STAT_CHARS, assert_contracts, contract, contracted,
                                            for_prompt, route_table, routes_for, violations)
from stripe_link.domain.ai_floor import FLOOR_SECTIONS
from stripe_link.domain.ai_schema import SECTION_SHAPES

# The actual cards from the reported page.
REPORTED = [{"id": "b", "type": "bragging_points", "items": [
    {"value": "30g of premium milk protein", "label": "Protein Per Scoop"},
    {"value": "Isolated and hydrolyzed for quality absorption", "label": "Blend Type"},
    {"value": "Included in every serving", "label": "Digestive Enzymes"},
    {"value": "A cleaner way to hit your protein goals", "label": "Low Sugar & Low Fat"},
    {"value": "Strawberry, Blueberry, and Vanilla", "label": "Flavors Available"},
    {"value": "30-day guarantee", "label": "Money-Back Guarantee"}]}]

CORRECTED = [{"id": "b", "type": "bragging_points", "items": [
    {"value": "30g", "label": "of protein per scoop"},
    {"value": "2M+", "label": "Tubs sold"},
    {"value": "4.9/5", "label": "Average customer rating"}]}]


class ContractCoverageTests(unittest.TestCase):
    def test_every_emittable_element_has_a_contract(self):
        # An element the AI can emit but has never been told the purpose of is exactly how V1 failed.
        self.assertEqual(sorted(SECTION_SHAPES), contracted())

    def test_no_contract_describes_an_element_that_cannot_be_emitted(self):
        # Teaching the model about an element it may not use invites it to try.
        for element in contracted():
            with self.subTest(element=element):
                self.assertIn(element, SECTION_SHAPES)
                self.assertNotIn(element, FLOOR_SECTIONS)

    def test_every_contract_states_a_purpose_and_a_boundary(self):
        for element in contracted():
            with self.subTest(element=element):
                spec = contract(element)
                self.assertTrue(spec["purpose"].strip())
                self.assertTrue(spec["use_when"].strip())
                # The do-not-use half is the one that teaches the decision boundary.
                self.assertTrue(spec["do_not_use_when"].strip())

    def test_every_contract_carries_a_tempting_wrong_example(self):
        # An example where the wrong answer LOOKS right teaches a boundary a correct one cannot.
        for element in contracted():
            with self.subTest(element=element):
                bad = contract(element).get("bad") or []
                self.assertTrue(bad, f"{element} has no counter-example")
                for case in bad:
                    self.assertTrue(str(case.get("why") or "").strip(),
                                    f"{element} has a bad example that does not say why")

    def test_contracts_only_name_real_neighbours(self):
        for element in contracted():
            for other in (contract(element).get("confusable_with") or {}):
                with self.subTest(element=element, other=other):
                    self.assertIn(other, SECTION_SHAPES)

    def test_the_fields_a_contract_describes_are_the_fields_that_render(self):
        """A contract promising a field the renderer ignores is advice that produces nothing.

        Compared against top-level AND item properties together, because a contract describes what
        the tenant sees on the card -- `value` and `label` -- while the schema nests those inside
        `items`. Both spellings are right; only the comparison had to know that.
        """
        for element in contracted():
            with self.subTest(element=element):
                shape = SECTION_SHAPES[element]
                renderable = set(shape)
                items = shape.get("items") or {}
                renderable |= set(((items.get("items") or {}).get("properties") or {}))
                described = set(contract(element).get("fields") or {})
                self.assertTrue(described <= renderable,
                                f"{element} documents {sorted(described - renderable)}")


class RoutingTests(unittest.TestCase):
    """Junior Bay has no feature or benefit element. The contracts route those facts rather than
    leaving the model to guess -- and it guessed bragging_points."""

    def test_features_route_to_the_numbered_list(self):
        self.assertEqual(route_table()["feature"], "numbered_list")
        self.assertIn("specification", routes_for("numbered_list"))

    def test_benefits_route_to_a_content_block(self):
        self.assertEqual(route_table()["benefit"], "content_block")

    def test_quantified_social_proof_routes_to_bragging_points(self):
        # The routable half of "social proof". Ratings and counts ARE evidence.
        self.assertEqual(route_table()["quantified_social_proof"], "bragging_points")

    def test_an_attributed_testimonial_routes_nowhere(self):
        # The unroutable half: generating one fabricates a review, so it stays floored (§A.7).
        self.assertNotIn("testimonial", route_table())
        self.assertIn("testimonials", FLOOR_SECTIONS)

    def test_every_route_names_an_element_that_can_be_emitted(self):
        for kind, element in route_table().items():
            with self.subTest(kind=kind):
                self.assertIn(element, SECTION_SHAPES)


class BraggingPointTests(unittest.TestCase):
    """The measured failure, and the mechanical rule that catches it."""

    def test_the_reported_page_is_rejected(self):
        found = violations(REPORTED)
        self.assertGreaterEqual(len(found), 5)

    def test_a_value_with_no_figure_is_rejected(self):
        for value in ("Premium Quality", "Built to Last", "Great for Busy Moms",
                      "Strawberry, Blueberry, and Vanilla"):
            with self.subTest(value=value):
                found = violations([{"id": "b", "type": "bragging_points",
                                     "items": [{"value": value, "label": "x"}]}])
                self.assertTrue(found)
                self.assertIn("no figure", found[0]["reason"])

    def test_a_figure_buried_in_a_sentence_is_rejected(self):
        # "30g of premium milk protein" HAS a digit -- the fault is that the card wanted "30g".
        found = violations([{"id": "b", "type": "bragging_points",
                             "items": [{"value": "30g of premium milk protein", "label": "Per Scoop"}]}])
        self.assertIn("sentence, not a stat", found[0]["reason"])

    def test_a_rejection_says_where_the_fact_should_go_instead(self):
        # A complaint the model can act on beats one it can only apologise for.
        found = violations([{"id": "b", "type": "bragging_points",
                             "items": [{"value": "Premium Quality", "label": "x"}]}])
        self.assertIn("numbered_list", found[0]["reason"])
        self.assertIn("content_block", found[0]["reason"])

    def test_real_stats_pass(self):
        self.assertEqual(violations(CORRECTED), [])

    def test_the_spec_s_own_good_examples_pass(self):
        items = contract("bragging_points")["good"]
        self.assertEqual(violations([{"id": "b", "type": "bragging_points", "items": items}]), [])

    def test_the_spec_s_own_bad_examples_are_caught(self):
        # A documented counter-example the checker accepts is a lie in the documentation.
        for case in contract("bragging_points")["bad"]:
            with self.subTest(value=case["value"]):
                item = {k: v for k, v in case.items() if k != "why"}
                self.assertTrue(violations([{"id": "b", "type": "bragging_points", "items": [item]}]))

    def test_too_many_points_are_rejected_with_the_ideal_named(self):
        items = [{"value": f"{n}0g", "label": "x"} for n in range(1, 10)]
        found = violations([{"id": "b", "type": "bragging_points", "items": items}])
        self.assertIn("at most 7", found[0]["reason"])
        self.assertIn("strongest 3", found[0]["reason"])

    def test_the_stat_ceiling_is_generous_enough_for_real_stats(self):
        for value in ("10M+", "4.9/5", "30 years", "97%", "9,400+", "24 hours"):
            with self.subTest(value=value):
                self.assertLessEqual(len(value), MAX_STAT_CHARS)


class OtherElementTests(unittest.TestCase):
    def test_an_attributed_quote_is_rejected(self):
        # An attributed quote is a testimonial, and a generated testimonial is a fabricated review.
        found = violations([{"id": "q", "type": "quote",
                             "text": '"Best protein I have ever had!" - Sarah M.'}])
        self.assertTrue(found)
        self.assertIn("testimonial", found[0]["reason"])

    def test_an_unattributed_pull_quote_passes(self):
        self.assertEqual(violations([{"id": "q", "type": "quote",
                                      "text": "The hardest part is remembering to take it."}]), [])

    def test_an_overlong_seo_title_is_rejected(self):
        found = violations([{"id": "t", "type": "seo_title", "text": "x" * 80}])
        self.assertIn("about 60", found[0]["reason"])

    def test_elements_without_a_contract_are_left_alone(self):
        self.assertEqual(violations([{"id": "x", "type": "not_an_element", "text": "hi"}]), [])

    def test_it_survives_junk(self):
        for value in (None, [], [None], ["string"], [{"type": None}]):
            with self.subTest(value=value):
                violations(value)


class ValidatorTests(unittest.TestCase):
    def test_it_raises_into_the_repair_loop(self):
        with self.assertRaises(ValueError) as caught:
            assert_contracts({"sections": REPORTED})
        self.assertIn("bragging_points", str(caught.exception))

    def test_clean_output_passes_silently(self):
        assert_contracts({"sections": CORRECTED})


class PromptTests(unittest.TestCase):
    def test_the_prompt_leads_with_the_job_not_the_shape(self):
        # A model that only knows shapes puts a sentence in a card built for a number.
        text = for_prompt(["bragging_points"])
        self.assertLess(text.index("WHAT IT IS FOR"), text.index("FIELDS"))

    def test_the_prompt_carries_the_boundary_and_the_neighbours(self):
        text = for_prompt(["bragging_points"])
        self.assertIn("DO NOT USE WHEN", text)
        self.assertIn("NOT numbered_list", text)
        self.assertIn("WRONG", text)

    def test_design_rules_reach_the_prompt(self):
        # "With exactly one item, use contrast" is invisible otherwise.
        self.assertIn("contrast", for_prompt(["bragging_points"]))

    def test_an_unknown_element_contributes_nothing(self):
        self.assertEqual(for_prompt(["not_an_element"]), "")


class NumberedListShapeTests(unittest.TestCase):
    """`numbered_list` items are plain STRINGS, and three places have to agree about that.

    The renderer is the authority: `render_numbered_list` does `str(item or "").strip()` into one <p> per
    item. The generation schema said {label, value} objects, so the model dutifully emitted objects, and the
    builder's loader coerced them with String(i) — which is how a real generated page ended up showing
    "[object Object]" three times (author, 2026-09-29).
    """

    def test_the_schema_asks_for_strings(self):
        from stripe_link.domain.ai_schema import SECTION_SHAPES

        self.assertEqual(SECTION_SHAPES["numbered_list"]["items"]["items"]["type"], "string")

    def test_the_contract_shows_string_examples(self):
        from stripe_link.domain.ai_elements import contract

        for example in contract("numbered_list")["good"]:
            with self.subTest(example=example):
                self.assertIsInstance(example, str, "an object example teaches the model the wrong shape")

    def test_the_contract_names_the_object_mistake_explicitly(self):
        from stripe_link.domain.ai_elements import contract

        bad = json.dumps(contract("numbered_list")["bad"])
        self.assertIn("object Object", bad, "the failure it caused should be the lesson")

    def test_the_renderer_still_only_understands_strings(self):
        # The assertion that keeps the other three honest: if the renderer ever learns objects, this fails
        # and whoever changed it has to update the schema and the builder in the same breath.
        from stripe_link.runtime.html import render_numbered_list

        html = render_numbered_list({"id": "n1", "items": [{"label": "Steel", "value": "Double-walled."}]})
        # It does not reject the object, it STRINGIFIES it — which is the whole problem. The raw dict keys
        # leak onto the page, so the failure is visible to a buyer rather than caught anywhere.
        self.assertIn("label", html, "an object leaks its keys onto the page")
        self.assertIn("&#x27;", html, "and its quoting — this is a Python repr, not content")


class PolicyTermTests(unittest.TestCase):
    """A policy term is never a bragging point, however numeric it looks.

    The field floor did not catch "30 days / Refund window" because the claim was perfectly GROUNDED — the
    brief carried a 30-day policy. Being true was never the question; being EVIDENCE was. This is an element
    contract violation, not a grounding one, which is exactly why both layers exist.
    """

    def _violations(self, items):
        from stripe_link.domain.ai_elements import violations

        return violations([{"id": "b1", "type": "bragging_points", "items": items}])

    def test_a_refund_window_is_refused(self):
        found = self._violations([{"value": "30 days", "label": "Refund window"}])
        self.assertTrue(found)
        self.assertIn("policy term", found[0]["reason"])

    def test_every_policy_flavour_is_caught(self):
        for label in ("Refund window", "Return period", "Warranty length", "Money-back guarantee",
                      "Exchange window"):
            with self.subTest(label=label):
                self.assertTrue(self._violations([{"value": "30 days", "label": label}]))

    def test_a_real_measurement_is_still_allowed(self):
        # The check must not swallow genuine stats. "30g of protein" is evidence; "30 days to return" is not.
        self.assertEqual(self._violations([{"value": "30g", "label": "of protein per scoop"},
                                           {"value": "4.9/5", "label": "Average customer rating"}]), [])

    def test_it_reaches_the_repair_loop_rather_than_being_stripped(self):
        # violations() feeds the repair round, so the model gets told and rewrites it — a silently dropped
        # card would leave the tenant wondering why they asked for four stats and got three.
        found = self._violations([{"value": "30 days", "label": "Refund window"}])
        self.assertEqual(found[0]["element"], "bragging_points")


class TonePresetTests(unittest.TestCase):
    """The tenant's VOICE reaches the palette, not just the words.

    `tone` was collected, bounded to five values, and changed only the copy — so every generated page came
    out "clean-slate", the first fallback, whatever the tenant said they sounded like (author, 2026-09-29).

    Deliberately a table rather than the model's judgment: picking a palette is a taste call with nothing to
    ground it, and a deterministic resolver can be explained to a tenant, reproduced, and tested. The
    shortlist is still returned, so handing the final pick to the model later needs no rework.
    """

    def _preset(self, **kwargs):
        from stripe_link.domain.ai_resolvers import resolve_preset

        return resolve_preset(**kwargs)

    def test_voice_changes_the_default_for_the_same_product(self):
        chosen = {tone: self._preset(category="electronics", tone=tone)["value"]
                  for tone in ("warm", "technical", "premium")}
        self.assertEqual(len(set(chosen.values())), 3, f"each voice should land somewhere else: {chosen}")

    def test_no_tone_still_resolves(self):
        # The old behaviour has to survive: a brief without a tone is valid, tone being optional.
        self.assertTrue(self._preset(category="electronics")["value"])

    def test_the_CATEGORY_keeps_its_say(self):
        # A playful supplement brand is still a supplement brand. Tone REORDERS the category's shortlist
        # rather than replacing it, so the palette never chases the adjective out of its own sector.
        from stripe_link.domain.ai_resolvers import CATEGORY_PRESETS

        decision = self._preset(category="supplement", tone="playful")
        self.assertIn(decision["value"], CATEGORY_PRESETS["supplement"])

    def test_the_options_are_unchanged_only_the_default_moves(self):
        plain = set(self._preset(category="supplement")["shortlist"])
        toned = set(self._preset(category="supplement", tone="premium")["shortlist"])
        self.assertTrue(plain.issubset(toned), "a tone must not take options away")

    def test_an_explicit_request_and_a_tenant_preset_still_win(self):
        # Precedence is the file's contract: explicit > tenant > rules > AI. Tone lives at the bottom.
        self.assertEqual(
            self._preset(category="supplement", tone="playful", requested="royal-velvet")["source"],
            "explicit")
        self.assertEqual(
            self._preset(category="supplement", tone="playful", tenant_preset="trust-blue")["source"],
            "tenant")

    def test_an_unsupported_preset_is_never_chosen(self):
        decision = self._preset(category="supplement", tone="premium", supported={"clean-slate"})
        self.assertEqual(decision["value"], "clean-slate")

    def test_the_reason_names_the_voice(self):
        # "the AI chose it" is not a diagnosis — this file returns WHY for exactly that reason.
        self.assertIn("premium", self._preset(category="electronics", tone="premium")["why"])

    def test_an_unknown_tone_is_ignored_rather_than_breaking(self):
        self.assertTrue(self._preset(category="supplement", tone="shouty")["value"])
