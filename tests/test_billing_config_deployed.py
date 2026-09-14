"""The fee table that is DEPLOYED must be the fee table the code decided on.

Found 2026-09-14, live on dev AND prod: the Payments screen showed "Physical 10% / Digital 15%" for a free
tenant, and it was not a display bug — `/prices/calculate` really was charging 10%. `deploy.sh` uploads
`schemas/examples/global-billing-config.json` to the config bucket on every deploy, and
`cached_billing_config()` prefers that object over `DEFAULT_GLOBAL_BILLING_CONFIG`. The 2026-08-26 pricing
pivot (5/6/7 free, 2/2/2/0 premium) updated the code default and never touched the file, so the deployed
config quietly outranked the decision for ~3 weeks. `tip_jar` was 5% in BOTH tables, which is why tip work
never tripped over it.

Two things that must agree, with nothing forcing them to — the same failure this repo keeps paying for. This
is the thing that forces them.
"""
import json
import pathlib
import unittest
from decimal import Decimal

from stripe_link.domain.fees import DEFAULT_GLOBAL_BILLING_CONFIG, platform_fee_rate

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOYED = json.loads((ROOT / "schemas" / "examples" / "global-billing-config.json").read_text(encoding="utf-8"))
DEPLOY_SCRIPT = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


class DeployedConfigTests(unittest.TestCase):
    def test_the_file_the_deploy_uploads_is_this_one(self):
        # If the path moves, this test has to move with it — otherwise it pins a file nobody ships.
        self.assertIn("schemas/examples/global-billing-config.json", DEPLOY_SCRIPT)
        self.assertIn("global_billing_config.json", DEPLOY_SCRIPT)

    def test_the_deployed_fee_table_matches_the_code_default(self):
        self.assertEqual(_plain(DEPLOYED["platform_fees"]), _plain(DEFAULT_GLOBAL_BILLING_CONFIG["platform_fees"]))

    def test_the_whole_document_matches(self):
        # Not just the fees: a stale processing schedule would mis-gross every price the same way.
        self.assertEqual(_plain(DEPLOYED), _plain(DEFAULT_GLOBAL_BILLING_CONFIG))

    def test_the_pivot_rates_are_what_a_tenant_is_actually_charged(self):
        # The 2026-08-26 model, asserted through the reader every caller uses rather than off the dict.
        for plan, expected in (("basic", {"physical": 5, "service": 6, "digital": 7}),
                               ("pro", {"physical": 2, "service": 2, "digital": 2})):
            for product_type, percent in expected.items():
                self.assertEqual(
                    platform_fee_rate(DEPLOYED, tenant_plan=plan, product_type=product_type),
                    Decimal(percent) / 100, f"{plan}/{product_type}")
        # Tips: 5% free, free on premium.
        self.assertEqual(platform_fee_rate(DEPLOYED, tenant_plan="basic", pricing_model="customer_chooses"),
                         Decimal("0.05"))
        self.assertEqual(platform_fee_rate(DEPLOYED, tenant_plan="pro", pricing_model="customer_chooses"),
                         Decimal("0"))

    def test_every_tier_prices_every_fee_class(self):
        # `service` was absent from all three tiers in the stale file, so services silently fell through to
        # the code default while physical and digital did not — one table, two sources of truth.
        for tier, rates in DEPLOYED["platform_fees"]["tiers"].items():
            self.assertEqual(set(rates), {"physical", "service", "digital", "tip_jar"}, tier)


if __name__ == "__main__":
    unittest.main()
