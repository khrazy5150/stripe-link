"""The page brief -- the contract the generation pipeline meets at (plans/AI_PAGE_BRIEF.md).

The tests that matter most are the ones pinning the relationship between the brief and the §A.7
floor, because that is the design: the brief IS the grounding, so an answer the tenant gives is the
difference between copy that survives and copy that gets rejected into a repair round.
"""

import unittest

from stripe_link.domain.ai_floor import CLAIM_CLASSES, claim_violations
from stripe_link.domain.page_brief import (BOOKING_MODES, BriefError, KINDS, LICENCES, SOURCES,
                                           STEP_LABELS, TONES, field, grounding_text, kind_block,
                                           step_labels, steps_for, unlocked, validate, withheld)

CORE = {
    "kind": "physical",
    "name": "Poliaxis Creatine Gummies",
    "what_it_is": "Creatine monohydrate in a chewable gummy, sold as a monthly subscription.",
    "audience": "Lifters in their 20s-40s who dislike swallowing powder.",
    "facts": ["5g creatine monohydrate per serving", "60 gummies per tub"],
    "price": {"unit_amount": 3291, "currency": "usd",
              "pricing_model": "recurring", "recurring_interval": "month"},
}
SERVICE = {**CORE, "kind": "service", "service": {"duration_minutes": 60, "location_mode": "remote"}}


class StepTests(unittest.TestCase):
    def test_the_kind_decides_the_steps(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(len(steps_for(kind)), 9)

    def test_a_download_is_never_asked_about_shipping(self):
        self.assertIn("delivery", steps_for("digital"))
        self.assertNotIn("shipping_use", steps_for("digital"))

    def test_a_physical_product_is_never_asked_about_sessions(self):
        self.assertIn("shipping_use", steps_for("physical"))
        self.assertNotIn("session", steps_for("physical"))

    def test_nothing_is_offered_until_the_kind_is_known(self):
        # The shape cannot be known before the kind, so the wizard must not pretend otherwise.
        self.assertEqual(steps_for(""), ["identity"])
        self.assertEqual(steps_for("nonsense"), ["identity"])

    def test_every_step_has_a_label(self):
        for kind in KINDS:
            for step in steps_for(kind):
                with self.subTest(kind=kind, step=step):
                    self.assertIn(step, STEP_LABELS)

    def test_labels_come_back_in_step_order(self):
        self.assertEqual(step_labels("service")[0], STEP_LABELS["identity"])
        self.assertEqual(step_labels("service")[-1], STEP_LABELS["review"])


class ValidationTests(unittest.TestCase):
    def test_a_minimal_brief_is_enough(self):
        validate(CORE)   # four answers and a price; optional stays optional

    def test_the_kind_is_required_first(self):
        with self.assertRaises(BriefError) as caught:
            validate({**CORE, "kind": ""})
        self.assertIn("physical, digital, or a service", str(caught.exception))

    def test_each_required_core_answer_is_enforced(self):
        for missing in ("name", "what_it_is", "audience"):
            with self.subTest(missing=missing):
                with self.assertRaises(BriefError):
                    validate({**CORE, missing: ""})

    def test_at_least_one_fact_is_required(self):
        # Facts are the substance of almost every generatable section; none means nothing to say.
        with self.assertRaises(BriefError):
            validate({**CORE, "facts": []})

    def test_facts_may_be_typed_as_lines(self):
        validate({**CORE, "facts": "5g per serving\n60 per tub"})

    def test_a_price_must_be_a_positive_integer_amount(self):
        for bad in (0, -1, "3291", 32.91, None):
            with self.subTest(bad=bad):
                with self.assertRaises(BriefError):
                    validate({**CORE, "price": {"unit_amount": bad, "currency": "usd"}})

    def test_a_recurring_price_needs_an_interval(self):
        with self.assertRaises(BriefError):
            validate({**CORE, "price": {"unit_amount": 3291, "currency": "usd",
                                        "pricing_model": "recurring"}})

    def test_a_service_must_say_how_long_and_where(self):
        # The one kind block that can block: a service page unable to say either is not worth making.
        with self.assertRaises(BriefError):
            validate({**SERVICE, "service": {"location_mode": "remote"}})
        with self.assertRaises(BriefError):
            validate({**SERVICE, "service": {"duration_minutes": 60}})
        validate(SERVICE)

    def test_a_digital_brief_needs_no_kind_answers_at_all(self):
        validate({**CORE, "kind": "digital"})

    def test_an_unknown_tone_or_source_is_refused(self):
        with self.assertRaises(BriefError):
            validate({**CORE, "tone": "shouty"})
        with self.assertRaises(BriefError):
            validate({**CORE, "source": "telepathy"})

    def test_the_declared_vocabularies_are_self_consistent(self):
        self.assertIn("wizard", SOURCES)
        self.assertIn("existing_product", SOURCES)   # the entry point that skips known answers
        self.assertIn("direct", TONES)
        self.assertIn("scheduled", BOOKING_MODES)


class LicenceTests(unittest.TestCase):
    def test_every_licence_names_a_real_claim_class(self):
        # A licence for a class the floor does not know would silently grant nothing.
        for path, cls in LICENCES.items():
            with self.subTest(path=path):
                self.assertIn(cls, CLAIM_CLASSES)

    def test_a_thin_brief_licenses_nothing(self):
        self.assertEqual(unlocked(CORE), [])

    def test_each_answer_unlocks_its_own_class(self):
        self.assertEqual(unlocked({**CORE, "guarantee": "30-day money back"}), ["guarantee"])
        self.assertEqual(unlocked({**CORE, "terms": "Cancel any time"}), ["cancellation"])
        self.assertEqual(unlocked({**CORE, "physical": {"shipping": "Free in the US"}}), ["shipping"])
        self.assertEqual(unlocked({**CORE, "certifications": ["GMP"]}), ["certification"])

    def test_withheld_says_what_is_missing_and_how_to_fix_it(self):
        classes = {w["claim_class"] for w in withheld(CORE)}
        self.assertIn("cancellation", classes)
        for entry in withheld(CORE):
            with self.subTest(cls=entry["claim_class"]):
                self.assertTrue(entry["prompt"].strip())
                self.assertTrue(entry["label"].strip())

    def test_withheld_does_not_nag_about_another_kinds_fields(self):
        # A download has nothing to ship; silence about shipping is not a gap worth reporting.
        classes = {w["claim_class"] for w in withheld({**CORE, "kind": "digital"})}
        self.assertNotIn("shipping", classes)
        self.assertNotIn("dosage", classes)
        self.assertIn("guarantee", classes)

    def test_answering_moves_a_class_from_withheld_to_unlocked(self):
        before = {w["claim_class"] for w in withheld(CORE)}
        self.assertIn("guarantee", before)
        after = {w["claim_class"] for w in withheld({**CORE, "guarantee": "30-day money back"})}
        self.assertNotIn("guarantee", after)

    def test_field_reads_flat_and_nested_paths_alike(self):
        self.assertEqual(field({**CORE, "physical": {"shipping": "x"}}, "physical.shipping"), "x")
        self.assertEqual(field(CORE, "guarantee"), None)
        self.assertEqual(kind_block({**CORE, "physical": {"shipping": "x"}}), {"shipping": "x"})
        self.assertEqual(kind_block({**CORE, "kind": "digital"}), {})


class GroundingTests(unittest.TestCase):
    """The design, in one pair of assertions: the brief IS the grounding."""

    COPY = [{"id": "f", "type": "faq", "items": [
        {"question": "Can I cancel?", "answer": "Yes, cancel any time with no fee."},
        {"question": "Guarantee?", "answer": "30-day money-back guarantee."},
        {"question": "Shipping?", "answer": "Ships free in the US."}]}]

    def test_identical_copy_fails_against_a_thin_brief(self):
        violations = claim_violations(self.COPY, grounding_text(CORE))
        self.assertTrue(violations)
        self.assertEqual({v["claim_class"] for v in violations},
                         {"cancellation", "guarantee", "shipping"})

    def test_and_passes_against_a_brief_that_answered_those_questions(self):
        rich = {**CORE, "guarantee": "30-day money-back guarantee",
                "terms": "Cancel any time, no fee",
                "physical": {"shipping": "Ships free in the US"}}
        self.assertEqual(claim_violations(self.COPY, grounding_text(rich)), [])

    def test_the_price_is_grounded_so_copy_may_state_it(self):
        text = grounding_text(CORE)
        self.assertIn("32.91", text)
        self.assertIn("month", text)

    def test_must_say_lines_are_grounded(self):
        # A tenant who insists on a sentence must not have it rejected as ungrounded.
        text = grounding_text({**CORE, "must_say": ["Made in small batches in Oregon"]})
        self.assertIn("small batches in Oregon", text)

    def test_the_kind_block_is_grounded_whichever_kind_it_is(self):
        self.assertIn("PDF", grounding_text({**CORE, "kind": "digital", "digital": {"format": "PDF, 48 pages"}}))
        self.assertIn("remote", grounding_text(SERVICE))

    def test_it_survives_junk(self):
        for value in (None, {}, {"facts": None}, {"price": "free"}):
            with self.subTest(value=value):
                grounding_text(value)
