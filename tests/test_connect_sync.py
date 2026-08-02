import unittest

from handlers.stripe_webhook import reconcile_account_updated
from stripe_link.domain.connect_sync import (
    business_profile_seed,
    compute_site_eligibility,
    connect_verification_state,
    seed_business_identity,
)
from stripe_link.runtime.html import page_robots_directive
from tests.fakes import FakeDocumentRepository


def account(**overrides):
    acct = {
        "charges_enabled": True,
        "payouts_enabled": True,
        "details_submitted": True,
        "requirements": {"disabled_reason": None},
        "country": "US",
        "email": "owner@bean.bros",
        "business_profile": {
            "name": "Bean Bros",
            "support_phone": "2065551234",
            "support_email": "hi@bean.bros",
            "support_address": {"line1": "1 Main St", "city": "Denver", "state": "CO",
                                "postal_code": "80204", "country": "US"},
        },
    }
    acct.update(overrides)
    return acct


class ConnectVerificationTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(connect_verification_state(account()), "verified")
        self.assertEqual(connect_verification_state(account(charges_enabled=False)), "pending")
        self.assertEqual(connect_verification_state(account(charges_enabled=False, details_submitted=False)), "not_started")
        self.assertEqual(connect_verification_state(account(requirements={"disabled_reason": "rejected.fraud"})), "restricted")
        self.assertEqual(connect_verification_state(account(requirements={"disabled_reason": "under_review"})), "restricted")


class BusinessProfileSeedTests(unittest.TestCase):
    def test_seed_extracts_and_normalizes(self):
        seed = business_profile_seed(account())
        self.assertEqual(seed["name"], "Bean Bros")
        self.assertEqual(seed["email"], "hi@bean.bros")
        self.assertEqual(seed["phone"], "+12065551234")            # normalized to E.164
        self.assertEqual(seed["address"]["street"], "1 Main St")
        self.assertEqual(seed["address"]["locality"], "Denver")
        self.assertEqual(seed["address"]["region"], "CO")
        self.assertEqual(seed["address"]["country"], "US")

    def test_seed_skips_an_unusable_phone(self):
        seed = business_profile_seed(account(business_profile={"name": "X", "support_phone": "555"}))
        self.assertNotIn("phone", seed)

    def test_fill_empty_only_and_provenance(self):
        existing = {"name": "My Own Shop", "phone": "+15550001111"}   # tenant already set these
        seed = {"name": "Bean Bros", "email": "hi@bean.bros", "phone": "+12065551234"}
        business, changed = seed_business_identity(existing, seed)
        self.assertTrue(changed)
        self.assertEqual(business["name"], "My Own Shop")             # not clobbered
        self.assertEqual(business["phone"], "+15550001111")           # not clobbered
        self.assertEqual(business["email"], "hi@bean.bros")           # filled (was empty)
        self.assertEqual(business["sources"], {"email": "stripe"})    # only the filled field is stamped

    def test_no_change_when_all_present(self):
        _, changed = seed_business_identity({"name": "A", "email": "b@c.d", "phone": "+15550001111"},
                                            {"name": "X", "email": "y@z.w", "phone": "+12065551234"})
        self.assertFalse(changed)


class SiteEligibilityTests(unittest.TestCase):
    def _site(self, hosting_type="platform"):
        return {"hosting": {"type": hosting_type}, "indexing": {"eligibility": "blocked"}}

    def test_platform_site_never_eligible(self):
        self.assertEqual(compute_site_eligibility(self._site(), connect_verified=True, connect_restricted=False, domain_verified=False), "pending")
        self.assertEqual(compute_site_eligibility(self._site(), connect_verified=False, connect_restricted=False, domain_verified=False), "blocked")

    def test_custom_domain_plus_connect_is_eligible(self):
        self.assertEqual(compute_site_eligibility(self._site("custom"), connect_verified=True, connect_restricted=False, domain_verified=True), "eligible")
        self.assertEqual(compute_site_eligibility(self._site("custom"), connect_verified=False, connect_restricted=False, domain_verified=True), "pending")

    def test_restricted_revokes_a_domain_site(self):
        self.assertEqual(compute_site_eligibility(self._site("custom"), connect_verified=False, connect_restricted=True, domain_verified=True), "revoked")
        self.assertEqual(compute_site_eligibility(self._site(), connect_verified=False, connect_restricted=True, domain_verified=False), "blocked")


class RobotsDirectiveTests(unittest.TestCase):
    def test_page_not_on_custom_domain_is_always_noindex(self):
        # Platform host, or a non-homepage page of a custom-domain Site: never indexed even in prod.
        self.assertEqual(page_robots_directive(kind="published", environment="prod", eligibility="eligible", page_type="landing", on_custom_domain=False), "noindex,nofollow")

    def test_eligible_custom_domain_landing_indexes(self):
        d = page_robots_directive(kind="published", environment="prod", eligibility="eligible", page_type="landing", on_custom_domain=True)
        self.assertEqual(d, "index,follow,max-image-preview:large,max-snippet:-1")

    def test_eligible_checkout_page_is_crawl_not_index(self):
        self.assertEqual(page_robots_directive(kind="published", environment="prod", eligibility="eligible", page_type="checkout", on_custom_domain=True), "noindex,follow")

    def test_pending_custom_domain_is_crawl(self):
        self.assertEqual(page_robots_directive(kind="published", environment="prod", eligibility="pending", page_type="landing", on_custom_domain=True), "noindex,follow")

    def test_preview_and_nonprod_are_noindex_nofollow(self):
        self.assertEqual(page_robots_directive(kind="preview", environment="prod", eligibility="eligible", page_type="landing", on_custom_domain=True), "noindex,nofollow")
        self.assertEqual(page_robots_directive(kind="published", environment="dev", eligibility="eligible", page_type="landing", on_custom_domain=True), "noindex,nofollow")

    def test_archived_site_de_indexes_every_page(self):
        # An archived Site overrides everything — even an otherwise-indexable eligible custom-domain page — and
        # adds noarchive so the cached snapshot drops too.
        self.assertEqual(
            page_robots_directive(kind="published", environment="prod", eligibility="eligible", page_type="landing", on_custom_domain=True, site_archived=True),
            "noindex,nofollow,noarchive",
        )


class FakeKeysRepo:
    def __init__(self):
        self.saved = None

    def put(self, document):
        self.saved = document
        return document


class ReconcileAccountUpdatedTests(unittest.TestCase):
    def setUp(self):
        self.keys = FakeKeysRepo()
        self.profiles = FakeDocumentRepository("user_id")
        self.sites = FakeDocumentRepository("site_id")
        self.profiles.put({"tenant_id": "t1", "user_id": "t1", "document_type": "user_profile", "business": {}})
        self.sites.put({"tenant_id": "t1", "site_id": "site_1", "document_type": "site",
                        "hosting": {"type": "platform"}, "indexing": {"eligibility": "blocked"}, "pages": {}})

    def _run(self, acct, tenant_document=None):
        event = {"type": "account.updated", "account": "acct_1", "data": {"object": acct}}
        return reconcile_account_updated(
            event, mode="test",
            tenant_document=tenant_document or {"tenant_id": "t1", "connect_account_id": "acct_1"},
            stripe_keys_repo=self.keys, user_profiles_repo=self.profiles, sites_repo=self.sites,
            now_fn=lambda: 1790000000,
        )

    def test_persists_state_seeds_nap_and_recomputes_eligibility(self):
        result = self._run(account())
        self.assertEqual(result["connect_verification"], "verified")
        # 1) connect state on the stripe_keys doc
        self.assertTrue(self.keys.saved["charges_enabled"])
        self.assertEqual(self.keys.saved["connect_verification"], "verified")
        # 2) NAP seeded into the owner profile (fill-empty)
        business = self.profiles.get("t1", "t1")["business"]
        self.assertEqual(business["name"], "Bean Bros")
        self.assertEqual(business["phone"], "+12065551234")
        self.assertEqual(business["sources"]["name"], "stripe")
        # 3) platform Site recomputed to 'pending' (Connect verified, still no custom domain)
        self.assertEqual(self.sites.get("t1", "site_1")["indexing"]["eligibility"], "pending")
        self.assertIn("site_1", result["sites_recomputed"])

    def test_does_not_clobber_existing_business_fields(self):
        self.profiles.put({"tenant_id": "t1", "user_id": "t1", "document_type": "user_profile",
                           "business": {"name": "My Own Shop"}})
        self._run(account())
        self.assertEqual(self.profiles.get("t1", "t1")["business"]["name"], "My Own Shop")

    def test_restricted_account_blocks_platform_site(self):
        self._run(account(charges_enabled=False, requirements={"disabled_reason": "rejected.fraud"}))
        self.assertEqual(self.keys.saved["connect_verification"], "restricted")
        self.assertEqual(self.sites.get("t1", "site_1")["indexing"]["eligibility"], "blocked")

    def test_refreshes_bnpl_capability_status_from_event(self):
        # A merchant activates Affirm in their own Stripe dashboard -> account.updated carries the new capability
        # status; the cached status on the stripe_keys doc is refreshed via push (no polling needed), enabled kept.
        doc = {"tenant_id": "t1", "connect_account_id": "acct_1",
               "payment_methods": {"bnpl": {"affirm": {"enabled": True, "capability_status": "inactive"}}}}
        result = self._run(account(capabilities={"affirm_payments": "active", "klarna_payments": "active"}), doc)
        affirm = self.keys.saved["payment_methods"]["bnpl"]["affirm"]
        self.assertEqual(affirm["capability_status"], "active")
        self.assertTrue(affirm["enabled"])                      # tenant intent preserved
        self.assertIn("affirm", result["bnpl_refreshed"])
        self.assertEqual(self.keys.saved["payment_methods"]["account_country"], "US")   # country cached too

    def test_no_bnpl_write_when_capabilities_unchanged(self):
        doc = {"tenant_id": "t1", "connect_account_id": "acct_1",
               "payment_methods": {"bnpl": {"klarna": {"enabled": True, "capability_status": "active"}},
                                   "account_country": "US"}}
        result = self._run(account(capabilities={"klarna_payments": "active"}), doc)
        self.assertNotIn("bnpl_refreshed", result)             # nothing changed → no noisy report
        self.assertEqual(self.keys.saved["payment_methods"]["bnpl"]["klarna"]["capability_status"], "active")


if __name__ == "__main__":
    unittest.main()
