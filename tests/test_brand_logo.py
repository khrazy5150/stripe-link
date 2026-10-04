"""`<img src="">` does not render nothing — it renders the browser's broken-image icon.

Reported 2026-10-04: the login screen's logo appeared broken after a tenant's session timed out. The mark
is built by `assetUrl`, which reads `public_asset_base_url` out of app_config — fetched at boot and cached
in localStorage — and returns `""` until that resolves. A normal visit has the cache warm from last time;
the timeout path reaches the auth screen with it cold or cleared, so the src is empty and every browser
draws the broken icon.

Two things were needed and neither alone is enough. The template must not render an empty src, so the
worst case is no logo rather than a broken one. And the URL must be REACTIVE: `assetUrl()` called inline
in a template is evaluated once with nothing to invalidate it, so a base that arrives a moment later never
reaches the DOM.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"
COMPOSABLE = (DASH / "composables" / "useBrandLogo.js").read_text()

# Every component that shows the brand mark. All three had the same bug; only one was visible, because
# after login the cache is warm.
USERS = ("App.vue", "components/AuthPage.vue", "components/shared/ConnectIntroModal.vue")


class NoComponentRendersAnEmptySrcTests(unittest.TestCase):
    def test_none_of_them_call_assetUrl_inline_in_a_template(self):
        offenders = [name for name in USERS if "assetUrl('/icon/favicon.png')" in (DASH / name).read_text()]
        self.assertEqual(offenders, [], "an inline assetUrl() is evaluated once and can be empty")

    def test_every_logo_img_is_guarded(self):
        for name in USERS:
            source = (DASH / name).read_text()
            self.assertIn('v-if="logoUrl" :src="logoUrl"', source, f"{name} renders an unguarded logo")

    def test_every_one_of_them_uses_the_composable(self):
        for name in USERS:
            self.assertIn("useBrandLogo", (DASH / name).read_text(), f"{name} has its own copy of this")


class TheUrlArrivesLateAndMustStillLandTests(unittest.TestCase):
    def test_it_is_a_ref_not_a_one_shot_call(self):
        self.assertIn("const logoUrl = ref(", COMPOSABLE)

    def test_it_loads_the_config_itself_rather_than_assuming(self):
        # The auth screen renders before App.vue's bootstrap resolves, and on the timeout path it may have
        # no cached config at all. Waiting for someone else to fetch it is how it stayed broken.
        self.assertIn("await loadAppConfigApiBase()", COMPOSABLE)

    def test_it_re_reads_the_url_after_the_config_lands(self):
        after = COMPOSABLE.split("await loadAppConfigApiBase()", 1)[1]
        self.assertIn("logoUrl.value = assetUrl(", after)

    def test_a_failed_config_fetch_is_not_an_error(self):
        # No logo is a fine outcome on a login screen; a crash or a broken icon is not.
        self.assertIn("catch {", COMPOSABLE)

    def test_it_does_not_refetch_when_the_cache_was_already_warm(self):
        self.assertIn("if (logoUrl.value) return;", COMPOSABLE)
