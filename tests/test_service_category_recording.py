"""A service's category has to reach the shared taxonomy, and with the right SCOPE.

Two failure modes this pins:

* the category is never recorded, so it never comes back as a suggestion — not to other tenants, and not
  even to the tenant who typed it (`search_suggestions` reads "yours" from the table, not from the
  service document);
* it is recorded with an EMPTY product_type. That is not a harmless blank: `search_suggestions` only
  filters an entry that HAS types, so an unscoped "Massage Therapy" would be offered for T-shirts.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from stripe_link.category_usage import record_category_usage
from stripe_link.document_route import save_document
from handlers.services import handler as services_handler
from tests.fakes import FakeDocumentRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]

SERVICE = {
    "schema_version": "2026-05-29", "document_type": "service", "tenant_id": "tenant_demo",
    "service_id": "svc_massage", "name": "Swedish Massage", "duration_minutes": 60,
    "price": {"currency": "usd", "unit_amount": 9000},
    "product_category": "massage_therapy",
}


class FakeCategoriesRepo:
    def __init__(self):
        self.recorded = []

    def record_usage(self, key, label, product_type, tenant_id, now):
        self.recorded.append((key, label, product_type, tenant_id))


def save(service, categories_repo):
    repos = [FakeDocumentRepository(f) for f in
             ("service_id", "fulfiller_id", "availability_id", "exception_id", "appointment_id")]
    return services_handler(
        {"httpMethod": "PUT", "path": "/services", "body": json.dumps(service)},
        None, *repos, categories_repo=categories_repo,
    )


class ServiceCategoryIsRecorded(unittest.TestCase):
    def test_saving_a_service_records_its_category_scoped_to_service(self):
        repo = FakeCategoriesRepo()
        self.assertEqual(201, save(SERVICE, repo)["statusCode"])
        self.assertEqual([("massage_therapy", "Massage Therapy", "service", "tenant_demo")], repo.recorded)

    def test_the_scope_is_not_empty_which_is_the_bug_the_override_exists_for(self):
        """Without the explicit product_type a service document supplies none, and an unscoped category
        is suggested for every product type."""
        repo = FakeCategoriesRepo()
        record_category_usage(SERVICE, repo)  # no override: what the product-shaped call would do
        self.assertEqual("", repo.recorded[0][2])
        repo.recorded.clear()
        record_category_usage(SERVICE, repo, product_type="service")
        self.assertEqual("service", repo.recorded[0][2])

    def test_a_service_without_a_category_records_nothing(self):
        repo = FakeCategoriesRepo()
        service = {k: v for k, v in SERVICE.items() if k != "product_category"}
        self.assertEqual(201, save(service, repo)["statusCode"])
        self.assertEqual([], repo.recorded)

    def test_the_category_survives_the_save(self):
        """Recording usage is bookkeeping; the document still has to carry the field."""
        repos = [FakeDocumentRepository(f) for f in
                 ("service_id", "fulfiller_id", "availability_id", "exception_id", "appointment_id")]
        saved = services_handler(
            {"httpMethod": "PUT", "path": "/services", "body": json.dumps(SERVICE)},
            None, *repos, categories_repo=FakeCategoriesRepo(),
        )
        self.assertEqual("massage_therapy", json.loads(saved["body"])["service"]["product_category"])


class SaveSurvivesItsOwnBookkeeping(unittest.TestCase):
    def test_a_failing_hook_does_not_unsay_a_completed_save(self):
        """The put already happened. Reporting an error now would tell the tenant their service was not
        saved, when it was."""
        calls = []

        class Repo:
            def put(self, document):
                calls.append(document)
                return document

        def boom(_saved):
            raise RuntimeError("categories table down")

        response = save_document(
            {"httpMethod": "PUT", "body": json.dumps({"id": "x"})},
            Repo(), lambda _doc: None, "service", "invalid_service", on_saved=boom,
        )
        self.assertEqual(201, response["statusCode"])
        self.assertEqual(1, len(calls))

    def test_the_hook_receives_what_was_actually_stored(self):
        seen = []

        class Repo:
            def put(self, document):
                return {**document, "stamped_by_repo": True}

        save_document(
            {"httpMethod": "PUT", "body": json.dumps({"id": "x"})},
            Repo(), lambda _doc: None, "service", "invalid_service", on_saved=seen.append,
        )
        self.assertEqual([{"id": "x", "stamped_by_repo": True}], seen)

    def test_the_hook_does_not_run_when_validation_rejects_the_document(self):
        ran = []

        class Repo:
            def put(self, document):  # pragma: no cover - must never be reached
                raise AssertionError("put must not happen on an invalid document")

        from stripe_link.domain.documents import DocumentValidationError

        def reject(_doc):
            raise DocumentValidationError("nope")

        response = save_document(
            {"httpMethod": "PUT", "body": json.dumps({"id": "x"})},
            Repo(), reject, "service", "invalid_service", on_saved=ran.append,
        )
        self.assertEqual(400, response["statusCode"])
        self.assertEqual([], ran)


class ServicesFunctionCanReachTheTable(unittest.TestCase):
    """The recorder swallows its own failures, so a missing env var or grant would surface only as a log
    line nobody reads — the category would simply never be recorded (`feedback_absence_reads_as_safety`)."""

    @classmethod
    def setUpClass(cls):
        # Text + regex, not PyYAML: this repo keeps third-party deps out, and tests/test_table_grants.py
        # reads the template the same way.
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        blocks = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", template, re.M))
        cls.block = blocks.get("ServicesFunction", "")

    def test_the_block_was_actually_found(self):
        """Without this, every assertion below would pass on an empty string."""
        self.assertIn("Handler: handlers.services.handler", self.block)

    def test_the_env_var_is_declared(self):
        self.assertRegex(self.block, r"PRODUCT_CATEGORIES_TABLE:\s*!Ref\s+ProductCategoriesTable")

    def test_the_function_may_write_the_table(self):
        self.assertRegex(
            self.block,
            r"DynamoDBCrudPolicy:\s*\n\s+TableName:\s*!Ref\s+ProductCategoriesTable",
            "ServicesFunction needs write access to record category usage",
        )


if __name__ == "__main__":
    unittest.main()
