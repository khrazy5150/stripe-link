"""The sitemap covers the whole Site, not just its homepage (plans/OFFERLESS_PAGES_IN_BUILDER.md P5).

`publish_site_crawl_files` wrote a sitemap holding exactly ONE url for as long as a Site could only serve
one page. By the time P1-P4 had made storefront, category and store-profile pages indexable, a tenant with
a storefront, three category pages, an about page and a dozen product pages was advertising one of them and
leaving the other sixteen to be found by a crawler following links.

Nothing covered this function before, which is also why nothing failed when it changed. Two bugs it had
been carrying are pinned here:

* The files were written under the page CURRENTLY PUBLISHING, while custom_domains_resolve serves
  /sitemap.xml from the Site's ROOT page. Publishing anything but the homepage wrote all three files to a
  prefix nothing reads.
* IndexNow was always pinged with the root, so publishing a product page told the crawler to re-fetch the
  one URL that had not changed.
"""

import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_site
from stripe_link.runtime.publishing import (
    _denormalize_page_crawl,
    publish_site_crawl_files,
    site_sitemap_entries,
)

DOMAIN = "probestore.com"


def _site(pages, **overrides):
    site = {
        "schema_version": "2026-05-29", "document_type": "site", "tenant_id": "tenant_demo",
        "site_id": "site_1", "name": "Probe Store", "status": "active", "stripe_mode": "live",
        "hosting": {"type": "custom", "platform_hostname": "probe.jbay.uk",
                    "custom_domain": DOMAIN, "verification": {"verified": True}},
        "indexing": {"eligibility": "eligible"},
        "organization": {"name": "Probe Store"},
        "pages": pages, "revision": 1, "created_at": 1, "updated_at": 2,
    }
    site.update(overrides)
    return site


def _entry(page_id, *, page_type="landing", enabled=True, indexable=True, lastmod=1700000000, **extra):
    entry = {"page_id": page_id, "page_type": page_type, "enabled": enabled, "lastmod": lastmod}
    if indexable is not None:
        entry["indexable"] = indexable
    entry.update(extra)
    return entry


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, CacheControl):  # noqa: N803 - boto3 casing
        self.objects[Key] = Body.decode("utf-8")


class SitemapEntryTests(unittest.TestCase):
    def test_every_indexable_page_is_listed_homepage_first(self):
        site = _site({
            "/": _entry("page_home", page_type="homepage"),
            "/about": _entry("page_about", page_type="about"),
            "/widgets": _entry("page_widgets", page_type="category"),
            "/gummies": _entry("page_gummies"),
        })
        locs = [item["loc"] for item in site_sitemap_entries(site, DOMAIN)]
        self.assertEqual(locs, [
            f"https://{DOMAIN}/",
            f"https://{DOMAIN}/about",
            f"https://{DOMAIN}/gummies",
            f"https://{DOMAIN}/widgets",
        ])

    def test_a_page_is_listed_once_at_its_own_address(self):
        """A page owns its own slug plus the /sale and /flash-sale context views and the reserved funnel
        steps. The context views are the same page at a different price -- listing both would be submitting
        our own duplicate content -- and the funnel artifacts are noindex by page_type anyway."""
        site = _site({
            "/": _entry("page_home", page_type="homepage"),
            "/gummies": _entry("page_gummies"),
            "/gummies/sale": _entry("page_gummies", price_context="sale"),
            "/gummies/flash-sale": _entry("page_gummies", price_context="flash_sale"),
            "/upsell": _entry("page_gummies", funnel_role="upsell", strategy="sequence"),
            "/thank-you": _entry("page_gummies", funnel_role="thank_you"),
        })
        locs = [item["loc"] for item in site_sitemap_entries(site, DOMAIN)]
        self.assertEqual(locs, [f"https://{DOMAIN}/", f"https://{DOMAIN}/gummies"])

    def test_a_page_we_cannot_vouch_for_is_left_out(self):
        """`indexable` absent means the page has not published since the flag existed. Advertising a URL
        that might publish `noindex` is the contradiction the flag exists to prevent."""
        site = _site({
            "/": _entry("page_home", page_type="homepage"),
            "/never-published": _entry("page_unknown", indexable=None),
            "/demoted": _entry("page_thin", indexable=False),
            "/draft": _entry("page_draft", enabled=False),
        })
        self.assertEqual([item["loc"] for item in site_sitemap_entries(site, DOMAIN)],
                         [f"https://{DOMAIN}/"])

    def test_lastmod_and_images_travel_with_each_page(self):
        site = _site({
            "/": _entry("page_home", page_type="homepage", lastmod=1700000001,
                        images=["https://images.example.com/a.jpg", "https://images.example.com/b.jpg"]),
        })
        item = site_sitemap_entries(site, DOMAIN)[0]
        self.assertEqual(item["lastmod"], 1700000001)
        self.assertEqual(len(item["images"]), 2)

    def test_no_site_or_no_domain_yields_nothing(self):
        self.assertEqual(site_sitemap_entries(None, DOMAIN), [])
        self.assertEqual(site_sitemap_entries(_site({"/": _entry("page_home")}), ""), [])


class DenormalizationTests(unittest.TestCase):
    def test_it_records_what_the_sitemap_needs_and_validates(self):
        site = _site({"/": {"page_id": "page_home", "page_type": "homepage", "enabled": True}})
        changed = _denormalize_page_crawl(
            site, "page_home", indexable=True, lastmod=1700000005,
            image_urls=["https://images.example.com/a.jpg"])
        self.assertTrue(changed)
        entry = site["pages"]["/"]
        self.assertIs(entry["indexable"], True)
        self.assertEqual(entry["lastmod"], 1700000005)
        self.assertEqual(entry["images"], ["https://images.example.com/a.jpg"])
        validate_site(site)   # the new fields must be legal on a Site document

    def test_it_is_idempotent(self):
        site = _site({"/": _entry("page_home", page_type="homepage", lastmod=7,
                                  images=["https://images.example.com/a.jpg"])})
        self.assertFalse(_denormalize_page_crawl(
            site, "page_home", indexable=True, lastmod=7,
            image_urls=["https://images.example.com/a.jpg"]))

    def test_losing_every_image_removes_the_key(self):
        """A page whose images were deleted must stop advertising them, so an empty list is a removal
        rather than a skip."""
        site = _site({"/": _entry("page_home", page_type="homepage",
                                  images=["https://images.example.com/a.jpg"])})
        self.assertTrue(_denormalize_page_crawl(site, "page_home", indexable=True, lastmod=7,
                                                image_urls=[]))
        self.assertNotIn("images", site["pages"]["/"])

    def test_it_is_capped(self):
        site = _site({"/": {"page_id": "page_home", "page_type": "homepage", "enabled": True}})
        _denormalize_page_crawl(site, "page_home", indexable=True, lastmod=7,
                                image_urls=[f"https://images.example.com/{i}.jpg" for i in range(12)])
        # The cap protects the SITE DOCUMENT -- the route map is one DynamoDB item.
        self.assertEqual(len(site["pages"]["/"]["images"]), 5)

    def test_a_demoted_page_is_recorded_as_not_indexable(self):
        site = _site({"/thin": _entry("page_thin", indexable=True)})
        self.assertTrue(_denormalize_page_crawl(site, "page_thin", indexable=False, lastmod=9,
                                                image_urls=[]))
        self.assertIs(site["pages"]["/thin"]["indexable"], False)

    def test_an_unknown_page_id_changes_nothing(self):
        site = _site({"/": _entry("page_home", page_type="homepage")})
        self.assertFalse(_denormalize_page_crawl(site, "page_elsewhere", indexable=True, lastmod=9,
                                                 image_urls=[]))


class CrawlFilePublishTests(unittest.TestCase):
    SITE_PAGES = {
        "/": _entry("page_home", page_type="homepage"),
        "/about": _entry("page_about", page_type="about"),
        "/gummies": _entry("page_gummies"),
    }

    def _publish(self, *, publishing_page_id, homepage_page_id="page_home", site=None,
                 indexable=True, pinged=None):
        s3 = FakeS3()
        calls = []

        def opener(request, **kwargs):  # stands in for urlopen, which is called with timeout=
            calls.append(request)
            class _R:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return _R()

        result = publish_site_crawl_files(
            site=site if site is not None else _site(dict(self.SITE_PAGES),
                                                     seo={"indexnow_key": "a" * 32}),
            homepage_page_id=homepage_page_id, custom_domain=DOMAIN,
            page={"page_id": publishing_page_id, "updated_at": 1700000009},
            image_urls=[], s3_client=s3, pages_bucket="pages",
            indexnow_opener=opener, homepage_indexable=indexable,
        )
        return s3, result, calls

    def test_the_sitemap_lists_every_page(self):
        s3, result, _ = self._publish(publishing_page_id="page_home")
        sitemap = s3.objects["page_home/sitemap.xml"]
        for path in ("/", "/about", "/gummies"):
            self.assertIn(f"<loc>https://{DOMAIN}{path}</loc>", sitemap)
        self.assertEqual(sitemap.count("<url>"), 3)
        self.assertEqual(result["urls"], 3)

    def test_the_files_land_under_the_sites_root_page_not_the_publishing_one(self):
        """custom_domains_resolve serves /sitemap.xml from `{target_page_id}/sitemap.xml`, the Site's root
        page. Writing them under whichever page just published put them where nothing reads."""
        s3, _, _ = self._publish(publishing_page_id="page_gummies", homepage_page_id="page_home")
        self.assertIn("page_home/sitemap.xml", s3.objects)
        self.assertIn("page_home/robots.txt", s3.objects)
        self.assertNotIn("page_gummies/sitemap.xml", s3.objects)

    def test_publishing_a_product_page_still_refreshes_the_whole_sitemap(self):
        s3, result, _ = self._publish(publishing_page_id="page_gummies")
        self.assertEqual(result["urls"], 3)
        self.assertIn(f"<loc>https://{DOMAIN}/about</loc>", s3.objects["page_home/sitemap.xml"])

    def test_indexnow_is_pinged_with_the_page_that_changed(self):
        _, result, calls = self._publish(publishing_page_id="page_gummies")
        self.assertEqual(result["indexnow_url"], f"https://{DOMAIN}/gummies")
        self.assertTrue(result["indexnow_submitted"])
        self.assertEqual(len(calls), 1)
        self.assertIn("/gummies", calls[0].data.decode("utf-8"))

    def test_the_live_answer_beats_the_stored_flag_for_the_publishing_page(self):
        """A page that just rendered noindex must leave the sitemap in the same publish, not one later."""
        s3, result, _ = self._publish(publishing_page_id="page_gummies", indexable=False)
        sitemap = s3.objects["page_home/sitemap.xml"]
        self.assertNotIn(f"<loc>https://{DOMAIN}/gummies</loc>", sitemap)
        self.assertIn(f"<loc>https://{DOMAIN}/about</loc>", sitemap)
        self.assertFalse(result["indexnow_submitted"])

    def test_a_page_is_never_listed_twice(self):
        s3, result, _ = self._publish(publishing_page_id="page_home", indexable=True)
        self.assertEqual(s3.objects["page_home/sitemap.xml"].count(f"<loc>https://{DOMAIN}/</loc>"), 1)
        self.assertEqual(result["urls"], 3)

    def test_an_archived_site_advertises_nothing(self):
        site = _site(dict(self.SITE_PAGES), status="archived", seo={"indexnow_key": "a" * 32})
        s3, result, calls = self._publish(publishing_page_id="page_home", site=site)
        self.assertNotIn("<url>", s3.objects["page_home/sitemap.xml"])
        self.assertIn("Disallow: /", s3.objects["page_home/robots.txt"])
        self.assertEqual(result["urls"], 0)
        self.assertEqual(calls, [])

    def test_search_visibility_off_advertises_nothing(self):
        site = _site(dict(self.SITE_PAGES), indexing={"eligibility": "eligible", "seo_enabled": False},
                     seo={"indexnow_key": "a" * 32})
        s3, result, calls = self._publish(publishing_page_id="page_home", site=site)
        self.assertNotIn("<url>", s3.objects["page_home/sitemap.xml"])
        self.assertIn("Disallow: /", s3.objects["page_home/robots.txt"])
        self.assertEqual(calls, [])

    def test_robots_still_points_at_the_sitemap_when_the_site_is_open(self):
        s3, _, _ = self._publish(publishing_page_id="page_home")
        self.assertIn(f"Sitemap: https://{DOMAIN}/sitemap.xml", s3.objects["page_home/robots.txt"])
        self.assertIn("Allow: /", s3.objects["page_home/robots.txt"])


class SiteSchemaTests(unittest.TestCase):
    def test_the_new_entry_fields_are_type_checked(self):
        for field, bad in (("indexable", "yes"), ("lastmod", -1), ("images", "not-a-list")):
            with self.subTest(field=field):
                site = _site({"/": {"page_id": "page_home", "page_type": "homepage", field: bad}})
                with self.assertRaises(DocumentValidationError):
                    validate_site(site)


if __name__ == "__main__":
    unittest.main()
