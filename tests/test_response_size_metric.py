"""Response-size telemetry.

The 6MB Lambda proxy limit is a cliff: a response that reaches it does not degrade, the request fails and
the screen stops loading. So we need the trend BEFORE it matters. json_response is the single choke point
every endpoint already passes through and it already serializes the body, so measuring costs nothing and
needs no handler changes.

Bytes, not record counts, deliberately: documents vary enough in size that counting records misleads.
"""

import io
import json
import unittest
from contextlib import redirect_stdout

from stripe_link.common import RESPONSE_LIMIT_BYTES, RESPONSE_TRACK_BYTES, json_response


def emitted(body):
    """The EMF lines json_response printed while building this response."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        response = json_response(body)
    lines = []
    for line in buffer.getvalue().splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if "_aws" in parsed:
            lines.append(parsed)
    return response, lines


class ResponseSizeMetricTests(unittest.TestCase):
    def test_a_small_response_emits_nothing(self):
        # Every API call would otherwise log; a response this size cannot be near the limit.
        _, lines = emitted({"ok": True})
        self.assertEqual(lines, [])

    def test_a_large_response_emits_one_emf_metric(self):
        _, lines = emitted({"offers": ["x" * 200 for _ in range(1000)]})
        self.assertEqual(len(lines), 1)
        metric = lines[0]
        self.assertEqual(metric["_aws"]["CloudWatchMetrics"][0]["Namespace"], "JuniorBay/Api")
        self.assertEqual(metric["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"], "ResponseBytes")
        self.assertGreaterEqual(metric["ResponseBytes"], RESPONSE_TRACK_BYTES)

    def test_percent_of_limit_is_reported_against_the_real_ceiling(self):
        _, lines = emitted({"offers": ["x" * 200 for _ in range(1000)]})
        metric = lines[0]
        expected = round(100 * metric["ResponseBytes"] / RESPONSE_LIMIT_BYTES, 1)
        self.assertEqual(metric["PercentOfLimit"], expected)

    def test_the_response_body_is_unchanged_by_measuring_it(self):
        body = {"offers": [{"offer_id": f"o{i}"} for i in range(50)]}
        response, _ = emitted(body)
        self.assertEqual(json.loads(response["body"]), body)
        self.assertEqual(response["statusCode"], 200)

    def test_telemetry_failure_never_breaks_a_response(self):
        # A metric is worth nothing if it can take the API down with it. This calls json_response WHILE the
        # emitter is broken -- an earlier version of this test restored it first and therefore proved
        # nothing, which also hid that the guard sat inside the emitter instead of around the call.
        import stripe_link.common as common

        original = common._emit_response_size

        def explode(size):
            raise RuntimeError("clock exploded")

        common._emit_response_size = explode
        try:
            response = json_response({"offers": ["x" * 200 for _ in range(1000)]})
            self.assertEqual(response["statusCode"], 200)
            self.assertIn("offers", json.loads(response["body"]))
        finally:
            common._emit_response_size = original


if __name__ == "__main__":
    unittest.main()
