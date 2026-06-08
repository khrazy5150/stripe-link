import json
import unittest

from handlers import prices


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


class FakeBillingConfigLoader:
    def __init__(self, document):
        self.document = document
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.document


class PriceCalculationHandlerTests(unittest.TestCase):
    def setUp(self):
        prices.clear_config_cache()

    def tearDown(self):
        prices.clear_config_cache()

    def event(self, body):
        return {
            "httpMethod": "POST",
            "headers": {"X-Tenant-Id": "tenant_demo"},
            "body": json.dumps(body),
        }

    def test_calculates_net_guaranteed_price(self):
        loader = FakeBillingConfigLoader(BILLING_CONFIG)
        response = prices.handler(
            self.event({
                "tenant_keyed_amount": 2900,
                "currency": "usd",
                "product_type": "physical",
                "fee_handling": "net_guaranteed",
            }),
            None,
            billing_config_loader=loader,
            now_fn=lambda: 1000.0,
        )

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["unit_amount"], 3364)
        self.assertEqual(body["breakdown"]["net_payout"], 2900)

    def test_uses_cached_billing_config_until_ttl_expires(self):
        loader = FakeBillingConfigLoader(BILLING_CONFIG)
        event = self.event({
            "tenant_keyed_amount": 2900,
            "currency": "usd",
            "product_type": "physical",
            "fee_handling": "standard",
        })

        prices.handler(event, None, billing_config_loader=loader, now_fn=lambda: 1000.0)
        prices.handler(event, None, billing_config_loader=loader, now_fn=lambda: 1200.0)
        self.assertEqual(loader.calls, 1)

        prices.handler(event, None, billing_config_loader=loader, now_fn=lambda: 1301.0)
        self.assertEqual(loader.calls, 2)


if __name__ == "__main__":
    unittest.main()
