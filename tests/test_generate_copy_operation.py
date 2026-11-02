"""The copy trigger: `operation: "generate_copy"` on POST /ai/generate.

Folded onto that route for the third time, for the reason the image and enrichment operations already
record — the Api-event guard — plus one the author settled on 2026-11-02: this function owns the provider
adapter, the BYOK configuration and the usage counter, so generating in `../sam/attention` would mean a
second stack re-reaching all three.

The tests that matter are the gates and the ledger, not the copy. The ledger rule is the one worth stating:
**debit first, refund anything that did not produce copy** — somebody who pressed the button and got
nothing back must not have paid for it.
"""

import json
import unittest

from handlers.ai_generate import handler

TENANT = "t1"

BRIEF = {"pillar": "problem", "goal": "agitate latent friction", "brief": "Name the painful status quo.",
         "anchor": "Shakes clump in a shaker bottle", "subject": "Protein Shake", "channel": "tiktok",
         "format": "short_video", "format_label": "TikTok", "seconds": [7, 12],
         "hooks": ["Nobody warns you about shakes clumping"]}

CAROUSEL = {**{k: v for k, v in BRIEF.items() if k != "seconds"},
            "channel": "instagram", "format": "carousel", "format_label": "Instagram carousel",
            "slides": [3, 7]}

ANSWER = {"hook": "Nobody warns you about this", "body": "It clumps every time.\n\nHere is the fix.",
          "slides": []}


def event(brief=BRIEF, **body):
    return {"httpMethod": "POST", "queryStringParameters": {"tenant_id": TENANT},
            "body": json.dumps({"operation": "generate_copy", "brief": brief, **body})}


class Config:
    def __init__(self, provider="bedrock"):
        self._provider = provider

    def get(self, _tenant):
        return {"provider": self._provider, "model": "sonnet-4.6"} if self._provider else {}


class Usage:
    def __init__(self, allowed=True, explodes=False):
        self.allowed = allowed
        self.explodes = explodes
        self.taken = 0
        self.released = 0

    def consume_if_available(self, _tenant, _period, *, allowance=0, at=0, **_kw):
        if self.explodes:
            raise RuntimeError("counter unavailable")
        if not self.allowed:
            return {"allowed": False, "used": allowance}
        self.taken += 1
        return {"allowed": True, "used": self.taken}

    def release(self, _tenant, _period, *, at=0):
        self.released += 1

    def list_for_tenant(self, _tenant):
        return []

    def get(self, *_a, **_k):
        return None


class Jobs:
    """Resolved at the top of `handler` before any dispatch. This operation never touches it."""

    def get(self, *_a, **_k):
        return None

    def put(self, document):
        return document


class Tenants:
    def __init__(self, profile=None):
        self.profile = profile or {"tenant_id": TENANT, "billing_exempt": True,
                                   "business_name": "Poliaxis Nutrition"}

    def get(self, _tenant, _document_id=None):
        """TWO arguments. `_profile` calls `get(tenant_id, tenant_id)`; a one-argument fake raises
        TypeError, the handler swallows it, and every tenant silently looks profile-less."""
        return dict(self.profile)


def run(*, usage=None, config=None, generator=None, tenants=None, brief=BRIEF, **body):
    usage = usage or Usage()
    response = handler(event(brief, **body), None, config_repo=config or Config(), usage_repo=usage,
                       jobs_repo=Jobs(), tenant_repo=tenants or Tenants(), generator=generator,
                       now_fn=lambda: 1_793_000_000)
    return response, usage


def answering(value=ANSWER, captured=None):
    def gen(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return {"value": value}
    return gen


def body_of(response):
    return json.loads(response["body"])


class TheHappyPath(unittest.TestCase):
    def test_it_returns_the_copy(self):
        response, usage = run(generator=answering())
        self.assertEqual(response["statusCode"], 200)
        payload = body_of(response)
        self.assertTrue(payload["generated"])
        self.assertEqual(payload["copy"]["hook"], "Nobody warns you about this")
        self.assertIn("\n\n", payload["copy"]["body"])
        self.assertEqual((usage.taken, usage.released), (1, 0))

    def test_the_copy_is_matched_back_to_its_brief(self):
        """So the dashboard can place it without holding state of its own."""
        payload = body_of(run(generator=answering())[0])
        self.assertEqual(payload["copy"]["pillar"], "problem")
        self.assertEqual(payload["copy"]["channel"], "tiktok")
        self.assertEqual(payload["copy"]["anchor"], BRIEF["anchor"])

    def test_the_ANCHOR_reaches_the_model(self):
        """The bound. A prompt without it is the free-form request this design refuses."""
        captured = {}
        run(generator=answering(captured=captured))
        self.assertIn(BRIEF["anchor"], captured["prompt"])

    def test_it_is_generated_as_BUYER_FACING_copy(self):
        """A social post is published copy, so §A.7's floor applies as it does to a landing page."""
        captured = {}
        run(generator=answering(captured=captured))
        self.assertTrue(captured["for_page"])

    def test_a_carousel_brief_asks_for_slides(self):
        captured = {}
        run(brief=CAROUSEL, generator=answering({"hook": "h", "body": "", "slides": ["One", "Two"]},
                                                captured=captured))
        self.assertIn("`slides`", captured["prompt"])

    def test_the_tenants_configured_provider_and_model_are_used(self):
        captured = {}
        run(generator=answering(captured=captured))
        self.assertEqual(captured["provider"], "bedrock")
        self.assertEqual(captured["model"], "sonnet-4.6")


class TheGatesTests(unittest.TestCase):
    def test_a_brief_with_no_anchor_is_declined_BEFORE_the_counter(self):
        """It would produce a post about nothing in particular, so the tenant keeps the generation."""
        response, usage = run(brief={**BRIEF, "anchor": ""}, generator=answering())
        self.assertEqual(body_of(response)["error"], "missing_brief")
        self.assertEqual((usage.taken, usage.released), (0, 0))

    def test_a_missing_brief_is_declined(self):
        for brief in (None, {}, "", []):
            with self.subTest(brief=brief):
                response, usage = run(brief=brief, generator=answering())
                self.assertEqual(body_of(response)["error"], "missing_brief")
                self.assertEqual(usage.taken, 0)

    def test_no_provider_configured_says_so(self):
        response, usage = run(config=Config(provider=""), generator=answering())
        self.assertEqual(body_of(response)["error"], "ai_not_configured")
        self.assertEqual(usage.taken, 0)

    def test_an_unentitled_tenant_is_refused_before_the_counter(self):
        """"Not on your plan" rather than "you have used 0 of 0"."""
        profile = {"tenant_id": TENANT, "billing_status": "trial", "trial_ends_at": 1,
                   "entitlements": []}
        response, usage = run(tenants=Tenants(profile), generator=answering())
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(body_of(response)["error"], "ai_builder_not_entitled")
        self.assertEqual(usage.taken, 0)

    def test_an_exhausted_allowance_is_429(self):
        response, usage = run(usage=Usage(allowed=False), generator=answering())
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(body_of(response)["error"], "quota_exhausted")

    def test_an_UNUSABLE_counter_fails_CLOSED(self):
        """Never a free run. An unreadable counter is not permission."""
        response, usage = run(usage=Usage(explodes=True), generator=answering())
        self.assertEqual(body_of(response)["error"], "quota_unavailable")
        self.assertEqual(usage.taken, 0)

    def test_the_model_is_not_called_when_a_gate_refuses(self):
        called = []

        def never(**_kw):
            called.append(1)
            return {"value": ANSWER}

        run(config=Config(provider=""), generator=never)
        run(brief={**BRIEF, "anchor": ""}, generator=never)
        run(usage=Usage(allowed=False), generator=never)
        self.assertEqual(called, [])


class TheLedgerTests(unittest.TestCase):
    """Debit first, refund anything that did not produce copy."""

    def test_an_empty_answer_RELEASES_the_generation(self):
        response, usage = run(generator=answering({"hook": "", "body": "", "slides": []}))
        payload = body_of(response)
        self.assertFalse(payload["generated"])
        self.assertEqual(payload["reason"], "no_copy_produced")
        self.assertEqual((usage.taken, usage.released), (1, 1))

    def test_a_PROVIDER_FAILURE_releases_the_generation(self):
        def explodes(**_kw):
            raise RuntimeError("provider down")

        response, usage = run(generator=explodes)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(body_of(response)["error"], "generation_failed")
        self.assertEqual((usage.taken, usage.released), (1, 1))
        self.assertIn("not used", body_of(response)["message"])

    def test_a_carousel_that_came_back_without_slides_releases(self):
        """The tenant asked for a carousel; a paragraph is not one."""
        response, usage = run(brief=CAROUSEL,
                              generator=answering({"hook": "h", "body": "a paragraph", "slides": []}))
        self.assertFalse(body_of(response)["generated"])
        self.assertEqual(usage.released, 1)

    def test_junk_from_the_model_releases_rather_than_500s(self):
        for value in (None, "a string", [], 7):
            with self.subTest(value=value):
                response, usage = run(generator=answering(value))
                self.assertEqual(response["statusCode"], 200)
                self.assertFalse(body_of(response)["generated"])
                self.assertEqual(usage.released, 1)


class TheCounterChoiceTests(unittest.TestCase):
    def test_it_spends_the_PAGE_counter_not_a_third_one(self):
        """A tenant deriving five angles and writing copy for two is doing one piece of work; splitting it
        across two allowances would make them budget against themselves."""
        from stripe_link.domain.ai_quota import OPERATION_COPY, OPERATION_IMAGE, entitlement_for

        profile = {"tenant_id": TENANT, "billing_exempt": True}
        copy = entitlement_for(profile, provider="bedrock", now=1_793_000_000,
                               operation=OPERATION_COPY)
        page = entitlement_for(profile, provider="bedrock", now=1_793_000_000)
        image = entitlement_for(profile, provider="bedrock", now=1_793_000_000,
                                operation=OPERATION_IMAGE)
        self.assertEqual(copy["period"], page["period"])
        self.assertNotEqual(copy["period"], image["period"])


if __name__ == "__main__":
    unittest.main()
