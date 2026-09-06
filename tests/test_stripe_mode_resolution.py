import json
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


class ResolveModeFromUnparsedBodyTests(unittest.TestCase):
    """A published page sends `mode` in the POST body and nothing else — no query string, no header.

    The handlers call resolve_stripe_mode(event) with no body, so until the function parsed the body itself
    every such POST resolved to "test" and read the wrong mode's documents. A live page's Page Ribbon looked
    up its own section under PAGE#test#... and 404'd. These lock the real client payload, not a synthetic one.
    """

    @staticmethod
    def _post(payload):
        return {"httpMethod": "POST", "body": json.dumps(payload)}

    def test_live_mode_in_json_body_is_read_without_being_passed(self):
        self.assertEqual(resolve_stripe_mode(self._post({"mode": "live", "page_id": "p1"})), "live")

    def test_body_mode_outranks_query_and_header(self):
        event = self._post({"mode": "live"})
        event["queryStringParameters"] = {"mode": "test"}
        event["headers"] = {"X-Stripe-Mode": "test"}
        self.assertEqual(resolve_stripe_mode(event), "live")

    def test_header_still_wins_when_body_has_no_mode(self):
        event = self._post({"page_id": "p1"})
        event["headers"] = {"X-Stripe-Mode": "live"}
        self.assertEqual(resolve_stripe_mode(event), "live")

    def test_unparseable_body_falls_back_instead_of_raising(self):
        event = {"httpMethod": "POST", "body": "not json", "headers": {"X-Stripe-Mode": "live"}}
        self.assertEqual(resolve_stripe_mode(event), "live")

    def test_non_object_body_falls_back(self):
        self.assertEqual(resolve_stripe_mode({"body": "[1,2,3]"}), "test")

    def test_explicitly_passed_body_is_not_second_guessed(self):
        # page_render.py passes its parsed body; an empty one must NOT re-read the raw event.
        self.assertEqual(resolve_stripe_mode(self._post({"mode": "live"}), {}), "test")
