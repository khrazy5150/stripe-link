"""The public endpoint that receives Shippo's `track_updated`.

Two halves worth pinning: it fails CLOSED when unconfigured, and it answers 200 to everything it cannot
act on so Shippo stops retrying. The rest of the behaviour belongs to `domain/tracking.py`.
"""

import json
import unittest

from handlers import shipping_tracking
from handlers.shipping_tracking import handler


def event(body, *, token="s3cret", method="POST", mode=None):
    params = {}
    if token is not None:
        params["token"] = token
    if mode is not None:
        params["mode"] = mode
    return {
        "httpMethod": method,
        "queryStringParameters": params or None,
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def payload(status="DELIVERED", *, metadata="shp_abc", date="2026-07-24T15:02:00Z"):
    return {"event": "track_updated", "data": {
        "carrier": "usps", "tracking_number": "9400111", "metadata": metadata,
        "tracking_status": {"status": status, "status_date": date},
    }}


class FakeRepo:
    def __init__(self, shipment=None, *, fail=False):
        self.shipment = shipment
        self.fail = fail
        self.written = None

    def find_by_id(self, document_id):
        if self.shipment and self.shipment.get("shipment_id") == document_id:
            return dict(self.shipment)
        return None

    def update_tracking(self, tenant_id, document_id, fields):
        if self.fail:
            raise RuntimeError("dynamo is unhappy")
        self.written = (tenant_id, document_id, fields)
        return True


def repo_fn_for(repo):
    """Mode-scoped in production -- the webhook tries test then live, so both calls get the same fake."""
    return lambda mode=None: repo


class FakeSecrets:
    def __init__(self, token, *, raises=False):
        self.token = token
        self.raises = raises

    def get_secret_value(self, SecretId=None):  # noqa: N803 - boto3's own parameter name
        if self.raises:
            raise RuntimeError("AccessDenied")
        return {"SecretString": json.dumps({"token": self.token})}


SHIPMENT = {"shipment_id": "shp_abc", "tenant_id": "t1", "carrier": "usps",
            "tracking_number": "9400111", "status": "shipped"}


class TrackingWebhookCase(unittest.TestCase):
    """`load_token` memoises per process, so the first test to resolve a token would otherwise decide
    every later test's answer -- including the ones asserting that an unconfigured deploy stays closed."""

    def setUp(self):
        shipping_tracking._TOKEN_CACHE.clear()

    tearDown = setUp


class Authentication(TrackingWebhookCase):
    def test_a_good_token_is_accepted(self):
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"), now_fn=lambda: 1000)
        self.assertEqual(response["statusCode"], 200)

    def test_a_wrong_token_is_401_and_writes_nothing(self):
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload(), token="guess"), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 401)
        self.assertIsNone(repo.written)

    def test_no_token_at_all_is_401(self):
        response = handler(event(payload(), token=None), None, repo_fn=repo_fn_for(FakeRepo(SHIPMENT)),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 401)

    def test_an_unconfigured_deploy_rejects_everything(self):
        """FAILS CLOSED, the opposite of the Debounce key. An endpoint that silently stopped checking
        would accept anonymous writes to delivery state, and that is worse than one plainly off."""
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets(""))
        self.assertEqual(response["statusCode"], 401)
        self.assertIsNone(repo.written)

    def test_a_denied_secret_leaves_it_closed(self):
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets(None, raises=True))
        self.assertEqual(response["statusCode"], 401)
        self.assertIsNone(repo.written)

    def test_the_401_says_nothing_useful_to_a_guesser(self):
        body = json.loads(handler(event(payload(), token="guess"), None,
                                  repo_fn=repo_fn_for(FakeRepo(SHIPMENT)),
                                  secrets_client=FakeSecrets("s3cret"))["body"])
        self.assertNotIn("s3cret", json.dumps(body))
        self.assertNotIn("token", json.dumps(body).lower())


class WhatItDoes(TrackingWebhookCase):
    def test_a_delivery_is_written(self):
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"), now_fn=lambda: 9000)
        tenant_id, shipment_id, fields = repo.written
        self.assertEqual((tenant_id, shipment_id), ("t1", "shp_abc"))
        self.assertEqual(fields["tracking_status"], "DELIVERED")
        self.assertEqual(fields["delivered_at"], 1784905320)
        self.assertEqual(json.loads(response["body"])["applied"], True)

    def test_only_tracking_attributes_are_written(self):
        """The document has two writers now: a carrier can scan a parcel in the same minute a tenant
        voids its label. A full-document write from here would restore what it read a moment earlier over
        the tenant's own change (`feedback_shared_document_read_modify_write`)."""
        repo = FakeRepo(SHIPMENT)
        handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                secrets_client=FakeSecrets("s3cret"), now_fn=lambda: 9000)
        _, _, fields = repo.written
        self.assertTrue(all(k.startswith("tracking_") or k == "delivered_at" for k in fields), fields)

    def test_an_unknown_shipment_is_200_not_an_error(self):
        """Shippo retries on 5xx, so a deleted test parcel would otherwise generate retries for days."""
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload(metadata="shp_gone")), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["reason"], "unknown_shipment")
        self.assertIsNone(repo.written)

    def test_an_event_for_a_tracker_we_did_not_register_is_200(self):
        """A tenant tracking a parcel in their own Shippo account produces events with no metadata."""
        repo = FakeRepo(SHIPMENT)
        response = handler(event(payload(metadata="")), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["reason"], "nothing_to_apply")

    def test_a_stale_event_is_200_and_writes_nothing(self):
        delivered = dict(SHIPMENT, tracking_status="DELIVERED", tracking_status_at=1784905320,
                         delivered_at=1784905320)
        repo = FakeRepo(delivered)
        response = handler(event(payload("TRANSIT", date="2026-07-20T00:00:00Z")), None,
                           repo_fn=repo_fn_for(repo), secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["reason"], "not_newer")
        self.assertIsNone(repo.written)

    def test_a_failed_write_is_a_5xx_so_shippo_retries(self):
        """Unlike a bad body, a failed write is worth attempting again -- and swallowing it would lose
        the delivery silently, the one thing a delivery guarantee cannot afford."""
        repo = FakeRepo(SHIPMENT, fail=True)
        response = handler(event(payload()), None, repo_fn=repo_fn_for(repo),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 503)

    def test_an_unparseable_body_is_400_not_a_retry(self):
        response = handler(event("{not json"), None, repo_fn=repo_fn_for(FakeRepo(SHIPMENT)),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 400)

    def test_a_get_is_refused(self):
        response = handler(event(payload(), method="GET"), None,
                           repo_fn=repo_fn_for(FakeRepo(SHIPMENT)),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(response["statusCode"], 405)

    def test_a_declared_mode_is_never_widened(self):
        """THE MODE IS CARRIED, NEVER INFERRED. Each deployment serves both modes, so neither the Shippo
        environment nor the hostname identifies one -- it travels in the URL we hand Shippo. Searching the
        other partition anyway is how a test-mode carrier event comes to apply to a LIVE shipment."""
        seen = []

        def repo_fn(mode=None):
            seen.append(mode)
            return FakeRepo(None)

        handler(event(payload(), mode="live"), None, repo_fn=repo_fn,
                secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(seen, ["live"])

    def test_a_declared_test_mode_never_reaches_live(self):
        live_only = FakeRepo(SHIPMENT)
        response = handler(event(payload(), mode="test"), None,
                           repo_fn=lambda mode=None: live_only if mode == "live" else FakeRepo(None),
                           secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(json.loads(response["body"])["reason"], "unknown_shipment")
        self.assertIsNone(live_only.written)

    def test_rubbish_in_the_mode_param_falls_back_rather_than_failing(self):
        seen = []

        def repo_fn(mode=None):
            seen.append(mode)
            return FakeRepo(None)

        handler(event(payload(), mode="production"), None, repo_fn=repo_fn,
                secrets_client=FakeSecrets("s3cret"))
        self.assertEqual(seen, ["test", "live"])

    def test_both_stripe_modes_are_tried(self):
        """A webhook registered before the mode param existed must keep working, and trying both is the
        old behaviour rather than a new guess."""
        seen = []

        def repo_fn(mode=None):
            seen.append(mode)
            return FakeRepo(SHIPMENT if mode == "live" else None)

        response = handler(event(payload()), None, repo_fn=repo_fn,
                           secrets_client=FakeSecrets("s3cret"), now_fn=lambda: 9000)
        self.assertEqual(seen, ["test", "live"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["applied"], True)


def setUpModule():
    """A secret NAME must be present or `load_token` short-circuits before the fake is consulted, and the
    per-process cache has to be empty so one test's token does not leak into the next."""
    import os

    os.environ["SHIPPO_WEBHOOK_SECRET_NAME"] = "jb/shippo-webhook/test"


def tearDownModule():
    import os

    os.environ.pop("SHIPPO_WEBHOOK_SECRET_NAME", None)


if __name__ == "__main__":
    unittest.main()
