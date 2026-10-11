"""The dashboard must send the ID token, or the Cognito authorizer refuses every private route.

**Found live, 2026-10-11, minutes after the authorizer was deployed to dev.** The operator could log in
and every screen came back empty: "No Stripe keys saved yet" for a tenant whose keys have been in use all
week. The cause was not in any handler — 35 4xx at the API Gateway and **zero Lambda invocations** on
every private function, which is the signature of a request refused before it reaches the code.

API Gateway's Cognito authorizer requires an **identity** token unless the authorizer declares
`AuthorizationScopes`. Given an access token it answers 401 upstream of everything. The dashboard had
always sent `access_token`, which was harmless while nothing checked it.

It is also the better token to send, which is why this is a fix rather than a workaround: only an ID
token carries custom attributes, so `api_auth.caller_tenant` can read `custom:client_id` — the
authoritative tenant — instead of falling back to `sub`. That fallback is correct today only because
every user happens to own their tenant (6 of 6), which is a property of the data and not of the schema.

Static guards, in the shape of the other dashboard tests: there is no JS runner here.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT / "dashboard" / "src" / "api" / "client.js"
AUTH = ROOT / "src" / "handlers" / "auth.py"


class TheAuthorizationHeaderCarriesTheIdToken(unittest.TestCase):
    def test_the_header_prefers_id_token(self):
        text = CLIENT.read_text(encoding="utf-8")
        self.assertIn("active?.id_token || active?.access_token", text,
                      "the Authorization header must prefer the ID token")

    def test_the_access_token_remains_only_as_a_fallback(self):
        """A session stored before this shipped has no id_token. It will 401, and the refresh path mints
        one carrying both — so the fallback buys a graceful recovery rather than a forced logout."""
        text = CLIENT.read_text(encoding="utf-8")
        self.assertNotIn("Bearer ${active.access_token}", text,
                         "sending the access token alone is what the authorizer refuses")

    def test_a_session_with_either_token_is_allowed_to_send(self):
        text = CLIENT.read_text(encoding="utf-8")
        self.assertIn("!session?.id_token && !session?.access_token", text,
                      "the fail-closed guard must not reject a session that has an id token")

    def test_the_reason_is_recorded_where_the_header_is_built(self):
        """This is a one-word change that silently breaks every authenticated screen if reverted."""
        text = CLIENT.read_text(encoding="utf-8")
        self.assertIn("AuthorizationScopes", text,
                      "name the API Gateway rule that forces this, or it reads as an arbitrary choice")


class TheServerSuppliesItOnBothPaths(unittest.TestCase):
    """Login AND refresh. If refresh returned only a new access token, the stored ID token would go stale
    and every session would start 401ing about an hour in -- the exact failure the refresh path was built
    to prevent, arriving through the other token."""

    def test_login_returns_an_id_token(self):
        self.assertIn('"id_token": auth.get("IdToken")', AUTH.read_text(encoding="utf-8"))

    def test_refresh_returns_an_id_token_too(self):
        text = AUTH.read_text(encoding="utf-8")
        start = text.index("def refresh_session(")
        body = text[start:text.index("\ndef ", start + 1)]
        self.assertIn('"id_token": auth.get("IdToken")', body,
                      "a refresh that omits the ID token leaves the session with a dead one")

    def test_both_paths_still_return_the_access_token(self):
        """Kept for the fallback above, and because nothing should be removed from a session payload on
        the strength of one screen's needs."""
        self.assertGreaterEqual(AUTH.read_text(encoding="utf-8").count('"access_token": auth.get("AccessToken")'), 2)


if __name__ == "__main__":
    unittest.main()
