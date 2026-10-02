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
        "/thank-you": {"page_id": "page_ty", "page_type": "thank_you", "funnel_role": "thank_you",
                       "enabled": True},
    },
}
WITH_UPSELL = {**SITE, "pages": {**SITE["pages"],
                                 "/upsell": {"page_id": "page_src", "funnel_role": "upsell",
                                             "enabled": True}}}


def url(site, next_page_id, source="page_src"):
    return _next_page_url(site, "t1", next_page_id, "pages.example.com",
                          origin_host="https://shop.jbay.be", mode="test", source_page_id=source)


class WhenTheFunnelIsRoutedTests(unittest.TestCase):
    def test_an_attached_upsell_slug_wins(self):
        self.assertEqual(url(WITH_UPSELL, "page_src__upsell_1"), "https://shop.jbay.be/upsell")

    def test_a_real_page_goes_to_its_own_slug(self):
        self.assertEqual(url(SITE, "page_ty"), "https://shop.jbay.be/thank-you")


class WhenItIsNotRoutedTests(unittest.TestCase):
    def test_the_buyer_goes_back_to_the_page_they_BOUGHT_FROM(self):
        # Published and routed by definition -- checkout refuses an unpublished page -- so unlike the root
        # it is guaranteed to exist. The upsell is lost either way; a 404 loses the buyer's trust as well.
        self.assertEqual(url(SITE, "page_src__upsell_1"),
                         "https://shop.jbay.be/dietary-supplement-bundle")

    def test_it_no_longer_assumes_a_root_page_exists(self):
        # The old answer, and the bug: this Site has nothing at "/".
        self.assertNotEqual(url(SITE, "page_src__upsell_1"), "https://shop.jbay.be")

    def test_a_site_WITH_a_root_page_still_works(self):
        rooted = {**SITE, "pages": {**SITE["pages"], "/": {"page_id": "page_home", "enabled": True}}}
        self.assertEqual(url(rooted, "page_home"), "https://shop.jbay.be/")

    def test_an_unknown_source_falls_back_to_the_root_as_before(self):
        # Nothing better to offer; the previous behaviour is still the last resort rather than an error.
        self.assertEqual(url(SITE, "page_src__upsell_1", source="page_gone"), "https://shop.jbay.be")

    def test_no_source_at_all_falls_back_to_the_root(self):
        self.assertEqual(url(SITE, "page_src__upsell_1", source=""), "https://shop.jbay.be")


class TheDesignLimitIsRealTests(unittest.TestCase):
    def test_only_the_root_page_can_own_the_funnel_slugs(self):
        # Recorded as a test because it is WHY the fallback runs so often, and because the limitation is
        # easy to mistake for a bug when a tenant's funnel silently never attaches.
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src/stripe_link/runtime/publishing.py").read_text(encoding="utf-8")
        self.assertIn('if str(site_page_slug(site, page_id)) != "/":', source)
