"""The favicon a browser fetches on first paint of EVERY published page.

Found 2026-09-23: `default_favicon_url()` served a 200x200 PNG of 30,115 bytes -- roughly 15x oversized
for something drawn at 32 pixels -- as `icon`, `shortcut icon` AND `apple-touch-icon`, with no
Cache-Control header at all. It is fetched on first paint, competing with the LCP image for connections,
which is the same lane the font work moved a real page +18 PageSpeed points in.

Published 2026-09-25 on the images CDN: `icon/favicon-32.png` (2,993 bytes) and `icon/favicon-40.png`
(3,928 bytes), both with `public, max-age=31536000, immutable`.
"""
import unittest
from unittest.mock import patch

from stripe_link.domain.platform_signature import SIGNATURE_LOGO_URL, signature_html
from stripe_link.platform_config import FAVICON_LARGE, FAVICON_SMALL
from stripe_link.runtime.html import render_favicon_tags

LARGE = "https://images.juniorbay.com/icon/favicon.png"
SMALL = "https://images.juniorbay.com/icon/favicon-32.png"


class TagTests(unittest.TestCase):
    def test_the_tab_icon_is_the_SMALL_file(self):
        tags = render_favicon_tags({}, LARGE, SMALL)
        self.assertIn(f'<link rel="icon" href="{SMALL}" sizes="32x32">', tags)
        self.assertIn(f'<link rel="shortcut icon" href="{SMALL}">', tags)

    def test_apple_touch_keeps_the_LARGE_one(self):
        """It wants a big square, and it is only fetched when someone adds the page to a home screen --
        so its weight is not on the first-paint path at all."""
        self.assertIn(f'<link rel="apple-touch-icon" href="{LARGE}">', render_favicon_tags({}, LARGE, SMALL))

    def test_a_TENANTS_own_favicon_is_used_for_all_three(self):
        """They gave us one file at one size. Deriving a "-32" URL from it would 404."""
        tags = render_favicon_tags({"favicon_url": "https://cdn.example.com/mine.png"}, LARGE, SMALL)
        self.assertEqual(tags.count("https://cdn.example.com/mine.png"), 3)
        self.assertNotIn(SMALL, tags)
        self.assertNotIn(LARGE, tags)

    def test_an_unconfigured_cdn_emits_NOTHING_rather_than_a_broken_href(self):
        self.assertEqual(render_favicon_tags({}, "", ""), "")

    def test_a_missing_small_url_falls_back_to_the_large_one(self):
        """A deployment whose app_config predates the small asset must still get a working icon."""
        tags = render_favicon_tags({}, LARGE, "")
        self.assertIn(f'<link rel="icon" href="{LARGE}" sizes="32x32">', tags)

    def test_the_three_tags_are_still_all_emitted(self):
        tags = render_favicon_tags({}, LARGE, SMALL)
        for rel in ("icon", "shortcut icon", "apple-touch-icon"):
            self.assertIn(f'rel="{rel}"', tags)


class ConfigTests(unittest.TestCase):
    def test_the_paths_are_named_once(self):
        self.assertEqual(FAVICON_SMALL, "/icon/favicon-32.png")
        self.assertEqual(FAVICON_LARGE, "/icon/favicon.png")

    def test_both_urls_are_empty_when_the_asset_cdn_is_unconfigured(self):
        """No literal is baked in -- an unconfigured deployment emits no favicon rather than a 404."""
        from stripe_link import platform_config

        with patch.object(platform_config, "asset_base_url", return_value=""):
            self.assertEqual(platform_config.default_favicon_url(), "")
            self.assertEqual(platform_config.default_favicon_small_url(), "")

    def test_both_urls_hang_off_the_configured_base(self):
        from stripe_link import platform_config

        with patch.object(platform_config, "asset_base_url", return_value="https://cdn.test"):
            self.assertEqual(platform_config.default_favicon_small_url(), "https://cdn.test/icon/favicon-32.png")
            self.assertEqual(platform_config.default_favicon_url(), "https://cdn.test/icon/favicon.png")


class EmailSignatureTests(unittest.TestCase):
    def test_the_signature_mark_is_the_2x_of_its_render(self):
        """It is drawn at 20x20 and fetched on every open, often over a phone connection. 40 is the retina
        asset; 200 was 30KB for a 20-pixel mark."""
        self.assertEqual(SIGNATURE_LOGO_URL, "https://images.juniorbay.com/icon/favicon-40.png")
        self.assertIn('width="20" height="20"', signature_html())
        self.assertIn(SIGNATURE_LOGO_URL, signature_html())


if __name__ == "__main__":
    unittest.main()
