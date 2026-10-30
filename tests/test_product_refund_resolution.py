"""The product's refund policy is decided by the SERVER, and the literal is gone.

plans/REFUND_POLICY.md steps 4-6. `dashboard/src/stores/products.js` used to return a hardcoded policy at
product-creation time -- 30 days of delivery in unused condition for physical, non-refundable for digital --
stamped `source: "user_preference_default"`, published on live pages, claiming a provenance nothing read.

The test that matters most is `test_a_client_sending_the_old_literal_is_overruled`: an old dashboard still
posting the literal must get the tenant's real default written instead. Fixing the browser is not enough,
because a browser is not a place you can enforce anything.
"""
import json
import unittest
from pathlib import Path

from handlers.products import create_product, handler, resolve_refund_policy
from stripe_link.domain.refund_policy import (
    NON_REFUNDABLE,
    SOURCE_PLATFORM_DEFAULT,
    SOURCE_PRODUCT_OVERRIDE,
    SOURCE_TENANT_DEFAULT,
    SOURCE_TIP_JAR,
)
from stripe_link.repositories.documents import RepositoryError
from tests.fakes import FakeDocumentRepository

THE_LITERAL = {
    "source": "user_preference_default", "refund_window": "30_days", "condition": "unused",
    "return_method": "no_return_customer_keeps", "short_label": "30-day money-back",
    "full_policy": ("Refunds are available within 30 days of delivery in unused condition.\n\nThis item does "
                    "not need to be returned. The customer may keep the item and dispose of it in a "
                    "responsible way. The seller may still grant a refund."),
}

TENANT_CONFIG = {"document_type": "tenant_config", "tenant_id": "t1", "legal_defaults": {
    "refund_policies": {
        "physical": {"refund_window": "14_days", "condition": "unopened",
                     "return_method": "return_required"},
    }}}


class FakeConfigRepository:
    def __init__(self, config=None, raises=False):
        self.config = config
        self.raises = raises
        self.reads = 0

    def get(self, tenant_id):
        self.reads += 1
        if self.raises:
            raise RepositoryError("table unavailable")
        return self.config


def product(**overrides):
    document = {"tenant_id": "t1", "product_id": "p1", "name": "Thing", "product_type": "physical",
                "prices": [{"price_id": "pr1", "pricing_model": "one_time", "unit_amount": 5000}]}
    document.update(overrides)
    return document


class TheTenantsDefaultWins(unittest.TestCase):
    """Renamed in spirit: the write no longer stamps anything (P3).

    It used to compose the tenant's default into the product document at save time, which is exactly what
    made a Configuration change reach nothing -- the promise froze at the save and only thawed if the
    product happened to be edited again. The product is now the OVERRIDE CHANNEL ONLY and the promise is
    composed at publish from the live default.
    """

    def test_no_policy_sent_stores_no_policy(self):
        document = product()
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertIsNone(document.get("refund_policy"))

    def test_a_client_sending_the_old_literal_is_still_overruled(self):
        """The property that fixes the original bug, and it survives the change: a browser is not a place
        you can enforce anything, and an old cached bundle keeps posting the literal. It is now DISCARDED
        rather than replaced -- the page gets the tenant's live default at publish instead."""
        document = product(refund_policy=dict(THE_LITERAL))
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertIsNone(document.get("refund_policy"))

    def test_the_promise_now_comes_from_resolution_at_publish(self):
        """What the page will say, asked of the same function publish asks."""
        from stripe_link.domain.refund_policy import resolve
        policy = resolve(tenant_config=TENANT_CONFIG, product=product())
        self.assertEqual(policy["refund_window"], "14_days")
        self.assertEqual(policy["source"], SOURCE_TENANT_DEFAULT)

    def test_no_tenant_default_resolves_to_nothing(self):
        """The platform fallback is gone (P2). No policy chosen means the page says nothing about
        refunds -- silence is recoverable, a promise nobody made is a dispute."""
        from stripe_link.domain.refund_policy import resolve
        self.assertEqual(resolve(tenant_config=None, product=product())["mode"], "unset")

    def test_the_class_follows_the_product(self):
        from stripe_link.domain.refund_policy import resolve
        # The tenant set only `physical`, so a digital product resolves to nothing at all.
        self.assertEqual(resolve(tenant_config=TENANT_CONFIG,
                                 product=product(product_type="digital"))["mode"], "unset")

    def test_a_subscription_only_product_uses_the_subscription_class(self):
        """The class still follows the recurring price. This tenant set only `physical`, so the right
        answer is NOTHING -- reaching for the physical terms because they are the ones that exist is the
        mistake the class split prevents."""
        from stripe_link.domain.refund_policy import resolve
        document = product(prices=[{"price_id": "pr1", "pricing_model": "recurring",
                                    "recurring": {"interval": "month"}}])
        policy = resolve(tenant_config=TENANT_CONFIG, product=document)
        self.assertEqual(policy["policy_class"], "subscription")
        self.assertEqual(policy["mode"], "unset")

    def test_a_subscription_window_runs_from_RENEWAL(self):
        """The legacy generator rendered a 72-hour subscription window as "within 3 days of delivery" --
        wrong unit AND wrong event, on a page making a commercial promise. Nothing is delivered to a
        subscriber and nothing arrives on renewal."""
        from stripe_link.domain.refund_policy import resolve
        tenant = {"legal_defaults": {"refund_policies": {
            "subscription": {"refund_window": "72_hours", "condition": "any",
                             "return_method": "no_return_customer_keeps"}}}}
        document = product(prices=[{"price_id": "pr1", "pricing_model": "recurring",
                                    "recurring": {"interval": "month"}}])
        policy = resolve(tenant_config=tenant, product=document)
        self.assertEqual(policy["full_policy"], "Refunds are available within 72 hours of renewal.")

    def test_mixed_pricing_keeps_the_goods_class(self):
        """A product sold one-time AND recurring makes two promises; the one-time buyers are not
        renewing."""
        from stripe_link.domain.refund_policy import resolve
        document = product(prices=[{"price_id": "a", "pricing_model": "one_time"},
                                   {"price_id": "b", "pricing_model": "recurring",
                                    "recurring": {"interval": "month"}}])
        self.assertEqual(resolve(tenant_config=TENANT_CONFIG, product=document)["refund_window"],
                         "14_days")



class OverridesAreHonoured(unittest.TestCase):
    def test_an_override_is_kept_and_its_copy_generated(self):
        document = product(refund_policy={"source": "product_override", "refund_window": "7_days",
                                          "condition": "any", "return_method": "return_required"})
        repository = FakeConfigRepository(TENANT_CONFIG)
        resolve_refund_policy(document, config_repository=repository)
        self.assertEqual(document["refund_policy"]["source"], SOURCE_PRODUCT_OVERRIDE)
        self.assertEqual(document["refund_policy"]["full_policy"],
                         "Refunds are available within 7 days of delivery.")
        self.assertEqual(repository.reads, 0, "an override needs no tenant config read")

    def test_an_overrides_own_wording_survives(self):
        document = product(refund_policy={"source": "product_override", "refund_window": "custom",
                                          "condition": "any", "return_method": "return_required",
                                          "full_policy": "Ring us and we'll sort it."})
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertEqual(document["refund_policy"]["full_policy"], "Ring us and we'll sort it.")

    def test_an_invalid_override_is_left_for_the_validator(self):
        """Quietly substituting something would give the tenant a policy they did not ask for."""
        sent = {"source": "product_override", "refund_window": "45_days", "condition": "any",
                "return_method": "return_required"}
        document = product(refund_policy=dict(sent))
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertEqual(document["refund_policy"], sent)

    def test_tips_are_left_alone(self):
        document = product(product_type="tip-jar", refund_policy={
            "source": SOURCE_TIP_JAR, "refund_window": NON_REFUNDABLE, "condition": "any",
            "return_method": "digital_revoke_access", "short_label": "Non-refundable",
            "full_policy": "Tips are gifts and are non-refundable."})
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertEqual(document["refund_policy"]["full_policy"],
                         "Tips are gifts and are non-refundable.")

    def test_a_threshold_without_an_override_is_not_a_policy(self):
        """`keep_it_below` alone never made this product's terms its own, and the document cannot carry a
        bare threshold -- the schema requires source/short_label/full_policy. Per-class thresholds live
        on the tenant default, which Configuration already edits, and `resolve` carries one through."""
        document = product(refund_policy={"keep_it_below": 1500})
        resolve_refund_policy(document, config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertIsNone(document.get("refund_policy"))


class BothWritePathsAgree(unittest.TestCase):
    """The rule lives in the domain so the AI generation path applies the identical one.

    Before this, `ai_provision.product_document` set no policy at all, so an AI-generated product saved with
    none: its page showed no refund section and `chosen_badges` had no guarantee to read. A second write path
    quietly disagreeing with the first is how the original literal survived so long.
    """

    def test_the_ai_path_uses_the_same_domain_rule(self):
        from stripe_link.domain.refund_policy import apply_to_product

        generated = product()
        generated.pop("refund_policy", None)
        apply_to_product(generated, TENANT_CONFIG)
        self.assertIsNone(generated.get("refund_policy"))

    def test_the_handler_wrapper_and_the_domain_rule_agree(self):
        through_handler = product()
        resolve_refund_policy(through_handler, config_repository=FakeConfigRepository(TENANT_CONFIG))

        from stripe_link.domain.refund_policy import apply_to_product
        through_domain = product()
        apply_to_product(through_domain, TENANT_CONFIG)

        self.assertEqual(through_handler.get("refund_policy"), through_domain.get("refund_policy"))

    def test_an_override_needs_no_config_read_on_either_path(self):
        """A product that decides for itself must not fail because a settings table blinked."""
        document = product(refund_policy={"source": "product_override", "refund_window": "7_days",
                                          "condition": "any", "return_method": "return_required"})
        repository = FakeConfigRepository(raises=True)
        resolve_refund_policy(document, config_repository=repository)
        self.assertEqual(repository.reads, 0)
        self.assertEqual(document["refund_policy"]["refund_window"], "7_days")


class ThroughTheHandler(unittest.TestCase):
    def setUp(self):
        with (Path(__file__).resolve().parents[1] / "schemas" / "examples"
              / "product-creatine-gummies.json").open(encoding="utf-8") as handle:
            self.product = json.load(handle)
        self.product["tenant_id"] = "t1"
        self.repository = FakeDocumentRepository("product_id")

    def test_create_resolves_before_validating(self):
        self.product["refund_policy"] = dict(THE_LITERAL)
        response = handler({"httpMethod": "POST", "body": json.dumps(self.product)}, None,
                           repository=self.repository,
                           sync_invoker=lambda *args, **kwargs: None,
                           config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertEqual(response["statusCode"], 201)
        stored = self.repository.get("t1", self.product["product_id"])
        # DISCARDED, not replaced. The page gets the tenant's live default at publish instead.
        self.assertIsNone(stored.get("refund_policy"))

    def test_a_product_sent_with_no_policy_stores_none(self):
        self.product.pop("refund_policy", None)
        response = handler({"httpMethod": "POST", "body": json.dumps(self.product)}, None,
                           repository=self.repository,
                           sync_invoker=lambda *args, **kwargs: None,
                           config_repository=FakeConfigRepository(TENANT_CONFIG))
        self.assertEqual(response["statusCode"], 201)
        stored = self.repository.get("t1", self.product["product_id"])
        self.assertIsNone(stored.get("refund_policy"))

    def test_reads_never_resolve_anything(self):
        """The author's rule: nothing alters old data, everything is organic. A GET must not rewrite a
        policy, so a product nobody saves keeps exactly what it has."""
        self.product["refund_policy"] = dict(THE_LITERAL)
        self.repository.put(self.product)
        before = json.dumps(self.repository.get("t1", self.product["product_id"]), sort_keys=True)
        handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"},
                 "pathParameters": {"product_id": self.product["product_id"]}}, None,
                repository=self.repository)
        after = json.dumps(self.repository.get("t1", self.product["product_id"]), sort_keys=True)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
