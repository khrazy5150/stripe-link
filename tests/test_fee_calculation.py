import unittest

from stripe_link.domain.fees import calculate_price, fee_class_for, platform_fee_rate
from decimal import Decimal


BILLING_CONFIG = {
    "platform_fees": {
        "unit": "percent",
        "tiers": {
            "basic": {
                "physical": 10.0,
                "digital": 15.0,
                "tip_jar": 5.0,
            },
        },
    },
    "payment_processing": {
        "schedules": {
            "US_USD": {
                "merchant_loc": "US",
                "settlement_currency": "USD",
                "rates": {
                    "domestic_card": {
                        "percentage": 2.9,
                        "fixed_cents": 30,
                        "condition": "always",
                    },
                },
            },
        }
    },
}


class FeeCalculationTests(unittest.TestCase):
    def test_net_guaranteed_physical_basic(self):
        result = calculate_price(
            tenant_keyed_amount=2900,
            currency="usd",
            product_type="physical",
            fee_handling="net_guaranteed",
            tenant_plan="basic",
            billing_config=BILLING_CONFIG,
        )

        self.assertEqual(result, {
            "unit_amount": 3364,
            "breakdown": {
                "tenant_keyed_amount": 2900,
                "stripe_fee": 128,
                "platform_fee": 336,
                "net_payout": 2900,
            },
        })

    def test_net_guaranteed_ceil_components_match_customer_amount(self):
        result = calculate_price(
            tenant_keyed_amount=5800,
            currency="usd",
            product_type="physical",
            fee_handling="net_guaranteed",
            tenant_plan="basic",
            billing_config=BILLING_CONFIG,
        )

        self.assertEqual(result, {
            "unit_amount": 6694,
            "breakdown": {
                "tenant_keyed_amount": 5800,
                "stripe_fee": 225,
                "platform_fee": 669,
                "net_payout": 5800,
            },
        })

    def test_standard_physical_basic(self):
        result = calculate_price(
            tenant_keyed_amount=2900,
            currency="usd",
            product_type="physical",
            fee_handling="standard",
            tenant_plan="basic",
            billing_config=BILLING_CONFIG,
        )

        self.assertEqual(result, {
            "unit_amount": 2900,
            "breakdown": {
                "tenant_keyed_amount": 2900,
                "stripe_fee": 115,
                "platform_fee": 290,
                "net_payout": 2495,
            },
        })

    def test_default_table_2026_08_26_pricing_pivot(self):
        """Pin the decided fee ladder: free (basic) 5/6/7/5, premium (pro) 2/2/2/0."""
        cases = [
            ("basic", "physical", "5"), ("basic", "service", "6"),
            ("basic", "digital", "7"), ("basic", "tip_jar", "5"),
            ("pro", "physical", "2"), ("pro", "service", "2"),
            ("pro", "digital", "2"), ("pro", "tip_jar", "0"),
        ]
        for plan, product_type, percent in cases:
            with self.subTest(plan=plan, product_type=product_type):
                pricing_model = "customer_chooses" if product_type == "tip_jar" else "one_time"
                rate = platform_fee_rate(None, tenant_plan=plan, product_type=product_type, pricing_model=pricing_model)
                self.assertEqual(rate, Decimal(percent) / Decimal("100"))

    def test_service_fee_class_is_its_own(self):
        self.assertEqual(fee_class_for("service"), "service")

    def test_service_falls_back_to_default_when_config_lacks_the_class(self):
        # Older S3 configs predate the "service" class; the default table's 6% must apply.
        rate = platform_fee_rate(BILLING_CONFIG, tenant_plan="basic", product_type="service")
        self.assertEqual(rate, Decimal("6") / Decimal("100"))

    def test_premium_tip_jar_takes_no_platform_fee(self):
        result = calculate_price(
            tenant_keyed_amount=1000,
            currency="usd",
            product_type="tip_jar",
            fee_handling="standard",
            pricing_model="customer_chooses",
            tenant_plan="pro",
        )
        self.assertEqual(result["breakdown"]["platform_fee"], 0)

    def test_zero_amount_stays_zero_for_net_guaranteed(self):
        result = calculate_price(
            tenant_keyed_amount=0,
            currency="usd",
            product_type="physical",
            fee_handling="net_guaranteed",
            tenant_plan="basic",
            billing_config=BILLING_CONFIG,
        )

        self.assertEqual(result["unit_amount"], 0)
        self.assertEqual(result["breakdown"]["net_payout"], 0)


if __name__ == "__main__":
    unittest.main()
