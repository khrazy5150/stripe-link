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
        self.costs = {}
    def used(self, tenant_id, period):
        if self.fail_read:
            raise RuntimeError("dynamo is having a day")
        return self._used
    def consume(self, tenant_id, period, *, at, **kw):
        self.consumed += 1
        return self._used + self.consumed
    def consume_if_available(self, tenant_id, period, *, allowance, at, **kw):
        # Mirrors the real repository's contract: the WRITE decides. A fake that always says yes would
        # let the handler's refusal path rot untested, which is how the read-then-write race survived.
        if self.fail_read:
            raise RuntimeError("dynamo is having a day")
        total = self._used + self.consumed + 1
        if int(allowance) >= 0 and total > int(allowance):
            return {"allowed": False, "used": self._used + self.consumed}
        self.consumed += 1
        return {"allowed": True, "used": total}
    def release(self, tenant_id, period, *, at):
        self.released += 1
    def cost(self, tenant_id, period):
        return self.costs.get((tenant_id, period), 0)
    def add_cost(self, tenant_id, period, *, micros, at, **kw):
        self.costs[(tenant_id, period)] = self.costs.get((tenant_id, period), 0) + int(micros)
        return self.costs[(tenant_id, period)]


class FakeEvents:
    """The permanent ledger. Records what was written so the tests can assert on evidence, not on silence."""
    def __init__(self, fail=False):
        self.rows, self.patches, self.fail = [], [], fail
    def put(self, event):
        if self.fail:
            raise RuntimeError("ledger table is unreachable")
        self.rows.append(dict(event))
        return event
    def complete(self, tenant_id, event_key, patch):
        if self.fail:
            raise RuntimeError("ledger table is unreachable")
        self.patches.append((tenant_id, event_key, dict(patch)))


class FakeProfiles:
    def __init__(self, **p):
        self.p = p
    def get(self, tenant_id):
        return dict(self.p) if self.p else None


def subscriber(allowance=20, **extra):
    """A paying tenant. The allowance rides on the PROFILE, denormalized off the plan row by the billing
    webhook -- it is not derived from tier_id, which is the transaction-fee tier every paid plan shares."""
    return FakeProfiles(billing_status="active", stripe_subscription_id="sub_1",
                        billing_plan_key="premium", ai_generations=allowance,
                        # Gate 1. Denormalized off the plan row by the billing webhook -- a subscriber whose
                        # PLAN does not grant ai_builder does not get it, however large their allowance.
                        entitlements=["ai_builder"], **extra)


def ok_generator(**kwargs):
    return {"value": {"sections": SECTIONS}, "usage": {"input": 2000, "output": 700, "cache_read": 0},
            "model": kwargs.get("model"), "repairs": 0, "stop_reason": "end_turn"}


class FakeStore(FakeDocs):
    """A repository that can also read back, for the regenerate path."""

    def __init__(self, *docs):
        super().__init__()
        self.rows = {(d["tenant_id"], d.get("page_id") or d.get("offer_id")): d for d in docs}
    def get(self, tenant_id, doc_id):
        found = self.rows.get((tenant_id, doc_id))
        return dict(found) if found else None
    def put(self, document):
        self.rows[(document["tenant_id"], document.get("page_id") or document.get("offer_id"))] = document
        return super().put(document)


class RegenerateTests(unittest.TestCase):
    """`page_id` rewrites the COPY. The product, the offer and their Stripe sync are untouched --
    otherwise every retry leaves a duplicate product behind."""

    def setUp(self):
        self.existing = {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
                         "page_id": "page_X", "name": "Whey", "status": "draft", "published_at": None,
                         "stripe_mode": "test", "route": {"slug": "whey"}, "offer_id": "offer_X",
                         "theme": {"preset": "clean-slate"}, "short_code": "abc123",
                         "sections": [{"id": "old", "type": "headline", "text": "Old words"}],
                         "created_at": 1, "updated_at": 1}
        self.pages = FakeStore(self.existing)
        self.offers = FakeStore({"tenant_id": "t1", "offer_id": "offer_X", "status": "active"})
        self.products = FakeDocs()
        self.usage = FakeUsage()

    def call(self, page_id="page_X", *, page=None):
        if page is not None:
            self.pages = FakeStore(page)
        self.jobs = FakeJobs()
        kwargs = dict(products_repo=self.products, offers_repo=self.offers, pages_repo=self.pages,
                      config_repo=FakeKeyed({"provider": "bedrock", "model": "sonnet-4.6"}),
                      usage_repo=self.usage, tenant_repo=subscriber(),
                      jobs_repo=self.jobs, generator=ok_generator, events_repo=FakeEvents(),
                      now_fn=lambda: 1790500000, randomiser=lambda a: a[0])
        return run_to_completion(
            {"httpMethod": "POST", "resource": "/ai/generate",
             "queryStringParameters": {"tenant_id": "t1"},
             "body": json.dumps({"brief": BRIEF, "page_id": page_id})}, self.jobs, kwargs)

    def test_it_replaces_the_copy_and_creates_no_duplicate_product(self):
        body = json.loads(self.call()["body"])
        self.assertEqual(self.products.saved, [])
        self.assertEqual(body["page"]["page_id"], "page_X")
        self.assertEqual([s["type"] for s in body["page"]["sections"]], ["headline", "subheadline"])
        self.assertNotIn("Old words", json.dumps(body["page"]["sections"]))

    def test_the_page_keeps_its_identity(self):
        # Same id, same slug, same short_code -- the preview link a tenant may already have shared.
        body = json.loads(self.call()["body"])
        self.assertEqual(body["page"]["short_code"], "abc123")
        self.assertEqual(body["page"]["route"]["slug"], "whey")

    def test_it_still_costs_a_generation(self):
        # The model ran. Releasing on taste is unbounded.
        self.call()
        self.assertEqual(self.usage.consumed, 1)
        self.assertEqual(self.usage.released, 0)

    def test_a_published_page_is_refused_rather_than_rewritten(self):
        # Replacing the words under a live URL unasked is what the draft-only rule exists to prevent.
        response = self.call(page=dict(self.existing, status="published", published_at=1790000000))
        self.assertEqual(json.loads(response["body"])["error"], "save_failed")
        self.assertIn("Unpublish", json.loads(response["body"])["message"])

    def test_a_missing_page_is_refused(self):
        response = self.call("page_gone")
        self.assertEqual(json.loads(response["body"])["error"], "save_failed")


def run_to_completion(event, jobs, kwargs):
    """Queue, run the job inline, and flatten the outcome to the old request-shaped reply.

    The endpoint answers 202 with a job id now, because generation outlives API Gateway's 29-second
    ceiling. These tests care about the PIPELINE, not the queueing, so the job is run synchronously
    and its terminal state is presented the way the caller used to receive it.
    """
    def run_now(job):
        handler({"internal_job": True, "tenant_id": job["tenant_id"], "job_id": job["job_id"]},
                None, **kwargs)
    queued = handler(event, None, invoker=run_now, **kwargs)
    if queued.get("statusCode") != 202:
        return queued
    job = jobs.get("t1", json.loads(queued["body"])["job"]["job_id"])
    if job.get("status") == "failed":
        return {"statusCode": 400,
                "body": json.dumps({"error": job["error"]["code"], "message": job["error"]["message"]})}
    return {"statusCode": 201, "body": json.dumps({**job["result"], "usage": job["usage"],
                                                   "withheld": job["withheld"]})}


class FakeJobs:
    """Tenant+job keyed, like DynamoDocumentRepository."""

    def __init__(self):
        self.rows = {}
    def put(self, document):
        self.rows[(document["tenant_id"], document["job_id"])] = dict(document)
        return document
    def get(self, tenant_id, job_id):
        found = self.rows.get((tenant_id, job_id))
        return dict(found) if found else None


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.products, self.offers, self.pages = FakeDocs(), FakeDocs(), FakeDocs()
        self.usage = FakeUsage()
        self.jobs = FakeJobs()
        self.config = FakeKeyed({"provider": "bedrock", "model": "sonnet-4.6", "verified_at": 1})
        self.profiles = subscriber()
        self.events = FakeEvents()
        self.seen = []

    def call(self, brief=None, *, generator=None, usage=None, config=None, profiles=None, events=None):
        if events is not None:
            self.events = events
        def recording(**kwargs):
            self.seen.append(kwargs)
            return (generator or ok_generator)(**kwargs)
        event = {"httpMethod": "POST", "resource": "/ai/generate",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"brief": BRIEF if brief is None else brief})}
        kwargs = dict(products_repo=self.products, offers_repo=self.offers, pages_repo=self.pages,
                      config_repo=config or self.config, usage_repo=usage or self.usage,
                      tenant_repo=profiles or self.profiles, jobs_repo=self.jobs,
                      generator=recording, events_repo=self.events, now_fn=lambda: 1790500000,
                      randomiser=lambda alphabet: alphabet[0])
        return run_to_completion(event, self.jobs, kwargs)

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
        # The count is spent before the model runs, so our outage is what refunds it -- never the tenant's
        # taste. The ordering is the contract; `release` is the only way back.
        order = []
        def slow(**kwargs):
            order.append("generate")
            return ok_generator(**kwargs)
        class Watching(FakeUsage):
            def consume_if_available(self, *a, **k):
                order.append("consume")
                return super().consume_if_available(*a, **k)
        self.call(generator=slow, usage=Watching())
        self.assertEqual(order, ["consume", "generate"])

    def test_the_allowance_is_decided_by_the_write_not_a_read(self):
        # The race this replaced: the handler read `used`, decided on it, then incremented. A repository
        # that refuses must be believed even when a prior read said there was room -- otherwise the
        # decision is still being made in Python and the window is still open.
        class AlwaysFull(FakeUsage):
            def used(self, tenant_id, period):
                return 0          # a read that says "plenty left"
            def consume_if_available(self, tenant_id, period, *, allowance, at, **kw):
                return {"allowed": False, "used": 99}   # ...and a write that disagrees
        ran = []
        def watched(**kwargs):
            ran.append(1)
            return ok_generator(**kwargs)
        response = self.call(generator=watched, usage=AlwaysFull())
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(json.loads(response["body"])["error"], "quota_exhausted")
        self.assertEqual(ran, [], "no generation may run on a refused slot")

    def test_a_refused_slot_is_never_released(self):
        # Nothing was taken, so there is nothing to give back. Releasing here would CREDIT a tenant who
        # never spent, and on a lifetime trial counter that is a free generation every time they retry.
        class AlwaysFull(FakeUsage):
            def consume_if_available(self, *a, **k):
                return {"allowed": False, "used": 99}
        usage = AlwaysFull()
        self.call(usage=usage)
        self.assertEqual(usage.released, 0)

    def test_a_provider_failure_gives_the_slot_back(self):
        def failing(**kwargs):
            raise AiError("boom", kind="throttled")
        response = self.call(generator=failing)
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

    def test_a_missing_tenant_profile_gets_NOTHING(self):
        # Reversed 2026-09-29. It used to fall to a small free allowance, on the theory that zero "is a lie
        # to a tenant whose profile read merely blipped". That theory does not survive the free tier losing
        # AI: an unreadable profile now looks exactly like a free tenant, and guessing generously on the
        # platform's Bedrock bill is an open tap on the one path that must fail closed.
        response = self.call(profiles=FakeProfiles())      # no profile at all
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(json.loads(response["body"])["error"], "quota_exhausted")
        self.assertEqual(self.usage.consumed, 0)

    def test_a_live_trial_may_generate_without_a_subscription(self):
        # The acquisition path: every signup starts here, and the trial is what carries the taste now that
        # the free tier carries none.
        trial = FakeProfiles(billing_status="trial", trial_ends_at=1790600000)
        response = self.call(profiles=trial)
        self.assertEqual(response["statusCode"], 201)

    def test_a_trial_spends_from_the_LIFETIME_counter(self):
        trial = FakeProfiles(billing_status="trial", trial_ends_at=1790600000)
        self.call(profiles=trial)
        period = [row["period"] for row in self.jobs.rows.values()][-1]
        self.assertEqual(period, "trial",
                         "a calendar period would hand a trial its allowance again next month")

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


class JobTests(unittest.TestCase):
    """Queueing, polling, and the failure modes that only exist once the work is asynchronous.

    This became a job because it had to: a four-fact brief measured 35.3s against API Gateway's hard
    29s ceiling. The Lambda succeeded and wrote every document while the browser showed "Failed to
    fetch" -- work done, quota spent, invisible.
    """

    def setUp(self):
        self.jobs = FakeJobs()
        self.usage = FakeUsage()
        self.products, self.offers, self.pages = FakeDocs(), FakeDocs(), FakeDocs()
        self.queued = []

    def kwargs(self, **over):
        base = dict(products_repo=self.products, offers_repo=self.offers, pages_repo=self.pages,
                    config_repo=FakeKeyed({"provider": "bedrock", "model": "sonnet-4.6"}),
                    usage_repo=self.usage, tenant_repo=subscriber(),
                    jobs_repo=self.jobs, generator=ok_generator, now_fn=lambda: 1790500000,
                    randomiser=lambda a: a[0])
        base.update(over)
        return base

    def post(self, **over):
        return handler({"httpMethod": "POST", "resource": "/ai/generate",
                        "queryStringParameters": {"tenant_id": "t1"},
                        "body": json.dumps({"brief": BRIEF})}, None,
                       invoker=self.queued.append, **self.kwargs(**over))

    def run_queued(self, **over):
        job = self.queued[-1]
        return handler({"internal_job": True, "tenant_id": job["tenant_id"], "job_id": job["job_id"]},
                       None, **self.kwargs(**over))

    def test_the_request_answers_immediately_with_a_job(self):
        response = self.post()
        self.assertEqual(response["statusCode"], 202)      # not 201 -- nothing exists yet
        body = json.loads(response["body"])
        self.assertEqual(body["job"]["status"], "queued")
        self.assertTrue(body["job"]["job_id"])
        self.assertEqual(self.pages.saved, [])             # no work done on the request path

    def test_the_brief_is_not_echoed_back_to_the_poller(self):
        # The client sent it; returning it on every poll is bytes for nothing.
        self.assertNotIn("brief", json.loads(self.post()["body"])["job"])

    def test_the_quota_is_spent_at_QUEUE_time(self):
        # Otherwise two requests both pass the allowance check while neither has generated yet.
        self.post()
        self.assertEqual(self.usage.consumed, 1)

    def test_running_the_job_produces_the_documents(self):
        self.post()
        self.run_queued()
        job = self.jobs.get("t1", self.queued[-1]["job_id"])
        self.assertEqual(job["status"], "complete")
        self.assertEqual(len(self.pages.saved), 1)
        self.assertEqual(job["result"]["page"]["status"], "draft")

    def test_polling_reports_each_state(self):
        self.post()
        job_id = self.queued[-1]["job_id"]
        def poll():
            response = handler({"httpMethod": "GET", "resource": "/ai/jobs/{job_id}",
                                "pathParameters": {"job_id": job_id},
                                "queryStringParameters": {"tenant_id": "t1"}}, None,
                               **self.kwargs())
            return json.loads(response["body"])["job"]["status"]
        self.assertEqual(poll(), "queued")
        self.run_queued()
        self.assertEqual(poll(), "complete")

    def test_a_failed_generation_reaches_the_job_and_refunds(self):
        # A job stuck at `running` is indistinguishable from one still going, and the poller would
        # spin forever.
        def failing(**kwargs):
            raise AiError("boom", kind="throttled")
        self.post()
        self.run_queued(generator=failing)
        job = self.jobs.get("t1", self.queued[-1]["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("busy", job["error"]["message"])
        self.assertEqual(self.usage.released, 1)

    def test_an_unexpected_failure_still_reaches_the_job(self):
        def exploding(**kwargs):
            raise RuntimeError("something nobody predicted")
        self.post()
        self.run_queued(generator=exploding)
        self.assertEqual(self.jobs.get("t1", self.queued[-1]["job_id"])["status"], "failed")
        self.assertEqual(self.usage.released, 1)

    def test_a_redelivered_job_does_not_run_twice(self):
        # Lambda's async invoke is at-least-once, and running twice would create a second product.
        self.post()
        self.run_queued()
        self.run_queued()
        self.assertEqual(len(self.pages.saved), 1)
        self.assertEqual(len(self.products.saved), 1)

    def test_a_failure_to_queue_refunds_and_says_so(self):
        def broken(job):
            raise RuntimeError("lambda is unreachable")
        response = self.post(**{})  # placeholder to build kwargs
        self.usage.consumed = 0
        response = handler({"httpMethod": "POST", "resource": "/ai/generate",
                            "queryStringParameters": {"tenant_id": "t1"},
                            "body": json.dumps({"brief": BRIEF})}, None,
                           invoker=broken, **self.kwargs())
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["error"], "enqueue_failed")
        self.assertEqual(self.usage.released, 1)

    def test_another_tenants_job_is_not_readable(self):
        self.post()
        response = handler({"httpMethod": "GET", "resource": "/ai/jobs/{job_id}",
                            "pathParameters": {"job_id": self.queued[-1]["job_id"]},
                            "queryStringParameters": {"tenant_id": "someone_else"}}, None,
                           **self.kwargs())
        self.assertEqual(response["statusCode"], 404)


class ReaperTests(unittest.TestCase):
    """Lambda retries an async invoke twice and then drops it silently.

    A dropped job is indistinguishable from a slow one: it sits at `queued`, the dashboard polls
    until it gives up, and the tenant's generation is never refunded. Nothing else can tell, so
    something has to look.
    """

    def setUp(self):
        self.usage = FakeUsage()
        self.rows = {}
        outer = self
        class Jobs(FakeJobs):
            def unfinished(self, limit=200):
                return [dict(j) for j in outer.rows.values()
                        if j.get("status") in ("queued", "running")]
        self.jobs = Jobs()
        self.jobs.rows = self.rows

    def job(self, job_id, *, status="queued", age):
        row = {"tenant_id": "t1", "job_id": job_id, "status": status, "period": "2026-09",
               "created_at": 1790500000 - age, "updated_at": 1790500000 - age}
        self.rows[("t1", job_id)] = row
        return row

    def reap(self):
        return handler({"internal_reap": True}, None, jobs_repo=self.jobs, usage_repo=self.usage,
                       now_fn=lambda: 1790500000)

    def test_an_abandoned_job_is_failed_and_the_generation_refunded(self):
        self.job("job_dead", age=3600)
        result = self.reap()
        self.assertEqual(result["reaped"], 1)
        self.assertEqual(self.jobs.get("t1", "job_dead")["status"], "failed")
        self.assertEqual(self.usage.released, 1)

    def test_the_tenant_is_told_it_did_not_cost_them(self):
        self.job("job_dead", age=3600)
        self.reap()
        message = self.jobs.get("t1", "job_dead")["error"]["message"]
        self.assertIn("did not use one of your generations", message)

    def test_a_job_still_waiting_behind_the_concurrency_cap_is_left_alone(self):
        # Excess async invocations queue rather than fail, so a job that has not started yet is
        # healthy. Reaping it would refund work that is about to happen.
        self.job("job_waiting", age=60)
        self.assertEqual(self.reap()["reaped"], 0)
        self.assertEqual(self.jobs.get("t1", "job_waiting")["status"], "queued")

    def test_a_running_job_is_reaped_too_once_it_is_clearly_dead(self):
        # A worker killed mid-generation leaves `running` behind, which is just as stuck.
        self.job("job_hung", status="running", age=3600)
        self.assertEqual(self.reap()["reaped"], 1)

    def test_finished_jobs_are_never_touched(self):
        self.rows[("t1", "job_done")] = {"tenant_id": "t1", "job_id": "job_done", "status": "complete",
                                         "created_at": 1, "updated_at": 1}
        self.assertEqual(self.reap()["reaped"], 0)
        self.assertEqual(self.usage.released, 0)

    def test_one_unwritable_row_does_not_strand_the_rest(self):
        self.job("job_a", age=3600)
        self.job("job_b", age=3600)
        original = self.jobs.put
        def flaky(document):
            if document["job_id"] == "job_a":
                raise RuntimeError("conditional check failed")
            return original(document)
        self.jobs.put = flaky
        self.assertEqual(self.reap()["reaped"], 1)

    def test_an_unreadable_table_reports_rather_than_crashing(self):
        # A reaper that dies silently is worse than no reaper: nothing would ever be refunded again.
        class Broken(FakeJobs):
            def unfinished(self, limit=200):
                raise RuntimeError("dynamo is having a day")
        result = handler({"internal_reap": True}, None, jobs_repo=Broken(), usage_repo=self.usage,
                         now_fn=lambda: 1790500000)
        self.assertFalse(result["ok"])
        self.assertIn("unreadable", result["reason"])


class GenerationLedgerTests(GenerateTests):
    """The permanent record: what was authorized, and what it cost.

    Separate from the quota counter on purpose. `ai_usage` expires with its period and `ai_jobs` after seven
    days, and the brief snapshot -- the evidence of what the model was LICENSED to assert -- was going onto
    the job, so it would have been gone in a week (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.9).
    """

    def test_the_ledger_records_the_generation_when_the_slot_is_spent(self):
        self.call()
        self.assertEqual(len(self.events.rows), 1)
        row = self.events.rows[0]
        self.assertEqual(row["status"], "started")
        self.assertEqual(row["tenant_id"], "t1")
        self.assertTrue(row["generation_id"].startswith("gen_"))
        self.assertEqual(row["source"], "plan")

    def test_the_ledger_carries_its_own_copy_of_the_brief(self):
        # The point of the table. The job holds a brief too, and the job is gone in seven days.
        row = (self.call(), self.events.rows[0])[1]
        self.assertEqual(row["brief_snapshot"], BRIEF)

    def test_the_ledger_row_never_expires(self):
        self.call()
        self.assertNotIn("expires_at", self.events.rows[0])

    def test_one_id_correlates_the_job_and_the_ledger(self):
        # "Why was this tenant charged a generation?" has to be answerable by following one identifier.
        self.call()
        row = self.events.rows[0]
        job = ([row for row in self.jobs.rows.values()] or [None])[-1]
        self.assertTrue(row["job_id"], "the ledger references the job it came from")
        if job:
            self.assertEqual(job.get("generation_id"), row["generation_id"])

    def test_a_successful_generation_records_tokens_and_cost(self):
        self.call()
        self.assertTrue(self.events.patches, "the outcome must reach the ledger")
        _, _, patch = self.events.patches[-1]
        self.assertEqual(patch["status"], "succeeded")
        self.assertEqual(patch["input_tokens"], 2000)
        self.assertEqual(patch["output_tokens"], 700)
        self.assertGreater(patch["estimated_cost_micros"], 0)
        self.assertTrue(patch["rate_confidence"], "a hand-maintained rate must travel with its confidence")

    def test_cost_is_an_integer_so_it_can_be_summed_without_drift(self):
        self.call()
        _, _, patch = self.events.patches[-1]
        self.assertIsInstance(patch["estimated_cost_micros"], int)

    def test_a_released_slot_is_not_recorded_as_a_charge(self):
        # A provider failure refunds the slot, so the ledger must not read as a generation the tenant paid
        # for -- otherwise the counter and the ledger disagree and neither can be trusted.
        def failing(**kwargs):
            raise AiError("boom", kind="throttled")
        self.call(generator=failing)
        _, _, patch = self.events.patches[-1]
        self.assertEqual(patch["status"], "released")
        self.assertEqual(self.usage.released, 1)

    def test_an_unwritable_ledger_never_fails_a_generation(self):
        # Evidence, not a gate. The tenant has already spent a slot by this point; failing here would take
        # their generation AND give them nothing.
        response = self.call(events=FakeEvents(fail=True))
        self.assertIn(response["statusCode"], (200, 201))


class AiBuilderCapabilityTests(GenerateTests):
    """Gate 1: may this tenant use AI Builder at all — a different question from how many generations."""

    def test_a_free_tenant_is_refused_before_the_quota_is_touched(self):
        # The refusal has to be "not on your plan", not "you have used 0 of 0". They are different problems
        # with different answers, and only one of them is fixed by waiting for the 1st.
        response = self.call(profiles=FakeProfiles(billing_status="active", entitlements=[]))
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(json.loads(response["body"])["error"], "ai_builder_not_entitled")
        self.assertEqual(self.usage.consumed, 0, "gate 1 must not spend a slot")

    def test_a_subscriber_whose_PLAN_lacks_it_is_refused(self):
        # The live premium plan granted 10 capabilities when ai_builder was added as an 11th. A paying tenant
        # whose plan row was never updated does NOT get the feature — which is why the plan rows have to be
        # edited in the same change as the code.
        paying = FakeProfiles(billing_status="active", stripe_subscription_id="sub_1",
                              billing_plan_key="premium", ai_generations=20, entitlements=["landing_pages"])
        self.assertEqual(self.call(profiles=paying)["statusCode"], 403)

    def test_a_live_trial_passes_gate_one(self):
        trial = FakeProfiles(billing_status="trial", trial_ends_at=1790600000)
        self.assertEqual(self.call(profiles=trial)["statusCode"], 201)

    def test_a_free_tenant_with_a_VERIFIED_own_key_may_build(self):
        # Their key, their bill. Refusing here would withhold a feature the platform does not pay for, and
        # it is the whole acquisition story now that the free tier carries no platform-paid generations.
        byok = FakeKeyed({"provider": "anthropic", "model": "claude", "verified_at": 1790000000})
        response = self.call(profiles=FakeProfiles(billing_status="active", entitlements=[]), config=byok)
        self.assertEqual(response["statusCode"], 201)

    def test_an_UNVERIFIED_own_key_does_not_open_the_gate(self):
        # A key that exists in the database and cannot actually call a model is worse than none: it admits a
        # tenant to a feature that then fails. `verified_at` is set by a real generation, not a lookup.
        unverified = FakeKeyed({"provider": "anthropic", "model": "claude"})
        response = self.call(profiles=FakeProfiles(billing_status="active", entitlements=[]), config=unverified)
        self.assertEqual(response["statusCode"], 403)

    def test_a_bedrock_key_is_not_a_byok_carve_out(self):
        # Bedrock is PLATFORM-paid. A verified bedrock config must not let a free tenant spend our money.
        platform = FakeKeyed({"provider": "bedrock", "model": "sonnet-4.6", "verified_at": 1790000000})
        response = self.call(profiles=FakeProfiles(billing_status="active", entitlements=[]), config=platform)
        self.assertEqual(response["statusCode"], 403)


class PlatformBudgetTests(GenerateTests):
    """Gate 3: will we spend another platform dollar this month?

    The only gate that is identity-independent, which is why it carries real weight while gate 1 is advisory
    (tenant_id still comes from the request). Per-tenant caps cannot see the abuse that matters here — serial
    trial signups, each one perfectly within its own allowance.
    """

    def test_platform_spend_accumulates_on_a_reserved_row(self):
        from stripe_link.domain.ai_quota import PLATFORM_TENANT

        self.call()
        spent = self.usage.cost(PLATFORM_TENANT, "2026-09")
        self.assertGreater(spent, 0, "a completed generation must reach the platform counter")

    def test_a_byok_generation_never_touches_the_platform_counter(self):
        # Their key, their bill. Counting it would pause everyone else over money we never spent.
        from stripe_link.domain.ai_quota import PLATFORM_TENANT

        byok = FakeKeyed({"provider": "anthropic", "model": "claude", "verified_at": 1790000000})
        self.call(config=byok)
        self.assertEqual(self.usage.cost(PLATFORM_TENANT, "2026-09"), 0)

    def test_an_exhausted_budget_refuses_before_spending_a_slot(self):
        from unittest.mock import patch

        from stripe_link.domain.ai_quota import PLATFORM_TENANT

        self.usage.costs[(PLATFORM_TENANT, "2026-09")] = 50_000_000     # $50 spent
        with patch("handlers.ai_generate._platform_budget", return_value=10):   # $10 ceiling
            response = self.call()
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(json.loads(response["body"])["error"], "platform_budget_exhausted")
        self.assertEqual(self.usage.consumed, 0, "the tenant must not be charged for our ceiling")

    def test_an_exhausted_budget_still_lets_BYOK_through(self):
        from unittest.mock import patch

        from stripe_link.domain.ai_quota import PLATFORM_TENANT

        self.usage.costs[(PLATFORM_TENANT, "2026-09")] = 50_000_000
        byok = FakeKeyed({"provider": "anthropic", "model": "claude", "verified_at": 1790000000})
        with patch("handlers.ai_generate._platform_budget", return_value=10):
            response = self.call(config=byok)
        self.assertEqual(response["statusCode"], 201, "our ceiling must not ration their own key")

    def test_no_budget_configured_means_no_ceiling(self):
        # 0 means unset, NOT "spend nothing". A settings row nobody filled in must not stop the platform.
        from unittest.mock import patch

        from stripe_link.domain.ai_quota import PLATFORM_TENANT

        self.usage.costs[(PLATFORM_TENANT, "2026-09")] = 999_000_000
        with patch("handlers.ai_generate._platform_budget", return_value=0):
            self.assertEqual(self.call()["statusCode"], 201)
