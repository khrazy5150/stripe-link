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
