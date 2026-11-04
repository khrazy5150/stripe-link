"""The business-identity migration (plans/SITE_AS_BUSINESS_IDENTITY.md §P4), tested because it WRITES.

The author chose the clean end state: once every tenant has moved, the tenant-level fallback is DELETED
rather than kept as a safety net. This script is what "has moved" means, so the fallback reads can only be
removed after it has run — which makes it the load-bearing piece of P4 rather than a convenience.

It carries `name`, `brands` and a VERIFIED `email`. Not `phone`/`address`/`timezone`/`shipping_cutoff_hour`
— those are operational, read by shipping and the delivery estimate, and moving under their own plan.

The rule that makes this safe is the one the resolver already uses: **move them only where the answer is
unambiguous.** A tenant with two businesses has no answer to "which one owns Luxe Wellness", and guessing
would put one business's brand in the other's picker — the bug this plan exists to close.

This file exists because an earlier draft of the script called `migrate` TWICE per tenant, once applying
and once not, so a real run would have written and then reported the dry-run answer.
"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location(
    "migrate_identity", ROOT / "deploy/migrate_business_identity_to_site.py")
migrate_identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_identity)


class FakeSites:
    def __init__(self, sites):
        self.sites = [dict(s) for s in sites]
        self.puts = []

    def list_for_tenant(self, _tenant_id, **_kw):
        return [dict(s) for s in self.sites]

    def put(self, doc):
        self.puts.append(dict(doc))
        index = next(i for i, s in enumerate(self.sites) if s["site_id"] == doc["site_id"])
        self.sites[index] = dict(doc)
        return dict(doc)


def site(site_id, name, brands=None):
    org = {"name": name}
    if brands is not None:
        org["brands"] = list(brands)
    return {"site_id": site_id, "tenant_id": "t1", "organization": org}


class SoleSiteTests(unittest.TestCase):
    def test_one_named_site_is_the_answer(self):
        found = migrate_identity.sole_site(FakeSites([site("site_qui", "Quill")]), "t1")
        self.assertEqual(found["site_id"], "site_qui")

    def test_TWO_named_sites_is_NO_answer(self):
        sites = FakeSites([site("site_qui", "Quill"), site("site_pol", "Poliaxis Nutrition")])
        self.assertIsNone(migrate_identity.sole_site(sites, "t1"))

    def test_a_site_with_no_business_name_is_not_a_candidate(self):
        """Nobody has told us it is a business yet, so it cannot be the one that owns a brand — and it must
        not make an otherwise clear answer ambiguous either."""
        sites = FakeSites([site("site_qui", "Quill"), {"site_id": "site_blank", "tenant_id": "t1",
                                                       "organization": {}}])
        self.assertEqual(migrate_identity.sole_site(sites, "t1")["site_id"], "site_qui")

    def test_no_sites_at_all_is_no_answer(self):
        self.assertIsNone(migrate_identity.sole_site(FakeSites([]), "t1"))


class FillIsEmptyOnlyTests(unittest.TestCase):
    """Fill-empty-only is the never-clobber guarantee — the same rule the Stripe seed uses. Demonstrated on
    real dev data: the account says "Poliaxis Nutrition" and the live Site says "Quill", and the Site keeps
    its own name."""

    PROFILE = {"name": "Poliaxis Nutrition", "brands": ["Luxe Wellness"],
               "email": "hi@poliaxis.test", "email_verified_at": 99}

    def test_an_EMPTY_site_is_filled(self):
        org, changed = migrate_identity.fill({}, self.PROFILE)
        self.assertEqual(org["name"], "Poliaxis Nutrition")
        self.assertEqual(org["brands"], ["Luxe Wellness"])
        self.assertEqual(org["email"], "hi@poliaxis.test")
        self.assertTrue(org["email_verified"])
        self.assertEqual(len(changed), 3)

    def test_a_site_that_NAMED_ITSELF_keeps_its_name(self):
        org, _ = migrate_identity.fill({"name": "Quill"}, self.PROFILE)
        self.assertEqual(org["name"], "Quill")

    def test_a_site_with_its_OWN_email_keeps_it(self):
        org, _ = migrate_identity.fill({"email": "hi@quill.test", "email_verified": True}, self.PROFILE)
        self.assertEqual(org["email"], "hi@quill.test")

    def test_brands_are_ADDED_not_replaced(self):
        org, _ = migrate_identity.fill({"brands": ["House Label"]}, self.PROFILE)
        self.assertEqual(org["brands"], ["House Label", "Luxe Wellness"])

    def test_nothing_to_do_reports_NO_changes(self):
        org = {"name": "Quill", "brands": ["Luxe Wellness"], "email": "hi@quill.test"}
        _, changed = migrate_identity.fill(org, self.PROFILE)
        self.assertEqual(changed, [])

    def test_provenance_is_stamped(self):
        """`sources` was added by §P3b as a carrier with no writer. This is its first one, and it is what
        stops a later Stripe or GBP seed clobbering a value that came from the tenant's own account."""
        org, _ = migrate_identity.fill({}, self.PROFILE)
        self.assertEqual(org["sources"], {"name": "profile", "brands": "profile", "email": "profile"})

    def test_sources_is_NOT_written_when_nothing_changed(self):
        org, _ = migrate_identity.fill({"name": "Quill", "email": "x@q.test",
                                        "brands": ["Luxe Wellness"]}, self.PROFILE)
        self.assertNotIn("sources", org)

    def test_an_UNVERIFIED_account_email_is_not_identity_to_move(self):
        """Pending is not verified — the gate's whole point. The scan filters it out, so `fill` never sees
        one; this pins the scan's rule where it is written."""
        source = (ROOT / "deploy/migrate_business_identity_to_site.py").read_text(encoding="utf-8")
        block = source.split("def _profiles(", 1)[1].split("\n\n", 1)[0]
        self.assertIn('if business.get("email_verified") else ""', block)

    def test_the_PENDING_code_is_never_carried(self):
        """A pending `code_hash` is salted with the TENANT scope, so under the Site scope it could never be
        confirmed — carrying it would leave a code that looks live and is permanently dead."""
        org, _ = migrate_identity.fill({}, {**self.PROFILE, "email_verification": {"code_hash": "x"}})
        self.assertNotIn("email_verification", org)

    def test_the_operational_fields_are_NOT_carried(self):
        """The author's call: they move under their own plan, not riding along with identity."""
        org, _ = migrate_identity.fill({}, {**self.PROFILE, "phone": "+12065551234",
                                            "address": {"locality": "Seattle"}, "timezone": "US/Pacific",
                                            "shipping_cutoff_hour": 15})
        for operational in ("phone", "telephone", "address", "timezone", "shipping_cutoff_hour"):
            with self.subTest(field=operational):
                self.assertNotIn(operational, org)


class MigrateTests(unittest.TestCase):
    PROFILE = {"tenant_id": "t1", "user_id": "t1", "name": "",
               "brands": ["Luxe Wellness", "Quill Basics"], "email": ""}

    def _run(self, sites, *, apply=True, profile=None):
        original = migrate_identity.sites_repository
        migrate_identity.sites_repository = lambda mode=None: sites
        try:
            return migrate_identity.migrate(profile or self.PROFILE, "live", apply=apply)
        finally:
            migrate_identity.sites_repository = original

    def test_a_single_business_RECEIVES_the_brands(self):
        sites = FakeSites([site("site_qui", "Quill")])
        self.assertEqual(self._run(sites), "migrated")
        self.assertEqual(sites.sites[0]["organization"]["brands"], ["Luxe Wellness", "Quill Basics"])

    def test_a_DRY_RUN_writes_nothing(self):
        sites = FakeSites([site("site_qui", "Quill")])
        self.assertEqual(self._run(sites, apply=False), "migrated")
        self.assertEqual(sites.puts, [])

    def test_it_is_ADDITIVE_not_a_replacement(self):
        """A Site that already has brands of its own keeps them."""
        sites = FakeSites([site("site_qui", "Quill", ["House Label"])])
        self._run(sites)
        self.assertEqual(sites.sites[0]["organization"]["brands"],
                         ["House Label", "Luxe Wellness", "Quill Basics"])

    def test_it_is_IDEMPOTENT(self):
        sites = FakeSites([site("site_qui", "Quill")])
        self.assertEqual(self._run(sites), "migrated")
        self.assertEqual(self._run(sites), "already")
        self.assertEqual(len(sites.puts), 1)
        self.assertEqual(sites.sites[0]["organization"]["brands"], ["Luxe Wellness", "Quill Basics"])

    def test_a_name_the_site_already_owns_is_skipped_case_insensitively(self):
        sites = FakeSites([site("site_qui", "Quill", ["luxe wellness"])])
        self._run(sites)
        self.assertEqual(sites.sites[0]["organization"]["brands"], ["luxe wellness", "Quill Basics"])

    def test_TWO_businesses_are_left_ALONE(self):
        """The whole point. Guessing would put one business's brand in the other's picker."""
        sites = FakeSites([site("site_qui", "Quill"), site("site_pol", "Poliaxis Nutrition")])
        self.assertEqual(self._run(sites), "ambiguous")
        self.assertEqual(sites.puts, [])

    def test_a_tenant_with_no_business_named_anywhere_is_left_ALONE(self):
        sites = FakeSites([{"site_id": "site_blank", "tenant_id": "t1", "organization": {}}])
        self.assertEqual(self._run(sites), "no_site")
        self.assertEqual(sites.puts, [])

    def test_the_PROFILE_copy_is_never_touched(self):
        """Removing the fallback is a separate step, gated on this having run everywhere. The script holds
        no profiles repository at all, which is the strongest form of that guarantee."""
        source = (ROOT / "deploy/migrate_business_identity_to_site.py").read_text(encoding="utf-8")
        self.assertNotIn("user_profiles_repository", source)
        self.assertNotIn(".put(profile", source)

    def test_every_outcome_is_counted_ONCE(self):
        """The bug this file was written for: `migrate` called twice per tenant, once applying and once
        not, so a real run wrote and then reported the dry-run answer."""
        source = (ROOT / "deploy/migrate_business_identity_to_site.py").read_text(encoding="utf-8")
        body = source.split("tally: dict[str, int] = {}", 1)[1].split("\n    print(", 1)[0]
        self.assertEqual(body.count("migrate(profile"), 1, body)


if __name__ == "__main__":
    unittest.main()
