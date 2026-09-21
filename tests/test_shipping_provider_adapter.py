"""The provider adapter, and the connection test that finally makes `connection_status` mean something.

`connection_status` has been in ShippingConfig since it was written and could only ever say "untested" or
"not_configured": nothing tested it, and no endpoint existed to. The dashboard displayed a field nothing
could advance, for four providers that had no code at all.

The adapter is standard-library only -- src/requirements.txt is deliberately empty, and Stripe is already
called with urllib. ../stripe-cart's version is built on `requests` in a Lambda layer, so its CALL SHAPES
are the reference and its code is not.
"""
import io
import json
import unittest
from urllib.error import HTTPError, URLError

from stripe_link.domain.shipping_providers import (
    MockProvider,
    ProviderError,
    ShippoProvider,
    provider_for,
    to_cents,
)


class MoneyTests(unittest.TestCase):
    def test_a_decimal_string_becomes_exact_cents(self):
        """Through Decimal, never float.

        int(float("8.12") * 100) is 811. A rate one cent wrong is a PRICE one cent wrong on every order
        that uses it, and this number feeds Calculate Price.
        """
        self.assertEqual(to_cents("8.12"), 812)
        self.assertEqual(int(float("8.12") * 100), 811)  # the bug being avoided, pinned

    def test_a_spread_of_awkward_values(self):
        for amount, cents in (("0", 0), ("1", 100), ("10.00", 1000), ("29.35", 2935), ("0.05", 5)):
            with self.subTest(amount=amount):
                self.assertEqual(to_cents(amount), cents)

    def test_zero_decimal_currencies_are_not_multiplied(self):
        self.assertEqual(to_cents("500", "jpy"), 500)

    def test_junk_is_refused_not_guessed(self):
        with self.assertRaises(ProviderError):
            to_cents("about eight dollars")


def _response(payload):
    class _Ctx(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return _Ctx(json.dumps(payload).encode())


class ShippoRateTests(unittest.TestCase):
    ADDRESS = {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
               "postal_code": "90001", "country": "US"}
    PARCEL = {"length": 10, "width": 8, "height": 4, "weight": 1.5,
              "distance_unit": "in", "mass_unit": "lb"}

    def _provider(self, payload, captured=None):
        def opener(request, timeout=None):
            if captured is not None:
                captured.append(request)
            return _response(payload)
        return ShippoProvider("shippo_test_key", opener=opener)

    def test_rates_are_normalised_into_one_shape(self):
        provider = self._provider({"rates": [{
            "object_id": "rate_1", "provider": "USPS", "amount": "8.12", "currency": "USD",
            "servicelevel": {"name": "Priority Mail", "token": "usps_priority"},
            "estimated_days": 2, "attributes": ["CHEAPEST"],
        }]})
        rate = provider.rates(from_address=self.ADDRESS, to_address=self.ADDRESS, parcel=self.PARCEL)[0]
        self.assertEqual(rate["carrier"], "USPS")
        self.assertEqual(rate["service"], "Priority Mail")
        self.assertEqual(rate["amount"], 812)
        self.assertEqual(rate["estimated_days"], 2)

    def test_servicelevel_as_a_bare_string_is_handled(self):
        """Shippo returns `servicelevel` as an object, and sometimes as a string. The legacy adapter knew
        this; it is expensive to rediscover and cheap to carry over."""
        provider = self._provider({"rates": [{"object_id": "r", "provider": "UPS",
                                              "amount": "9.00", "servicelevel": "Ground"}]})
        self.assertEqual(provider.rates(from_address=self.ADDRESS, to_address=self.ADDRESS,
                                        parcel=self.PARCEL)[0]["service"], "Ground")

    def test_no_rates_reports_the_carrier_message(self):
        # "No rates" with no reason is unactionable; Shippo says why in `messages`.
        provider = self._provider({"rates": [], "messages": [{"text": "Invalid destination postal code"}]})
        with self.assertRaises(ProviderError) as caught:
            provider.rates(from_address=self.ADDRESS, to_address=self.ADDRESS, parcel=self.PARCEL)
        self.assertIn("postal code", str(caught.exception))

    def test_the_postal_code_is_sent_as_zip(self):
        captured = []
        provider = self._provider({"rates": [{"object_id": "r", "provider": "USPS", "amount": "1.00"}]},
                                  captured)
        provider.rates(from_address=self.ADDRESS, to_address=self.ADDRESS, parcel=self.PARCEL)
        sent = json.loads(captured[0].data.decode())
        self.assertEqual(sent["address_to"]["zip"], "90001")
        self.assertIs(sent["async"], False)


class ShippoFailureTests(unittest.TestCase):
    def _raising(self, exc):
        def opener(request, timeout=None):
            raise exc
        return ShippoProvider("shippo_test_key", opener=opener)

    def test_a_rejected_key_says_so_without_echoing_it(self):
        provider = self._raising(HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"{}")))
        with self.assertRaises(ProviderError) as caught:
            provider.test_connection()
        self.assertIn("rejected the API key", str(caught.exception))
        self.assertNotIn("shippo_test_key", str(caught.exception))

    def test_an_error_body_is_read_because_the_status_alone_explains_nothing(self):
        body = json.dumps({"detail": "parcel weight must be greater than zero"}).encode()
        provider = self._raising(HTTPError("u", 400, "Bad Request", {}, io.BytesIO(body)))
        with self.assertRaises(ProviderError) as caught:
            provider.test_connection()
        self.assertIn("weight must be greater", str(caught.exception))

    def test_an_unreachable_provider_is_not_a_crash(self):
        with self.assertRaises(ProviderError):
            self._raising(URLError("connection refused")).test_connection()

    def test_a_missing_key_is_refused_at_construction(self):
        with self.assertRaises(ProviderError):
            ShippoProvider("")


class RegistryTests(unittest.TestCase):
    def test_an_unwired_provider_does_not_silently_become_a_mock(self):
        """A silent fallback would report a WORKING connection for a provider that has no code."""
        for name in ("shipstation", "easyship", "easypost", ""):
            with self.subTest(name=name):
                with self.assertRaises(ProviderError):
                    provider_for(name, "key")

    def test_mock_needs_no_key_and_contacts_nothing(self):
        self.assertIsInstance(provider_for("mock", ""), MockProvider)
        self.assertTrue(provider_for("mock", "").test_connection()["ok"])

    def test_mock_rates_are_deterministic(self):
        # A test that asserts a price cannot depend on a carrier's live pricing.
        first = MockProvider().rates(from_address={}, to_address={}, parcel={"weight": 2})
        second = MockProvider().rates(from_address={}, to_address={}, parcel={"weight": 2})
        self.assertEqual(first, second)

    def test_mock_carries_both_axes(self):
        # Price and transit time: "cheapest" is the wrong default for a two-day promise.
        for rate in MockProvider().rates(from_address={}, to_address={}, parcel={"weight": 1}):
            self.assertIsInstance(rate["amount"], int)
            self.assertIsInstance(rate["estimated_days"], int)


class ConnectionTestEndpointTests(unittest.TestCase):
    class Repo:
        def __init__(self, doc): self.doc = doc
        def get(self, tenant_id): return self.doc
        def put(self, document): self.doc = document; return document

    class Cipher:
        SECRET = "shippo_live_SECRET_VALUE"
        def decrypt(self, ref, **kwargs): return self.SECRET

    CONFIG = {"schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
              "ship_from_address": {}, "return_address": {}, "default_parcel": {}}
    EVENT = {"httpMethod": "POST", "path": "/shipping/test",
             "queryStringParameters": {"tenant_id": "t1"}, "headers": {}}

    def _call(self, provider):
        from handlers import shipping
        repo = self.Repo({**self.CONFIG, "provider": provider})
        response = shipping.handler(self.EVENT, None, repository=repo, secret_cipher=self.Cipher())
        return response, json.loads(response["body"]), repo.doc

    def test_a_working_provider_records_connected(self):
        response, body, stored = self._call({"name": "mock"})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["connection"]["status"], "connected")
        self.assertEqual(stored["provider"]["connection_status"], "connected")
        self.assertIn("last_tested_at", stored["provider"])

    def test_a_failure_is_an_answer_not_a_500(self):
        response, body, stored = self._call({"name": "shipstation", "api_key_ref": "kms:v1:x"})
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(body["connection"]["status"], "failed")
        self.assertEqual(stored["provider"]["connection_status"], "failed")

    def test_the_key_never_appears_in_the_response(self):
        for provider in ({"name": "mock", "api_key_ref": "kms:v1:x"},
                         {"name": "shipstation", "api_key_ref": "kms:v1:x"}):
            with self.subTest(provider=provider["name"]):
                response, _, _ = self._call(provider)
                self.assertNotIn(self.Cipher.SECRET, response["body"])
                self.assertIn("********", response["body"])

    def test_testing_before_saving_a_key_says_which_is_missing(self):
        response, body, _ = self._call({"name": "shippo"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"], "missing_api_key")

    def test_the_route_exists(self):
        import pathlib
        template = (pathlib.Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")
        self.assertIn("Path: /shipping/test", template)


if __name__ == "__main__":
    unittest.main()
