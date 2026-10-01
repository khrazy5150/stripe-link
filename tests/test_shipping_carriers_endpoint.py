"""Carriers are CHOSEN, never typed.

plans/SHIPPING_ELEMENT.md. The author, 2026-09-30: *"Carriers cannot be manually entered in free-text form.
That begs for typos and human error. They should be choices that come straight from the API."*

The typo is the smaller half. A `service_code` a tenant invents will never match a real carrier rate — Shippo's
token for USPS ground is `usps_ground_advantage`, and a tenant who types `ground` has configured a service that
can never be quoted. A picker fixes the spelling; the rate viewer fixes the identity.

The rule this endpoint must never break: it always returns a LIST. A field that falls back to free text falls
back to the bug.
"""
import json
import unittest

from handlers.shipping import list_carriers


class Repo:
    def __init__(self, config=None):
        self.config = config or {}

    def get(self, tenant_id):
        return self.config


class Cipher:
    def __init__(self, key="sk_test", raises=None):
        self.key = key
        self.raises = raises

    def decrypt(self, ref, **kwargs):
        if self.raises:
            raise self.raises
        return self.key


CONNECTED = {"provider": {"name": "shippo", "api_key_ref": "ref", "connection_status": "connected"}}


def call(config=None, cipher=None):
    response = list_carriers({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}},
                             Repo(config), cipher or Cipher())
    return json.loads(response["body"])


class ItAlwaysReturnsAList(unittest.TestCase):
    """A field that falls back to free text falls back to the bug."""

    def test_no_provider_still_gives_the_registry(self):
        body = call({})
        self.assertEqual(body["source"], "registry")
        self.assertIn("usps", [c["key"] for c in body["carriers"]])

    def test_a_provider_with_no_key_still_gives_the_registry(self):
        self.assertEqual(call({"provider": {"name": "shippo"}})["source"], "registry")

    def test_an_unreachable_provider_still_gives_the_registry(self):
        """Logged as a message, not an error: a picker backed by the registry is still a picker, and a tenant
        whose list looks short should not be left guessing."""
        body = call(CONNECTED, Cipher(raises=RuntimeError("kms down")))
        self.assertEqual(body["source"], "registry")
        self.assertTrue(body["carriers"])
        self.assertIn("RuntimeError", body["message"])

    def test_a_missing_tenant_is_refused_rather_than_guessed(self):
        response = list_carriers({"httpMethod": "GET", "queryStringParameters": {}}, Repo(), Cipher())
        self.assertEqual(response["statusCode"], 400)


class TheTenantsOwnCarriersWin(unittest.TestCase):
    """Someone with no UPS account should not be offered UPS."""

    def setUp(self):
        import handlers.shipping as module

        self.module = module
        self.real = module.provider_for

    def tearDown(self):
        self.module.provider_for = self.real

    def connect(self, carriers):
        class Provider:
            def test_connection(self):
                return {"ok": True, "message": "ok", "carriers": carriers}

        self.module.provider_for = lambda *args, **kwargs: Provider()

    def test_only_the_connected_carriers_are_offered(self):
        self.connect(["usps"])
        body = call(CONNECTED)
        self.assertEqual(body["source"], "provider")
        self.assertEqual([c["key"] for c in body["carriers"]], ["usps"])

    def test_they_are_enriched_with_the_registrys_label_and_services(self):
        self.connect(["usps"])
        carrier = call(CONNECTED)["carriers"][0]
        self.assertTrue(carrier["label"])
        self.assertTrue(carrier.get("services"))

    def test_a_carrier_the_registry_does_not_know_is_still_offered(self):
        """The provider is the authority on what this account can quote. Dropping an unknown would hide a
        carrier the tenant actually has."""
        self.connect(["canada_post"])
        keys = [c["key"] for c in call(CONNECTED)["carriers"]]
        self.assertEqual(keys, ["canada_post"])

    def test_a_connected_account_with_NO_carriers_falls_back(self):
        """An empty picker is not a picker."""
        self.connect([])
        body = call(CONNECTED)
        self.assertEqual(body["source"], "registry")
        self.assertTrue(body["carriers"])


if __name__ == "__main__":
    unittest.main()
