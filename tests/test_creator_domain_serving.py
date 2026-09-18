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
import pathlib
import unittest
from unittest import mock

from handlers import custom_domains_resolve
from stripe_link.domain.custom_domains import (
    creator_domain_index_record, creator_host_key, creator_page_entry, creator_page_url,
    creator_username)

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


class PublicUrlTests(unittest.TestCase):
    """Resolution was only half of it.

    Reported 2026-09-17: "publishing a social page goes here: poliaxis-nutrition.jbay.uk/link-bio NOT to
    jbay.page". Correct at the time -- serving was off and the domain unbought -- but it exposed that the
    index record makes the creator URL RESOLVE while nothing made it the page's identity or showed it to the
    tenant. A URL that works and that nobody is told about is not shipped.
    """

    def test_the_hub_url_is_the_username_not_the_slug(self):
        # jbay.page/maria IS the page. jbay.page/maria/link-bio would be a slug nobody typed.
        self.assertEqual(creator_page_url(_site(), "page_hub", DOMAIN), "https://jbay.page/maria")

    def test_only_the_hub_gets_one(self):
        for other in ("page_home", "page_buy", ""):
            self.assertEqual(creator_page_url(_site(), other, DOMAIN), "", other)

    def test_an_unconfigured_environment_offers_no_url(self):
        self.assertEqual(creator_page_url(_site(), "page_hub", ""), "")

    def test_the_artifact_takes_it_as_canonical_and_home(self):
        """Which of the two addresses is the real one -- the hub stays reachable on the Site's host too."""
        import inspect

        from stripe_link.runtime import publishing

        source = inspect.getsource(publishing)
        block = source.split("creator_url = creator_page_url(", 1)[1].split("eligibility =", 1)[0]
        self.assertIn("page_canonical = creator_url", block)
        self.assertIn("page_home_url = creator_url", block)

    def test_the_dashboard_is_told_the_apex_rather_than_hardcoding_it(self):
        """It differs per environment and is off until configured, so a hardcoded default would show a URL
        that does not resolve."""
        root = pathlib.Path(__file__).resolve().parents[1]
        handler = (root / "src" / "handlers" / "sites.py").read_text(encoding="utf-8")
        self.assertIn('"creator_domain": creator_hosting_domain() if creator_serving_enabled() else ""', handler)
        store = (root / "dashboard" / "src" / "stores" / "sites.js").read_text(encoding="utf-8")
        self.assertIn('creatorDomain: ""', store)
        builder = (root / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertIn('entry?.composition === "lead_social" && sitesStore.creatorDomain', builder)


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

    def test_an_unconfigured_environment_serves_nothing(self):
        """No built-in default, deliberately.

        A hardcoded `jbay.page` fallback would have made a dev stack with an unset variable write records for
        TEST pages on the apex prod serves live ones from. Empty is what an unconfigured environment gets.
        """
        from stripe_link.runtime.publishing import creator_hosting_domain

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(creator_hosting_domain(), "")
        self.assertIsNone(creator_domain_index_record(_site(), ""))

    def test_the_two_environments_use_different_apexes(self):
        """The same live/test split the platform host makes with jbay.uk vs jbay.be.

        Asserted on the deploy script, because that is where the value is actually decided -- a constant in
        Python would be a second copy of a fact CloudFormation owns.
        """
        deploy = (pathlib.Path(__file__).resolve().parents[1] / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn("CreatorHostingDomain=jbay.page", deploy)
        self.assertIn("CreatorHostingDomain=test.jbay.page", deploy)
        # ...and the creator apex is never the platform one: separate domains IS the reputation argument.
        self.assertNotIn("CreatorHostingDomain=jbay.uk", deploy)

    def test_an_ordinary_deploy_cannot_silently_switch_it_off(self):
        # Same preserve-on-silence rule platform serving already has: re-reads the stack when unexported.
        deploy = (pathlib.Path(__file__).resolve().parents[1] / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        block = deploy.split("CREATOR_SERVING_ENABLED:-", 1)[1].split("PARAMETER_OVERRIDES+=", 1)[0]
        self.assertIn("describe-stacks", block)

    def test_the_worker_apex_guard_is_templated_per_environment(self):
        """A dev worker must not treat the prod apex as its own front door."""
        root = pathlib.Path(__file__).resolve().parents[1]
        worker = (root / "deploy" / "cloudflare-custom-domain-worker.js").read_text(encoding="utf-8")
        setup = (root / "deploy" / "setup-cloudflare-custom-domain-worker.sh").read_text(encoding="utf-8")
        self.assertIn("REPLACE_WITH_CREATOR_HOST", worker)
        self.assertIn("REPLACE_WITH_CREATOR_HOST", setup)
        self.assertNotIn('CREATOR_HOST = "jbay.page"', worker)


if __name__ == "__main__":
    unittest.main()
