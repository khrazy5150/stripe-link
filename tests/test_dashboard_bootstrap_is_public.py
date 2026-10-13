"""Whatever the dashboard fetches WITHOUT a token must be classified public.

`tests/test_buyer_routes_are_public.py` derives its list from the published page's JavaScript, so it sees
every buyer route and none of the dashboard's. That left one gap, and the gap bit: attaching the Cognito
authorizer on 2026-10-11 made `GET /app-config/{config_key}` return 401.

That request is the BOOTSTRAP read — `loadAppConfigApiBase` calls it with a bare `fetch()` and no
Authorization header, because it is how the dashboard learns where the API is. Its failure path is silent
by design (fall back to a built-in base), and it does one more thing: it CLEARS the cached config. So
every config-derived URL resolved to `""`, and the only symptom anyone saw, a day later, was draft preview
links opening the dashboard instead of the page.

Derived the same way its sibling is: read the bare `fetch()` calls out of the API client rather than
listing them, so the next one cannot be added without this test seeing it.
"""
import pathlib
import re
import unittest

from stripe_link.api_auth import PUBLIC, PUBLIC_ROUTES, classify

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "api" / "client.js"
TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "template.yaml"


def unauthenticated_paths():
    """API paths the client fetches with a bare `fetch()`, i.e. with no Authorization header.

    `apiRequest` attaches the token; anything calling `fetch` directly does not. The URL is built as
    `${base}/some/path`, so the literal segment after the interpolation is the route.
    """
    source = CLIENT.read_text(encoding="utf-8")
    found = set()
    for match in re.finditer(r"new URL\(\s*`\$\{[^`]*?\}([^`$]*)`", source):
        path = match.group(1).strip()
        if path.startswith("/"):
            found.add(path)
    return found


class TheBootstrapReadIsReachableWithoutAToken(unittest.TestCase):
    def test_the_derivation_finds_something(self):
        """A guard that matches nothing passes forever."""
        paths = unauthenticated_paths()
        self.assertTrue(paths, "no bare fetch() paths found -- the regex has drifted from the client")
        self.assertTrue(any("app-config" in p for p in paths), sorted(paths))

    def test_every_unauthenticated_fetch_is_classified_public(self):
        for path in sorted(unauthenticated_paths()):
            # `/app-config/app_config` in the client is the templated `/app-config/{config_key}`.
            resource = re.sub(r"/app-config/[^/]+$", "/app-config/{config_key}", path)
            with self.subTest(path=path):
                self.assertEqual(
                    classify({"httpMethod": "GET", "resource": resource}), PUBLIC,
                    f"{path} is fetched with no token but is classified private -- it will 401, and the "
                    f"client's failure path is silent")

    def test_the_template_exempts_it_from_the_authorizer(self):
        """The classification table is what the code believes; this is what API Gateway enforces. They
        are different files and only one of them returns 401."""
        body = TEMPLATE.read_text(encoding="utf-8")
        start = body.index("        AppConfigGet:")
        block = body[start:body.index("        AppConfigPut:")]
        self.assertIn("Authorizer: NONE", block,
                      "GET /app-config must be exempt or the dashboard cannot bootstrap")

    def test_writing_config_stays_private(self):
        """The asymmetry is the point: anyone may READ where the API is; nobody may rewrite it."""
        self.assertNotEqual(
            classify({"httpMethod": "PUT", "resource": "/app-config/{config_key}"}), PUBLIC)
        body = TEMPLATE.read_text(encoding="utf-8")
        put = body[body.index("        AppConfigPut:"):]
        put = put[:put.index("  OfferResolveFunction:")]
        self.assertNotIn("Authorizer: NONE", put)

    def test_the_public_entry_carries_its_reason(self):
        self.assertIn(("GET", "/app-config/{config_key}"), PUBLIC_ROUTES)
        self.assertIn("token", PUBLIC_ROUTES[("GET", "/app-config/{config_key}")])


if __name__ == "__main__":
    unittest.main()
