"""The brands migration (plans/SITE_AS_BUSINESS_IDENTITY.md §P4), tested because it WRITES.

`business.brands` is the last piece of business identity on the user profile. It cannot simply be deleted:
the page builder reads it as a fallback, so a tenant whose brands lived only there would open the picker
and find it empty.

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
    "migrate_brands", ROOT / "deploy/migrate_profile_brands_to_site.py")
migrate_brands = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_brands)


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
        found = migrate_brands.sole_site(FakeSites([site("site_qui", "Quill")]), "t1")
        self.assertEqual(found["site_id"], "site_qui")

    def test_TWO_named_sites_is_NO_answer(self):
        sites = FakeSites([site("site_qui", "Quill"), site("site_pol", "Poliaxis Nutrition")])
        self.assertIsNone(migrate_brands.sole_site(sites, "t1"))

    def test_a_site_with_no_business_name_is_not_a_candidate(self):
        """Nobody has told us it is a business yet, so it cannot be the one that owns a brand — and it must
        not make an otherwise clear answer ambiguous either."""
        sites = FakeSites([site("site_qui", "Quill"), {"site_id": "site_blank", "tenant_id": "t1",
                                                       "organization": {}}])
        self.assertEqual(migrate_brands.sole_site(sites, "t1")["site_id"], "site_qui")

    def test_no_sites_at_all_is_no_answer(self):
        self.assertIsNone(migrate_brands.sole_site(FakeSites([]), "t1"))


class MigrateTests(unittest.TestCase):
    PROFILE = {"tenant_id": "t1", "user_id": "t1", "brands": ["Luxe Wellness", "Quill Basics"]}

    def _run(self, sites, *, apply=True, profile=None):
        original = migrate_brands.sites_repository
        migrate_brands.sites_repository = lambda mode=None: sites
        try:
            return migrate_brands.migrate(profile or self.PROFILE, "live", apply=apply)
        finally:
            migrate_brands.sites_repository = original

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
        source = (ROOT / "deploy/migrate_profile_brands_to_site.py").read_text(encoding="utf-8")
        self.assertNotIn("user_profiles_repository", source)
        self.assertNotIn(".put(profile", source)

    def test_every_outcome_is_counted_ONCE(self):
        """The bug this file was written for: `migrate` called twice per tenant, once applying and once
        not, so a real run wrote and then reported the dry-run answer."""
        source = (ROOT / "deploy/migrate_profile_brands_to_site.py").read_text(encoding="utf-8")
        body = source.split("tally: dict[str, int] = {}", 1)[1].split("\n    print(", 1)[0]
        self.assertEqual(body.count("migrate(profile"), 1, body)


if __name__ == "__main__":
    unittest.main()
