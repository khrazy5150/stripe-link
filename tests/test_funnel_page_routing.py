"""One reserved `/upsell` slug serves every page's funnel — no homepage required.

The author, 2026-10-02: *"'/' is reserved for the homepage, which applies only to website-like behavior.
Landing pages don't need a homepage. The funnel steps worked before without one, so why do we need to
create one now?"* They do not.

`attach_funnel_slugs` let only the page at "/" own the reserved funnel slugs, so a Site could run a
post-purchase funnel on exactly one landing page -- and a Site with no homepage on none at all.
Meanwhile `post_checkout` has sent `funnel_page` on every funnel redirect since it was written and
`custom_domains_resolve` never read it.
"""
import unittest

from handlers.custom_domains_resolve import _resolve_slug, _site_page_ids
from stripe_link.runtime.publishing import attach_funnel_slugs

ROUTES = {
    "/": {"page_id": "page_home", "enabled": True},
    "/bundle": {"page_id": "page_bundle", "enabled": True},
    "/gummies": {"page_id": "page_gummies", "enabled": True},
    "/upsell": {"page_id": "page_home", "funnel_role": "upsell", "strategy": "sequence",
                "enabled": True},
    "/thank-you": {"page_id": "page_home", "funnel_role": "thank_you", "strategy": "sequence",
                   "enabled": True},
}


def resolve(slug, step="", funnel_page=""):
    target, _ = _resolve_slug(slug, ROUTES, "page_home", step, funnel_page)
    return (target or {}).get("page_id")


class TheSlugServesWhicheverFunnelIsAskedForTests(unittest.TestCase):
    def test_without_funnel_page_it_serves_the_slugs_own_default(self):
        # Exactly what it did before, so a Site that worked is unchanged.
        self.assertEqual(resolve("/upsell", "1"), "page_home__upsell_1")

    def test_funnel_page_selects_another_pages_funnel(self):
        self.assertEqual(resolve("/upsell", "1", "page_bundle"), "page_bundle__upsell_1")

    def test_the_step_still_picks_which_upsell(self):
        # Upsells were never limited to one; funnel_step walks the sequence.
        self.assertEqual(resolve("/upsell", "2", "page_bundle"), "page_bundle__upsell_2")
        self.assertEqual(resolve("/upsell", "3", "page_bundle"), "page_bundle__upsell_3")

    def test_thank_you_follows_the_same_page(self):
        self.assertEqual(resolve("/thank-you", "", "page_bundle"), "page_bundle__thank_you")


class ItCannotBeUsedToServeSomeoneElsesArtifactTests(unittest.TestCase):
    """`funnel_page` arrives in a query string a buyer can edit."""

    def test_a_page_this_site_does_not_route_is_ignored(self):
        self.assertEqual(resolve("/upsell", "1", "page_someone_else"), "page_home__upsell_1")

    def test_the_allow_list_is_the_sites_own_routes(self):
        self.assertEqual(_site_page_ids(ROUTES), {"page_home", "page_bundle", "page_gummies"})

    def test_a_disabled_route_does_not_count(self):
        routes = {**ROUTES, "/gummies": {"page_id": "page_gummies", "enabled": False}}
        self.assertNotIn("page_gummies", _site_page_ids(routes))

    def test_empty_or_junk_is_ignored(self):
        for junk in ("", "   ", "../../etc", None):
            with self.subTest(junk=junk):
                self.assertEqual(resolve("/upsell", "1", junk), "page_home__upsell_1")


def site(pages):
    return {"hosting": {"platform_hostname": "shop.jbay.be"}, "pages": dict(pages)}


OFFER = {"offer_id": "o1"}


class AnyPageWithAFunnelCanClaimTheSlugTests(unittest.TestCase):
    def _plan(self, monkey):
        import stripe_link.runtime.publishing as pub

        real = pub.post_purchase_plan
        pub.post_purchase_plan = monkey
        return real, pub

    def setUp(self):
        self.real, self.pub = self._plan(
            lambda offer, products: {"upsells": [{"product_id": "p1"}], "strategy": "sequence"})

    def tearDown(self):
        self.pub.post_purchase_plan = self.real

    def test_a_page_that_is_NOT_the_homepage_can_own_the_funnel(self):
        # The whole point: a Site with no homepage at all still runs a funnel.
        out, changed = attach_funnel_slugs(
            site({"/bundle": {"page_id": "page_bundle"}}), {"page_id": "page_bundle"}, OFFER, {})
        self.assertTrue(changed)
        self.assertEqual(out["pages"]["/upsell"]["page_id"], "page_bundle")

    def test_the_root_page_keeps_the_default_when_there_is_one(self):
        pages = {"/": {"page_id": "page_home"}, "/bundle": {"page_id": "page_bundle"}}
        rooted, _ = attach_funnel_slugs(site(pages), {"page_id": "page_home"}, OFFER, {})
        # A second page publishing must not steal the default...
        after, _ = attach_funnel_slugs(rooted, {"page_id": "page_bundle"}, OFFER, {})
        self.assertEqual(after["pages"]["/upsell"]["page_id"], "page_home")

    def test_a_second_page_never_RETIRES_the_first_pages_slug(self):
        # Only the root reached this code before, so the entry found was always its own. Now that any page
        # can claim one, an unrelated republish would otherwise delete a working funnel.
        pages = {"/": {"page_id": "page_home"}, "/bundle": {"page_id": "page_bundle"}}
        rooted, _ = attach_funnel_slugs(site(pages), {"page_id": "page_home"}, OFFER, {})
        self.pub.post_purchase_plan = lambda offer, products: {"upsells": [], "strategy": "sequence"}
        after, _ = attach_funnel_slugs(rooted, {"page_id": "page_bundle"}, OFFER, {})
        self.assertIn("/upsell", after["pages"])
        self.assertEqual(after["pages"]["/upsell"]["page_id"], "page_home")

    def test_a_page_still_retires_ITS_OWN_slug_when_the_funnel_goes(self):
        out, _ = attach_funnel_slugs(
            site({"/bundle": {"page_id": "page_bundle"}}), {"page_id": "page_bundle"}, OFFER, {})
        self.pub.post_purchase_plan = lambda offer, products: {"upsells": [], "strategy": "sequence"}
        gone, changed = attach_funnel_slugs(out, {"page_id": "page_bundle"}, OFFER, {})
        self.assertTrue(changed)
        self.assertNotIn("/upsell", gone["pages"])


class TheEdgeMustForwardThemTests(unittest.TestCase):
    """The resolver can only honour what reaches it.

    `_resolve_slug` has read `funnel_step` since reserved slugs shipped, and the Worker sent only
    `host` and `path` -- so a sequence past step 1 could not resolve at the edge at all. `funnel_page` was
    about to have the identical journey.
    """

    import pathlib as _pathlib

    WORKER = (_pathlib.Path(__file__).resolve().parents[1]
              / "deploy/cloudflare-custom-domain-worker.js").read_text(encoding="utf-8")

    def test_both_funnel_params_are_forwarded(self):
        self.assertIn("funnel_step=${encodeURIComponent(funnelStep)}", self.WORKER)
        self.assertIn("funnel_page=${encodeURIComponent(funnelPage)}", self.WORKER)

    def test_they_are_part_of_the_CACHE_KEY(self):
        # Caching /upsell by host+path alone pins the first buyer's step and serves it to everyone after:
        # upsell 2 answering with upsell 1, or one page's funnel answering for another's.
        self.assertIn("`${hostname}${path}${funnelQuery}`", self.WORKER)

    def test_a_plain_page_still_caches_by_host_and_path(self):
        # funnelQuery is empty without them, so ordinary pages keep exactly the key they had.
        self.assertIn('const funnelQuery = (funnelStep ?', self.WORKER)


class RepublishingIsIdempotentTests(unittest.TestCase):
    """Republishing a page must not destroy its own funnel.

    The first version of the non-root filter skipped every slug that was already occupied -- including the
    ones this very page owned. A second publish dropped them from `desired`, the retire loop saw them as
    unwanted, and deleted them. The author republished the Workout Bundle and `/thank-you` started 404ing
    (2026-10-02).
    """

    def setUp(self):
        import stripe_link.runtime.publishing as pub

        self.pub = pub
        self.real = pub.post_purchase_plan
        pub.post_purchase_plan = lambda offer, products: {"upsells": [{"product_id": "p1"}],
                                                          "strategy": "sequence"}

    def tearDown(self):
        self.pub.post_purchase_plan = self.real

    def _publish(self, state, page_id="page_b"):
        out, _ = self.pub.attach_funnel_slugs(state, {"page_id": page_id}, OFFER, {})
        return out

    def test_publishing_three_times_keeps_the_funnel(self):
        state = site({"/bundle": {"page_id": "page_b"}})
        for _ in range(3):
            state = self._publish(state)
        self.assertEqual(state["pages"]["/upsell"]["page_id"], "page_b")
        self.assertEqual(state["pages"]["/thank-you"]["page_id"], "page_b")

    def test_the_second_publish_changes_nothing(self):
        state = self._publish(site({"/bundle": {"page_id": "page_b"}}))
        _, changed = self.pub.attach_funnel_slugs(state, {"page_id": "page_b"}, OFFER, {})
        self.assertFalse(changed, "a no-op republish must not rewrite the Site")

    def test_a_tenants_OWN_thank_you_page_is_never_overwritten(self):
        # It has no funnel_role; it is a real page the tenant attached themselves.
        state = site({"/bundle": {"page_id": "page_b"},
                      "/thank-you": {"page_id": "page_mine", "page_type": "thank_you"}})
        out = self._publish(state)
        self.assertEqual(out["pages"]["/thank-you"]["page_id"], "page_mine")

    def test_another_funnel_pages_slug_is_never_taken(self):
        state = site({"/bundle": {"page_id": "page_b"}, "/other": {"page_id": "page_o"}})
        state = self._publish(state, "page_b")
        state = self._publish(state, "page_o")
        self.assertEqual(state["pages"]["/upsell"]["page_id"], "page_b")

    def test_a_page_still_retires_its_own_funnel_when_the_offer_loses_its_upsells(self):
        state = self._publish(site({"/bundle": {"page_id": "page_b"}}))
        self.pub.post_purchase_plan = lambda offer, products: {"upsells": [], "strategy": "sequence"}
        gone, changed = self.pub.attach_funnel_slugs(gone_state := state, {"page_id": "page_b"}, OFFER, {})
        self.assertTrue(changed)
        self.assertNotIn("/upsell", gone["pages"])


class APagesPublicUrlIsItsOwnSlugTests(unittest.TestCase):
    """A reserved funnel slug carries the base sales page's id, because that is what its synthetic
    artifact derives from -- not because the page lives there.

    `site_page_slug` returned whichever route matched FIRST, so once a page owned funnel slugs as well as
    its own, the Landing Pages card advertised its public URL as `…/thank-you` while the card's own Slug
    field said `/dietary-supplement-bundle` (author, 2026-10-02).
    """

    from stripe_link.runtime.publishing import site_page_slug as _slug

    SITE = {"pages": {
        "/thank-you": {"page_id": "page_b", "funnel_role": "thank_you"},
        "/upsell": {"page_id": "page_b", "funnel_role": "upsell"},
        "/dietary-supplement-bundle": {"page_id": "page_b"},
    }}

    def test_the_pages_own_slug_wins_over_its_funnel_routes(self):
        self.assertEqual(self._slug(self.SITE, "page_b"), "/dietary-supplement-bundle")

    def test_order_in_the_map_does_not_decide_it(self):
        reordered = {"pages": dict(reversed(list(self.SITE["pages"].items())))}
        self.assertEqual(self._slug(reordered, "page_b"), "/dietary-supplement-bundle")

    def test_a_homepage_that_owns_funnel_slugs_is_still_the_root(self):
        # `attach_funnel_slugs` asks whether this slug is "/" -- a root page owning `/thank-you` could
        # answer "/thank-you" and stop being treated as the root.
        root = {"pages": {"/thank-you": {"page_id": "page_h", "funnel_role": "thank_you"},
                          "/": {"page_id": "page_h"}}}
        self.assertEqual(self._slug(root, "page_h"), "/")

    def test_a_page_attached_ONLY_as_a_funnel_route_has_no_address(self):
        # It is not served at an address of its own, so there is no public URL to advertise.
        only = {"pages": {"/upsell": {"page_id": "page_x", "funnel_role": "upsell"}}}
        self.assertEqual(self._slug(only, "page_x"), "")

    def test_an_unattached_page_still_has_none(self):
        self.assertEqual(self._slug(self.SITE, "page_missing"), "")
