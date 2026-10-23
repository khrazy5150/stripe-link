"""A Site's Stripe mode is SERVER-OWNED: it follows the request's mode, never the payload.

The field was called `environment` until 2026-10-23 and a Site carried the answer twice -- `stripe_mode`,
stamped by the mode-scoped repository, and `environment`, which arrived from the client and was what the
live-only custom-domain gate read. A document sent with environment="live" during a test-mode request
landed in the TEST partition and still passed that gate: "a test Site serving a real domain would present
sandbox pages as a real business", reached by a door nobody was watching.

That was first closed by setting the field server-side, which is what this file originally tested. The
two fields are now ONE, so the disagreement is not merely prevented but unrepresentable -- and the name
no longer borrows the word this codebase uses for the DEPLOYMENT (see stripe_link/silo.py). What still
needs a test is the half that remains load-bearing: the client does not get to choose.
"""
import json
import unittest

from handlers.sites import create_site


class FakeRepo:
    def __init__(self):
        self.saved = None

    def get(self, *a):
        return None

    def put(self, document):
        self.saved = dict(document)
        return dict(document)

    def list_for_tenant(self, tenant_id):
        return []


class FakeRegistry:
    def reserve(self, *a, **k):
        return True

    def release(self, *a, **k):
        return True

    def owner_of(self, *a, **k):
        return None


def save(payload, mode):
    repo = FakeRepo()
    event = {"httpMethod": "POST", "resource": "/sites", "headers": {"X-Tenant-Id": "t1"},
             "requestContext": {}, "queryStringParameters": {"mode": mode},
             "body": json.dumps({"tenant_id": "t1", **payload})}
    response = create_site(event, repo, registry=FakeRegistry(), mode=mode)
    return response, repo.saved


class TheStripeModeFollowsTheRequestTests(unittest.TestCase):
    BASE = {"site_id": "site_abc", "name": "Shop", "status": "draft",
            "hosting": {"type": "platform", "platform_subdomain": "quill-emporium"}}

    def test_a_test_mode_save_stores_a_test_site(self):
        _, saved = save({**self.BASE, "stripe_mode": "test"}, "test")
        self.assertEqual(saved["stripe_mode"], "test")

    def test_a_live_mode_save_stores_a_live_site(self):
        _, saved = save({**self.BASE, "stripe_mode": "live"}, "live")
        self.assertEqual(saved["stripe_mode"], "live")

    def test_a_CLAIMED_live_mode_cannot_survive_a_test_mode_save(self):
        """The door this closes. A client that could name its own mode could put a Site in the test
        partition and still pass the live-only custom-domain gate."""
        _, saved = save({**self.BASE, "stripe_mode": "live"}, "test")
        self.assertEqual(saved["stripe_mode"], "test")

    def test_and_the_reverse_is_corrected_too(self):
        _, saved = save({**self.BASE, "stripe_mode": "test"}, "live")
        self.assertEqual(saved["stripe_mode"], "live")

    def test_a_payload_with_no_stripe_mode_still_gets_one(self):
        _, saved = save(self.BASE, "test")
        self.assertEqual(saved["stripe_mode"], "test")


    def test_the_old_field_is_not_written_any_more(self):
        """Carrying both again would restore exactly the disagreement this file exists to prevent."""
        _, saved = save({**self.BASE, "environment": "live"}, "test")
        self.assertNotIn("environment", saved)
        self.assertEqual(saved["stripe_mode"], "test")


if __name__ == "__main__":
    unittest.main()
