"""POST /ai/generate with `operation: image` -- the gate, the clamp, and giving the credit back.

The money path. Every test here is a way a tenant could be charged for nothing, or we could be charged
for something nobody was entitled to.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from handlers import ai_generate  # noqa: E402
from stripe_link import ai_image_client  # noqa: E402
from tests.test_ai_generate import FakeEvents, FakeJobs, FakeProfiles, FakeUsage  # noqa: E402

NOW = 1_800_000_000
TENANT = "t1"
ALLOWANCES = {"trial_allowance": 7, "free_allowance": 0, "trial_quality": "low"}


def trial(**extra):
    return FakeProfiles(billing_status="trial", trial_ends_at=NOW + 86400, **extra)


def subscriber(images=30, quality="low", **extra):
    return FakeProfiles(billing_status="active", stripe_subscription_id="sub_1",
                        billing_plan_key="premium", ai_generations=20, ai_images=images,
                        ai_image_quality=quality, entitlements=["ai_builder"], **extra)


def _event(body):
    return {"httpMethod": "POST", "resource": "/ai/generate", "headers": {},
            "body": json.dumps({"operation": "image", "tenant_id": TENANT, **body})}


class Harness(unittest.TestCase):
    def setUp(self):
        self.usage, self.jobs, self.events = FakeUsage(), FakeJobs(), FakeEvents()
        self.started = []

    def run_it(self, body, *, profile=None, start=None, configured=True):
        def fake_start(**kwargs):
            self.started.append(kwargs)
            if start is not None:
                return start(**kwargs)
            return {"job_id": "img_remote", "status": "queued"}

        with patch.object(ai_generate, "_configured_image_allowances", lambda: dict(ALLOWANCES)), \
             patch.object(ai_generate, "_platform_budget", lambda: 0), \
             patch.object(ai_image_client, "configured", lambda: configured), \
             patch.object(ai_image_client, "start", fake_start):
            response = ai_generate.handler(
                _event(body), None, jobs_repo=self.jobs, usage_repo=self.usage,
                tenant_repo=profile or subscriber(), events_repo=self.events,
                now_fn=lambda: NOW, randomiser=lambda seq: seq[0])
        return response, json.loads(response["body"])


class TheGateTests(Harness):
    def test_a_subscriber_may_generate(self):
        response, payload = self.run_it({"prompt": "a dog by the door", "count": 2})
        self.assertEqual(response["statusCode"], 202)
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["job"]["remote_job_id"], "img_remote")

    def test_a_live_trial_may_generate(self):
        response, _ = self.run_it({"prompt": "a dog by the door"}, profile=trial())
        self.assertEqual(response["statusCode"], 202)

    def test_the_free_tier_is_refused(self):
        # Images are for a paying tenant or one inside their 14 days. Nobody else.
        response, payload = self.run_it({"prompt": "a dog"}, profile=FakeProfiles(billing_status="canceled"))
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(payload["error"], "image_quota_exhausted")
        self.assertEqual(self.started, [])

    def test_an_expired_trial_is_refused(self):
        expired = FakeProfiles(billing_status="trial", trial_ends_at=NOW - 1)
        response, _ = self.run_it({"prompt": "a dog"}, profile=expired)
        self.assertEqual(response["statusCode"], 429)

    def test_running_out_refuses_without_calling_the_service(self):
        self.usage = FakeUsage(used=7)
        response, payload = self.run_it({"prompt": "a dog"}, profile=trial())
        self.assertEqual(response["statusCode"], 429)
        self.assertEqual(self.started, [])

    def test_an_unusable_counter_fails_closed(self):
        self.usage = FakeUsage(fail_read=True)
        response, payload = self.run_it({"prompt": "a dog"})
        self.assertEqual(payload["error"], "quota_unavailable")
        self.assertEqual(self.started, [])

    def test_an_empty_prompt_costs_nothing(self):
        response, _ = self.run_it({"prompt": "  "})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(self.usage.consumed, 0)

    def test_a_misconfigured_service_refuses_BEFORE_spending_a_credit(self):
        # Charging a tenant and then discovering we cannot generate bills them for our mistake.
        response, payload = self.run_it({"prompt": "a dog"}, configured=False)
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(payload["error"], "image_service_unconfigured")
        self.assertEqual(self.usage.consumed, 0)
        self.assertEqual(self.events.rows, [])


class TheCounterIsItsOwnTests(Harness):
    def test_an_image_does_not_spend_a_page_generation(self):
        self.run_it({"prompt": "a dog"})
        self.assertTrue(all(p.startswith("images#") for p in self.usage.periods),
                        f"image spend landed on a page counter: {self.usage.periods}")

    def test_a_trial_spends_the_lifetime_counter(self):
        # A monthly key would hand a trial starting on the 25th a fresh seven in six days.
        self.run_it({"prompt": "a dog"}, profile=trial())
        self.assertEqual(self.usage.periods, ["images#trial"])

    def test_the_credit_cost_follows_the_image_count(self):
        self.run_it({"prompt": "a dog", "count": 3})
        self.assertEqual(self.usage.consumed, 3)

    def test_a_count_above_the_maximum_is_bounded_not_refused(self):
        self.run_it({"prompt": "a dog", "count": 99})
        self.assertEqual(self.started[0]["count"], 4)


class QualityIsClampedServerSideTests(Harness):
    def test_a_trial_asking_for_high_is_given_low(self):
        # The parameter travels in the request body, so omitting the control is not a limit.
        self.run_it({"prompt": "a dog", "quality": "high"}, profile=trial())
        self.assertEqual(self.started[0]["quality"], "low")

    def test_a_subscriber_is_clamped_to_their_plans_ceiling(self):
        self.run_it({"prompt": "a dog", "quality": "high"}, profile=subscriber(quality="low"))
        self.assertEqual(self.started[0]["quality"], "low")

    def test_a_lifted_ceiling_is_honoured_without_a_code_change(self):
        # The whole point of the ceiling being data: this is the $29 tier, and nothing here changes.
        self.run_it({"prompt": "a dog", "quality": "high"}, profile=subscriber(quality="high"))
        self.assertEqual(self.started[0]["quality"], "high")

    def test_clamping_does_not_refuse_the_request(self):
        response, _ = self.run_it({"prompt": "a dog", "quality": "high"}, profile=trial())
        self.assertEqual(response["statusCode"], 202)


class TheStyleIsAppendedTests(Harness):
    def test_the_style_fragment_rides_on_the_prompt(self):
        self.run_it({"prompt": "a golden retriever", "style": "lifestyle"})
        sent = self.started[0]["prompt"]
        self.assertTrue(sent.startswith("a golden retriever"))
        self.assertIn("natural window light", sent)

    def test_the_hero_shape_is_landscape_by_default(self):
        self.run_it({"prompt": "a dog"})
        self.assertEqual(self.started[0]["size"], "1536x1024")


class WhenWeFailTheCreditGoesBackTests(Harness):
    def _boom(self, **kwargs):
        raise ai_image_client.ImageServiceError("the provider is down", status_code=502,
                                                code="provider_unavailable", blame="transient")

    def test_a_service_failure_releases_the_credit(self):
        # A tenant is not billed for our outage -- and here the outage can be somebody else's.
        response, payload = self.run_it({"prompt": "a dog"}, start=self._boom)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(self.usage.released, 1)

    def test_the_failure_is_written_to_the_permanent_ledger(self):
        self.run_it({"prompt": "a dog"}, start=self._boom)
        self.assertEqual(len(self.events.rows), 1)
        self.assertEqual(self.events.patches[0][2]["status"], "failed")

    def test_the_services_own_reason_reaches_the_caller(self):
        _, payload = self.run_it({"prompt": "a dog"}, start=self._boom)
        self.assertEqual(payload["error"], "provider_unavailable")
        self.assertIn("provider is down", payload["message"])


class TheLedgerTests(Harness):
    def test_the_slot_is_recorded_the_moment_it_is_spent(self):
        self.run_it({"prompt": "a dog"})
        row = self.events.rows[0]
        self.assertEqual(row["operation"], "image_generation")
        self.assertEqual(row["status"], "started")
        self.assertTrue(str(row["period"]).startswith("images#"))

    def test_the_job_carries_the_correlation_id(self):
        _, payload = self.run_it({"prompt": "a dog"})
        self.assertEqual(payload["job"]["generation_id"], self.events.rows[0]["generation_id"])


class SettlingOnPollTests(unittest.TestCase):
    """The remote job is the truth; the local row follows it."""

    def setUp(self):
        self.usage, self.jobs, self.events = FakeUsage(), FakeJobs(), FakeEvents()
        self.job = {"document_type": "ai_image_job", "tenant_id": TENANT, "job_id": "img_1",
                    "remote_job_id": "img_remote", "status": "queued", "period": "images#trial",
                    "quality": "low", "event_key": "k1", "generation_id": "gen_1"}
        self.jobs.put(self.job)

    def _get(self):
        # The tenant comes from the VERIFIED claims on a GET, not from a body -- the route is behind
        # the authorizer and there is no body to read.
        return {"httpMethod": "GET", "resource": "/ai/jobs/{job_id}",
                "pathParameters": {"job_id": "img_1"},
                "requestContext": {"authorizer": {"claims": {"sub": TENANT}}}}

    def poll(self, remote):
        with patch.object(ai_image_client, "read", lambda **kw: remote):
            response = ai_generate.handler(self._get(), None, jobs_repo=self.jobs,
                                           usage_repo=self.usage, events_repo=self.events,
                                           now_fn=lambda: NOW)
        return json.loads(response["body"])["job"]

    def test_a_finished_job_returns_its_images_and_settles_the_ledger(self):
        payload = self.poll({"status": "done", "images": [{"id": "a"}, {"id": "b"}],
                             "usage": {"cost_micros": 33000}})
        self.assertEqual(payload["status"], "done")
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(self.events.patches[0][2]["status"], "succeeded")
        self.assertEqual(self.events.patches[0][2]["images"], 2)
        self.assertEqual(self.usage.released, 0)

    def test_a_failed_remote_job_gives_the_credit_back(self):
        payload = self.poll({"status": "failed",
                             "error": {"message": "the safety system refused it", "blame": "tenant"}})
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(self.usage.released, 1)
        self.assertEqual(self.events.patches[0][2]["status"], "failed")

    def test_a_running_job_is_left_alone(self):
        payload = self.poll({"status": "running"})
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(self.usage.released, 0)
        self.assertEqual(self.events.patches, [])

    def test_an_unreachable_service_does_not_fail_the_generation(self):
        # A poll that cannot reach the service is not a failed generation. The row stays pollable.
        def boom(**kw):
            raise ai_image_client.ImageServiceError("timeout")

        with patch.object(ai_image_client, "read", boom):
            response = ai_generate.handler(self._get(), None, jobs_repo=self.jobs,
                                           usage_repo=self.usage, events_repo=self.events,
                                           now_fn=lambda: NOW)
        self.assertEqual(json.loads(response["body"])["job"]["status"], "queued")
        self.assertEqual(self.usage.released, 0)

    def test_settling_twice_does_not_refund_twice(self):
        self.poll({"status": "failed", "error": {"message": "nope"}})
        self.poll({"status": "failed", "error": {"message": "nope"}})
        self.assertEqual(self.usage.released, 1)


if __name__ == "__main__":
    unittest.main()


class TheLibraryTests(unittest.TestCase):
    """The picker's contents. Keyed by TENANT, proxied from the service that owns the record."""

    def _get(self, sub=TENANT):
        return {"httpMethod": "GET", "resource": "/ai/jobs", "pathParameters": {},
                "requestContext": {"authorizer": {"claims": {"sub": sub}}}}

    def call(self, reader):
        with patch.object(ai_image_client, "call", reader):
            response = ai_generate.handler(self._get(), None, jobs_repo=FakeJobs(),
                                           usage_repo=FakeUsage(), events_repo=FakeEvents(),
                                           now_fn=lambda: NOW)
        return response, json.loads(response["body"])

    def test_it_asks_for_this_tenants_folder(self):
        seen = {}

        def reader(path, **kw):
            seen["path"] = path
            return {"jobs": []}

        self.call(reader)
        self.assertIn(f"owner_id={TENANT}", seen["path"])

    def test_newest_first(self):
        _, payload = self.call(lambda path, **kw: {"jobs": [
            {"job_id": "old", "created_at": 100}, {"job_id": "new", "created_at": 900}]})
        self.assertEqual([j["job_id"] for j in payload["jobs"]], ["new", "old"])

    def test_an_unreachable_library_is_an_empty_picker_not_a_broken_builder(self):
        # The tenant can still upload an image by hand. Failing the whole field would take away a
        # working feature to report the absence of a new one.
        def boom(path, **kw):
            raise ai_image_client.ImageServiceError("down")

        response, payload = self.call(boom)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(payload["jobs"], [])
        self.assertTrue(payload["unavailable"])
