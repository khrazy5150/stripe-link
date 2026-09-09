"""The store's font preference, read at publish and beaten by a page override.

plans/FONT_SERVICE.md §9 specified `user_preferences` for this. That does not work: the table is keyed
(tenant_id, user_id), pages carry no owner, and publish runs from a DynamoDB stream holding only the page --
so there is no user to look up. It is also the wrong home on its own terms, since type is a property of the
STORE customers see rather than of a staff login. It lives on the tenant profile instead.

The read happens at PUBLISH, once, because a page is a static artifact. It costs nothing at view time, which
is the whole reason this is not a lookup inside the font service.
"""
import json
import pathlib
import re
import unittest

from stripe_link.runtime.html import render_page
from stripe_link.runtime.publishing import load_tenant_preferences

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _fixture(name):
    return json.loads((ROOT / "schemas" / "examples" / name).read_text(encoding="utf-8"))


class _Repo:
    def __init__(self, doc=None, raises=False):
        self.doc, self.raises = doc, raises

    def get(self, tenant_id, document_id):
        if self.raises:
            raise RuntimeError("table unavailable")
        return self.doc


class LoadTenantPreferencesTests(unittest.TestCase):
    def test_reads_the_profile_keyed_by_tenant(self):
        self.assertEqual(load_tenant_preferences(_Repo({"fonts": {"heading": "x"}}), "t"),
                         {"fonts": {"heading": "x"}})

    def test_absent_table_or_tenant_is_not_an_error(self):
        # Without the table the preset stays in charge, exactly as every page behaved before this existed.
        self.assertEqual(load_tenant_preferences(None, "t"), {})
        self.assertEqual(load_tenant_preferences(_Repo({"fonts": {}}), ""), {})

    def test_a_failing_read_never_blocks_a_publish(self):
        # Failing closed here would mean a page silently refusing to publish over a preference nobody set.
        self.assertEqual(load_tenant_preferences(_Repo(raises=True), "t"), {})


class RenderedPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.page = _fixture("page-creatine-standard.json")
        self.offer = _fixture("offer-creatine-standard.json")
        product = _fixture("product-creatine-gummies.json")
        self.products = {product.get("product_id"): product}

    def heading(self, **kwargs):
        html = render_page(self.page, self.offer, self.products, **kwargs)
        return re.search(r"--sl-font-heading:'?([^,']+)", html).group(1)

    def test_the_preset_wins_when_no_preference_is_set(self):
        self.assertEqual(self.heading(), "Source Code Pro")

    def test_a_store_preference_overrides_the_preset_only_behind_the_toggle(self):
        prefs = {"fonts": {"override_presets": True, "heading": {"family": "Merriweather"}}}
        self.assertEqual(self.heading(preferences=prefs), "Merriweather")

        off = {"fonts": {"override_presets": False, "heading": {"family": "Merriweather"}}}
        self.assertEqual(self.heading(preferences=off), "Source Code Pro",
                         "without the toggle, idly picking a font would re-typeset every published page")

    def test_a_page_override_beats_the_store_preference(self):
        # A tenant with a house style still wants one page to look different, and should not have to turn
        # their own preference off to get it.
        self.page = {**self.page, "theme": {**self.page.get("theme", {}),
                                            "fonts": {"heading": {"family": "Oswald"}}}}
        prefs = {"fonts": {"override_presets": True, "heading": {"family": "Merriweather"}}}
        self.assertEqual(self.heading(preferences=prefs), "Oswald")

    def test_one_tenants_preference_does_not_leak_into_the_next_render(self):
        # The store is a render-scoped global, so a warm container must not carry it across pages.
        self.heading(preferences={"fonts": {"override_presets": True, "heading": {"family": "Merriweather"}}})
        self.assertEqual(self.heading(), "Source Code Pro")


class GrantTests(unittest.TestCase):
    def test_the_publish_function_can_read_tenant_profiles(self):
        # Same silent-failure shape as the favicon bug: without the grant the read raises, the failsafe
        # swallows it, and every page quietly renders the preset instead of the store's font.
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", template, re.M))["PagePublishFunction"]
        self.assertIn("TenantProfilesTable", block)


if __name__ == "__main__":
    unittest.main()


class EmbeddedTenantFontTests(unittest.TestCase):
    """A tenant font is embedded at publish, not fetched at view time.

    It is the ONE font a page still fetched cross-origin — the catalogue's arrive embedded via fs=true — and
    that fetch is exactly what Chromium and Firefox refuse for a missing Access-Control-Allow-Origin that
    curl, from the same machine and origin, is served correctly (plans/FONT_SERVICE.md 12b, unexplained).
    Embedding removes the request rather than the symptom.
    """
    WOFF2 = b"wOF2" + b"\x00" * 64
    URL = "https://juniorbay.com/fonts/tenant/t1/acme-700-normal.woff2"

    def _prefs(self, url=None):
        return {"fonts": {"imported": [{"family": "Acme", "weight": "700", "style": "normal",
                                        "url": url or self.URL}]}}

    class _S3:
        def __init__(self, body=None, raises=False):
            self.body, self.raises, self.keys = body, raises, []

        def get_object(self, Bucket, Key):
            self.keys.append(Key)
            if self.raises:
                raise RuntimeError("denied")
            return {"Body": type("B", (), {"read": lambda _self: self.body})()}

    def _embed(self, s3, prefs=None):
        from stripe_link.runtime.publishing import embed_imported_fonts
        return embed_imported_fonts(prefs or self._prefs(), s3, "bucket")

    def test_the_bytes_replace_the_url(self):
        s3 = self._S3(self.WOFF2)
        face = self._embed(s3)["fonts"]["imported"][0]
        self.assertTrue(face["data_uri"].startswith("data:font/woff2;base64,"))
        self.assertEqual(s3.keys, ["fonts/tenant/t1/acme-700-normal.woff2"])

    def test_an_unreadable_font_keeps_its_url_rather_than_blocking_the_publish(self):
        # A page that publishes with a possibly-blocked font beats a page that will not publish.
        face = self._embed(self._S3(raises=True))["fonts"]["imported"][0]
        self.assertNotIn("data_uri", face)
        self.assertEqual(face["url"], self.URL)

    def test_something_that_is_not_a_woff2_is_not_embedded(self):
        face = self._embed(self._S3(b"not a font"))["fonts"]["imported"][0]
        self.assertNotIn("data_uri", face)

    def test_an_oversized_font_stays_a_url(self):
        from stripe_link.runtime import publishing
        big = b"wOF2" + b"\x00" * (publishing.MAX_EMBEDDED_FONT_BYTES + 1)
        self.assertNotIn("data_uri", self._embed(self._S3(big))["fonts"]["imported"][0])

    def test_a_url_outside_the_tenant_prefix_is_never_read(self):
        # The catalogue's own files are not this function's business, and the IAM grant scopes to the
        # tenant prefix — but the code must not even ask.
        s3 = self._S3(self.WOFF2)
        self._embed(s3, self._prefs("https://juniorbay.com/fonts/Inter/Inter-Variable-latin.woff2"))
        self.assertEqual(s3.keys, [])

    def test_the_rendered_page_carries_the_bytes_not_a_url(self):
        page = _fixture("page-creatine-standard.json")
        page = {**page, "theme": {**page.get("theme", {}), "fonts": {"heading": {"family": "Acme"}}}}
        offer = _fixture("offer-creatine-standard.json")
        product = _fixture("product-creatine-gummies.json")
        html = render_page(page, offer, {product.get("product_id"): product},
                           preferences=self._embed(self._S3(self.WOFF2)))
        self.assertIn("data:font/woff2;base64,", html)
        self.assertNotIn(self.URL, html)


class EmbedSwitchTests(unittest.TestCase):
    """One switch governs BOTH halves of embedding.

    The catalogue's fonts are embedded by the service (fs=true) and the tenant's own by publishing (a data:
    URI). Both existed for the same reason -- the cross-origin font fetch Chromium and Firefox blocked --
    so they must not be able to disagree. A page referencing catalogue fonts while inlining a tenant one is
    the state that made the live preview unable to show an imported font.
    """

    def test_the_renderer_and_the_publisher_read_the_same_flag(self):
        from stripe_link.runtime import html, publishing
        self.assertIs(publishing.FONT_EMBED, html.FONT_EMBED)

    def test_referencing_mode_leaves_the_url_alone(self):
        from stripe_link.runtime import html
        if html.FONT_EMBED:
            self.skipTest("embedding is on; this pins the other position")
        page = _fixture("page-creatine-standard.json")
        page = {**page, "theme": {**page.get("theme", {}), "fonts": {"heading": {"family": "Acme"}}}}
        offer = _fixture("offer-creatine-standard.json")
        product = _fixture("product-creatine-gummies.json")
        prefs = {"fonts": {"imported": [{"family": "Acme", "weight": "700", "style": "normal",
                                         "url": "https://juniorbay.com/fonts/tenant/t1/acme.woff2"}]}}
        rendered = render_page(page, offer, {product.get("product_id"): product}, preferences=prefs)
        self.assertIn("https://juniorbay.com/fonts/tenant/t1/acme.woff2", rendered)
        self.assertNotIn("data:font/woff2", rendered)


class PreviewParityTests(unittest.TestCase):
    """The live preview must resolve fonts the same way a published page does.

    The preview is an <iframe srcdoc> fed by the RENDER endpoint, a different Lambda from publish. Tenant
    preferences were wired into publish only, so the preview resolved three of the four levels: presets
    previewed correctly while an imported font fell back to the system stack, which reads as "my font does
    not work" rather than "the preview cannot see it".
    """

    def test_the_render_endpoint_reads_the_store_profile(self):
        source = (ROOT / "src" / "handlers" / "page_render.py").read_text(encoding="utf-8")
        self.assertIn("load_tenant_preferences", source)
        self.assertIn("preferences=preferences", source)

    def test_the_render_function_can_read_it(self):
        # Without the grant the read raises, load_tenant_preferences swallows it by design, and the preview
        # silently goes back to showing the preset font.
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", template, re.M))["PageRenderFunction"]
        self.assertIn("TenantProfilesTable", block)
