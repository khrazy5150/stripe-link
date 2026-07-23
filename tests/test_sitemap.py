import re
import unittest

from stripe_link.domain.sitemap import generate_indexnow_key, indexnow_body, robots_txt, sitemap_xml


class SitemapTests(unittest.TestCase):
    def test_sitemap_has_loc_lastmod_and_image(self):
        xml = sitemap_xml([{"loc": "https://shop.example.com/", "lastmod": 1784600000,
                            "images": ["https://images.juniorbay.com/p/a/large.webp"]}])
        self.assertTrue(xml.startswith("<?xml"))
        self.assertIn("<loc>https://shop.example.com/</loc>", xml)
        self.assertRegex(xml, r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>")
        self.assertIn("<image:loc>https://images.juniorbay.com/p/a/large.webp</image:loc>", xml)

    def test_sitemap_skips_empty_loc(self):
        self.assertNotIn("<url>", sitemap_xml([{"loc": ""}]))

    def test_robots_allows_and_references_sitemap(self):
        r = robots_txt("https://shop.example.com/sitemap.xml")
        self.assertIn("Allow: /", r)
        self.assertIn("Sitemap: https://shop.example.com/sitemap.xml", r)

    def test_robots_disallow_all_for_archived_site(self):
        r = robots_txt("https://shop.example.com/sitemap.xml", allow=False)
        self.assertIn("Disallow: /", r)
        self.assertNotIn("Allow: /", r)
        self.assertNotIn("Sitemap:", r)

    def test_empty_sitemap_has_no_urls(self):
        self.assertNotIn("<url>", sitemap_xml([]))

    def test_indexnow_key_is_hex(self):
        key = generate_indexnow_key()
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", key))

    def test_indexnow_body_shape(self):
        body = indexnow_body("shop.example.com", "k1", ["https://shop.example.com/", ""])
        self.assertEqual(body["host"], "shop.example.com")
        self.assertEqual(body["key"], "k1")
        self.assertEqual(body["keyLocation"], "https://shop.example.com/k1.txt")
        self.assertEqual(body["urlList"], ["https://shop.example.com/"])   # empties dropped


if __name__ == "__main__":
    unittest.main()
