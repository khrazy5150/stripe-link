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


class TenantTierAuthorityTests(unittest.TestCase):
    """The server reads the tenant's live tier_id — the client-sent tenant_plan is only a fallback."""

    def setUp(self):
        prices.clear_config_cache()

    class _ProRepo:
        def get(self, tenant_id, document_id):
            return {"tenant_id": tenant_id, "tier_id": "pro"}

    class _MissingRepo:
        def get(self, tenant_id, document_id):
            return None

    def _event(self, tenant_plan="basic"):
        return {"httpMethod": "POST", "body": json.dumps({
            "tenant_id": "t1", "tenant_keyed_amount": 10000, "currency": "usd",
            "product_type": "digital", "fee_handling": "standard", "tenant_plan": tenant_plan})}

    def test_premium_tenant_gets_pro_rate_despite_client_claiming_basic(self):
        resp = prices.handler(self._event("basic"), None,
                              billing_config_loader=lambda: None, tenant_repo=self._ProRepo())
        body = json.loads(resp["body"])
        self.assertEqual(body["breakdown"]["platform_fee"], 200)  # 2% pro, not 7% basic

    def test_unknown_tenant_falls_back_to_client_plan(self):
        resp = prices.handler(self._event("basic"), None,
                              billing_config_loader=lambda: None, tenant_repo=self._MissingRepo())
        body = json.loads(resp["body"])
        self.assertEqual(body["breakdown"]["platform_fee"], 700)  # free-tier digital 7%
