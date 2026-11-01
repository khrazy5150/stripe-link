"""What comes off the refund, when it lands, and what you get back (P8 and P9).

A restocking fee, the outbound postage the buyer already paid, and how long the refund takes. Three facts
every mainstream returns policy states and this vocabulary could not express -- checked against TikTok
Shop's clothing policy, which states all three.

They are FIELDS ON THE POLICY, not a third primitive, because unlike `buyer_guarantees` they qualify the
same refund the window governs. The tests here pin the two things that makes them: the gates (a term is
silent wherever it would describe something that does not happen) and the wording's single source.
"""

import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_refund_policies
from stripe_link.domain.refund_policy import (
    CONDITION_LABELS,
    CONDITION_OPTIONS,
    DIGITAL,
    NON_REFUNDABLE,
    ORIGINAL_SHIPPING_NOT_REFUNDED,
    ORIGINAL_SHIPPING_REFUNDED,
    ORIGINAL_SHIPPING_UNSTATED,
    PHYSICAL,
    REFUND_PROCESSING_MAX_DAYS,
    RESOLUTION_OPTIONS,
    RESOLUTION_REFUND_ONLY,
    RESOLUTION_REPLACEMENT_FIRST,
    RESOLUTION_REPLACEMENT_OR_REFUND,
    RESTOCKING_FEE_MAX_PERCENT,
    SUBSCRIPTION,
    RefundPolicyError,
    build,
    generate_copy,
    normalize,
    refund_processing_days,
    refund_terms,
    restocking_fee_percent,
    vocabulary,
)
from stripe_link.domain.returns import KEEPS, RETURN_REQUIRED, REVOKE
from stripe_link.runtime.html import merchant_return_policy, render_refund_policy

FULL = {
    "refund_window": "30_days",
    "condition": "complete_in_packaging",
    "return_method": RETURN_REQUIRED,
    "return_shipping": "buyer_pays",
    "restocking_fee_percent": 15,
    "original_shipping": ORIGINAL_SHIPPING_NOT_REFUNDED,
    "refund_processing_days": 7,
    "resolution": RESOLUTION_REPLACEMENT_OR_REFUND,
    "policy_class": PHYSICAL,
}


class TheClamps(unittest.TestCase):
    """Clamped on read, refused on write -- this module's standing split. A form that rejects 80 teaches
    the tenant to fight it; a stored 80 that silently became a different promise is the fault the whole
    plan family exists to stop."""

    def test_a_fee_above_the_ceiling_is_held_at_it(self):
        self.assertEqual(restocking_fee_percent(80), RESTOCKING_FEE_MAX_PERCENT)

    def test_a_window_above_the_ceiling_is_held_at_it(self):
        self.assertEqual(refund_processing_days(999), REFUND_PROCESSING_MAX_DAYS)

    def test_nothing_chosen_is_zero_not_a_number(self):
        """0 rather than a default. These terms have no sensible fallback: a tenant who set no restocking
        fee has no restocking fee, and inventing one would be the platform promising on their behalf."""
        for value in (None, "", 0, -5, "abc", False):
            with self.subTest(value=value):
                self.assertEqual(restocking_fee_percent(value), 0)
                self.assertEqual(refund_processing_days(value), 0)

    def test_a_decimal_from_dynamo_reads_as_a_number(self):
        """`isinstance(x, int)` is False for the Decimal a stored document comes back as, and that trap
        has already 404'd published pages once (feedback_decimal_from_dynamo)."""
        from decimal import Decimal
        self.assertEqual(restocking_fee_percent(Decimal("15")), 15)
        self.assertEqual(refund_processing_days(Decimal("7")), 7)


class TheClauses(unittest.TestCase):
    def test_all_three_in_the_order_a_buyer_wants_them(self):
        """Order is load-bearing, for GUARANTEES' reason: less what, and when do I see the money. A buyer
        who has read one tenant's policy knows where to look on the next."""
        terms = refund_terms(FULL)
        self.assertEqual(len(terms), 4)
        self.assertIn("replace it or refund you", terms[0])
        self.assertIn("restocking fee of 15%", terms[1])
        self.assertIn("original shipping charge is not refunded", terms[2])
        self.assertIn("within 7 days of receiving your return", terms[3])

    def test_non_refundable_states_none_of_them(self):
        """There is no refund, so there is nothing to deduct from and nothing to time. A page saying "all
        sales are final" and then "we deduct 15%" would be describing two different policies."""
        self.assertEqual(refund_terms(dict(FULL, refund_window=NON_REFUNDABLE)), [])

    def test_nothing_is_restocked_when_nothing_comes_back(self):
        for method in (KEEPS, REVOKE):
            with self.subTest(method=method):
                terms = refund_terms(dict(FULL, return_method=method))
                self.assertFalse(any("restocking" in term for term in terms))

    def test_the_clock_starts_at_approval_when_nothing_comes_back(self):
        terms = refund_terms(dict(FULL, return_method=KEEPS))
        self.assertTrue(any("of approving your request" in term for term in terms))
        self.assertFalse(any("receiving your return" in term for term in terms))

    def test_nothing_shipped_means_no_outbound_charge_to_talk_about(self):
        """There is no outbound postage on a download or a renewal, so the sentence would be about a line
        that is not on the order."""
        for policy_class in (DIGITAL, SUBSCRIPTION):
            with self.subTest(policy_class=policy_class):
                terms = refund_terms(dict(FULL, policy_class=policy_class))
                self.assertFalse(any("shipping charge" in term for term in terms))

    def test_a_tenant_who_refunds_the_postage_gets_to_say_so(self):
        terms = refund_terms(dict(FULL, original_shipping=ORIGINAL_SHIPPING_REFUNDED))
        self.assertIn("We refund your original shipping charge too.", terms)

    def test_unstated_says_nothing_either_way(self):
        terms = refund_terms(dict(FULL, original_shipping=ORIGINAL_SHIPPING_UNSTATED))
        self.assertFalse(any("shipping charge" in term for term in terms))

    def test_a_replacement_is_physical_only(self):
        """A month of a subscription cannot be replaced, and re-granting a download is
        `digital_revoke_access` running backwards rather than a replacement."""
        for policy_class in (DIGITAL, SUBSCRIPTION):
            with self.subTest(policy_class=policy_class):
                terms = refund_terms(dict(FULL, policy_class=policy_class))
                self.assertFalse(any("replace" in term for term in terms))

    def test_a_replacement_survives_the_customer_keeping_the_item(self):
        """"Keep the broken one, here is a new one" is an ordinary policy for low-value goods, and the two
        fields are independent: `return_method` is about the ITEM, `resolution` about what travels back."""
        terms = refund_terms(dict(FULL, return_method=KEEPS))
        self.assertTrue(any("replace it or refund you" in term for term in terms))

    def test_replacement_first_reads_as_an_exchange_before_a_refund(self):
        terms = refund_terms(dict(FULL, resolution=RESOLUTION_REPLACEMENT_FIRST))
        self.assertIn("We replace the item. Where we cannot, we refund you instead.", terms)

    def test_refund_only_states_nothing(self):
        """There is no open question: a refund policy silent on replacements refunds you, and a sentence
        saying so is the noise CONDITION_OPTIONS["any"] deliberately omits."""
        terms = refund_terms(dict(FULL, resolution=RESOLUTION_REFUND_ONLY))
        self.assertFalse(any("replace" in term for term in terms))

    def test_nothing_set_states_nothing(self):
        self.assertEqual(refund_terms({"refund_window": "30_days", "return_method": RETURN_REQUIRED}), [])

    def test_never_raises_on_rubbish(self):
        """Lenient on read, like every other reader here: a malformed stored policy still renders
        something true rather than failing a publish."""
        for junk in (None, "", [], {"refund_window": None}, {"restocking_fee_percent": {}}):
            with self.subTest(junk=junk):
                self.assertIsInstance(refund_terms(junk), list)

    def test_the_timing_promise_is_about_issuing_not_arriving(self):
        """Pressing the button is the merchant's act and the only part of this they control. The card
        network then takes its own week, and promising the landing date would be promising a clock nobody
        in this system holds."""
        # From the END: the timing clause is last by design, and a positional index from the front rots
        # every time a term is added above it -- which it just did.
        term = refund_terms(FULL)[-1]
        self.assertIn("issue your refund", term)
        self.assertIn("Your bank may take a few days longer", term)

    def test_the_platform_is_never_named(self):
        """These are the TENANT's terms. A sentence naming Junior Bay would claim the platform deducts the
        fee or issues the refund, and it does neither."""
        for term in refund_terms(FULL) + refund_terms(dict(FULL, return_method=KEEPS,
                                                           original_shipping=ORIGINAL_SHIPPING_REFUNDED)):
            with self.subTest(term=term):
                text = term.lower()
                self.assertNotIn("junior", text)
                self.assertNotIn("jbay", text)
                self.assertNotIn("the platform", text)


class WritingThem(unittest.TestCase):
    def test_build_keeps_all_four(self):
        policy = build(PHYSICAL, refund_window="30_days", condition="unused",
                       return_method=RETURN_REQUIRED, restocking_fee=15,
                       original_shipping=ORIGINAL_SHIPPING_NOT_REFUNDED, processing_days=7,
                       resolution=RESOLUTION_REPLACEMENT_FIRST)
        self.assertEqual(policy["restocking_fee_percent"], 15)
        self.assertEqual(policy["resolution"], RESOLUTION_REPLACEMENT_FIRST)
        self.assertEqual(policy["original_shipping"], ORIGINAL_SHIPPING_NOT_REFUNDED)
        self.assertEqual(policy["refund_processing_days"], 7)

    def test_build_omits_what_was_not_chosen(self):
        """Absence is what "no restocking fee" looks like in the document. A stored
        `restocking_fee_percent: 0` would be a tenant's non-choice sitting there as a decision, and the
        settings screen reads these straight back."""
        policy = build(PHYSICAL, refund_window="30_days", condition="unused",
                       return_method=RETURN_REQUIRED)
        for field in ("restocking_fee_percent", "original_shipping", "refund_processing_days",
                      "resolution"):
            self.assertNotIn(field, policy)

    def test_build_refuses_an_unknown_original_shipping(self):
        with self.assertRaises(RefundPolicyError):
            build(PHYSICAL, refund_window="30_days", condition="unused",
                  return_method=RETURN_REQUIRED, original_shipping="half_of_it")

    def test_build_refuses_an_unknown_resolution(self):
        with self.assertRaises(RefundPolicyError):
            build(PHYSICAL, refund_window="30_days", condition="unused",
                  return_method=RETURN_REQUIRED, resolution="store_credit")

    def test_normalize_drops_rubbish_rather_than_coercing_it(self):
        """Unlike the three enums, which fall back to a class seed. A window has to be something; a
        restocking fee does not, and coercing nonsense into a real percentage would invent a deduction."""
        policy = normalize({"refund_window": "30_days", "condition": "any",
                            "return_method": RETURN_REQUIRED, "restocking_fee_percent": "lots",
                            "original_shipping": "sometimes"}, policy_class=PHYSICAL)
        self.assertNotIn("restocking_fee_percent", policy)
        self.assertNotIn("original_shipping", policy)

    def test_the_vocabulary_carries_the_templates_and_the_bounds(self):
        """The screens preview these live as the tenant types, and `{n}` is the ONE thing a browser may
        fill in. The bounds travel so a hint quotes the real cap instead of a literal that can drift."""
        terms = vocabulary()["terms"]
        self.assertIn("{n}", terms["restocking_fee"]["template"])
        self.assertEqual(terms["restocking_fee"]["max"], RESTOCKING_FEE_MAX_PERCENT)
        self.assertIn("{n}", terms["processing_days"]["template_after_return"])
        self.assertIn("{n}", terms["processing_days"]["template_after_approval"])
        self.assertEqual(terms["processing_days"]["max"], REFUND_PROCESSING_MAX_DAYS)

    def test_the_vocabulary_offers_the_outbound_choices_with_their_clauses(self):
        values = {o["value"]: o["clause"] for o in vocabulary()["original_shipping"]}
        self.assertEqual(values[ORIGINAL_SHIPPING_UNSTATED], "")
        self.assertTrue(values[ORIGINAL_SHIPPING_NOT_REFUNDED])
        self.assertTrue(values[ORIGINAL_SHIPPING_REFUNDED])

    def test_the_vocabulary_offers_the_resolutions_with_their_clauses(self):
        values = {o["value"]: o["clause"] for o in vocabulary()["resolutions"]}
        self.assertEqual(sorted(values), sorted(RESOLUTION_OPTIONS))
        self.assertEqual(values[RESOLUTION_REFUND_ONLY], "")
        self.assertTrue(values[RESOLUTION_REPLACEMENT_OR_REFUND])
        self.assertTrue(values[RESOLUTION_REPLACEMENT_FIRST])


class TheValidator(unittest.TestCase):
    def policies(self, **overrides):
        return {PHYSICAL: {"refund_window": "30_days", "condition": "unused",
                           "return_method": RETURN_REQUIRED, **overrides}}

    def test_a_fee_in_range_is_accepted(self):
        validate_refund_policies(self.policies(restocking_fee_percent=15), "cfg")

    def test_a_fee_above_the_ceiling_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(restocking_fee_percent=80), "cfg")

    def test_a_window_above_the_ceiling_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(refund_processing_days=90), "cfg")

    def test_zero_is_refused_rather_than_stored_as_a_non_choice(self):
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(restocking_fee_percent=0), "cfg")

    def test_an_unknown_resolution_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(resolution="store_credit"), "cfg")

    def test_an_unknown_outbound_choice_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(original_shipping="maybe"), "cfg")

    def test_return_shipping_is_checked_at_last(self):
        """It was enforced only by `build`, which substitutes a default rather than refusing -- so a typo
        became "the customer pays" silently. An enum the screen offers from a server-supplied list should
        be refused when it arrives as something else, so a stale bundle is caught, not guessed at."""
        with self.assertRaises(DocumentValidationError):
            validate_refund_policies(self.policies(return_shipping="someone_else"), "cfg")


class WhatGoogleReads(unittest.TestCase):
    def test_a_free_return_is_marked_up_as_one(self):
        for shipping in ("seller_pays", "seller_pays_label"):
            with self.subTest(shipping=shipping):
                node = merchant_return_policy(dict(FULL, return_shipping=shipping))
                self.assertEqual(node["returnFees"], "https://schema.org/FreeReturn")

    def test_a_buyer_paid_return_is_customer_responsibility(self):
        node = merchant_return_policy(FULL)
        self.assertEqual(node["returnFees"], "https://schema.org/ReturnFeesCustomerResponsibility")

    def test_return_shipping_fees_is_never_claimed(self):
        """Google requires a non-zero `returnShippingFeesAmount` with it, and the buyer arranges that
        postage themselves -- nothing in this system knows what it cost them. Claiming the category
        without the amount would be markup that fails its own validator."""
        for shipping in ("seller_pays", "seller_pays_label", "buyer_pays", "not_applicable"):
            node = merchant_return_policy(dict(FULL, return_shipping=shipping)) or {}
            with self.subTest(shipping=shipping):
                self.assertNotEqual(node.get("returnFees"), "https://schema.org/ReturnShippingFees")
                self.assertNotIn("returnShippingFeesAmount", node)

    def test_the_restocking_fee_is_a_bare_number(self):
        """Google reads a Number as a percentage of what the buyer paid, which is exactly what the tenant
        typed -- so no conversion and no currency are involved. `RestockingFees` is a schema.org value
        Google's ReturnFeesEnumeration does not accept, so it travels in its own property."""
        node = merchant_return_policy(FULL)
        self.assertEqual(node["restockingFee"], 15)
        self.assertNotEqual(node["returnFees"], "https://schema.org/RestockingFees")

    def test_a_refund_type_is_always_stated(self):
        """This node is only built for a finite window, which means a refund IS available -- so FullRefund
        is the honest default rather than an assumption, and it is another recommended property that was
        never sent."""
        self.assertEqual(merchant_return_policy(dict(FULL, resolution=RESOLUTION_REFUND_ONLY))["refundType"],
                         "https://schema.org/FullRefund")

    def test_replacement_first_marks_up_an_exchange(self):
        node = merchant_return_policy(dict(FULL, resolution=RESOLUTION_REPLACEMENT_FIRST))
        self.assertEqual(node["refundType"], "https://schema.org/ExchangeRefund")

    def test_a_choice_marks_up_the_money(self):
        """Google documents "one or more" for returnMethod and says no such thing for refundType, and both
        its examples carry one value -- so an array is not something to find out about in production. The
        money is the claim that holds either way."""
        node = merchant_return_policy(FULL)
        self.assertEqual(node["refundType"], "https://schema.org/FullRefund")

    def test_no_exchange_is_claimed_off_the_physical_class(self):
        """Markup and prose have to agree: `refund_terms` suppresses the clause there, so the property
        must suppress too, or a crawler reads a promise the page does not make."""
        node = merchant_return_policy(dict(FULL, resolution=RESOLUTION_REPLACEMENT_FIRST,
                                           policy_class=DIGITAL))
        self.assertEqual(node["refundType"], "https://schema.org/FullRefund")

    def test_no_fee_is_claimed_when_nothing_comes_back(self):
        """A tenant who set a fee and later switched to "customer keeps it" leaves the number in the
        document, and markup that still charged it would contradict the page."""
        node = merchant_return_policy(dict(FULL, return_method=KEEPS))
        self.assertNotIn("restockingFee", node)


class OnThePage(unittest.TestCase):
    def render(self, policy):
        return render_refund_policy({"id": "rp"}, {"refund_policy": policy}, {})

    def test_the_terms_render_as_a_list(self):
        html = self.render(FULL)
        self.assertIn('<ul class="sl-refund-policy-terms">', html)
        self.assertEqual(html.count("<li>"), 4)

    def test_no_empty_list_when_nothing_is_set(self):
        """An empty <ul> is a visible gap in a grid with a gap, and it says nothing."""
        html = self.render({k: v for k, v in FULL.items()
                            if k not in ("restocking_fee_percent", "original_shipping",
                                         "refund_processing_days", "resolution")})
        self.assertNotIn("sl-refund-policy-terms", html)

    def test_the_renderer_does_not_compose_the_wording(self):
        """`refund_terms` has to clamp the numbers, read the return method and know nothing ships to a
        subscriber -- all of which is what a policy MEANS. The renderer's job is markup, and a second
        copy of those gates is how two readers of one policy come to disagree."""
        import inspect
        from stripe_link.runtime import html as html_module
        source = inspect.getsource(html_module.render_refund_policy)
        self.assertIn("refund_policy_terms(policy)", source)
        self.assertNotIn("restocking", source)


class TagsAndHygieneSeals(unittest.TestCase):
    """APPAREL's `complete_in_packaging`, and not a stricter form of it: a garment has no packaging worth
    the name, and the two things a clothing seller needs intact are the price tag and the hygiene seal. A
    tenant selling swimwear had to choose between `unused` (unprovable) and `complete_in_packaging`
    (describing a box that never existed)."""

    def test_it_is_in_the_vocabulary_with_a_label(self):
        self.assertIn("tags_intact", CONDITION_OPTIONS)
        self.assertIn("tags_intact", CONDITION_LABELS)

    def test_it_reads_as_a_sentence(self):
        _, full = generate_copy(PHYSICAL, "30_days", "tags_intact")
        self.assertEqual(full, "Refunds are available within 30 days of delivery with tags attached "
                               "and any hygiene seals intact.")

    def test_every_condition_still_has_a_preview(self):
        """The matrix is generated, so a value added to one table and not the other would leave a picker
        option whose preview is missing rather than wrong -- the harder failure to notice."""
        previews = vocabulary()["previews"]
        for condition in CONDITION_OPTIONS:
            with self.subTest(condition=condition):
                self.assertIn(f"{PHYSICAL}|30_days|{condition}", previews)


if __name__ == "__main__":
    unittest.main()
