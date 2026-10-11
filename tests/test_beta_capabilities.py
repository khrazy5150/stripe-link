"""Letting a tenant try a feature before it ships, without a second deployment.

`plans/MONEY_ACROSS_SILOS.md` P1. The author wanted a STAGING environment: introduce the AI builder
there, let real tenants use it on real data, promote it later. That cannot work as a deployment — a
third silo starts with empty tables, so a tenant's staging work is stranded the day the feature
graduates, which is the exact failure that prompted the question, rebuilt on purpose.

A per-tenant flag in production gives the same thing and keeps the data: the feature ships dark, named
tenants see it, graduating it is deleting a line.

**Two things the plan did not anticipate, both found while building it.**

1. `tenant_entitlement_set` has FOUR return paths, not one. A grant unioned into the obvious one would
   be absent for comped accounts, live trials and expired trials.
2. Two of those paths grant `set(CAPABILITIES)` — the whole catalogue. So merely DECLARING an unreleased
   capability would hand it to every exempt tenant and every live trial on day one, which is the single
   thing a beta must not do. Hence `GENERAL_CAPABILITIES`, which is the catalogue minus what is
   beta-only.
"""
import unittest

from stripe_link.domain.entitlements import (BETA_CAPABILITIES, CAPABILITIES, FREE_TIER_CAPABILITIES,
                                             GENERAL_CAPABILITIES, beta_capabilities,
                                             tenant_entitlement_set)

GRANT = "ai_builder"


def tenant(**extra):
    base = {"billing_status": "canceled", "entitlements": []}
    base.update(extra)
    return base


class TheGrantReachesEveryPath(unittest.TestCase):
    """Four ways out of the resolver. A grant that works on one of them is a grant that silently does
    not work for most tenants."""

    def test_a_subscribed_or_canceled_tenant(self):
        self.assertIn(GRANT, tenant_entitlement_set(tenant(beta=[GRANT])))

    def test_a_comped_tenant(self):
        self.assertIn(GRANT, tenant_entitlement_set(tenant(billing_exempt=True, beta=[GRANT])))

    def test_a_live_trial(self):
        live = tenant(billing_status="trial", trial_ends_at=4_000_000_000, beta=[GRANT])
        self.assertIn(GRANT, tenant_entitlement_set(live))

    def test_an_expired_trial_keeps_its_beta(self):
        """The free floor exists so the store keeps selling; being in a beta is orthogonal to billing."""
        expired = tenant(billing_status="trial", trial_ends_at=1, beta=[GRANT])
        granted = tenant_entitlement_set(expired, now=2_000_000_000)
        self.assertIn(GRANT, granted)
        self.assertTrue(set(FREE_TIER_CAPABILITIES) <= granted, "the floor is still there")


class SuspensionStillHolds(unittest.TestCase):
    def test_a_suspended_tenant_gets_nothing_extra(self):
        """Suspension is a hold on the account. A beta grant says which features EXIST, not whether the
        account is in good standing — and letting it through would make an unreleased feature the one
        thing a suspended tenant could still use."""
        held = tenant(billing_status="suspended", beta=[GRANT])
        self.assertEqual(tenant_entitlement_set(held), set())


class DeclaringABetaDoesNotShipIt(unittest.TestCase):
    """The leak the plan did not see. Two paths hand out `set(CAPABILITIES)`, so adding an unreleased
    name to the catalogue would grant it to every comped account and every trial immediately."""

    def test_general_access_excludes_beta_only_capabilities(self):
        self.assertEqual(set(GENERAL_CAPABILITIES), set(CAPABILITIES) - set(BETA_CAPABILITIES))

    def test_a_comped_tenant_without_the_grant_does_not_get_a_beta_feature(self):
        import stripe_link.domain.entitlements as module
        original_beta, original_general = module.BETA_CAPABILITIES, module.GENERAL_CAPABILITIES
        try:
            module.BETA_CAPABILITIES = frozenset({GRANT})
            module.GENERAL_CAPABILITIES = frozenset(set(CAPABILITIES) - {GRANT})
            self.assertNotIn(GRANT, tenant_entitlement_set(tenant(billing_exempt=True)))
            self.assertNotIn(GRANT, tenant_entitlement_set(
                tenant(billing_status="trial", trial_ends_at=4_000_000_000)))
            # ...and the named tenant still gets it.
            self.assertIn(GRANT, tenant_entitlement_set(tenant(billing_exempt=True, beta=[GRANT])))
        finally:
            module.BETA_CAPABILITIES, module.GENERAL_CAPABILITIES = original_beta, original_general

    def test_nothing_is_beta_only_today(self):
        """Correct starting state: everything in the catalogue has shipped. Adding a name to
        BETA_CAPABILITIES is the act of making a feature beta-only."""
        self.assertEqual(set(BETA_CAPABILITIES), set())


class ItIsNotStoredWhereBillingWillWipeIt(unittest.TestCase):
    """`platform_subscription_sync` does `updates["entitlements"] = plan_entitlements(plan)` — a
    wholesale overwrite. A grant kept there is erased by the tenant's next Stripe event, silently, at an
    unpredictable moment. This is why `beta` is its own field."""

    import pathlib as _pathlib
    SYNC = (_pathlib.Path(__file__).resolve().parents[1]
            / "src/stripe_link/domain/platform_subscription_sync.py").read_text(encoding="utf-8")

    def test_the_billing_sync_never_writes_beta(self):
        self.assertNotIn('"beta"', self.SYNC)
        self.assertNotIn("['beta']", self.SYNC)

    def test_the_overwrite_this_guards_against_is_still_there(self):
        """If the sync stops overwriting, this test is defending against a risk that no longer exists —
        and should be re-read rather than silently kept."""
        self.assertIn('updates["entitlements"] = plan_entitlements(plan)', self.SYNC)

    def test_a_plan_overwrite_leaves_the_grant_standing(self):
        """The actual property, simulated: entitlements replaced wholesale, beta untouched."""
        subscriber = tenant(beta=[GRANT], entitlements=["invoicing"])
        subscriber["entitlements"] = []  # what the webhook does on cancellation
        self.assertIn(GRANT, tenant_entitlement_set(subscriber))


class ATypoGrantsNothingAndIsRefused(unittest.TestCase):
    def test_an_unknown_name_is_ignored_at_read_time(self):
        self.assertEqual(beta_capabilities({"beta": ["ai_buildr"]}), set())

    def test_and_refused_at_write_time(self):
        """Ignoring it quietly leaves an operator wondering why their beta tester sees nothing."""
        import json
        import pathlib

        from stripe_link.domain.documents import DocumentValidationError, validate_tenant_profile
        base = json.loads((pathlib.Path(__file__).resolve().parents[1]
                           / "schemas/examples/tenant-profile-demo.json").read_text(encoding="utf-8"))
        with self.assertRaises(DocumentValidationError):
            validate_tenant_profile({**base, "beta": ["ai_buildr"]})
        with self.assertRaises(DocumentValidationError):
            validate_tenant_profile({**base, "beta": "ai_builder"})
        validate_tenant_profile({**base, "beta": [GRANT]})
        validate_tenant_profile({**base, "beta": []})
        validate_tenant_profile(base)

    def test_a_tenant_with_no_beta_field_is_unaffected(self):
        """Union-only: every existing tenant behaves exactly as before, so there is no migration."""
        self.assertEqual(beta_capabilities({}), set())
        self.assertEqual(tenant_entitlement_set(tenant()),
                         tenant_entitlement_set(tenant(beta=[])))


class TheSchemaAdmitsIt(unittest.TestCase):
    """`TenantProfile.schema.json` sets `additionalProperties: false`, so a field the code validator
    accepts and the schema does not is a document that passes one gate and fails the other. Caught
    before shipping, by reading the schema rather than trusting the Python validator alone."""

    def test_the_schema_declares_beta(self):
        import json
        import pathlib as _pathlib
        schema = json.loads((_pathlib.Path(__file__).resolve().parents[1]
                             / "schemas/TenantProfile.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema.get("additionalProperties", True),
                         "if this becomes permissive the test below stops meaning anything")
        field = schema["properties"]["beta"]
        self.assertEqual(field["type"], "array")
        self.assertEqual(field["items"]["type"], "string")
        self.assertIn("overwrites wholesale", field["description"],
                      "the one rule a future reader must not get wrong")


if __name__ == "__main__":
    unittest.main()
