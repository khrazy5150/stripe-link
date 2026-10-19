"""Deleting a Site frees its platform name — but only once the Site is gone from BOTH modes.

A reservation is not per mode. `_reserve_subdomain` claims `{label}` and `{label}-test` together,
because "`{label}-test` is itself a legal label, so without this a second tenant could claim `maria-test`
and take over the first tenant's test-mode host". They are ONE claim in two rows, owned by one site_id —
and a site_id survives a cross-mode copy, so the live Site and its test counterpart share it.

That is what makes "release everything this site_id owns" wrong: deleting the test Site would hand back
the live hostname. Verified against prod, where both rows carry site_f6VRxFKUp2YEfa.
"""
import json
import unittest

from handlers.sites import delete_site


class FakeRegistry:
    def __init__(self, owners):
        self.owners = dict(owners)      # label -> site_id
        self.released = []

    def release(self, label, *, site_id):
        if self.owners.get(label) != site_id:
            return False
        del self.owners[label]
        self.released.append(label)
        return True


class FakeRepo:
    def __init__(self, site=None):
        self.site = site

    def delete(self, tenant_id, site_id):
        found, self.site = self.site, None
        return found

    def get(self, tenant_id, site_id):
        return self.site


SITE = {"site_id": "site_1", "tenant_id": "t1", "name": "Quill",
        "hosting": {"type": "platform", "platform_hostname": "quill-test.jbay.be"}}


def run(*, mode, other_exists, registry):
    event = {"httpMethod": "DELETE", "headers": {"X-Tenant-Id": "t1"}, "requestContext": {}, "body": None}
    response = delete_site(
        event, FakeRepo(dict(SITE)), "site_1",
        registry=registry, other_mode_repo=FakeRepo(dict(SITE) if other_exists else None), mode=mode)
    return response, json.loads(response["body"])


class TheSiteRowIsModeScopedTests(unittest.TestCase):
    def test_deleting_one_mode_leaves_the_other_untouched(self):
        """The question that prompted this: yes, only that mode's row is removed."""
        repo = FakeRepo(dict(SITE))
        other = FakeRepo(dict(SITE))
        delete_site({"httpMethod": "DELETE", "headers": {"X-Tenant-Id": "t1"}, "requestContext": {},
                     "body": None}, repo, "site_1",
                    registry=FakeRegistry({}), other_mode_repo=other, mode="test")
        self.assertIsNone(repo.site)
        self.assertIsNotNone(other.site)


class TheReservationIsSharedTests(unittest.TestCase):
    OWNED = {"quill": "site_1", "quill-test": "site_1"}

    def test_nothing_is_released_while_the_other_mode_still_has_the_site(self):
        """THE regression this guards. Releasing here would hand back the LIVE hostname — and reopen the
        hijack hole that claiming `{label}-test` exists to close."""
        registry = FakeRegistry(self.OWNED)
        _, body = run(mode="test", other_exists=True, registry=registry)
        self.assertEqual(registry.released, [])
        self.assertEqual(body["released_subdomains"], [])
        self.assertEqual(set(registry.owners), {"quill", "quill-test"})

    def test_BOTH_names_are_released_once_the_last_one_goes(self):
        registry = FakeRegistry(self.OWNED)
        _, body = run(mode="test", other_exists=False, registry=registry)
        self.assertEqual(sorted(body["released_subdomains"]), ["quill", "quill-test"])
        self.assertEqual(registry.owners, {})

    def test_the_label_is_the_BASE_name_not_the_test_host(self):
        """`quill-test.jbay.be` traces back to the reservation `quill`, which is what owns both."""
        registry = FakeRegistry(self.OWNED)
        run(mode="test", other_exists=False, registry=registry)
        self.assertIn("quill", registry.released)

    def test_another_sites_reservation_is_never_taken(self):
        registry = FakeRegistry({"quill": "someone_else", "quill-test": "someone_else"})
        _, body = run(mode="live", other_exists=False, registry=registry)
        self.assertEqual(body["released_subdomains"], [])
        self.assertEqual(set(registry.owners), {"quill", "quill-test"})

    def test_a_custom_domain_site_releases_nothing(self):
        registry = FakeRegistry(self.OWNED)
        event = {"httpMethod": "DELETE", "headers": {"X-Tenant-Id": "t1"}, "requestContext": {}, "body": None}
        custom = {**SITE, "hosting": {"type": "custom", "custom_domain": "shop.example.com"}}
        response = delete_site(event, FakeRepo(custom), "site_1", registry=registry,
                               other_mode_repo=FakeRepo(None), mode="live")
        self.assertEqual(json.loads(response["body"])["released_subdomains"], [])

    def test_an_unreadable_sibling_keeps_the_reservation(self):
        """Cannot prove it is gone, so do not free it. The orphan is the old behaviour and survivable."""
        class Exploding:
            def get(self, *a):
                raise RuntimeError("throttled")
        registry = FakeRegistry(self.OWNED)
        event = {"httpMethod": "DELETE", "headers": {"X-Tenant-Id": "t1"}, "requestContext": {}, "body": None}
        delete_site(event, FakeRepo(dict(SITE)), "site_1", registry=registry,
                    other_mode_repo=Exploding(), mode="test")
        self.assertEqual(registry.released, [])

    def test_the_delete_still_succeeds_when_a_release_fails(self):
        class Stubborn:
            def release(self, *a, **k):
                raise RuntimeError("AccessDenied")
        response, body = run(mode="test", other_exists=False, registry=Stubborn())
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["released_subdomains"], [])


if __name__ == "__main__":
    unittest.main()
