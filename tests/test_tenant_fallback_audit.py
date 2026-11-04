"""Is the tenant-level fallback still REACHED? (plans/SITE_AS_BUSINESS_IDENTITY.md §P4)

The author decided the fallback is deleted once every tenant has moved. The migration script was written
as the measure of "has moved" and that was the wrong gate: for a tenant running two businesses, which Site
owns a given brand is genuinely unknowable, so the migration reports `ambiguous` forever and the gate never
opens.

The answerable question is narrower — **if `UserProfile.business.{name,email,brands}` vanished right now,
what would change?** — and `blockers_for` is the answer. The deletion decision rests entirely on it, so a
wrong answer here green-lights a regression on a live published page. Hence this file.

The three fields block for three different reasons, which is why they are reported separately rather than
as one verdict: a tenant can be safe to delete `brands` from and not `name`.
"""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("audit_fallback", ROOT / "deploy/audit_tenant_fallback.py")
audit_fallback = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_fallback)
blockers_for = audit_fallback.blockers_for


def profile(**business):
    return {"tenant_id": "t1", "business": business}


def site(site_id="site_qui", **org):
    return {"site_id": site_id, "organization": org}


def page(page_id="p1", site_id="site_qui", status="published"):
    doc = {"page_id": page_id, "status": status}
    if site_id:
        doc["site_id"] = site_id
    return doc


class NothingStatedMeansNothingBlockedTests(unittest.TestCase):
    def test_an_empty_business_block_blocks_nothing(self):
        """Most tenants. The fallback cannot be reached for a field that holds nothing."""
        self.assertEqual(blockers_for(profile(), [site(name="Quill")], [page()]),
                         {"name": [], "email": [], "brands": []})

    def test_each_field_is_judged_INDEPENDENTLY(self):
        """A tenant can be safe to delete `brands` from and not `name` — one verdict for all three would
        hold the easy deletions hostage to the hard one."""
        found = blockers_for(profile(name="Poliaxis", brands=["Luxe"]),
                             [site(name="Quill", brands=["Luxe"])], [page(site_id="")])
        self.assertTrue(found["name"])
        self.assertEqual(found["brands"], [])


class TheNAMEIsReachedTwoWaysTests(unittest.TestCase):
    def test_an_UNNAMED_site_reaches_it(self):
        found = blockers_for(profile(name="Poliaxis"), [site(name="")], [page()])
        self.assertIn("has no business name", found["name"][0])

    def test_a_page_attached_to_NO_SITE_reaches_it(self):
        """The dev blocker, exactly: one published live page with no site_id. Deleting the name while it
        exists re-brands a live page after a person (`resolve_business_name` ends at the owner)."""
        found = blockers_for(profile(name="Poliaxis"), [site(name="Quill")], [page(site_id="")])
        self.assertIn("attached to no Site", found["name"][0])

    def test_every_site_named_and_every_page_attached_is_SAFE(self):
        found = blockers_for(profile(name="Poliaxis"),
                             [site("site_qui", name="Quill"), site("site_pol", name="Poliaxis")],
                             [page("p1", "site_qui"), page("p2", "site_pol")])
        self.assertEqual(found["name"], [])

    def test_a_tenant_with_NO_name_is_not_blocked_by_an_unnamed_site(self):
        """There is nothing to delete, so there is nothing to protect."""
        self.assertEqual(blockers_for(profile(), [site(name="")], [page(site_id="")])["name"], [])

    def test_a_DRAFT_page_with_no_Site_is_NOT_a_blocker(self):
        """It renders in the tenant's own builder preview and nowhere else, so the worst it can show is
        the owner their own name on their own screen. Blocking a deletion on that would hold the clean end
        state hostage to every abandoned draft a tenant ever made."""
        found = blockers_for(profile(name="Poliaxis"), [site(name="Quill")],
                             [page("p1", "", status="draft")])
        self.assertEqual(found["name"], [])
        self.assertTrue(found.get("notes"), "it should still be REPORTED, just not as a blocker")

    def test_an_ARCHIVED_page_is_not_a_blocker_either(self):
        found = blockers_for(profile(name="Poliaxis"), [site(name="Quill")],
                             [page("p1", "", status="archived")])
        self.assertEqual(found["name"], [])

    def test_a_PUBLISHED_page_with_no_Site_still_blocks(self):
        """A visitor sees it, and `resolve_business_name` ends at the owner's personal name."""
        found = blockers_for(profile(name="Poliaxis"), [site(name="Quill")],
                             [page("p1", "", status="published")])
        self.assertIn("PUBLISHED", found["name"][0])

    def test_EVERY_offender_is_listed_not_just_the_first(self):
        """The report is a to-do list. Naming one of four means three more rounds of the same discovery."""
        found = blockers_for(profile(name="Poliaxis"), [site(name="")],
                             [page("p1", ""), page("p2", "")])
        self.assertEqual(len(found["name"]), 3)


class TheEMAILIsReachedByAnUNVERIFIEDSiteTests(unittest.TestCase):
    def test_a_site_with_no_verified_address_reaches_it(self):
        found = blockers_for(profile(email="hi@p.test", email_verified=True), [site(name="Quill")], [])
        self.assertIn("has no verified address", found["email"][0])

    def test_every_site_verified_is_SAFE(self):
        found = blockers_for(profile(email="hi@p.test", email_verified=True),
                             [site(name="Quill", email="hi@q.test", email_verified=True)], [])
        self.assertEqual(found["email"], [])

    def test_an_UNVERIFIED_profile_email_is_not_a_blocker(self):
        """Pending is not verified — it was never usable as a Reply-To, so deleting it changes nothing."""
        found = blockers_for(profile(email="hi@p.test"), [site(name="Quill")], [])
        self.assertEqual(found["email"], [])


class TheBRANDSAreReachedByANameNoSiteCarriesTests(unittest.TestCase):
    def test_a_brand_on_no_site_reaches_it(self):
        found = blockers_for(profile(brands=["Luxe Wellness"]), [site(name="Quill")], [])
        self.assertIn("Luxe Wellness", found["brands"][0])

    def test_a_brand_ANY_site_carries_is_safe(self):
        found = blockers_for(profile(brands=["Luxe Wellness"]),
                             [site("site_a", name="Quill"),
                              site("site_b", name="Poliaxis", brands=["Luxe Wellness"])], [])
        self.assertEqual(found["brands"], [])

    def test_the_comparison_ignores_CASE_and_PADDING(self):
        """The dashboard trims and de-duplicates on save, so a stored value may differ in both from what
        the profile holds. Reporting that as missing would be a blocker nobody could clear."""
        found = blockers_for(profile(brands=["  Luxe Wellness "]),
                             [site(name="Quill", brands=["luxe wellness"])], [])
        self.assertEqual(found["brands"], [])

    def test_a_blank_brand_is_not_a_brand(self):
        self.assertEqual(blockers_for(profile(brands=["", "   "]), [site(name="Quill")], [])["brands"], [])


class TheAuditTouchesNOTHINGTests(unittest.TestCase):
    def test_it_holds_no_writer_at_all(self):
        """The strongest form of "read-only": there is no put, no update and no delete in the file."""
        source = (ROOT / "deploy/audit_tenant_fallback.py").read_text(encoding="utf-8")
        for writer in ("put_item", "update_item", "delete_item", ".put(", "--apply"):
            with self.subTest(writer=writer):
                self.assertNotIn(writer, source)

    def test_it_says_ONE_environment_is_not_enough(self):
        """The fallback is shared code; dev being clean says nothing about prod."""
        source = (ROOT / "deploy/audit_tenant_fallback.py").read_text(encoding="utf-8")
        self.assertIn("dev AND prod", source)


if __name__ == "__main__":
    unittest.main()
