"""Link-in-bio serving on a shared apex: `jbay.page/{username}`.

Author, 2026-09-17, asking the right question first: "does this require a new dedicated site to be created so
that jbay.page can run on them? I have the bad feeling that it will, which will duplicate existing
infrastructure."

It does not, and this file is the proof. A Site already emits one domain-index record per surface it is
reachable on -- the custom domain and the free platform host. The creator apex is a THIRD record off the SAME
Site. Everything downstream (artifact keys, the proxy, mode partitioning, the noindex stamp) is untouched.

The one real difference is WHERE the tenant is named. A custom domain and a platform subdomain identify a
tenant by hostname; on a shared apex the hostname identifies nobody, so the first path segment does.
"""
import os
import unittest
from unittest import mock

from handlers import custom_domains_resolve
from stripe_link.domain.custom_domains import (
    creator_domain_index_record, creator_host_key, creator_page_entry, creator_username)

DOMAIN = "jbay.page"


def _site(**over):
    site = {
        "tenant_id": "t1", "site_id": "site_1", "environment": "live",
        "hosting": {"type": "platform", "platform_hostname": "maria.jbay.uk"},
        "pages": {
            "/": {"page_id": "page_home", "page_type": "landing"},
            "/links": {"page_id": "page_hub", "page_type": "landing", "composition": "lead_social"},
            "/buy": {"page_id": "page_buy", "page_type": "landing", "composition": "single"},
        },
    }
    site.update(over)
    return site


class RecordTests(unittest.TestCase):
    def test_the_username_is_the_platform_label(self):
        """One namespace platform-wide, rather than a second one to keep in step with the first.

        It also inherits the syntax rule, the first-claim-wins registry and RESERVED_SUBDOMAINS -- which
        already holds `about`, `login`, `api`, `admin`, i.e. the path wordlist the plan says must exist
        before the first username is claimed.
        """
        self.assertEqual(creator_username(_site()), "maria")
        self.assertEqual(creator_host_key(DOMAIN, "Maria"), "jbay.page/maria")

    def test_it_is_a_third_record_off_the_same_site(self):
        record = creator_domain_index_record(_site(), DOMAIN)
        self.assertEqual(record["domain"], "jbay.page/maria")
        self.assertEqual(record["target_page_id"], "page_hub")
        self.assertEqual(record["site_id"], "site_1")
        self.assertEqual(record["tenant_id"], "t1")

    def test_it_serves_the_link_hub_and_NOTHING_else(self):
        """The empty route table is the reputation isolation, not an oversight.

        The Site's own table would expose its checkout and funnel pages at jbay.page/maria/..., putting
        commerce on the one domain whose whole premise is that it carries no payment.
        """
        record = creator_domain_index_record(_site(), DOMAIN)
        self.assertEqual(record["routes"], {})
        self.assertNotIn("page_buy", str(record))
        self.assertNotIn("page_home", str(record))

    def test_which_hub_is_deterministic(self):
        # Two hubs on one Site must not swap places between publishes.
        site = _site()
        site["pages"]["/a-hub"] = {"page_id": "page_a", "composition": "lead_social"}
        self.assertEqual(creator_page_entry(site)[1]["page_id"], "page_a")

    def test_no_hub_no_record(self):
        site = _site()
        site["pages"].pop("/links")
        self.assertIsNone(creator_domain_index_record(site, DOMAIN))

    def test_no_username_no_record(self):
        self.assertIsNone(creator_domain_index_record(_site(hosting={"type": "custom"}), DOMAIN))


class ResolverTests(unittest.TestCase):
    """The lookup key is host + first path segment; everything after it is the ordinary slug."""

    def _lookup(self, host, path, domain=DOMAIN):
        with mock.patch.dict(os.environ, {"CREATOR_HOSTING_DOMAIN": domain}):
            return custom_domains_resolve._creator_lookup(host, path)

    def test_the_username_is_eaten_from_the_path(self):
        self.assertEqual(self._lookup("jbay.page", "/maria"), ("jbay.page/maria", "/"))

    def test_a_deeper_path_stays_the_slug(self):
        # So jbay.page/maria is that hub's root exactly as maria.jbay.uk/ is.
        self.assertEqual(self._lookup("jbay.page", "/maria/press"), ("jbay.page/maria", "/press"))

    def test_the_bare_apex_belongs_to_the_platform(self):
        # Not to whoever claims it first.
        self.assertEqual(self._lookup("jbay.page", "/"), ("", "/"))
        self.assertEqual(self._lookup("jbay.page", ""), ("", ""))

    def test_every_other_host_is_untouched(self):
        self.assertEqual(self._lookup("shop.example.com", "/buy"), ("", "/buy"))
        self.assertEqual(self._lookup("maria.jbay.uk", "/links"), ("", "/links"))

    def test_it_is_inert_until_the_domain_is_configured(self):
        # An unset CREATOR_HOSTING_DOMAIN must not turn some other host into a creator apex.
        self.assertEqual(self._lookup("jbay.page", "/maria", domain=""), ("", "/maria"))


class NoIndexTests(unittest.TestCase):
    def test_a_creator_page_is_noindex_stamped_at_the_edge(self):
        """A shared UGC apex must never couple one creator's reputation to another's.

        Belt and braces with the artifact itself: page_robots_directive already refuses to emit index,follow
        anywhere but a verified custom domain, so the bytes say noindex too.
        """
        import inspect

        source = inspect.getsource(custom_domains_resolve.handler)
        self.assertIn('host_kind") in ("platform", "creator")', source)


class VisitorIdTests(unittest.TestCase):
    """localStorage is per-ORIGIN, and a shared apex is one origin for every creator."""

    def test_the_visitor_id_is_namespaced_per_tenant(self):
        from stripe_link.runtime import html as html_module

        beacon = html_module.render_view_beacon(
            {"page_id": "p1", "tenant_id": "t_abc"}, "published", "https://api.example")
        self.assertIn("sl_vid_", beacon)
        self.assertIn("t_abc", beacon)
        # A bare key would hand jbay.page/alice and jbay.page/bob the SAME visitor id -- a deliberately
        # first-party token turned cross-tenant by the move to a shared origin.
        self.assertNotIn("'sl_vid'", beacon)


class SwitchTests(unittest.TestCase):
    def test_serving_is_off_until_deliberately_turned_on(self):
        from stripe_link.runtime.publishing import creator_serving_enabled

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(creator_serving_enabled())
        with mock.patch.dict(os.environ, {"CREATOR_SERVING_ENABLED": "true"}):
            self.assertTrue(creator_serving_enabled())

    def test_the_creator_domain_is_not_the_platform_domain(self):
        """Separate domains is the entire reputation argument; a shared default would quietly undo it."""
        from stripe_link.runtime.publishing import DEFAULT_CREATOR_DOMAIN
        from handlers.sites import DEFAULT_HOSTING_DOMAIN

        self.assertNotEqual(DEFAULT_CREATOR_DOMAIN, DEFAULT_HOSTING_DOMAIN)


if __name__ == "__main__":
    unittest.main()
