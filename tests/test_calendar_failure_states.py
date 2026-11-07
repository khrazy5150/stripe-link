"""Google Calendar's three failure states, which were one failure until 2026-11-06.

The one that mattered did not even reach the handler: `template.yaml` points every environment at
`jb/google-oauth/${Environment}` and only the DEV secret was ever created, so production asked Secrets
Manager for a secret that did not exist. boto3's `ResourceNotFoundException` is not a
`GoogleCalendarError`, was caught nowhere, and surfaced as an unhandled 500 — so the calendar feature had
never worked in prod and nothing anywhere said so.
"""
import json
import unittest
from unittest import mock
from urllib.error import HTTPError

from handlers import calendar
from stripe_link.google_calendar import (GoogleCalendarError, GoogleCalendarNotConfigured,
                                         GoogleCalendarReauthRequired, exchange_code_for_tokens,
                                         fetch_access_token, load_google_oauth_secret)

CONFIGURED = {"GOOGLE_OAUTH_SECRET_NAME": "jb/google-oauth/prod",
              "CALENDAR_REDIRECT_URI": "https://x.test/cb", "AWS_DEFAULT_REGION": "us-west-2"}


def google_error(code, description=""):
    body = json.dumps({"error": code, "error_description": description}).encode()
    return HTTPError("https://oauth2.googleapis.com/token", 400, "Bad Request", {}, _Body(body))


class _Body:
    """HTTPError treats its fp as a file and closes it during cleanup, so the fake needs `close`."""

    def __init__(self, data): self._data = data
    def read(self): return self._data
    def close(self): return None


def connect_event(tenant="t1"):
    return {"httpMethod": "POST", "path": "/calendar/connect", "headers": {"X-Tenant-Id": tenant}}


class TheyAreStillGoogleCalendarErrorsTests(unittest.TestCase):
    """Existing callers catch the base class; narrowing must not change what they see."""

    def test_both_new_states_subclass_the_original(self):
        self.assertTrue(issubclass(GoogleCalendarNotConfigured, GoogleCalendarError))
        self.assertTrue(issubclass(GoogleCalendarReauthRequired, GoogleCalendarError))


class AMissingSecretIsNamedNotCrashedTests(unittest.TestCase):
    def test_the_loader_reports_the_secret_it_could_not_read(self):
        """"ResourceNotFoundException" says nothing about credentials. The name does."""
        client = mock.Mock()
        client.get_secret_value.side_effect = RuntimeError("ResourceNotFoundException")
        with self.assertRaises(GoogleCalendarNotConfigured) as caught:
            load_google_oauth_secret("jb/google-oauth/prod", client=client)
        self.assertIn("jb/google-oauth/prod", str(caught.exception))

    def test_connect_answers_503_rather_than_500(self):
        """THE ONE THAT MATTERS. This exact call 500'd in production for the life of the feature."""
        client = mock.Mock()
        client.get_secret_value.side_effect = RuntimeError("ResourceNotFoundException")
        with mock.patch.dict("os.environ", CONFIGURED, clear=True), \
             mock.patch("boto3.client", return_value=client):
            response = calendar.handler(connect_event(), None, connections_repo=object(),
                                        states_repo=object())
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(json.loads(response["body"])["error"], "calendar_not_configured")

    def test_an_unset_env_var_is_the_same_state(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            response = calendar.handler(connect_event(), None, connections_repo=object(),
                                        states_repo=object())
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(json.loads(response["body"])["error"], "calendar_not_configured")

    def test_the_message_does_not_blame_the_tenant(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            response = calendar.handler(connect_event(), None, connections_repo=object(),
                                        states_repo=object())
        self.assertIn("not available in this environment", json.loads(response["body"])["message"])


class ADeadTokenIsTheTenantsToFixTests(unittest.TestCase):
    def test_invalid_grant_on_refresh_is_its_own_state(self):
        """Routine: a revoked grant, a password change, or -- while the OAuth app is in Testing -- every
        refresh token expiring after seven days."""
        def opener(request, timeout=0):
            raise google_error("invalid_grant", "Token has been expired or revoked.")

        with self.assertRaises(GoogleCalendarReauthRequired):
            fetch_access_token("cid", "secret", "refresh", opener=opener)

    def test_invalid_grant_on_the_AUTH_CODE_is_the_same_remedy(self):
        def opener(request, timeout=0):
            raise google_error("invalid_grant", "Code was already redeemed.")

        with self.assertRaises(GoogleCalendarReauthRequired):
            exchange_code_for_tokens("cid", "secret", "code", "https://x.test/cb", opener=opener)

    def test_any_OTHER_google_error_stays_generic(self):
        """Only `invalid_grant` has a user action attached. Widening this would tell tenants to reconnect
        over faults reconnecting cannot fix."""
        for code in ("invalid_client", "unauthorized_client", "server_error"):
            with self.subTest(code=code):
                def opener(request, timeout=0, _c=code):
                    raise google_error(_c, "nope")

                with self.assertRaises(GoogleCalendarError) as caught:
                    fetch_access_token("cid", "secret", "refresh", opener=opener)
                self.assertNotIsInstance(caught.exception, GoogleCalendarReauthRequired)

    def test_the_handler_answers_409_with_a_stable_code(self):
        """409 and `calendar_reconnect_required` so the dashboard can show a Reconnect button rather than
        print an error nobody can act on."""
        with mock.patch.dict("os.environ", CONFIGURED, clear=True), \
             mock.patch.object(calendar, "_route",
                               side_effect=GoogleCalendarReauthRequired("expired")):
            response = calendar.handler(connect_event(), None)
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "calendar_reconnect_required")

    def test_an_upstream_fault_is_502(self):
        with mock.patch.object(calendar, "_route", side_effect=GoogleCalendarError("google is down")):
            response = calendar.handler(connect_event(), None)
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["error"], "calendar_upstream_error")


class TheInnerRoutesDoNotFlattenThemTests(unittest.TestCase):
    def test_connect_reraises_the_distinguishable_states(self):
        """`except GoogleCalendarError` in a route catches the subclasses too, which is how every cause
        came back as 'not configured'."""
        import inspect

        source = inspect.getsource(calendar.connect_route)
        self.assertIn("raise", source.split("except GoogleCalendarError", 1)[1][:400])

    def test_the_browser_callback_keeps_html_but_separates_the_causes(self):
        import inspect

        source = inspect.getsource(calendar.callback_route)
        self.assertIn("GoogleCalendarReauthRequired", source)
        self.assertIn("GoogleCalendarNotConfigured", source)


if __name__ == "__main__":
    unittest.main()
