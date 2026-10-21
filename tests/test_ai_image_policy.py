"""What a tenant may ask the image generator for, and what we actually send.

The policy half of the feature. Everything here is pure, and every test is about a way the money or the
ownership could go wrong quietly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain import ai_images  # noqa: E402
from stripe_link.domain.ai_quota import (OPERATION_IMAGE, entitlement_for,  # noqa: E402
                                         image_period, quality_ceiling_for)
from stripe_link.domain.platform_billing import (DEFAULT_AI_IMAGE_QUALITY,  # noqa: E402
                                                 plan_ai_image_quality, plan_ai_images)

NOW = 1_800_000_000
LIVE_TRIAL = {"billing_status": "trial", "trial_ends_at": NOW + 86400}


class QualityIsACeilingTests(unittest.TestCase):
    """`high` costs 15x `low`, and the parameter travels in the request body."""

    def test_a_request_above_the_ceiling_is_clamped_not_refused(self):
        # The control that offered it was built from the same ceiling, so a request above it means a
        # stale page, not an attack. Give them what they are entitled to; never send the dearer one.
        self.assertEqual(ai_images.clamp_quality("high", "low"), "low")
        self.assertEqual(ai_images.clamp_quality("medium", "low"), "low")

    def test_a_request_below_the_ceiling_is_honoured(self):
        self.assertEqual(ai_images.clamp_quality("low", "high"), "low")

    def test_an_unknown_quality_never_buys_the_dear_one(self):
        for junk in ("ultra", "", None, "HIGHEST"):
            self.assertEqual(ai_images.clamp_quality(junk, "low"), "low")
        # Even against a generous ceiling, nonsense gets the default rather than the top of the ladder.
        self.assertEqual(ai_images.clamp_quality("ultra", "high"), "low")

    def test_an_unknown_ceiling_fails_closed(self):
        # A profile carrying a quality we have since retired must not become unlimited.
        self.assertEqual(ai_images.clamp_quality("high", "platinum"), "low")

    def test_the_ladder_is_ordered_cheapest_first(self):
        self.assertEqual(ai_images.QUALITIES, ("low", "medium", "high"))
        self.assertLess(ai_images.rank("low"), ai_images.rank("high"))


class TheUiRendersWhatTheServerSendsTests(unittest.TestCase):
    """A one-entry list renders no control. That is why there is no quality selector today."""

    def test_a_low_ceiling_offers_exactly_one_choice(self):
        self.assertEqual([q["value"] for q in ai_images.allowed_qualities("low")], ["low"])

    def test_lifting_the_ceiling_grows_the_list_with_no_other_change(self):
        self.assertEqual([q["value"] for q in ai_images.allowed_qualities("medium")], ["low", "medium"])
        self.assertEqual([q["value"] for q in ai_images.allowed_qualities("high")],
                         ["low", "medium", "high"])

    def test_every_option_carries_its_credit_cost(self):
        # All 1 today because every tier is `low`. The field exists so a weighted charge can arrive
        # without a migration -- `consume_if_available` already takes `by=`.
        for option in ai_images.allowed_qualities("high"):
            self.assertEqual(option["credits"], 1)
        self.assertEqual(ai_images.credits_for("high", 4), 4)
        self.assertEqual(ai_images.credits_for("low", 1), 1)


class StyleIsAPromptFragmentTests(unittest.TestCase):
    """The provider has no `style` parameter -- proven 2026-10-20 by sending one and being refused."""

    def test_the_tenants_words_come_first_and_are_not_edited(self):
        composed = ai_images.compose_prompt("a golden retriever waiting by the door", "lifestyle")
        self.assertTrue(composed.startswith("a golden retriever waiting by the door"))
        self.assertIn("natural window light", composed)

    def test_no_style_leaves_the_prompt_alone(self):
        self.assertEqual(ai_images.compose_prompt("a red cube", ""), "a red cube")

    def test_an_unknown_style_is_no_style_rather_than_an_error(self):
        # A stale page naming a style we have retired must still generate.
        self.assertEqual(ai_images.compose_prompt("a red cube", "vaporwave"), "a red cube")

    def test_config_overrides_the_built_in_vocabulary(self):
        config = {"ai_image_styles": [{"value": "noir", "label": "Noir", "fragment": "high contrast"}]}
        self.assertEqual([s["value"] for s in ai_images.styles(config)], ["noir"])
        self.assertEqual(ai_images.compose_prompt("a street", "noir", config), "a street. high contrast")

    def test_a_style_with_no_fragment_is_dropped_not_rendered(self):
        # A button that does nothing is worse than a button that is not there.
        config = {"ai_image_styles": [{"value": "broken", "label": "Broken"}]}
        self.assertEqual([s["value"] for s in ai_images.styles(config)],
                         [s["value"] for s in ai_images.DEFAULT_STYLES])

    def test_the_composed_prompt_is_bounded(self):
        self.assertLessEqual(len(ai_images.compose_prompt("x" * 5000, "lifestyle")), ai_images.MAX_PROMPT)


class ImagesAreAlwaysPlatformPaidTests(unittest.TestCase):
    """The trap this exists to stop, and it would have been silent."""

    def test_a_byok_page_key_does_not_buy_200_images_on_our_card(self):
        # Page generation asks who pays, because a tenant on their own key spends their own money and
        # earns a far higher ceiling. There is no BYO-key path for images, so reading that branch would
        # hand anyone who configured a key 200 images billed to us.
        pages = entitlement_for(LIVE_TRIAL, provider="openai", now=NOW, trial_allowance=3)
        images = entitlement_for(LIVE_TRIAL, provider="openai", now=NOW, trial_allowance=7,
                                 operation=OPERATION_IMAGE)
        self.assertEqual((pages["allowance"], pages["source"]), (200, "byok"))
        self.assertEqual((images["allowance"], images["source"]), (7, "trial"))

    def test_an_unconfigured_provider_still_allows_images(self):
        # "unconfigured" refuses PAGE generation because nobody has chosen a model. Images have one
        # provider and always did, so that refusal would be about a question images never ask.
        pages = entitlement_for(LIVE_TRIAL, provider="", now=NOW, trial_allowance=3)
        images = entitlement_for(LIVE_TRIAL, provider="", now=NOW, trial_allowance=7,
                                 operation=OPERATION_IMAGE)
        self.assertEqual(pages["source"], "unconfigured")
        self.assertEqual((images["allowance"], images["source"]), (7, "trial"))


class TheImageCounterTests(unittest.TestCase):
    def test_the_trial_counter_is_a_lifetime_one(self):
        # A monthly key would hand a trial starting on the 25th a fresh seven in six days.
        got = entitlement_for(LIVE_TRIAL, provider="bedrock", now=NOW, trial_allowance=7,
                              operation=OPERATION_IMAGE)
        self.assertEqual(got["period"], "images#trial")

    def test_a_subscriber_counts_monthly_and_reads_the_denormalized_number(self):
        profile = {"stripe_subscription_id": "sub_1", "ai_images": 30}
        got = entitlement_for(profile, provider="bedrock", now=NOW, operation=OPERATION_IMAGE)
        self.assertEqual(got["allowance"], 30)
        self.assertEqual(got["source"], "plan")
        self.assertTrue(got["period"].startswith("images#2"))

    def test_a_subscriber_whose_webhook_has_not_run_gets_the_lowest_rung_not_nothing(self):
        got = entitlement_for({"stripe_subscription_id": "sub_1"}, provider="bedrock", now=NOW,
                              operation=OPERATION_IMAGE)
        self.assertEqual(got["allowance"], 30)

    def test_the_free_tier_gets_none(self):
        got = entitlement_for({"billing_status": "canceled"}, provider="bedrock", now=NOW,
                              free_allowance=0, operation=OPERATION_IMAGE)
        self.assertEqual((got["allowance"], got["source"]), (0, "free"))

    def test_an_expired_trial_gets_none(self):
        expired = {"billing_status": "trial", "trial_ends_at": NOW - 1}
        got = entitlement_for(expired, provider="bedrock", now=NOW, trial_allowance=7,
                              free_allowance=0, operation=OPERATION_IMAGE)
        self.assertEqual((got["allowance"], got["source"]), (0, "free"))

    def test_an_unreadable_profile_is_not_a_trial(self):
        # `_profile()` returns {} when the read fails. Defaulting that to a trial would be an open tap.
        got = entitlement_for({}, provider="bedrock", now=NOW, trial_allowance=7, free_allowance=0,
                              operation=OPERATION_IMAGE)
        self.assertEqual(got["allowance"], 0)

    def test_the_image_counter_never_collides_with_the_page_counter(self):
        pages = entitlement_for(LIVE_TRIAL, provider="bedrock", now=NOW, trial_allowance=3)
        images = entitlement_for(LIVE_TRIAL, provider="bedrock", now=NOW, trial_allowance=7,
                                 operation=OPERATION_IMAGE)
        self.assertNotEqual(pages["period"], images["period"])
        self.assertEqual(image_period(pages["period"]), images["period"])

    def test_prefixing_is_idempotent(self):
        self.assertEqual(image_period("images#trial"), "images#trial")


class OneCeilingResolverTests(unittest.TestCase):
    """The screen must report the ceiling the generator will clamp to, or they disagree in public."""

    def test_a_trial_reads_the_config_ceiling(self):
        self.assertEqual(quality_ceiling_for(LIVE_TRIAL, "trial", trial_quality="low"), "low")
        self.assertEqual(quality_ceiling_for(LIVE_TRIAL, "trial", trial_quality="medium"), "medium")

    def test_a_subscriber_reads_the_denormalized_plan_ceiling(self):
        profile = {"stripe_subscription_id": "sub_1", "ai_image_quality": "high"}
        self.assertEqual(quality_ceiling_for(profile, "plan"), "high")

    def test_a_profile_with_no_ceiling_gets_the_cheapest(self):
        self.assertEqual(quality_ceiling_for({"stripe_subscription_id": "s"}, "plan"), "low")

    def test_exempt_does_not_mean_expensive(self):
        # The platform pays for an exempt tenant too, so there is no reason to buy the dear one.
        self.assertEqual(quality_ceiling_for({"billing_exempt": True}, "exempt"), "low")


class PlanRowAccessorTests(unittest.TestCase):
    def test_a_missing_image_allowance_does_not_strand_a_paying_tenant(self):
        self.assertEqual(plan_ai_images({}), 30)
        self.assertEqual(plan_ai_images({"ai_images": 5}), 5)

    def test_a_missing_quality_falls_back_to_the_cheapest(self):
        # The two fallbacks fail in OPPOSITE directions, chosen by who is harmed: a paying tenant must
        # not be told they have no images, and an omission must not buy the 15x option on our card.
        self.assertEqual(plan_ai_image_quality({}), DEFAULT_AI_IMAGE_QUALITY)
        self.assertEqual(plan_ai_image_quality({"ai_image_quality": " HIGH "}), "high")


if __name__ == "__main__":
    unittest.main()
