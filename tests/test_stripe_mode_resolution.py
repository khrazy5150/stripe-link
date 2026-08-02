import unittest

from stripe_link.common import normalize_stripe_mode, resolve_stripe_mode


class NormalizeStripeModeTests(unittest.TestCase):
    def test_only_explicit_live_is_live(self):
        self.assertEqual(normalize_stripe_mode("live"), "live")
        self.assertEqual(normalize_stripe_mode("LIVE"), "live")
        self.assertEqual(normalize_stripe_mode(" Live "), "live")

    def test_everything_else_is_test_failsafe(self):
        for value in ("test", "", None, "prod", "sandbox", "xyz", 0):
            self.assertEqual(normalize_stripe_mode(value), "test", value)


class ResolveStripeModeTests(unittest.TestCase):
    def test_reads_body_first(self):
        event = {"queryStringParameters": {"mode": "test"}}
        self.assertEqual(resolve_stripe_mode(event, {"mode": "live"}), "live")

    def test_reads_query_param(self):
        self.assertEqual(resolve_stripe_mode({"queryStringParameters": {"mode": "live"}}), "live")

    def test_reads_header(self):
        self.assertEqual(resolve_stripe_mode({"headers": {"X-Stripe-Mode": "live"}}), "live")

    def test_header_case_insensitive(self):
        self.assertEqual(resolve_stripe_mode({"headers": {"x-stripe-mode": "live"}}), "live")

    def test_absent_falls_back_to_test_by_default(self):
        # Fail-safe: a caller that forgets to send a mode can never target live.
        self.assertEqual(resolve_stripe_mode({}), "test")
        self.assertEqual(resolve_stripe_mode({"queryStringParameters": {}}, {}), "test")

    def test_explicit_default_override(self):
        self.assertEqual(resolve_stripe_mode({}, default="live"), "live")

    def test_unrecognized_value_is_test(self):
        self.assertEqual(resolve_stripe_mode({"queryStringParameters": {"mode": "prod"}}), "test")


if __name__ == "__main__":
    unittest.main()
