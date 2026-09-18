"""Addresses that must STOP answering, and the one mechanism that stops them.

Author, 2026-09-17/18, three requests that turned out to be the same shape:

  * a renamed handle should 404, not redirect -- "keep the username intact in the database (so no one can
    reclaim it) but any attempt to navigate to renamed jbay.page/maria should be met with 'Oopss! This page
    doesn't exist'";
  * a tenant should be able to sunset a failed business without renaming anything -- "a tenant has a business
    selling toys and another selling clothes. The toy business fails";
  * and the stale-record bug found while checking those: a moved-from hostname kept serving a snapshot frozen
    on the day of the rename, forever.

All three are one thing: an index record outliving what it pointed at, and a resolver that needs to know why.

Sunset is ARCHIVE, not a new switch. Archiving used to keep serving, which made it a near-duplicate of the
`seo_enabled` toggle -- the only functional difference between them was one `noarchive` token -- while nothing
did what a tenant winding a business down actually needs. Two states, two meanings: seo_enabled=false is
"open, don't rank me"; archived is "closed". Zero Sites were archived in dev or prod when this changed.
"""
import unittest

from stripe_link.domain.custom_domains import (
    CustomDomainError, MAX_USERNAME_CHANGES, record_hosting_history, site_index_records, usernames_left)

DOMAIN = "jbay.page"


def _site(**over):
    site = {
        "tenant_id": "t1", "site_id": "site_1", "environment": "live", "status": "active",
        "hosting": {"type": "platform", "platform_hostname": "toys.jbay.uk", "creator_username": "toybox"},
        "pages": {"/links": {"page_id": "hub", "composition": "lead_social"}},
    }
    site.update(over)
    return site


def _by_domain(site, creator_domain=DOMAIN):
    return {r["domain"]: r for r in site_index_records(site, creator_domain)}


class ArchivedSiteTests(unittest.TestCase):
    def test_an_active_site_serves_every_address(self):
        rows = _by_domain(_site())
        self.assertEqual(rows["toys.jbay.uk"]["status"], "active")
        self.assertEqual(rows["jbay.page/toybox"]["status"], "active")

    def test_archiving_stops_serving_all_of_them(self):
        """The toy business closes; the clothes business is a different Site and is untouched."""
        rows = _by_domain(_site(status="archived"))
        for domain, record in rows.items():
            self.assertEqual(record["status"], "archived", domain)

    def test_the_records_still_exist_so_the_names_stay_claimed(self):
        # Closing a shop must not put its address back on the market.
        self.assertIn("toys.jbay.uk", _by_domain(_site(status="archived")))
        self.assertIn("jbay.page/toybox", _by_domain(_site(status="archived")))

    def test_the_resolver_refuses_anything_not_active(self):
        import inspect

        from handlers import custom_domains_resolve

        source = inspect.getsource(custom_domains_resolve.handler)
        self.assertIn('record.get("status") != "active"', source)


class RetiredUsernameTests(unittest.TestCase):
    def _renamed(self, to="toy-box"):
        existing, document = _site(), _site()
        document["hosting"]["creator_username"] = to
        record_hosting_history(existing, document)
        return document

    def test_the_old_handle_is_remembered(self):
        self.assertEqual(self._renamed()["hosting"]["retired_usernames"], ["toybox"])

    def test_it_stops_resolving_rather_than_forwarding(self):
        """A handle is an IDENTITY: forwarding would tie the old name to the new person forever, which is
        wrong for the rebrand a rename usually is."""
        row = _by_domain(self._renamed())["jbay.page/toybox"]
        self.assertEqual(row["status"], "retired")
        self.assertNotIn("redirect_to", row)

    def test_but_nobody_else_can_ever_take_it(self):
        # Nothing in this codebase releases a reservation; the row exists purely to say "claimed, not serving".
        self.assertIn("jbay.page/toybox", _by_domain(self._renamed()))

    def test_renaming_back_does_not_leave_it_retired(self):
        existing = self._renamed()
        back = _site()                              # ...to the original handle
        record_hosting_history(existing, back)
        self.assertNotIn("toybox", back["hosting"].get("retired_usernames") or [])


class UsernameCapTests(unittest.TestCase):
    def test_three_changes_then_stop(self):
        site = _site()
        for n in range(MAX_USERNAME_CHANGES):
            self.assertEqual(usernames_left(site), MAX_USERNAME_CHANGES - n)
            nxt = _site()
            nxt["hosting"]["creator_username"] = f"name-{n}"
            nxt["hosting"]["retired_usernames"] = list(site["hosting"].get("retired_usernames") or [])
            record_hosting_history(site, nxt)
            site = nxt
        self.assertEqual(usernames_left(site), 0)
        spent = _site()
        spent["hosting"]["creator_username"] = "one-too-many"
        spent["hosting"]["retired_usernames"] = list(site["hosting"]["retired_usernames"])
        with self.assertRaises(CustomDomainError):
            record_hosting_history(site, spent)

    def test_saving_without_renaming_costs_nothing(self):
        # Editing anything else on a Site must not quietly spend a strike.
        site = _site()
        same = _site()
        same["name"] = "Toys, renamed the SITE not the handle"
        record_hosting_history(site, same)
        self.assertEqual(usernames_left(same), MAX_USERNAME_CHANGES)

    def test_the_count_reaches_the_tenant_before_they_commit(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        handler = (root / "src" / "handlers" / "sites.py").read_text(encoding="utf-8")
        self.assertIn('site["usernames_left"] = usernames_left(site)', handler)
        ui = (root / "dashboard" / "src" / "components" / "Sites.vue").read_text(encoding="utf-8")
        self.assertIn("usernameChangesLeft", ui)
        self.assertIn("anyone with the old link will see a page-not-found", ui)


class CopyTests(unittest.TestCase):
    """The UI said the opposite of what archiving now does."""

    def setUp(self):
        import pathlib

        self.ui = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"
                   / "Sites.vue").read_text(encoding="utf-8")

    def test_archive_no_longer_promises_it_keeps_serving(self):
        self.assertNotIn("The Site keeps serving", self.ui)
        self.assertNotIn("It keeps serving;", self.ui)

    def test_it_says_what_closing_actually_does_and_what_survives(self):
        self.assertIn("stops serving and visitors see a page-not-found", self.ui)
        # The reassurance that matters: closing a shop does not put its names back on the market.
        self.assertIn("usernames stay reserved to you", self.ui)

    def test_the_store_address_promise_is_now_kept_by_a_redirect(self):
        # It was previously kept by a page frozen on the day of the rename.
        self.assertIn("stays reserved to you and redirects here", self.ui)


class RetiredHostnameTests(unittest.TestCase):
    """A store address is an ADDRESS, not an identity -- so these REDIRECT where handles 404."""

    def _moved(self):
        existing, document = _site(), _site()
        document["hosting"]["platform_hostname"] = "clothes.jbay.uk"
        record_hosting_history(existing, document)
        return document

    def test_the_old_address_redirects_to_the_new_one(self):
        row = _by_domain(self._moved())["toys.jbay.uk"]
        self.assertEqual(row["redirect_to"], "clothes.jbay.uk")

    def test_which_is_what_the_ui_already_promised(self):
        """Before this, the old record was simply left behind -- still active, still carrying the route table
        as it was on the day of the rename. "Existing links keep working" was met by a frozen page."""
        row = _by_domain(self._moved())["toys.jbay.uk"]
        self.assertEqual(row["routes"], {})
        self.assertEqual(row["target_page_id"], "")

    def test_an_archived_site_does_not_redirect_either(self):
        site = self._moved()
        site["status"] = "archived"
        self.assertEqual(_by_domain(site)["toys.jbay.uk"]["status"], "archived")


class HistoryIsServerOwnedTests(unittest.TestCase):
    def test_a_new_site_cannot_seed_its_own_history(self):
        """These fields decide what the edge does with an address, so a client free to write them could name
        someone else's hostname and point it at itself."""
        document = {"hosting": {"platform_hostname": "mine.jbay.uk",
                                "retired_hostnames": ["victim.jbay.uk"], "retired_usernames": ["victim"]}}
        record_hosting_history(None, document)
        self.assertNotIn("retired_hostnames", document["hosting"])
        self.assertNotIn("retired_usernames", document["hosting"])

    def test_an_edit_cannot_inject_one_either(self):
        existing = _site()
        document = _site()
        document["hosting"]["retired_hostnames"] = ["victim.jbay.uk"]
        document["hosting"]["retired_usernames"] = ["victim"]
        record_hosting_history(existing, document)
        for field in ("retired_hostnames", "retired_usernames"):
            self.assertNotIn("victim", str(document["hosting"].get(field) or []), field)


class OneBuilderTests(unittest.TestCase):
    def test_both_writers_use_the_same_record_list(self):
        """Two callers used to assemble this separately, so a rule added to one would not exist in the other."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        for path in ("src/handlers/sites.py", "src/stripe_link/runtime/publishing.py"):
            source = (root / path).read_text(encoding="utf-8")
            self.assertIn("site_index_records(", source, path)
            self.assertNotIn("repo.put(platform_domain_index_record", source, path)


if __name__ == "__main__":
    unittest.main()
