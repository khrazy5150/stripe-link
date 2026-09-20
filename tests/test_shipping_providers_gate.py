"""A tenant may only choose a shipping provider that actually works.

The schema has listed five provider names since it was written, the dashboard offered all five in a
`<select>`, and **not one of them was wired** — no HTTP call to any carrier exists in this codebase. The
menu advertised four integrations that had never run.

Only two of the four can be verified end to end without spending money: Shippo and EasyPost both put test
mode in the API KEY, so a test token buys free labels on the production host. ShipStation needs a real
(paid) account before its `testLabel` flag can even be sent, and Easyship's sandbox story is unknown — the
legacy adapter reads `test_mode` into its constructor and never applies it to a request.

Shipping code that has only ever met a fake is the exact shape that cost this codebase twice in one day
(the four-decimal application_fee_percent, the Decimal-vs-int validator): every layer green, and the real
API refusing the result. So a provider stays off the menu until someone has held a working key.
"""
import json
import os
import pathlib
import unittest
from unittest.mock import patch

from stripe_link.domain.shipping import (
    ALL_PROVIDERS,
    GA_PROVIDERS,
    ProviderNotAvailable,
    assert_provider_available,
    selectable_providers,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AvailabilityTests(unittest.TestCase):
    def test_only_what_has_been_proven_is_generally_available(self):
        self.assertEqual(GA_PROVIDERS, ("shippo",))

    def test_the_unproven_providers_are_refused(self):
        for provider in ("shipstation", "easyship"):
            with self.subTest(provider=provider):
                with self.assertRaises(ProviderNotAvailable) as caught:
                    assert_provider_available(provider, "dev")
                # The message has to name what IS available: "invalid" for a name the UI itself offered is
                # a dead end for whoever hits it.
                self.assertIn("shippo", str(caught.exception))

    def test_mock_is_off_prod_only(self):
        self.assertIn("mock", selectable_providers("dev"))
        self.assertNotIn("mock", selectable_providers("prod"))
        with self.assertRaises(ProviderNotAvailable):
            assert_provider_available("mock", "prod")

    def test_a_name_outside_the_schema_is_refused_differently(self):
        with self.assertRaises(ProviderNotAvailable) as caught:
            assert_provider_available("fedex-direct", "dev")
        self.assertIn("not a provider this platform supports", str(caught.exception))

    def test_the_schema_still_accepts_every_name(self):
        """Availability is a rollout question, not a document-shape one.

        Withdrawing a provider from the menu must not make a document that already names it unvalidatable —
        otherwise turning one off would strand whoever had already saved it.
        """
        from stripe_link.domain.documents import validate_shipping_config
        base = {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                                  "postal_code": "90001", "country": "US"},
            "return_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                               "postal_code": "90001", "country": "US"},
            "default_parcel": {"length": 10, "width": 10, "height": 10, "weight": 1,
                               "distance_unit": "in", "mass_unit": "lb"},
        }
        for provider in ALL_PROVIDERS:
            with self.subTest(provider=provider):
                validate_shipping_config({**base, "provider": {"name": provider}})


class HandlerTests(unittest.TestCase):
    class Repo:
        def __init__(self, doc=None):
            self.doc = doc

        def get(self, tenant_id):
            return self.doc

        def put(self, doc):
            return doc

    class Cipher:
        def encrypt(self, value, **kwargs):
            return "kms:v1:" + value

    def _event(self, method, body=None):
        return {"httpMethod": method, "queryStringParameters": {"tenant_id": "t1"},
                "body": json.dumps(body) if body else None, "headers": {}}

    def _config(self, provider):
        return {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "provider": {"name": provider, "api_key_ref": "shippo_test_abc"},
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                                  "postal_code": "90001", "country": "US"},
            "return_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                               "postal_code": "90001", "country": "US"},
            "default_parcel": {"length": 10, "width": 10, "height": 10, "weight": 1,
                               "distance_unit": "in", "mass_unit": "lb"},
        }

    def _save(self, provider, environment):
        from handlers import shipping
        with patch.dict(os.environ, {"ENVIRONMENT": environment}, clear=False):
            return shipping.handler(self._event("PUT", self._config(provider)), None,
                                    repository=self.Repo(), secret_cipher=self.Cipher())

    def test_saving_an_unavailable_provider_is_refused(self):
        response = self._save("shipstation", "dev")
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "provider_not_available")

    def test_saving_an_available_one_still_works(self):
        self.assertEqual(self._save("shippo", "prod")["statusCode"], 201)

    def test_the_get_tells_the_dashboard_what_it_may_offer(self):
        from handlers import shipping
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=False):
            response = shipping.handler(self._event("GET"), None,
                                        repository=self.Repo(self._config("shippo")),
                                        secret_cipher=self.Cipher())
        self.assertEqual(json.loads(response["body"])["available_providers"], ["shippo", "mock"])

    def test_even_the_404_carries_the_list(self):
        """A tenant with no config yet is exactly who needs to know which providers they may choose."""
        from handlers import shipping
        with patch.dict(os.environ, {"ENVIRONMENT": "prod"}, clear=False):
            response = shipping.handler(self._event("GET"), None, repository=self.Repo(),
                                        secret_cipher=self.Cipher())
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(json.loads(response["body"])["available_providers"], ["shippo"])


class DashboardTests(unittest.TestCase):
    SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")
    CLIENT = (ROOT / "dashboard/src/api/client.js").read_text(encoding="utf-8")

    def test_the_menu_is_not_a_hardcoded_list(self):
        """A menu maintained separately from the server drifts, and this screen is the proof: it offered
        four carriers the backend had no code for."""
        self.assertIn('v-for="name in availableProviders"', self.SCREEN)
        for withdrawn in ("shipstation", "easyship"):
            self.assertNotIn(f'<option value="{withdrawn}"', self.SCREEN)

    def test_the_menu_comes_from_the_server(self):
        self.assertIn("applyAvailableProviders(body)", self.SCREEN)

    def test_the_404_path_reads_the_body_it_is_given(self):
        # Guards the wiring: err.body only exists because client.js attaches it.
        self.assertIn("failure.body = payload", self.CLIENT)
        self.assertIn("applyAvailableProviders(err.body", self.SCREEN)


if __name__ == "__main__":
    unittest.main()
