"""Every AI repository factory must be constructible.

These exist because the job repository shipped broken: the handler injects fakes in every test, so
the FACTORY itself was never called and a missing required kwarg reached production as a 502. The
fix is a test that touches the thing the fakes stand in for.
"""

import os
import unittest

from stripe_link.repositories.documents import (RepositoryError, ai_jobs_repository,
                                                ai_provider_config_repository, ai_usage_repository)

FACTORIES = {
    "AI_PROVIDER_CONFIG_TABLE": ai_provider_config_repository,
    "AI_USAGE_TABLE": ai_usage_repository,
    "AI_JOBS_TABLE": ai_jobs_repository,
}


class FactoryTests(unittest.TestCase):
    def test_each_factory_builds_with_its_table_configured(self):
        for variable, factory in FACTORIES.items():
            with self.subTest(variable=variable):
                os.environ[variable] = "jb-probe-dev"
                try:
                    repository = factory()
                    self.assertEqual(repository.table_name, "jb-probe-dev")
                finally:
                    os.environ.pop(variable, None)

    def test_each_factory_refuses_an_unconfigured_table(self):
        # Rather than building something that fails later, at the first read, in production.
        for variable, factory in FACTORIES.items():
            with self.subTest(variable=variable):
                os.environ.pop(variable, None)
                with self.assertRaises(RepositoryError):
                    factory()

    def test_the_jobs_repository_round_trips_on_its_real_key(self):
        os.environ["AI_JOBS_TABLE"] = "jb-probe-dev"
        try:
            rows = {}
            class FakeTable:
                def put_item(self, Item):  # noqa: N803 - boto3's own casing
                    rows[(Item["tenant_id"], Item["job_id"])] = Item
                def get_item(self, Key):  # noqa: N803
                    found = rows.get((Key["tenant_id"], Key["job_id"]))
                    return {"Item": found} if found else {}
            repository = ai_jobs_repository(table=FakeTable())
            repository.put({"tenant_id": "t1", "job_id": "job_1", "status": "queued"})
            self.assertEqual(repository.get("t1", "job_1")["status"], "queued")
            self.assertIsNone(repository.get("t1", "missing"))
        finally:
            os.environ.pop("AI_JOBS_TABLE", None)

    def test_a_job_without_its_keys_is_refused(self):
        os.environ["AI_JOBS_TABLE"] = "jb-probe-dev"
        try:
            repository = ai_jobs_repository(table=object())
            for bad in ({"job_id": "j"}, {"tenant_id": "t"}, {}):
                with self.subTest(bad=bad):
                    with self.assertRaises(RepositoryError):
                        repository.put(bad)
        finally:
            os.environ.pop("AI_JOBS_TABLE", None)


class ConcurrencyGuardTests(unittest.TestCase):
    """The generate worker must never be able to starve the functions that take money.

    The account has 1000 concurrent executions shared by 74 functions with nothing reserved, so an
    unbounded AI spike would throttle checkout, the Stripe webhook and page serving. This is a
    template test because the protection lives in the template.
    """

    TEMPLATE = None

    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.TEMPLATE = (pathlib.Path(__file__).resolve().parents[1]
                        / "template.yaml").read_text(encoding="utf-8")

    def _block(self):
        return self.TEMPLATE.split("AiGenerateFunction:", 1)[1].split("\n  Ai", 1)[0]

    def test_the_generate_worker_reserves_a_bounded_slice(self):
        block = self._block()
        self.assertIn("ReservedConcurrentExecutions:", block)
        reserved = int(block.split("ReservedConcurrentExecutions:", 1)[1].split("\n", 1)[0].strip())
        # Sized against Bedrock (~10s a generation, ~500/min entry-tier ceiling), not picked for
        # safety -- and small enough that the money paths keep almost the whole pool.
        self.assertGreaterEqual(reserved, 5)
        self.assertLessEqual(reserved, 100)

    def test_a_dropped_invocation_is_not_silent(self):
        # Lambda retries twice then discards. Without a destination nobody ever learns it happened.
        self.assertIn("OnFailure:", self._block())

    def test_abandoned_jobs_are_swept_on_a_schedule(self):
        self.assertIn("internal_reap", self._block())
        self.assertIn("Type: Schedule", self._block())


class AtomicConsumptionTests(unittest.TestCase):
    """`consume_if_available` — the check and the increment as ONE write.

    `consume()` returning the new total was not enough, and the handler that used it proved why: it read
    `used`, decided on that read, then incremented, so two requests at `used=2` of an allowance of 3 both
    passed and both incremented. The fake in test_ai_generate cannot catch that class of bug, because a fake
    has no concurrency and no ConditionExpression — which is exactly why these tests drive the REAL
    repository against a table that enforces the condition.
    """

    def _repo(self, stored=None):
        from stripe_link.repositories.documents import AiUsageRepository

        class ConditionalCheckFailedException(Exception):
            pass

        class FakeTable:
            """A DynamoDB stand-in that actually honours the ConditionExpression we send it."""

            def __init__(self, rows):
                self.rows = rows
                self.writes = 0

            def get_item(self, Key):  # noqa: N803 - boto3's casing
                row = self.rows.get((Key["tenant_id"], Key["period"]))
                return {"Item": dict(row)} if row else {}

            def update_item(self, **kwargs):
                key = (kwargs["Key"]["tenant_id"], kwargs["Key"]["period"])
                values = kwargs["ExpressionAttributeValues"]
                row = self.rows.get(key)
                condition = kwargs.get("ConditionExpression", "")
                if condition:
                    exists = row is not None
                    ceiling = values[":ceiling"]
                    if not (not exists or row["used"] <= ceiling):
                        raise ConditionalCheckFailedException("the condition failed")
                self.writes += 1
                new_used = (row or {}).get("used", 0) + values[":by"]
                self.rows[key] = {"used": new_used, "updated_at": values[":at"]}
                return {"Attributes": {"used": new_used}}

        table = FakeTable(dict(stored or {}))
        return AiUsageRepository("jb-probe-dev", table=table), table

    def test_the_first_generation_of_a_period_is_allowed(self):
        repo, table = self._repo()
        result = repo.consume_if_available("t1", "trial", allowance=3, at=1)
        self.assertEqual(result, {"allowed": True, "used": 1})
        self.assertEqual(table.writes, 1)

    def test_the_last_slot_is_allowed_and_the_next_is_not(self):
        repo, table = self._repo({("t1", "trial"): {"used": 2}})
        self.assertTrue(repo.consume_if_available("t1", "trial", allowance=3, at=1)["allowed"])
        refused = repo.consume_if_available("t1", "trial", allowance=3, at=2)
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["used"], 3, "the refusal reports what is already spent")
        self.assertEqual(table.writes, 1, "a refused slot must not be written and then handed back")

    def test_a_refusal_does_not_increment(self):
        # The whole point of a conditional update: a failed condition applies NOTHING. Taking the slot and
        # refunding it would leave a window where the count is wrong, and would corrupt a lifetime counter
        # permanently if the refund were ever lost.
        repo, table = self._repo({("t1", "trial"): {"used": 3}})
        repo.consume_if_available("t1", "trial", allowance=3, at=1)
        self.assertEqual(table.rows[("t1", "trial")]["used"], 3)

    def test_an_allowance_of_zero_refuses_without_writing(self):
        # The absent-row branch of the condition would otherwise let a FRESH row through on a zero
        # allowance -- which is exactly the free tier once ai_builder becomes a capability.
        repo, table = self._repo()
        result = repo.consume_if_available("t1", "2026-09", allowance=0, at=1)
        self.assertEqual(result, {"allowed": False, "used": 0})
        self.assertEqual(table.writes, 0)

    def test_unlimited_is_not_fed_to_the_comparison(self):
        # `exempt` tenants carry allowance -1. Comparing against it (used < -1) is false for every row, so a
        # naive implementation refuses an exempt tenant on their very first generation.
        repo, table = self._repo()
        for expected in (1, 2, 3, 4):
            result = repo.consume_if_available("t1", "2026-09", allowance=-1, at=1)
            self.assertEqual(result, {"allowed": True, "used": expected})
        self.assertEqual(table.writes, 4)

    def test_two_racing_requests_cannot_both_take_the_last_slot(self):
        # The original bug, reproduced at the repository level: both callers read the same `used` first.
        repo, table = self._repo({("t1", "trial"): {"used": 2}})
        seen_by_both = repo.used("t1", "trial")
        self.assertEqual(seen_by_both, 2, "both requests observe room for one more")
        first = repo.consume_if_available("t1", "trial", allowance=3, at=1)
        second = repo.consume_if_available("t1", "trial", allowance=3, at=1)
        self.assertTrue(first["allowed"])
        self.assertFalse(second["allowed"], "the loser is refused by the write, not by Python")
        self.assertEqual(table.rows[("t1", "trial")]["used"], 3, "never more than the allowance")


class GenerationEventsRepositoryTests(unittest.TestCase):
    """The real ledger class, not a fake — the key format is the part a fake cannot get wrong for you."""

    def _repo(self):
        from stripe_link.repositories.documents import AiGenerationEventsRepository

        class FakeTable:
            def __init__(self):
                self.items, self.updates = {}, []
            def put_item(self, Item):  # noqa: N803
                self.items[(Item["tenant_id"], Item["event_key"])] = dict(Item)
            def update_item(self, **kwargs):
                self.updates.append(kwargs)

        table = FakeTable()
        return AiGenerationEventsRepository("jb-probe-dev", table=table), table

    def test_a_row_without_its_keys_is_refused(self):
        from stripe_link.repositories.documents import RepositoryError

        repo, _ = self._repo()
        with self.assertRaises(RepositoryError):
            repo.put({"tenant_id": "t1"})

    def test_the_factory_refuses_an_unconfigured_table(self):
        from stripe_link.repositories.documents import (RepositoryError,
                                                        ai_generation_events_repository)

        os.environ.pop("AI_GENERATION_EVENTS_TABLE", None)
        with self.assertRaises(RepositoryError):
            ai_generation_events_repository()

    def test_completion_merges_only_the_fields_it_was_given(self):
        repo, table = self._repo()
        repo.complete("t1", "0001790500000#gen_a", {"status": "succeeded", "input_tokens": 10})
        self.assertEqual(len(table.updates), 1)
        update = table.updates[0]
        self.assertEqual(update["Key"], {"tenant_id": "t1", "event_key": "0001790500000#gen_a"})
        self.assertEqual(sorted(update["ExpressionAttributeValues"].values(), key=str),
                         sorted(["succeeded", 10], key=str))

    def test_an_empty_patch_writes_nothing(self):
        repo, table = self._repo()
        repo.complete("t1", "k", {})
        self.assertEqual(table.updates, [])


class EventKeyTests(unittest.TestCase):
    def test_the_key_sorts_chronologically_as_a_string(self):
        # The reason the epoch is zero-padded. Unpadded, "9..." sorts AFTER "10...", so a date-range query
        # silently returns the wrong window — and it would only start being wrong in 2286, or immediately for
        # any test that uses small timestamps.
        from stripe_link.domain.ai_generation_events import event_key

        keys = [event_key(9, "gen_b"), event_key(10, "gen_a"), event_key(1790500000, "gen_c")]
        self.assertEqual(sorted(keys), keys)

    def test_the_key_is_unique_per_generation_within_a_second(self):
        from stripe_link.domain.ai_generation_events import event_key

        self.assertNotEqual(event_key(100, "gen_a"), event_key(100, "gen_b"))


class GenerationSourceTests(unittest.TestCase):
    def test_byok_is_never_charged_to_the_platform(self):
        from stripe_link.domain.ai_generation_events import SOURCE_BYOK, source_for

        self.assertEqual(source_for(provider="anthropic", plan_key="basic"), SOURCE_BYOK)

    def test_trial_and_plan_are_distinguishable_after_the_fact(self):
        # The plan a tenant is on changes; what they were on when we spent the slot does not.
        from stripe_link.domain.ai_generation_events import SOURCE_PLAN, SOURCE_TRIAL, source_for

        self.assertEqual(source_for(provider="bedrock", trial=True), SOURCE_TRIAL)
        self.assertEqual(source_for(provider="bedrock", plan_key="premium"), SOURCE_PLAN)

    def test_exempt_is_its_own_source(self):
        from stripe_link.domain.ai_generation_events import SOURCE_EXEMPT, source_for

        self.assertEqual(source_for(provider="bedrock", exempt=True), SOURCE_EXEMPT)
