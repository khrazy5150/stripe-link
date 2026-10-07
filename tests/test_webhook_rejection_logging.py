"""A refused webhook has to say so.

Every rejection in `stripe_webhook.handler` was silent. `error_response` does not log, and the signature
check runs before the first structured log line, so a refused event left nothing behind but Lambda's own
START/END/REPORT.

What that cost, measured 2026-10-07: Stripe retried LIVE events against BOTH deployments for nine days,
counted 364 failures, disabled both endpoints, and the first anyone knew was an email. CloudWatch held
2,021 invocations over those nine days and not one line saying any of them had been turned away. Live
Connect events reach neither deployment today.

Same lesson as the upsell "card declined" bug, one layer down: an error branch that returns without
logging makes a real failure look like ordinary traffic.
"""
import hashlib
import hmac
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from handlers.stripe_webhook import handler as stripe_webhook_handler


SECRET = "whsec_preview_test"
TIMESTAMP = 1781230000


def signed(body, secret=SECRET, timestamp=TIMESTAMP):
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode("utf-8"), hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def call(body, *, signature=None, loader=lambda kind, mode: SECRET, path="/webhook/stripe-preview",
         method="POST"):
    """Run the handler and return `(response, [rejection log lines])`."""
    event = {"httpMethod": method, "path": path, "body": body,
             "headers": {"Stripe-Signature": signature} if signature is not None else {}}
    buffer = io.StringIO()
    with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=False), redirect_stdout(buffer):
        response = stripe_webhook_handler(event, None, webhook_secret_loader=loader,
                                          now_fn=lambda: TIMESTAMP)
    rejections = []
    for line in buffer.getvalue().splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "webhook_rejected" in parsed:
            rejections.append(parsed["webhook_rejected"])
    return response, rejections


LIVE_EVENT = json.dumps({"id": "evt_live_1", "type": "checkout.session.completed", "livemode": True,
                         "account": "acct_123", "data": {"object": {}}}, separators=(",", ":"))


class ARejectionIsAlwaysSpokenTests(unittest.TestCase):
    def test_a_bad_signature_says_so_and_names_the_event(self):
        """THE ONE THAT COST NINE DAYS. A stored secret that does not match the endpoint's own rejects
        every event of that mode, identically and forever."""
        response, rejections = call(LIVE_EVENT, signature=signed(LIVE_EVENT, secret="whsec_wrong"))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(len(rejections), 1)
        entry = rejections[0]
        self.assertEqual(entry["reason"], "invalid_signature")
        self.assertEqual(entry["event_id"], "evt_live_1")
        self.assertTrue(entry["livemode"], "the mode is the first thing anyone will ask")
        self.assertEqual(entry["mode"], "live")

    def test_a_missing_signature_header_is_distinguished_from_a_wrong_secret(self):
        """Different causes, different fixes: one is a misconfigured endpoint, the other a stale secret."""
        _, rejections = call(LIVE_EVENT)
        self.assertEqual(rejections[0]["detail"], "no Stripe-Signature header")

    def test_a_missing_signing_secret_says_which_kind_and_mode(self):
        """The rejection a redeploy can fix, and the one most likely to take out a whole mode at once."""
        response, rejections = call(LIVE_EVENT, signature=signed(LIVE_EVENT),
                                    loader=lambda kind, mode: None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(rejections[0]["reason"], "signing_secret_not_configured")
        self.assertEqual((rejections[0]["kind"], rejections[0]["mode"]), ("preview", "live"))

    def test_malformed_json_is_logged_without_an_event_id_to_quote(self):
        response, rejections = call("{not json")
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(rejections[0]["reason"], "invalid_json")
        self.assertEqual(rejections[0]["event_id"], "")

    def test_a_non_object_payload_is_its_own_reason(self):
        response, rejections = call('"a string"')
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(rejections[0]["reason"], "payload_not_an_object")

    def test_a_wrong_method_is_logged(self):
        response, rejections = call("", method="GET")
        self.assertEqual(response["statusCode"], 405)
        self.assertEqual(rejections[0]["reason"], "method_not_allowed")

    def test_an_accepted_event_logs_no_rejection(self):
        """The line has to mean something. If it appeared on success it would be noise within a day."""
        body = json.dumps({"id": "evt_ok", "type": "ping", "livemode": False,
                           "data": {"object": {}}}, separators=(",", ":"))
        response, rejections = call(body, signature=signed(body))
        self.assertEqual(rejections, [])
        self.assertLess(response["statusCode"], 400)


class TheLineIsQueryableTests(unittest.TestCase):
    """Shaped like `silo_routing` so both can be found the same way, and carrying the event id so a line
    here can be matched against Stripe's own delivery log."""

    def test_it_is_one_json_object_per_rejection(self):
        _, rejections = call(LIVE_EVENT, signature=signed(LIVE_EVENT, secret="whsec_wrong"))
        self.assertEqual(len(rejections), 1)

    def test_it_carries_the_fields_an_investigation_starts_from(self):
        _, rejections = call(LIVE_EVENT, signature=signed(LIVE_EVENT, secret="whsec_wrong"))
        for field in ("reason", "kind", "mode", "event_id", "event_type", "livemode", "account"):
            with self.subTest(field=field):
                self.assertIn(field, rejections[0])


if __name__ == "__main__":
    unittest.main()
