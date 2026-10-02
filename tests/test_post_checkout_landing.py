"""A buyer who has just paid must never land on a 404.

Found by the author 2026-10-02: a cart checkout completed, the funnel redirect fired, and the buyer got the
404 page. The fallback that exists to prevent exactly this sent them to the Site ROOT, described in its own
comment as "a host we govern, which always works" -- and that Site has no page attached at "/", so the root
404s.

It is not a rare edge either. `publishing.attach_funnel_slugs` only lets the page at the Site's "/" own
`/upsell`, so every funnel on a Site whose landing pages live at real slugs falls through to this branch.
"""
import os
import unittest

from handlers.post_checkout import _next_page_url


def setUpModule():
    # The platform host only counts as a legitimate redirect target when platform serving is on, which is
    # how it is deployed. Without it `_redirect_base` is empty and every case here falls to the artifact URL.
    os.environ["PLATFORM_SERVING_ENABLED"] = "true"


def tearDownModule():
    os.environ.pop("PLATFORM_SERVING_ENABLED", None)

SITE = {
    "hosting": {"platform_hostname": "shop.jbay.be", "type": "platform"},
    "pages": {
        "/dietary-supplement-bundle": {"page_id": "page_src", "page_type": "landing", "enabled": True},
        # A page the TENANT attached, at its own address. A funnel-derived `/thank-you` carries the base
        # sales page's id and a `funnel_role`; this is the other kind, and it has no role.
        "/thank-you": {"page_id": "page_ty", "page_type": "thank_you", "enabled": True},
    },
}
WITH_UPSELL = {**SITE, "pages": {**SITE["pages"],
                                 "/upsell": {"page_id": "page_src", "funnel_role": "upsell",
                                             "enabled": True}}}


def url(site, next_page_id):
    return _next_page_url(site, "t1", next_page_id, "pages.example.com",
                          origin_host="https://shop.jbay.be", mode="test")


class WhenTheFunnelIsRoutedTests(unittest.TestCase):
    def test_an_attached_upsell_slug_wins(self):
        # Best case: the funnel stays on the tenant's own host.
        self.assertEqual(url(WITH_UPSELL, "page_src__upsell_1"), "https://shop.jbay.be/upsell")

    def test_a_real_page_goes_to_its_own_slug(self):
        self.assertEqual(url(SITE, "page_ty"), "https://shop.jbay.be/thank-you")


class WhenTheFunnelHasNoSiteRouteTests(unittest.TestCase):
    """A landing page does not need a homepage, and funnels never used to want one.

    They ran off the ARTIFACT url -- no Site, no slug, no homepage -- and that url still serves. What
    broke them was `PLATFORM_SERVING_ENABLED`: once the platform host counted as a redirect target,
    `_redirect_base` stopped being empty, the slug branch started running, and the artifact fallback
    became unreachable for every page not at "/".
    """

    def test_the_funnel_still_runs_from_its_artifact(self):
        self.assertIn("page_src__upsell_1", url(SITE, "page_src__upsell_1"))

    def test_it_does_not_dump_the_buyer_on_the_site_root(self):
        # The root 404s on a Site with nothing attached at "/", which is how the author found this.
        self.assertNotEqual(url(SITE, "page_src__upsell_1"), "https://shop.jbay.be")

    def test_it_does_not_silently_throw_the_upsell_away(self):
        # An earlier fix sent the buyer back to the page they bought from. That stops the 404 and loses
        # the upsell, when the upsell was sitting there serving.
        self.assertNotIn("/dietary-supplement-bundle", url(SITE, "page_src__upsell_1"))

    def test_a_NON_funnel_orphan_still_goes_to_the_root(self):
        # The case the root fallback was written for, and it keeps it: a page with no route has nowhere
        # better to go. A funnel artifact is different -- it exists, it serves, and the buyer is mid-flow
        # towards it.
        rooted = {**SITE, "pages": {**SITE["pages"], "/": {"page_id": "page_home", "enabled": True}}}
        self.assertEqual(url(rooted, "page_orphan"), "https://shop.jbay.be")

    def test_a_site_with_a_root_page_still_routes_normally(self):
        rooted = {**SITE, "pages": {**SITE["pages"], "/": {"page_id": "page_home", "enabled": True}}}
        self.assertEqual(url(rooted, "page_home"), "https://shop.jbay.be/")


class TheDesignLimitIsRealTests(unittest.TestCase):
    def test_only_the_root_page_can_own_the_funnel_slugs(self):
        # Recorded as a test because it is WHY the fallback runs so often, and because the limitation is
        # easy to mistake for a bug when a tenant's funnel silently never attaches.
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src/stripe_link/runtime/publishing.py").read_text(encoding="utf-8")
        self.assertIn('if str(site_page_slug(site, page_id)) != "/":', source)
