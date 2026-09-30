"""The tenant's own refund defaults: a home, a validator, and copy written by the SERVER.

plans/REFUND_POLICY.md phases 2 and 3. The whole bug was that no such home existed, so
`dashboard/src/stores/products.js` invented a policy literal and the renderer published it.

These defaults live on **TenantConfig**, not TenantProfile as the plan first said. TenantProfile is written
only by registration, auth and Stripe webhooks and holds `billing_status`, `tier_id`, `billing_exempt` and
`stripe_subscription_id`; a dashboard PUT over that document to reach a refund setting would hand tenants
their own billing tier.
"""
import json
import unittest

from handlers.config import handler as config_handler
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_config
from stripe_link.domain.refund_policy import (
    DIGITAL,
    PHYSICAL,
    SOURCE_PLATFORM_DEFAULT,
    SOURCE_TENANT_DEFAULT,
    SUBSCRIPTION,
    stored_policies,
    tenant_policies,
    vocabulary,
)


def config_document(**overrides):
    document = {"schema_version": "1.0.0", "document_type": "tenant_config", "tenant_id": "t1"}
    document.update(overrides)
    return document


def with_policies(policies):
    return config_document(legal_defaults={"refund_policies": policies})


VALID_PHYSICAL = {"refund_window": "60_days", "condition": "unopened",
                  "return_method": "return_required"}


class FakeRepository:
    def __init__(self, stored=None):
        self.stored = stored
        self.written = None

    def get(self, tenant_id):
        return self.stored

    def put(self, document):
        self.written = document
        return document


def event(method, *, body=None, tenant="t1", params=None):
    query = {"tenant_id": tenant}
    query.update(params or {})
    return {"httpMethod": method, "queryStringParameters": query,
            "body": json.dumps(body) if body is not None else None}


class WhereTheyLive(unittest.TestCase):
    def test_read_from_legal_defaults(self):
        self.assertEqual(stored_policies(with_policies({PHYSICAL: VALID_PHYSICAL})),
                         {PHYSICAL: VALID_PHYSICAL})

    def test_a_bare_map_also_works(self):
        """So a caller holding just the map does not have to fake a whole config document."""
        self.assertEqual(stored_policies({"refund_policies": {PHYSICAL: VALID_PHYSICAL}}),
                         {PHYSICAL: VALID_PHYSICAL})

    def test_absent_is_empty_not_an_error(self):
        for document in (None, {}, config_document(), config_document(legal_defaults={})):
            self.assertEqual(stored_policies(document), {})

    def test_a_set_class_outranks_the_platform_fallback(self):
        policies = tenant_policies(with_policies({PHYSICAL: VALID_PHYSICAL}))
        self.assertEqual(policies[PHYSICAL]["refund_window"], "60_days")
        self.assertEqual(policies[PHYSICAL]["source"], SOURCE_TENANT_DEFAULT)
        self.assertEqual(policies[DIGITAL]["source"], SOURCE_PLATFORM_DEFAULT)


class Validation(unittest.TestCase):
    def test_a_valid_block_passes(self):
        validate_tenant_config(with_policies({PHYSICAL: VALID_PHYSICAL}))

    def test_absent_block_passes(self):
        validate_tenant_config(config_document())
        validate_tenant_config(config_document(legal_defaults={"refund_url": "https://x.test/refunds"}))

    def test_unknown_class_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({"services": VALID_PHYSICAL}))

    def test_the_three_choices_are_required(self):
        for field in ("refund_window", "condition", "return_method"):
            policy = dict(VALID_PHYSICAL)
            policy.pop(field)
            with self.assertRaises(DocumentValidationError):
                validate_tenant_config(with_policies({PHYSICAL: policy}))

    def test_a_typod_window_is_refused_not_defaulted(self):
        """Falling back silently would be the same class of fault as the literal: a commercial term the
        tenant did not choose."""
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({PHYSICAL: dict(VALID_PHYSICAL,
                                                                 refund_window="45_days")}))

    def test_stripe_cart_vocabulary_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({PHYSICAL: dict(VALID_PHYSICAL,
                                                                 refund_window="60_day_returns")}))
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({PHYSICAL: dict(VALID_PHYSICAL,
                                                                 return_method="print_label")}))

    def test_custom_window_requires_prose(self):
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({PHYSICAL: dict(VALID_PHYSICAL,
                                                                 refund_window="custom")}))
        validate_tenant_config(with_policies({PHYSICAL: dict(
            VALID_PHYSICAL, refund_window="custom", full_policy="Ask us within a fortnight.")}))

    def test_negative_keep_it_below_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_tenant_config(with_policies({PHYSICAL: dict(VALID_PHYSICAL, keep_it_below=-1)}))

    def test_copy_is_optional_because_the_server_writes_it(self):
        validate_tenant_config(with_policies({PHYSICAL: VALID_PHYSICAL}))


class TheServerWritesTheSentence(unittest.TestCase):
    """The correction. The dashboard sends three choices; the promise is composed on the server."""

    def test_put_generates_the_copy(self):
        repository = FakeRepository()
        response = config_handler(event("PUT", body=with_policies({PHYSICAL: VALID_PHYSICAL})),
                                  None, repository=repository)
        self.assertEqual(response["statusCode"], 201)
        written = stored_policies(repository.written)[PHYSICAL]
        self.assertEqual(written["short_label"], "60-day money-back")
        self.assertEqual(written["full_policy"],
                         "Refunds are available within 60 days of delivery in unopened condition.")

    def test_a_tenants_own_wording_survives(self):
        repository = FakeRepository()
        config_handler(event("PUT", body=with_policies({PHYSICAL: dict(
            VALID_PHYSICAL, short_label="Our promise", full_policy="Legally reviewed sentence.")})),
            None, repository=repository)
        written = stored_policies(repository.written)[PHYSICAL]
        self.assertEqual(written["short_label"], "Our promise")
        self.assertEqual(written["full_policy"], "Legally reviewed sentence.")

    def test_no_source_is_stored_on_a_default(self):
        """`source` belongs to a RESOLVED policy. Storing it would be a second place for the same fact to
        be wrong."""
        repository = FakeRepository()
        config_handler(event("PUT", body=with_policies({PHYSICAL: VALID_PHYSICAL})),
                       None, repository=repository)
        self.assertNotIn("source", stored_policies(repository.written)[PHYSICAL])

    def test_the_subscription_basis_is_renewal(self):
        repository = FakeRepository()
        config_handler(event("PUT", body=with_policies({SUBSCRIPTION: {
            "refund_window": "72_hours", "condition": "any",
            "return_method": "no_return_customer_keeps"}})), None, repository=repository)
        self.assertEqual(stored_policies(repository.written)[SUBSCRIPTION]["full_policy"],
                         "Refunds are available within 72 hours of renewal.")

    def test_an_invalid_policy_is_reported_not_silently_fixed(self):
        repository = FakeRepository()
        response = config_handler(event("PUT", body=with_policies({PHYSICAL: dict(
            VALID_PHYSICAL, refund_window="45_days")})), None, repository=repository)
        self.assertEqual(response["statusCode"], 400)
        self.assertIsNone(repository.written)

    def test_a_config_with_no_policies_is_untouched(self):
        repository = FakeRepository()
        response = config_handler(event("PUT", body=config_document(legal_defaults={
            "refund_url": "https://x.test/r"})), None, repository=repository)
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(repository.written["legal_defaults"], {"refund_url": "https://x.test/r"})


class WhatTheScreenReceives(unittest.TestCase):
    def test_get_always_returns_resolved_policies(self):
        repository = FakeRepository(stored=with_policies({PHYSICAL: VALID_PHYSICAL}))
        body = json.loads(config_handler(event("GET"), None, repository=repository)["body"])
        self.assertEqual(body["refund_policies"][PHYSICAL]["refund_window"], "60_days")
        self.assertEqual(body["refund_policies"][DIGITAL]["source"], SOURCE_PLATFORM_DEFAULT)

    def test_the_20kb_vocabulary_is_opt_in(self):
        """Every other screen that reads /config should not pay for the pickers' option tables."""
        repository = FakeRepository(stored=with_policies({PHYSICAL: VALID_PHYSICAL}))
        plain = json.loads(config_handler(event("GET"), None, repository=repository)["body"])
        self.assertNotIn("refund_policy_options", plain)
        asked = json.loads(config_handler(
            event("GET", params={"refund_options": "1"}), None, repository=repository)["body"])
        self.assertIn("refund_policy_options", asked)

    def test_every_option_has_a_preview(self):
        """So the screen never has to compose a sentence. A JS copy of that template is how the literal in
        stores/products.js came to be published."""
        options = vocabulary()
        for policy_class in options["classes"]:
            for window in options["windows"]:
                for condition in options["conditions"]:
                    key = f"{policy_class}|{window['value']}|{condition['value']}"
                    self.assertIn(key, options["previews"])
                    self.assertTrue(options["previews"][key]["short_label"])

    def test_a_tenant_with_no_config_still_gets_the_pickers(self):
        """The config table starts EMPTY, so this is the normal path for a tenant opening the screen for the
        first time. The 404 is true of the document; the vocabulary and the platform's default terms are not
        part of it, and withholding them left every dropdown blank."""
        repository = FakeRepository(stored=None)
        response = config_handler(event("GET", params={"refund_options": "1"}), None,
                                  repository=repository)
        self.assertEqual(response["statusCode"], 404)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "not_found")
        self.assertIn("refund_policy_options", body)
        self.assertEqual(body["refund_policies"][PHYSICAL]["source"], SOURCE_PLATFORM_DEFAULT)
        self.assertTrue(body["refund_policy_options"]["windows"])

    def test_the_404_still_reads_as_a_failure(self):
        """An `extra` must never disguise a failure as a success."""
        body = json.loads(config_handler(event("GET"), None,
                                         repository=FakeRepository(stored=None))["body"])
        self.assertEqual(body["error"], "not_found")
        self.assertIn("message", body)

    def test_window_days_are_published_for_the_ui(self):
        by_value = {w["value"]: w for w in vocabulary()["windows"]}
        self.assertEqual(by_value["72_hours"]["days"], 3)
        self.assertIsNone(by_value["non_refundable"]["days"])


if __name__ == "__main__":
    unittest.main()
