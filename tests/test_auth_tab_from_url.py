"""The homepage's "Start for free" must land on Register, not Login.

Two separate deployments: the marketing site is static HTML on its own bucket, the dashboard is the Vue
app. The only thing that crosses between them is the link, so the tab has to travel in the URL. If the
link and the reader disagree, a visitor who clicked "Start for free" is asked to sign in to an account
they do not have -- a dead end at the exact moment they decided to try the product.

Both halves are asserted here because either one alone passes while the journey is broken.
"""
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOMEPAGE = ROOT / "homepage" / "index.html"
AUTH_STORE = ROOT / "dashboard" / "src" / "stores" / "auth.js"


class TheLinkCarriesTheTabTests(unittest.TestCase):
    def test_every_homepage_trial_cta_asks_for_the_register_tab(self):
        html = HOMEPAGE.read_text(encoding="utf-8")
        # The trial buttons, by the class they share. "Sign in" deliberately does NOT carry the tab.
        ctas = re.findall(r'<a class="btn btn-trial[^"]*" href="([^"]+)"', html)
        self.assertTrue(ctas, "no trial CTAs found; the selector has drifted")
        for href in ctas:
            with self.subTest(href=href):
                self.assertIn("tab=register", href,
                              "a trial CTA lands on Login, where a new visitor cannot proceed")

    def test_sign_in_does_not_carry_it(self):
        html = HOMEPAGE.read_text(encoding="utf-8")
        for href in re.findall(r'<a class="hero-signin" href="([^"]+)"', html):
            with self.subTest(href=href):
                self.assertNotIn("tab=register", href)


class TheReaderUnderstandsItTests(unittest.TestCase):
    """Runs the real function in node, rather than asserting on its source text."""

    def _tab_for(self, url):
        script = f"""
        const src = require("fs").readFileSync({str(AUTH_STORE)!r}, "utf8");
        const body = src.slice(src.indexOf("function tabFromUrl"), src.indexOf("export const useAuthStore"));
        const u = new URL({url!r});
        globalThis.window = {{ location: {{ search: u.search, hash: u.hash }} }};
        eval(body);
        process.stdout.write(tabFromUrl());
        """
        return subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout.strip()

    def test_the_register_link_opens_the_register_tab(self):
        self.assertEqual(self._tab_for("https://app.juniorbay.com/?tab=register"), "register")

    def test_a_bare_visit_still_opens_login(self):
        self.assertEqual(self._tab_for("https://app.juniorbay.com/"), "login")

    def test_the_hash_form_works_too(self):
        self.assertEqual(self._tab_for("https://app.juniorbay.com/#register"), "register")

    def test_an_unknown_tab_falls_back_to_login(self):
        """A URL is not trusted input; there is no 'admin' tab to be talked into."""
        for asked in ("admin", "", "REGISTER", "../register"):
            with self.subTest(asked=asked):
                self.assertEqual(self._tab_for(f"https://app.juniorbay.com/?tab={asked}"), "login")


if __name__ == "__main__":
    unittest.main()
