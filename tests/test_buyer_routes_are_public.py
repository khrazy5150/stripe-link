"""Every route a published page fetches must be classified PUBLIC.

**The measurement found one that was not** (2026-10-11): `GET /shipping-quote`, with 323 token-less calls
in dev over 14 days, every one of them a buyer. The published page's shipping island asks for its own rate
on load (`runtime/html.py`), because a rate baked into the page starts rotting immediately.

Attaching the authorizer with that route private would have left every buyer with no postage rate — and
the shipping element is the ONLY thing that collects a postcode, so checkout would have silently charged
$0 for postage. That has already cost one real $7.83 parcel, which is why this is a test and not a note.

`plans/API_AUTHENTICATION.md` states the asymmetry plainly:

    a route wrongly PRIVATE -> buyers stop being able to check out, the moment enforcement lands
    a route wrongly PUBLIC  -> the hole stays open and looks closed

A hand-written list of buyer routes has the same failure mode as the thing it is guarding, so this
DERIVES the list from the page renderer: any path the published-page JavaScript builds a fetch URL for is
buyer-facing by construction. A new buyer-facing route cannot be added without this test seeing it.
"""
import pathlib
import re
import unittest

from stripe_link.api_auth import PUBLIC, PUBLIC_ROUTES, classify

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "src" / "stripe_link" / "runtime"


def page_fetch_paths():
    """Paths the published page's own JavaScript fetches, read out of the renderer.

    Interpolations are collapsed FIRST, then paths are parsed. Doing it the other way round truncated
    `${funnelPageId || cta.dataset.checkoutPageId}` at the space and produced `/pages/${funnelPageId` --
    a derivation that invents a path is worse than one that misses it, because it fails for a reason
    nobody can act on.
    """
    found = set()
    for source in sorted(RUNTIME.glob("*.py")):
        for line in source.read_text(encoding="utf-8").splitlines():
            if "${" not in line and ".replace(" not in line:
                continue
            # Every `${...}` becomes either the api-base marker or a path parameter, so what remains is a
            # plain path that a simple pattern can read.
            collapsed = re.sub(
                r"\$\{([^}]*)\}",
                lambda m: "\x00API\x00" if "api" in m.group(1).lower() else "{param}",
                line)
            for raw in re.findall(r"\x00API\x00((?:/[A-Za-z0-9_{}.\-]+)+)", collapsed):
                found.add(_normalize(raw))
            # The other shape: `api.replace(/\/$/,'') + '/shipping-quote?...'`
            for raw in re.findall(r"[Aa]pi[A-Za-z]*\.replace\([^)]*\)\s*\+\s*'(/[A-Za-z0-9_/-]+)", line):
                found.add(_normalize(raw))
    return {path for path in found if path}


def _normalize(raw):
    """`/pages/{param}/post-checkout/next?x=1` -> `/pages/{param}/post-checkout/next`."""
    path = raw.split("?")[0]
    path = re.sub(r"/+", "/", path).rstrip("/")
    return path if path.startswith("/") and len(path) > 1 else ""


def public_shapes():
    """PUBLIC_ROUTES paths with their path parameters collapsed, so `{page_id}` matches `{param}`."""
    return {re.sub(r"\{[^}]*\}", "{param}", path) for _method, path in PUBLIC_ROUTES}


class EveryRouteABuyerPageCallsIsPublic(unittest.TestCase):
    def test_the_derivation_actually_found_the_calls(self):
        """A guard that silently matches nothing proves nothing. These are the real endpoints a published
        page is known to hit, so if the regexes rot, this fails rather than passing vacuously."""
        paths = page_fetch_paths()
        # Named, not just counted: a regex that rots silently finds three paths and passes a >= 4 check
        # while missing the one that matters.
        for expected in ("/shipping-quote", "/upsell/charge", "/pages/{param}/post-checkout/next",
                         "/services/{param}/availability"):
            self.assertIn(expected, paths, f"derivation lost {expected}: {sorted(paths)}")
        self.assertGreaterEqual(len(paths), 7, sorted(paths))

    def test_no_buyer_path_is_classified_private(self):
        shapes = public_shapes()
        private = sorted(path for path in page_fetch_paths() if path not in shapes)
        self.assertEqual(private, [], "a published page fetches these and no buyer carries a token")

    def test_the_shipping_quote_route_specifically(self):
        """Named as well as derived, because this one has a measured history and a dollar cost."""
        self.assertEqual(classify({"httpMethod": "GET", "resource": "/shipping-quote"}), PUBLIC)

    def test_the_reason_is_recorded_beside_it(self):
        """The table's value is the reason a route is public. An unexplained entry is how a hole gets
        added later and looks deliberate."""
        reason = PUBLIC_ROUTES[("GET", "/shipping-quote")]
        self.assertTrue(reason.strip(), "every public route states why")
        self.assertIn("shipping", reason.lower())


class TheClassifierHasExactlyOneIdentitySource(unittest.TestCase):
    """`verified_claims` was defined TWICE in api_auth.py (found 2026-10-11). Both bodies happened to be
    identical, so the shadowing was behaviourally harmless -- but a security boundary with two definitions
    of "who is calling" is one edit away from being harmful, and nothing would have flagged it."""

    def test_verified_claims_is_defined_once(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "api_auth.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("def verified_claims("), 1)

    def test_it_reads_only_what_an_authorizer_wrote(self):
        from stripe_link.api_auth import verified_claims
        self.assertEqual(verified_claims({"requestContext": {"authorizer": {"claims": {"sub": "u1"}}}}),
                         {"sub": "u1"})
        self.assertEqual(verified_claims({"headers": {"Authorization": "Bearer forged"}}), {},
                         "a bearer token alone is verified by nobody")


if __name__ == "__main__":
    unittest.main()
