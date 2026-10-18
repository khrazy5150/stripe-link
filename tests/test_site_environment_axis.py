"""A Site says which books it belongs to twice, and the two must not be able to disagree.

`stripe_mode` is stamped by the mode-scoped repository. `environment` arrives in the payload — and it is
the field `_reject_non_live_site` reads, deliberately, because the SITE's axis is the one that matters
for custom domains (a deployment can host both). So a document sent with environment="live" while the
request is in test mode would land in the TEST partition and still pass the live-only gate.

That gate exists for a reputational harm its own docstring spells out: "a test Site serving a real domain
would present sandbox pages as a real business… a reputation the tenant cannot get back." It had already
been moved server-side once, for the deployment axis. This closes the other door.
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


class TheEnvironmentFollowsTheModeTests(unittest.TestCase):
    BASE = {"site_id": "site_abc", "name": "Shop", "status": "draft",
            "hosting": {"type": "platform", "platform_subdomain": "quill-emporium"}}

    def test_a_test_mode_save_stores_a_test_site(self):
        _, saved = save({**self.BASE, "environment": "test"}, "test")
        self.assertEqual(saved["environment"], "test")

    def test_a_live_mode_save_stores_a_live_site(self):
        _, saved = save({**self.BASE, "environment": "live"}, "live")
        self.assertEqual(saved["environment"], "live")

    def test_a_CLAIMED_live_environment_cannot_survive_a_test_mode_save(self):
        """The door this closes. Otherwise the Site sits in the test partition and still passes the
        live-only custom-domain gate."""
        _, saved = save({**self.BASE, "environment": "live"}, "test")
        self.assertEqual(saved["environment"], "test")

    def test_and_the_reverse_is_corrected_too(self):
        _, saved = save({**self.BASE, "environment": "test"}, "live")
        self.assertEqual(saved["environment"], "live")

    def test_a_payload_with_no_environment_still_gets_one(self):
        _, saved = save(self.BASE, "test")
        self.assertEqual(saved["environment"], "test")


if __name__ == "__main__":
    unittest.main()
