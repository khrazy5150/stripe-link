"""GET /ai/config and POST /ai/connect.

The behaviour under test that matters most is that connecting PROVES itself with a real generation.
Measured 2026-09-27: `list-foundation-models` lists models an account cannot call;
`get-foundation-model-availability` then reports agreement, entitlement, authorization and region all
positive for exactly those models; and a model whose agreement reads NOT_AVAILABLE invokes perfectly.
No readable field means "this model will answer", so a config that has not generated is not verified.
"""

import json
import unittest

from handlers.ai_config import handler
from stripe_link.ai_client import AiError


class FakeKeyed:
    """A tenant-keyed singleton store (SimpleKeyRepository's shape)."""

    def __init__(self):
        self.documents = {}

    def put(self, document):
        self.documents[document["tenant_id"]] = dict(document)
        return document

    def get(self, tenant_id):
        found = self.documents.get(tenant_id)
        return dict(found) if found else None


class FakeUsage:
    def __init__(self, used=0):
        self.counts = {}
        self._seed = used

    def used(self, tenant_id, period):
        return self.counts.get((tenant_id, period), self._seed)


class FakeProfiles:
    def __init__(self, **profile):
        self.profile = profile

    def get(self, tenant_id):
        return dict(self.profile) if self.profile else None


def ok_generator(**kwargs):
    return {"value": {"ok": True}, "usage": {"input": 30, "output": 5, "cache_read": 0},
            "model": kwargs.get("model"), "repairs": 0, "stop_reason": "end_turn"}


class AiConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = FakeKeyed()
        self.usage = FakeUsage()
        self.profiles = FakeProfiles(tier_id="premium")
        self.calls = []

    def call(self, method, body=None, *, generator=None, profiles=None, usage=None):
        def recording(**kwargs):
            self.calls.append(kwargs)
            return (generator or ok_generator)(**kwargs)
        event = {"httpMethod": method,
                 "resource": "/ai/config" if method == "GET" else "/ai/connect",
                 "queryStringParameters": {"tenant_id": "t1"}}
        if body is not None:
            event["body"] = json.dumps(body)
        return handler(event, None, config_repo=self.config, usage_repo=usage or self.usage,
                       tenant_repo=profiles or self.profiles, generator=recording,
                       now_fn=lambda: 1790000000)

    # ---- GET ---------------------------------------------------------------------------------
    def test_an_unconfigured_tenant_still_gets_the_catalogue_and_its_allowance(self):
        body = json.loads(self.call("GET")["body"])
        self.assertEqual(body["ai_config"], {})
        self.assertFalse(body["verified"])
        self.assertTrue(body["models"])
        self.assertEqual(body["default_model"], "sonnet-4.6")

    def test_a_model_barred_from_pages_is_absent_from_the_catalogue(self):
        # Not listed-with-a-warning: a model that drifted on facts it was not given (§A.7) should not be
        # one click from a buyer-facing page.
        names = {m["name"] for m in json.loads(self.call("GET")["body"])["models"]}
        self.assertIn("sonnet-4.6", names)
        self.assertNotIn("haiku-4.5", names)

    def test_every_offered_model_states_how_sure_its_price_is(self):
        for entry in json.loads(self.call("GET")["body"])["models"]:
            with self.subTest(model=entry["name"]):
                self.assertIn(entry["rate_confidence"], {"authoritative", "indicative", "unknown"})

    def test_the_usage_block_says_who_is_billed(self):
        self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"})
        usage = json.loads(self.call("GET")["body"])["usage"]
        self.assertEqual(usage["billed_to"], "platform")
        self.assertEqual(usage["allowance"], 50)
        self.assertEqual(usage["period"], "2026-09")

    def test_an_unreadable_tenant_profile_falls_to_the_free_tier(self):
        # Fail CLOSED: a missing profile must not hand out platform-paid inference.
        class Broken:
            def get(self, tenant_id):
                raise RuntimeError("dynamo is having a day")
        usage = json.loads(self.call("GET", profiles=Broken())["body"])["usage"]
        self.assertEqual(usage["allowance"], 0)

    def test_a_broken_counter_does_not_break_the_screen(self):
        class Broken:
            def used(self, tenant_id, period):
                raise RuntimeError("no")
        self.assertEqual(self.call("GET", usage=Broken())["statusCode"], 200)

    def test_tenant_id_is_required(self):
        response = handler({"httpMethod": "GET", "resource": "/ai/config"}, None,
                           config_repo=self.config, usage_repo=self.usage, tenant_repo=self.profiles)
        self.assertEqual(json.loads(response["body"])["error"], "missing_tenant")

    # ---- POST /ai/connect --------------------------------------------------------------------
    def test_connecting_runs_a_real_generation_before_saving(self):
        response = self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(self.calls), 1)                       # it actually called the model
        self.assertEqual(self.calls[0]["model"], "sonnet-4.6")
        self.assertTrue(json.loads(response["body"])["verified"])
        self.assertEqual(self.config.documents["t1"]["verified_at"], 1790000000)

    def test_the_probe_is_small(self):
        # It runs on every connect and the platform pays for it on the Bedrock path.
        self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"})
        self.assertLessEqual(self.calls[0]["max_tokens"], 64)

    def test_nothing_is_saved_when_the_model_will_not_answer(self):
        def denied(**kwargs):
            raise AiError("nope", kind="not_entitled")
        response = self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"}, generator=denied)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["error"], "verify_not_entitled")
        self.assertEqual(self.config.documents, {})   # an unverified config is not a config

    def test_an_entitlement_failure_tells_the_tenant_it_is_not_their_fault(self):
        def denied(**kwargs):
            raise AiError("nope", kind="not_entitled")
        body = json.loads(self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"},
                                    generator=denied)["body"])
        self.assertIn("Nothing is wrong with your settings", body["message"])

    def test_failure_messages_name_the_side_the_problem_is_on(self):
        for kind, needle in (("throttled", "busy right now"),
                             ("unusable_output", "could not follow the required format"),
                             ("provider_error", "Could not reach")):
            with self.subTest(kind=kind):
                def failing(**kwargs):
                    raise AiError("boom", kind=kind)
                body = json.loads(self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"},
                                            generator=failing)["body"])
                self.assertIn(needle, body["message"])

    def test_an_unknown_model_is_refused_without_calling_anything(self):
        response = self.call("POST", {"provider": "bedrock", "model": "gpt-42"})
        self.assertEqual(json.loads(response["body"])["error"], "unknown_model")
        self.assertEqual(self.calls, [])

    def test_byok_is_refused_as_unbuilt_rather_than_storing_a_key_in_clear(self):
        response = self.call("POST", {"provider": "anthropic", "model": "sonnet-4.6",
                                      "api_key": "sk-ant-secret"})
        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(self.config.documents, {})
        self.assertNotIn("sk-ant-secret", json.dumps(response))

    def test_byok_without_a_key_is_refused_before_anything_else(self):
        response = self.call("POST", {"provider": "anthropic", "model": "sonnet-4.6"})
        self.assertEqual(json.loads(response["body"])["error"], "missing_api_key")

    def test_an_unknown_provider_is_refused(self):
        response = self.call("POST", {"provider": "skynet", "model": "sonnet-4.6"})
        self.assertEqual(json.loads(response["body"])["error"], "invalid_ai_config")

    def test_connecting_defaults_the_model_when_none_is_given(self):
        self.call("POST", {"provider": "bedrock"})
        self.assertEqual(self.config.documents["t1"]["model"], "sonnet-4.6")

    def test_an_unsupported_method_is_rejected(self):
        response = handler({"httpMethod": "DELETE", "resource": "/ai/config",
                            "queryStringParameters": {"tenant_id": "t1"}}, None,
                           config_repo=self.config, usage_repo=self.usage, tenant_repo=self.profiles)
        self.assertEqual(response["statusCode"], 405)
