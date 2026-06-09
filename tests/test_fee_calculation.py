import unittest

from stripe_link.domain.fees import calculate_price


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
