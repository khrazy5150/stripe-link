"""POST /ai/generate -- brief in, Product + Offer + DRAFT page out.

The behaviour worth pinning is the ACCOUNTING. A generation costs the platform real money, so the
slot is taken before the work and returned only when WE failed -- never because the tenant disliked
the result (author, 2026-09-27). Everything else here is about not leaving half-made rows behind.
"""

import json
import unittest

from handlers.ai_generate import handler
from stripe_link.ai_client import AiError

BRIEF = {
    "kind": "physical", "name": "Poliaxis Creatine Gummies",
    "what_it_is": "Creatine monohydrate in a chewable gummy.",
    "audience": "Lifters who dislike powder.",
    "facts": ["5g creatine monohydrate per serving", "60 gummies per tub"],
    "category": "supplement",
    "price": {"unit_amount": 3291, "currency": "usd",
              "pricing_model": "recurring", "recurring_interval": "month"},
    "guarantee": "30-day money-back guarantee",
}
SECTIONS = [{"id": "h", "type": "headline", "text": "Creatine without the powder"},
            {"id": "s", "type": "subheadline", "text": "60 gummies per tub. 5g per serving."}]


class FakeKeyed:
    def __init__(self, doc=None):
        self.doc = doc
    def get(self, tenant_id):
        return dict(self.doc) if self.doc else None


class FakeDocs:
    def __init__(self):
        self.saved = []
    def put(self, document):
        self.saved.append(document)
        return document


class FakeUsage:
    def __init__(self, used=0, fail_read=False):
        self._used, self.fail_read = used, fail_read
        self.consumed, self.released = 0, 0
    def used(self, tenant_id, period):
        if self.fail_read:
            raise RuntimeError("dynamo is having a day")
        return self._used
    def consume(self, tenant_id, period, *, at, **kw):
        self.consumed += 1
        return self._used + self.consumed
    def release(self, tenant_id, period, *, at):
        self.released += 1


class FakeProfiles:
    def __init__(self, **p):
        self.p = p
    def get(self, tenant_id):
        return dict(self.p) if self.p else None


def ok_generator(**kwargs):
    return {"value": {"sections": SECTIONS}, "usage": {"input": 2000, "output": 700, "cache_read": 0},
            "model": kwargs.get("model"), "repairs": 0, "stop_reason": "end_turn"}


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.products, self.offers, self.pages = FakeDocs(), FakeDocs(), FakeDocs()
        self.usage = FakeUsage()
        self.config = FakeKeyed({"provider": "bedrock", "model": "sonnet-4.6", "verified_at": 1})
        self.profiles = FakeProfiles(tier_id="premium")
        self.seen = []

    def call(self, brief=None, *, generator=None, usage=None, config=None, profiles=None):
        def recording(**kwargs):
            self.seen.append(kwargs)
            return (generator or ok_generator)(**kwargs)
        event = {"httpMethod": "POST", "resource": "/ai/generate",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"brief": BRIEF if brief is None else brief})}
        # A fixed picker keeps generated ids deterministic across a test run.
        return handler(event, None, products_repo=self.products, offers_repo=self.offers,
                       pages_repo=self.pages, config_repo=config or self.config,
                       usage_repo=usage or self.usage, tenant_repo=profiles or self.profiles,
                       generator=recording, now_fn=lambda: 1790500000,
                       randomiser=lambda alphabet: alphabet[0])

    # ---- the happy path ------------------------------------------------------------------------
    def test_it_creates_a_product_an_offer_and_a_draft_page(self):
        response = self.call()
        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        self.assertEqual(len(self.products.saved), 1)
        self.assertEqual(len(self.offers.saved), 1)
        self.assertEqual(len(self.pages.saved), 1)
        self.assertEqual(body["page"]["status"], "draft")
        self.assertIsNone(body["page"]["published_at"])

    def test_the_platform_owns_every_id(self):
        # A model that invents a product_id produces a buy button pointing at nothing.
        body = json.loads(self.call()["body"])
        self.assertTrue(body["product"]["product_id"].startswith("local_"))
        self.assertTrue(body["offer"]["offer_id"].startswith("offer_"))
        self.assertEqual(body["offer"]["items"][0]["product_id"], body["product"]["product_id"])
        self.assertEqual(body["page"]["offer_id"], body["offer"]["offer_id"])

    def test_the_price_comes_from_the_brief_untouched(self):
        body = json.loads(self.call()["body"])
        self.assertEqual(body["product"]["prices"][0]["unit_amount"], 3291)
        # And the checkout mode follows it -- a recurring price behind a payment session charges once.
        self.assertEqual(body["offer"]["checkout"]["mode"], "subscription")

    def test_the_offer_is_active_so_the_page_can_be_previewed_and_edited(self):
        # pricing.py refuses to price a non-active offer at all, so a draft offer left the builder
        # showing "Offer ... is not active" and nothing else. The PAGE's draft status is the gate.
        self.assertEqual(json.loads(self.call()["body"])["offer"]["status"], "active")

    def test_the_page_gets_a_short_code_so_its_preview_link_works(self):
        # The dashboard keys the test viewer on short_code; without one a card falls through to the
        # live preview distribution, which is both the wrong host and an S3 AccessDenied.
        self.assertTrue(json.loads(self.call()["body"])["page"]["short_code"])

    def test_real_measurements_reach_the_product_so_it_can_be_shipped(self):
        brief = {**BRIEF, "physical": {"shipping": "Ships free in the US", "length_in": 4,
                                       "width_in": 4, "height_in": 6, "weight_lb": 1.2}}
        fulfillment = json.loads(self.call(brief)["body"])["product"]["fulfillment"]
        self.assertEqual(fulfillment["weight_lb"], 1.2)
        self.assertEqual(fulfillment["dimensions"], {"length_in": 4, "width_in": 4, "height_in": 6})

    def test_missing_measurements_stay_null_rather_than_guessed(self):
        # label_readiness gates on these; an invented weight is a confidently wrong quote.
        fulfillment = json.loads(self.call()["body"])["product"]["fulfillment"]
        self.assertIsNone(fulfillment["weight_lb"])
        self.assertIsNone(fulfillment["dimensions"]["length_in"])

    def test_a_measurement_licenses_no_claim(self):
        # Giving us a weight is not authorising a sentence about shipping.
        brief = {**BRIEF, "guarantee": "", "physical": {"weight_lb": 1.2}}
        classes = {w["claim_class"] for w in json.loads(self.call(brief)["body"])["withheld"]}
        self.assertIn("shipping", classes)

    def test_the_model_only_writes_copy(self):
        body = json.loads(self.call()["body"])
        self.assertEqual([s["type"] for s in body["page"]["sections"]], ["headline", "subheadline"])

    def test_the_brief_is_what_the_model_is_grounded_on(self):
        self.call()
        prompt = self.seen[0]["prompt"]
        self.assertIn("5g creatine monohydrate per serving", prompt)
        self.assertIn("30-day money-back guarantee", prompt)

    def test_must_not_say_reaches_the_prompt(self):
        self.call({**BRIEF, "must_not_say": ["best in the world"]})
        self.assertIn("best in the world", self.seen[0]["prompt"])

    def test_it_reports_what_the_page_could_not_say(self):
        # The tenant should understand a thin page rather than blame the AI.
        classes = {w["claim_class"] for w in json.loads(self.call()["body"])["withheld"]}
        self.assertIn("cancellation", classes)      # no terms given
        self.assertNotIn("guarantee", classes)      # guarantee WAS given

    def test_it_records_why_each_choice_was_made(self):
        body = json.loads(self.call()["body"])
        self.assertTrue(body["decisions"])
        self.assertTrue(any("preset=" in line for line in body["decisions"]))

    # ---- accounting ----------------------------------------------------------------------------
    def test_a_successful_generation_spends_a_slot(self):
        self.call()
        self.assertEqual(self.usage.consumed, 1)
        self.assertEqual(self.usage.released, 0)

    def test_the_slot_is_taken_before_the_work(self):
        # Two concurrent requests must not both pass the allowance check.
        order = []
        def slow(**kwargs):
            order.append("generate")
            return ok_generator(**kwargs)
        class Watching(FakeUsage):
            def consume(self, *a, **k):
                order.append("consume")
                return super().consume(*a, **k)
        self.call(generator=slow, usage=Watching())
        self.assertEqual(order, ["consume", "generate"])

    def test_a_provider_failure_gives_the_slot_back(self):
        def failing(**kwargs):
            raise AiError("boom", kind="throttled")
        response = self.call(generator=failing)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(self.usage.released, 1)
        self.assertIn("did not use a generation", json.loads(response["body"])["message"])

    def test_output_that_cannot_meet_the_floor_gives_the_slot_back(self):
        def unusable(**kwargs):
            raise AiError("nope", kind="unusable_output")
        self.call(generator=unusable)
        self.assertEqual(self.usage.released, 1)

    def test_an_exhausted_allowance_refuses_before_anything_is_spent(self):
        response = self.call(usage=FakeUsage(used=50))
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(json.loads(response["body"])["error"], "quota_exhausted")
        self.assertEqual(self.seen, [])
        self.assertEqual(self.products.saved, [])

    def test_an_unreadable_counter_fails_closed(self):
        # Failing open would hand out unmetered inference on the platform's bill.
        response = self.call(usage=FakeUsage(fail_read=True))
        self.assertEqual(json.loads(response["body"])["error"], "quota_unavailable")
        self.assertEqual(self.seen, [])

    def test_a_missing_tenant_profile_falls_to_the_free_allowance(self):
        response = self.call(profiles=FakeProfiles())      # no profile at all
        self.assertEqual(response["statusCode"], 201)      # free tier still gets a few
        self.assertEqual(self.usage.consumed, 1)

    # ---- refusals ------------------------------------------------------------------------------
    def test_an_invalid_brief_costs_nothing(self):
        response = self.call({**BRIEF, "facts": []})
        self.assertEqual(json.loads(response["body"])["error"], "invalid_brief")
        self.assertEqual(self.usage.consumed, 0)
        self.assertEqual(self.seen, [])

    def test_a_service_brief_is_handed_to_the_services_wizard(self):
        # Three wizards each creating services slightly differently is the confusion
        # plans/SERVICE_WIZARD.md exists to dissolve.
        response = self.call({**BRIEF, "kind": "service",
                              "service": {"duration_minutes": 60, "location_mode": "remote"}})
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "service_handoff")
        self.assertEqual(self.usage.consumed, 0)
        self.assertEqual(self.products.saved, [])

    def test_generating_before_ai_is_turned_on_is_refused(self):
        response = self.call(config=FakeKeyed(None))
        self.assertEqual(json.loads(response["body"])["error"], "ai_not_configured")
        self.assertEqual(self.usage.consumed, 0)

    def test_nothing_is_written_when_a_document_would_be_invalid(self):
        # A product saved beside a rejected page is the half-made thing a tenant cannot finish.
        def bad_sections(**kwargs):
            return {**ok_generator(**kwargs), "value": {"sections": [{"no_id": True}]}}
        response = self.call(generator=bad_sections)
        self.assertEqual(json.loads(response["body"])["error"], "save_failed")
        self.assertEqual(self.products.saved, [])
        self.assertEqual(self.offers.saved, [])
        self.assertEqual(self.pages.saved, [])
        self.assertEqual(self.usage.released, 1)
