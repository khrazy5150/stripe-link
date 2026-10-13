"""stripe-link must never create a Stripe webhook endpoint.

The legacy app did, once per tenant, on the tenant's own connected account
(`stripe-cart/src/admin_keys.py:149`). Its cleanup was `if existing_endpoint_id:` -- it could only delete
the endpoint whose id it had stored, and it had to re-create on every provision because Stripe reveals a
signing secret only at creation. Lose that stored id and the live endpoint is orphaned, still enabled,
still signed with a secret nobody holds any more.

Measured on a real account, 2026-10-13: FOUR destinations on the same URL, one at 0% errors and three at
100%, ~232 failed deliveries in 14 days, and Stripe stopped delivering on Oct 11.

stripe-link is immune by ARCHITECTURE, not by care: a small fixed set of Connect endpoints on the PLATFORM
account, created by hand, whose secrets live in Secrets Manager (`stripe_platform_secrets.py`). Connecting
a tenant creates nothing in Stripe, so N tenants still means the same handful of endpoints.

This guards the property rather than the architecture, because the architecture is only safe while nothing
reaches for the convenient thing the legacy app reached for.
"""
import pathlib
import re
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def python_sources():
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


class NothingProvisionsAWebhookEndpoint(unittest.TestCase):
    def test_no_source_file_creates_or_deletes_one(self):
        offenders = []
        for path in python_sources():
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"WebhookEndpoint\s*\.\s*(create|delete|modify)", text):
                offenders.append(f"{path.relative_to(SRC)}: {match.group(0)}")
        self.assertEqual(offenders, [], "a per-tenant endpoint is how the legacy app accumulated four")

    def test_no_source_file_calls_the_rest_route_by_hand(self):
        """Bypassing the SDK is the obvious way to reintroduce it without tripping the check above."""
        offenders = [str(p.relative_to(SRC)) for p in python_sources()
                     if "v1/webhook_endpoints" in p.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_the_secret_comes_from_the_platform_store_instead(self):
        """The reason nothing needs to create an endpoint: the secret is not read off a create response."""
        store = (SRC / "stripe_link" / "stripe_platform_secrets.py").read_text(encoding="utf-8")
        self.assertIn("def get_platform_webhook_secret", store)


if __name__ == "__main__":
    unittest.main()
