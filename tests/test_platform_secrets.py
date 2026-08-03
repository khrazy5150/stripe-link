import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link import stripe_platform_secrets as sps


class GetPlatformWebhookSecretTests(unittest.TestCase):
    def setUp(self):
        # Seed the in-module payload cache so no Secrets Manager call happens.
        sps._CACHE["payload"] = {
            "whsec_preview_test": "whsec_preview_t",
            "whsec_stable_test": "whsec_stable_t",
            "whsec_platform_billing_test": "whsec_pb_t",
            "whsec_platform_billing_live": "whsec_pb_l",
        }

    def tearDown(self):
        sps._CACHE.pop("payload", None)

    def test_platform_billing_kind_is_resolved(self):
        # Regression: "platform_billing" must NOT be coerced to "stable" (which would miss the key).
        self.assertEqual(sps.get_platform_webhook_secret("platform_billing", "test"), "whsec_pb_t")
        self.assertEqual(sps.get_platform_webhook_secret("platform_billing", "live"), "whsec_pb_l")

    def test_connect_kinds_still_resolve(self):
        self.assertEqual(sps.get_platform_webhook_secret("preview", "test"), "whsec_preview_t")
        self.assertEqual(sps.get_platform_webhook_secret("stable", "test"), "whsec_stable_t")

    def test_unknown_kind_falls_back_to_stable(self):
        self.assertEqual(sps.get_platform_webhook_secret("bogus", "test"), "whsec_stable_t")


if __name__ == "__main__":
    unittest.main()
