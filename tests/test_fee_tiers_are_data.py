"""Adding a pricing rung must be a configuration change, not a deploy.

The thing this exists to stop coming back: a hardcoded list of tier names. There was one -- it required
four specific tiers to exist and quietly ignored any fifth -- so a new rung meant editing Python, and a
rung added without one of its fee classes passed validation and then charged the free rate.
"""
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain.documents import (DEFAULT_PLATFORM_FEE_TIER,  # noqa: E402
                                          DocumentValidationError,
                                          validate_global_billing_config)
from stripe_link.domain.fees import (DEFAULT_GLOBAL_BILLING_CONFIG, apply_tier_overrides,  # noqa: E402
                                     platform_fee_rate)
from stripe_link.domain.platform_billing import plan_limit, plan_limits  # noqa: E402

FLAT_2 = {"physical": 2.0, "service": 2.0, "digital": 2.0, "tip_jar": 0.0}


def a_document(tiers):
    return {
        "schema_version": "2026-06-04", "document_type": "global_billing_config",
        "effective_date": "2026-10-21", "canonical": True,
        "created_at": 1780000000, "updated_at": 1792600000,
        "platform_fees": {"unit": "percent", "tiers": tiers},
        "payment_processing": {"schedules": {"US_USD": {
            "merchant_loc": "US", "settlement_currency": "USD",
            "rates": {"domestic_card": {"percentage": 2.9, "fixed_cents": 30, "condition": "always"}}}}},
    }


class ANewRungNeedsNoCodeTests(unittest.TestCase):
    def test_a_tier_nobody_named_in_python_validates(self):
        doc = a_document({"free": {"physical": 5.0, "service": 6.0, "digital": 7.0, "tip_jar": 5.0},
                          "pro_max": FLAT_2, "elite": FLAT_2})
        validate_global_billing_config(doc)  # must not raise

    def test_an_override_adds_a_rung_without_touching_the_baseline(self):
        merged = apply_tier_overrides(DEFAULT_GLOBAL_BILLING_CONFIG, {"pro_max": FLAT_2})
        self.assertIn("pro_max", merged["platform_fees"]["tiers"])
        self.assertNotIn("pro_max", DEFAULT_GLOBAL_BILLING_CONFIG["platform_fees"]["tiers"])
        self.assertEqual(
            platform_fee_rate(merged, tenant_plan="pro_max", product_type="digital"),
            Decimal("2") / 100)

    def test_an_override_cannot_destroy_the_processing_schedule(self):
        # It merges per TIER. An editor adding a rung must not be able to delete the thing that
        # grosses up every price on the platform.
        merged = apply_tier_overrides(DEFAULT_GLOBAL_BILLING_CONFIG, {"pro_max": FLAT_2})
        self.assertIn("US_USD", merged["payment_processing"]["schedules"])
        for tier in DEFAULT_GLOBAL_BILLING_CONFIG["platform_fees"]["tiers"]:
            self.assertIn(tier, merged["platform_fees"]["tiers"])

    def test_an_override_can_adjust_one_rate_without_restating_the_tier(self):
        merged = apply_tier_overrides(DEFAULT_GLOBAL_BILLING_CONFIG, {"pro": {"digital": 1.0}})
        tier = merged["platform_fees"]["tiers"]["pro"]
        self.assertEqual(tier["digital"], 1.0)
        self.assertEqual(tier["physical"], Decimal("2.0"))  # untouched

    def test_junk_overrides_are_ignored_rather_than_applied(self):
        merged = apply_tier_overrides(DEFAULT_GLOBAL_BILLING_CONFIG,
                                      {"": FLAT_2, "bad": "not-a-map", "ok": FLAT_2})
        tiers = merged["platform_fees"]["tiers"]
        self.assertIn("ok", tiers)
        self.assertNotIn("bad", tiers)
        self.assertNotIn("", tiers)


class TheFloorMustSurviveTests(unittest.TestCase):
    def test_a_document_without_the_free_tier_is_refused(self):
        # It is what an unknown or retired tier resolves to. Without it a typo has nothing safe to
        # land on, and the cheapest wrong answer becomes somebody's bill.
        with self.assertRaises(DocumentValidationError) as caught:
            validate_global_billing_config(a_document({"pro_max": FLAT_2}))
        self.assertIn(DEFAULT_PLATFORM_FEE_TIER, str(caught.exception))

    def test_an_empty_tier_table_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_global_billing_config(a_document({}))

    def test_a_rung_missing_a_fee_class_is_refused_rather_than_silently_free(self):
        # The old failure: an incomplete tier validated, then fell through to the free rate at read
        # time -- configured-looking and charging nothing extra.
        incomplete = {"physical": 2.0, "service": 2.0, "digital": 2.0}  # no tip_jar
        with self.assertRaises(DocumentValidationError) as caught:
            validate_global_billing_config(
                a_document({"free": {"physical": 5.0, "service": 6.0, "digital": 7.0, "tip_jar": 5.0},
                            "pro_max": incomplete}))
        self.assertIn("pro_max", str(caught.exception))


class AllowancesAreDataTooTests(unittest.TestCase):
    """So "Pro-Max includes 20 videos" is a row edit, not a new accessor."""

    def test_a_capability_nobody_wrote_an_accessor_for_reads_back(self):
        plan = {"ai_generations": 20, "ai_images": 200, "limits": {"ai_videos": 20}}
        self.assertEqual(plan_limit(plan, "ai_videos"), 20)
        self.assertEqual(plan_limits(plan),
                         {"ai_generations": 20, "ai_images": 200, "ai_videos": 20})

    def test_an_unset_capability_is_zero_not_unlimited(self):
        self.assertEqual(plan_limit({"limits": {}}, "ai_videos"), 0)
        self.assertEqual(plan_limit(None, "anything"), 0)

    def test_the_named_fields_still_work_for_plans_that_predate_limits(self):
        self.assertEqual(plan_limits({"ai_generations": 20, "ai_images": 200}),
                         {"ai_generations": 20, "ai_images": 200})

    def test_limits_wins_where_both_are_set(self):
        # One place to look when they disagree, and it is the editable one.
        self.assertEqual(plan_limit({"ai_images": 30, "limits": {"ai_images": 200}}, "ai_images"), 200)
