"""Slice 1 of AI_AND_COMMERCE Part A: the provider adapter, the registry, the quota.

The fakes reproduce failure modes MEASURED against real Bedrock on 2026-09-27 rather than imagined
ones -- the array-wrapped object and the malformed JSON are what `openai.gpt-oss-120b` actually did,
and the AccessDenied-on-a-fully-green-model is what every newly-agreed model did for minutes after its
agreement reported AVAILABLE.
"""

import json
import unittest

from stripe_link.ai_client import AiError, generate_structured
from stripe_link.domain.ai_models import (allows_page_generation, cache_checkpoint_worthwhile,
                                          default_model, estimate_cost, model, model_names, profile_id)
from stripe_link.domain.ai_provider import (AiConfigError, config_record, is_verified, needs_key,
                                            pays_platform, redacted, validate)
from stripe_link.domain.ai_quota import (BYOK_CEILING, UNLIMITED, entitlement_for, may_generate,
                                         period_key, remaining, usage_record)

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["sections"],
          "properties": {"sections": {"type": "array", "items": {"type": "object"}}}}
GOOD = {"sections": [{"id": "h", "type": "headline"}]}


class FakeConverse:
    """A Bedrock stand-in. `replies` are returned in order; each is text or an Exception to raise."""

    def __init__(self, *replies, usage=(100, 50)):
        self.replies = list(replies)
        self.calls = []
        self.usage = usage

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else json.dumps(GOOD)
        if isinstance(reply, Exception):
            raise reply
        return {"output": {"message": {"content": [{"text": reply}]}},
                "usage": {"inputTokens": self.usage[0], "outputTokens": self.usage[1]},
                "stopReason": "end_turn"}


def _exc(name):
    return type(name, (Exception,), {})(f"simulated {name}")


class RegistryTests(unittest.TestCase):
    def test_every_model_calls_the_GLOBAL_profile(self):
        # Regional costs exactly 10% more for identical output, and a page-composition prompt carries
        # tenant product copy rather than customer PII, so there is nothing to keep in one geography.
        for name in model_names():
            with self.subTest(name=name):
                self.assertTrue(profile_id(name).startswith("global."))

    def test_a_regional_profile_is_kept_for_whoever_needs_US_only_routing(self):
        for name in model_names():
            with self.subTest(name=name):
                self.assertTrue(model(name)["profile_regional"].startswith("us."))

    def test_every_model_declares_its_rate_confidence(self):
        # AWS publishes none of these rates machine-readably; a number without a confidence invites
        # someone to quote it to a tenant as fact.
        for name in model_names():
            with self.subTest(name=name):
                # Authoritative now that the Marketplace rate card turned out to carry them; the field
                # stays because a hand-edited future entry must be able to admit it is a guess.
                self.assertIn(model(name)["rate_confidence"], {"authoritative", "indicative", "unknown"})

    def test_the_default_model_exists_and_may_write_pages(self):
        self.assertIn(default_model(), model_names())
        self.assertTrue(allows_page_generation(default_model()))

    def test_haiku_is_barred_from_page_generation(self):
        # §A.7, measured: cheapest of the four and the only one that invented dosing and an efficacy
        # claim. The bar lives in the registry so it cannot depend on being remembered.
        self.assertFalse(allows_page_generation("haiku-4.5"))

    def test_cost_reproduces_the_measured_call_at_the_rate_we_actually_pay(self):
        # The real 2026-09-27 Sonnet 4.6 generation: 1552 in, 714 out, now priced at the GLOBAL rate we
        # moved to. Regional would be $0.016903 -- exactly 10% more for the same output.
        self.assertEqual(estimate_cost("sonnet-4.6", 1552, 714)["usd"], 0.015366)
        self.assertEqual(estimate_cost("sonnet-4.6", 1552, 714)["confidence"], "authoritative")

    def test_the_regional_premium_is_recorded_so_a_switch_back_can_be_priced(self):
        for name in model_names():
            with self.subTest(name=name):
                self.assertEqual(model(name)["rate_regional_multiplier"], 1.1)

    def test_an_unknown_model_costs_nothing_and_says_so(self):
        out = estimate_cost("no-such-model", 1000, 1000)
        self.assertEqual(out["usd"], 0.0)
        self.assertFalse(out["known"])

    def test_cache_checkpoint_respects_the_minimum(self):
        self.assertTrue(cache_checkpoint_worthwhile("sonnet-4.6", 1024))
        self.assertFalse(cache_checkpoint_worthwhile("sonnet-4.6", 1023))


class GenerateStructuredTests(unittest.TestCase):
    def call(self, fake, **kw):
        return generate_structured(prompt="p", json_schema=SCHEMA, model="sonnet-4.6",
                                   client=fake, **kw)

    def test_the_happy_path_returns_the_object_with_usage(self):
        fake = FakeConverse(json.dumps(GOOD))
        out = self.call(fake)
        self.assertEqual(out["value"], GOOD)
        self.assertEqual(out["usage"], {"input": 100, "output": 50, "cache_read": 0})
        self.assertEqual(out["repairs"], 0)

    def test_it_asks_for_native_structured_output_not_tool_use(self):
        fake = FakeConverse(json.dumps(GOOD))
        self.call(fake)
        sent = fake.calls[0]
        self.assertEqual(sent["outputConfig"]["textFormat"]["type"], "json_schema")
        self.assertNotIn("toolConfig", sent)
        self.assertEqual(json.loads(sent["outputConfig"]["textFormat"]["structure"]["jsonSchema"]["schema"]), SCHEMA)

    def test_it_sends_an_inference_profile_id(self):
        fake = FakeConverse(json.dumps(GOOD))
        self.call(fake)
        self.assertEqual(fake.calls[0]["modelId"], "global.anthropic.claude-sonnet-4-6")

    def test_a_single_element_array_wrapper_is_recovered_without_a_repair_round(self):
        # Exactly what openai.gpt-oss-120b did: `[{...}]` for an object-rooted schema. Re-prompting to
        # fix a bracket costs a whole request.
        fake = FakeConverse(json.dumps([GOOD]))
        out = self.call(fake)
        self.assertEqual(out["value"], GOOD)
        self.assertEqual(out["repairs"], 0)
        self.assertEqual(len(fake.calls), 1)

    def test_a_markdown_fence_is_recovered_without_a_repair_round(self):
        fake = FakeConverse("```json\n" + json.dumps(GOOD) + "\n```")
        self.assertEqual(self.call(fake)["value"], GOOD)
        self.assertEqual(len(fake.calls), 1)

    def test_malformed_json_is_repaired_and_the_complaint_says_what_was_wrong(self):
        fake = FakeConverse("{not json", json.dumps(GOOD))
        out = self.call(fake)
        self.assertEqual(out["value"], GOOD)
        self.assertEqual(out["repairs"], 1)
        followup = fake.calls[1]["messages"][-1]["content"][0]["text"]
        self.assertIn("not valid JSON", followup)   # an unexplained retry reproduces the same output

    def test_a_failing_caller_validator_drives_the_repair(self):
        seen = []
        def validator(value):
            seen.append(value)
            if len(seen) == 1:
                raise ValueError("sections must not be empty")
        fake = FakeConverse(json.dumps({"sections": []}), json.dumps(GOOD))
        out = self.call(fake, validate=validator)
        self.assertEqual(out["repairs"], 1)
        self.assertIn("sections must not be empty", fake.calls[1]["messages"][-1]["content"][0]["text"])

    def test_usage_accumulates_across_repairs(self):
        # A repair is a whole extra request; billing it as one would understate the real cost.
        fake = FakeConverse("{bad", "{bad", json.dumps(GOOD))
        out = self.call(fake)
        self.assertEqual(out["usage"]["input"], 300)
        self.assertEqual(out["usage"]["output"], 150)

    def test_it_gives_up_after_the_repair_budget(self):
        fake = FakeConverse("{bad", "{bad", "{bad", "{bad")
        with self.assertRaises(AiError) as caught:
            self.call(fake)
        self.assertEqual(caught.exception.kind, "unusable_output")
        self.assertEqual(len(fake.calls), 3)  # the first try plus MAX_REPAIRS

    def test_access_denied_is_its_own_kind(self):
        # The one failure a tenant cannot fix and an operator can: a missing Marketplace agreement.
        fake = FakeConverse(_exc("AccessDeniedException"))
        with self.assertRaises(AiError) as caught:
            self.call(fake)
        self.assertEqual(caught.exception.kind, "not_entitled")

    def test_throttling_is_distinguished_from_a_bad_request(self):
        for name, kind in (("ThrottlingException", "throttled"),
                           ("ServiceQuotaExceededException", "throttled"),
                           ("ValidationException", "invalid_request"),
                           ("SomethingElse", "provider_error")):
            with self.subTest(name=name):
                with self.assertRaises(AiError) as caught:
                    self.call(FakeConverse(_exc(name)))
                self.assertEqual(caught.exception.kind, kind)

    def test_a_barred_model_is_refused_before_any_call_is_made(self):
        fake = FakeConverse(json.dumps(GOOD))
        with self.assertRaises(AiError) as caught:
            generate_structured(prompt="p", json_schema=SCHEMA, model="haiku-4.5",
                                client=fake, for_page=True)
        self.assertEqual(caught.exception.kind, "invalid_request")
        self.assertEqual(fake.calls, [])  # refused locally -- no tokens spent proving the obvious

    def test_an_unknown_model_never_reaches_the_wire(self):
        fake = FakeConverse(json.dumps(GOOD))
        with self.assertRaises(AiError):
            generate_structured(prompt="p", json_schema=SCHEMA, model="gpt-9", client=fake)
        self.assertEqual(fake.calls, [])

    def test_a_long_system_prompt_gets_a_cache_checkpoint(self):
        fake = FakeConverse(json.dumps(GOOD))
        self.call(fake, system="x" * 8000)  # ~2000 tokens, over the 1024 minimum
        self.assertIn({"cachePoint": {"type": "default"}}, fake.calls[0]["system"])

    def test_a_short_system_prompt_does_not(self):
        fake = FakeConverse(json.dumps(GOOD))
        self.call(fake, system="short")
        self.assertNotIn({"cachePoint": {"type": "default"}}, fake.calls[0]["system"])


class ProviderConfigTests(unittest.TestCase):
    def test_bedrock_takes_no_key_and_the_platform_pays(self):
        record = config_record("t1", provider="bedrock", model="sonnet-4.6")
        self.assertNotIn("api_key_ref", record)
        self.assertTrue(pays_platform("bedrock"))
        self.assertFalse(needs_key("bedrock"))

    def test_a_byok_provider_needs_a_key_and_the_tenant_pays(self):
        self.assertTrue(needs_key("anthropic"))
        self.assertFalse(pays_platform("anthropic"))
        with self.assertRaises(AiConfigError):
            validate({"provider": "anthropic"})

    def test_a_key_on_bedrock_is_refused_rather_than_ignored(self):
        with self.assertRaises(AiConfigError):
            validate({"provider": "bedrock", "api_key_ref": "kms://x"})

    def test_the_ciphertext_never_survives_redaction(self):
        # The Connect OAuth lesson: the browser needs to know a key EXISTS, never what it is.
        record = config_record("t1", provider="openai", model="sonnet-4.6", api_key_ref="kms://secret")
        safe = redacted(record)
        self.assertNotIn("api_key_ref", safe)
        self.assertTrue(safe["has_api_key"])
        self.assertNotIn("secret", json.dumps(safe))

    def test_a_fresh_config_is_not_verified(self):
        # Verification means a real generation succeeded -- never a catalogue lookup, which was
        # measured reporting four green flags for models that still returned AccessDenied.
        self.assertFalse(is_verified(config_record("t1", provider="bedrock", model="sonnet-4.6")))
        self.assertTrue(is_verified({"verified_at": 1790000000}))


class QuotaTests(unittest.TestCase):
    """The allowance is DATA, and these tests exist to keep it that way.

    Nothing here asserts a price. The numbers live on the plan row (`ai_generations`) and the CONFIG row
    (`ai_trial_generations` / `ai_free_generations`) in PlatformPlansTable so the Admin Site can edit them
    without a deploy -- the same path `entitlements` and `fee_tier` already take. A test asserting "premium
    means 20" would quietly become the pricing, which is how the fee table ended up disagreeing with itself.
    """

    def test_the_period_is_a_calendar_month(self):
        self.assertEqual(period_key(1790000000), "2026-09")

    def test_a_subscriber_gets_the_allowance_the_PLAN_carried(self):
        # Off the tenant, put there by the billing webhook from the plan row. Whatever the Admin Site set.
        tenant = {"stripe_subscription_id": "sub_1", "billing_plan_key": "premium", "ai_generations": 37}
        entitlement = entitlement_for(tenant, provider="bedrock")
        self.assertEqual(entitlement["allowance"], 37)
        self.assertEqual(entitlement["source"], "plan")

    def test_the_allowance_is_not_keyed_on_the_fee_tier(self):
        # The bug this replaced. `tier_id` is the TRANSACTION-FEE tier and every paid plan carries "pro", so
        # an allowance keyed there gives a $19 and a $69 plan the same number. Two subscribers on the same
        # fee tier must be able to hold different allowances.
        cheap = {"stripe_subscription_id": "s", "tier_id": "pro", "ai_generations": 20}
        dear = {"stripe_subscription_id": "s", "tier_id": "pro", "ai_generations": 100}
        self.assertNotEqual(entitlement_for(cheap, provider="bedrock")["allowance"],
                            entitlement_for(dear, provider="bedrock")["allowance"])

    def test_a_paying_tenant_whose_webhook_has_not_run_still_gets_something(self):
        # They are paying. The missing denormalization is our failure, and the exposure is the lowest rung.
        entitlement = entitlement_for({"stripe_subscription_id": "sub_1"}, provider="bedrock")
        self.assertGreater(entitlement["allowance"], 0)

    def test_a_live_trial_draws_on_a_LIFETIME_counter(self):
        # Not a calendar period: a trial starting 25 September spans two months and would otherwise be
        # handed its allowance twice.
        trial = {"billing_status": "trial", "trial_ends_at": 1790000000}
        entitlement = entitlement_for(trial, provider="bedrock", now=1789000000, trial_allowance=3)
        self.assertEqual(entitlement["allowance"], 3)
        self.assertEqual(entitlement["period"], "trial")
        self.assertEqual(entitlement["source"], "trial")

    def test_an_expired_trial_falls_to_the_free_tier(self):
        trial = {"billing_status": "trial", "trial_ends_at": 1789000000}
        entitlement = entitlement_for(trial, provider="bedrock", now=1790000000, free_allowance=0)
        self.assertEqual(entitlement["allowance"], 0)
        self.assertEqual(entitlement["source"], "free")

    def test_the_free_tier_is_refused_with_a_reason_a_tenant_can_act_on(self):
        entitlement = entitlement_for({}, provider="bedrock", free_allowance=0)
        allowed, why = may_generate(0, entitlement["allowance"], entitlement["source"])
        self.assertFalse(allowed)
        self.assertIn("not included on your plan", why)

    def test_an_exhausted_trial_is_not_told_to_wait_for_a_reset(self):
        # There is no reset. Saying "they reset on the 1st" to a trial tenant is simply false.
        _, why = may_generate(3, 3, "trial")
        self.assertIn("trial", why)
        self.assertNotIn("reset on the 1st", why)

    def test_an_unconfigured_provider_gets_nothing(self):
        # Absence is not "not Bedrock": reading it as BYOK handed every tenant a 200-generation ceiling.
        self.assertEqual(entitlement_for({}, provider="")["allowance"], 0)

    def test_a_byok_tenant_on_any_plan_still_gets_the_safety_ceiling(self):
        # Their key, their bill -- the ceiling exists so a runaway loop cannot quietly spend their
        # money, not to ration them.
        self.assertEqual(entitlement_for({}, provider="anthropic")["allowance"], BYOK_CEILING)
        allowed, _ = may_generate(0, entitlement_for({}, provider="anthropic")["allowance"])
        self.assertTrue(allowed)

    def test_a_tenant_with_no_provider_configured_gets_nothing(self):
        # "Not bedrock" is not the same as "BYOK": reading the absence as BYOK granted every tenant who
        # had never opened the screen a 200-generation ceiling.
        self.assertEqual(entitlement_for({"stripe_subscription_id": "s"}, provider="")["allowance"], 0)
        self.assertFalse(
            may_generate(0, entitlement_for({"stripe_subscription_id": "s"}, provider="")["allowance"])[0])

    def test_an_exempt_tenant_is_uncapped(self):
        self.assertEqual(
            entitlement_for({"billing_exempt": True}, provider="bedrock")["allowance"], UNLIMITED)
        self.assertTrue(may_generate(10_000, UNLIMITED)[0])
        self.assertEqual(remaining(10_000, UNLIMITED), UNLIMITED)

    def test_the_boundary_is_exclusive(self):
        self.assertTrue(may_generate(49, 50)[0])
        self.assertFalse(may_generate(50, 50)[0])
        self.assertEqual(remaining(50, 50), 0)

    def test_a_refusal_tells_the_tenant_what_to_do(self):
        _, exhausted = may_generate(50, 50)
        self.assertIn("reset on the 1st", exhausted)
        self.assertIn("your own AI provider key", exhausted)
        _, none = may_generate(0, 0)
        self.assertIn("Upgrade", none)

    def test_the_counter_rolls_over_by_not_existing(self):
        record = usage_record("t1", at=1790000000)
        self.assertEqual(record["period"], "2026-09")
        self.assertEqual(record["used"], 0)
