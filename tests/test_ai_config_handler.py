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

    def get(self, tenant_id, document_id=None):
        # Two args, like DynamoDocumentRepository. A one-arg fake accepted a one-arg call that raises
        # TypeError against the real repository -- which is exactly how the AI handlers shipped reading
        # every tenant profile as absent.
        assert document_id is not None, "call it the way the real repository is called: get(tenant_id, id)"
        return dict(self.profile) if self.profile else None


class FakeCipher:
    """Records what it was asked to bind the ciphertext to, so the encryption context can be asserted."""

    def __init__(self):
        self.contexts = []

    def encrypt(self, plaintext, *, tenant_id, mode, field):
        self.contexts.append({"tenant_id": tenant_id, "mode": mode, "field": field})
        return f"kms:v1:enc({plaintext})"


def ok_generator(**kwargs):
    return {"value": {"ok": True}, "usage": {"input": 30, "output": 5, "cache_read": 0},
            "model": kwargs.get("model"), "repairs": 0, "stop_reason": "end_turn"}


class AiConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = FakeKeyed()
        self.usage = FakeUsage()
        # A paying subscriber: the allowance rides on the profile now, denormalized off the plan row, not
        # derived from tier_id (which is the transaction-FEE tier that every paid plan shares).
        self.profiles = FakeProfiles(billing_status="active", stripe_subscription_id="sub_1",
                                     billing_plan_key="premium", ai_generations=20)
        self.calls = []
        self.cipher = FakeCipher()

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
                       secret_cipher=self.cipher, now_fn=lambda: 1790000000)

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
        self.assertEqual(usage["allowance"], 20, "whatever the PLAN row carried, not a number in code")
        self.assertEqual(usage["period"], "2026-09")

    def test_an_unreadable_tenant_profile_gets_the_free_tier_which_is_now_ZERO(self):
        # Reversed 2026-09-29. This used to resolve to a small allowance on the grounds that zero "is a lie
        # to a tenant whose profile read merely blipped". Once the free tier carries no AI, an unreadable
        # profile is indistinguishable from a free one -- and guessing generously on the platform's Bedrock
        # bill is an open tap on the path that must fail closed.
        class Broken:
            def get(self, tenant_id):
                raise RuntimeError("dynamo is having a day")
        self.call("POST", {"provider": "bedrock", "model": "sonnet-4.6"})   # a provider IS configured
        usage = json.loads(self.call("GET", profiles=Broken())["body"])["usage"]
        self.assertEqual(usage["allowance"], 0)
        self.assertEqual(usage["source"], "free")

    def test_no_provider_configured_is_its_own_zero(self):
        # Distinct from an unknown PLAN: a tenant who has not turned AI on has no allowance because
        # there is nothing to spend it through, not because their plan excludes them.
        usage = json.loads(self.call("GET")["body"])["usage"]
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

    # ---- bring your own key ------------------------------------------------------------------
    def test_a_byok_key_is_encrypted_and_never_stored_or_returned_in_clear(self):
        response = self.call("POST", {"provider": "anthropic", "model": "claude-sonnet-4-6",
                                      "api_key": "sk-ant-SECRETVALUE"})
        self.assertEqual(response["statusCode"], 200)
        stored = self.config.documents["t1"]
        # Stored as a KMS reference, never the raw key (the fake echoes the plaintext inside enc(...)
        # on purpose, so that the binding below is assertable).
        self.assertTrue(stored["api_key_ref"].startswith("kms:v1:"))
        self.assertNotIn("sk-ant-SECRETVALUE", json.dumps(response))   # nor in what the browser sees
        self.assertTrue(json.loads(response["body"])["ai_config"]["has_api_key"])
        self.assertNotIn("api_key_ref", json.loads(response["body"])["ai_config"])

    def test_the_key_is_bound_to_this_tenant_by_the_encryption_context(self):
        # A ciphertext lifted from one row must not decrypt against another.
        self.call("POST", {"provider": "anthropic", "model": "claude-sonnet-4-6", "api_key": "k"})
        self.assertEqual(self.cipher.contexts[0], {"tenant_id": "t1", "mode": "ai", "field": "ai_api_key"})

    def test_the_key_is_proven_before_it_is_stored(self):
        # Verify first, encrypt second: a key that does not work never becomes a saved configuration
        # the tenant has to discover is broken later.
        def rejected(**kwargs):
            raise AiError("401", kind="bad_credentials")
        response = self.call("POST", {"provider": "anthropic", "model": "claude-sonnet-4-6",
                                      "api_key": "sk-bad"}, generator=rejected)
        self.assertEqual(json.loads(response["body"])["error"], "verify_bad_credentials")
        self.assertEqual(self.config.documents, {})
        self.assertEqual(self.cipher.contexts, [])   # never even encrypted

    def test_a_rejected_key_says_it_is_the_key(self):
        def rejected(**kwargs):
            raise AiError("401", kind="bad_credentials")
        body = json.loads(self.call("POST", {"provider": "openai", "model": "gpt-5.6",
                                             "api_key": "sk-bad"}, generator=rejected)["body"])
        self.assertIn("rejected by the provider", body["message"])

    def test_the_probe_is_routed_to_the_tenants_provider_with_their_key(self):
        self.call("POST", {"provider": "openai", "model": "gpt-5.6", "api_key": "sk-openai"})
        self.assertEqual(self.calls[0]["provider"], "openai")
        self.assertEqual(self.calls[0]["api_key"], "sk-openai")

    def test_byok_model_names_come_from_the_vendor_not_our_bedrock_registry(self):
        # Their account, their entitlements: "sonnet-4.6" is our registry's name, not Anthropic's.
        response = self.call("POST", {"provider": "anthropic", "model": "sonnet-4.6", "api_key": "k"})
        self.assertEqual(json.loads(response["body"])["error"], "unknown_model")
        self.assertEqual(self.calls, [])

    def test_byok_without_a_key_is_refused_before_anything_is_called(self):
        response = self.call("POST", {"provider": "anthropic", "model": "claude-sonnet-4-6"})
        self.assertEqual(json.loads(response["body"])["error"], "missing_api_key")
        self.assertEqual(self.calls, [])

    def test_a_byok_tenant_is_billed_to_themselves_and_gets_the_safety_ceiling(self):
        self.call("POST", {"provider": "anthropic", "model": "claude-sonnet-4-6", "api_key": "k"})
        usage = json.loads(self.call("GET")["body"])["usage"]
        self.assertEqual(usage["billed_to"], "tenant")
        self.assertEqual(usage["allowance"], 200)

    def test_a_failure_to_encrypt_never_falls_through_to_storing_the_key(self):
        class Broken:
            contexts = []
            def encrypt(self, *a, **k):
                raise RuntimeError("kms unavailable")
        response = handler({"httpMethod": "POST", "resource": "/ai/connect",
                            "queryStringParameters": {"tenant_id": "t1"},
                            "body": json.dumps({"provider": "anthropic", "model": "claude-sonnet-4-6",
                                                "api_key": "sk-secret"})}, None,
                           config_repo=self.config, usage_repo=self.usage, tenant_repo=self.profiles,
                           generator=ok_generator, secret_cipher=Broken(), now_fn=lambda: 1790000000)
        self.assertEqual(json.loads(response["body"])["error"], "encrypt_failed")
        self.assertEqual(self.config.documents, {})
        self.assertNotIn("sk-secret", json.dumps(response))

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
