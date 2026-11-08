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


class OnlyACalendarTheMerchantOwnsTests(unittest.TestCase):
    """We request `calendar.events.owned`, which can only write to calendars the merchant OWNS.

    A calendar merely shared with them would be accepted at selection time and then 403 at the first
    booking -- weeks later, when a customer is waiting and nobody is watching the logs. So the refusal
    happens at the moment of choosing (`feedback_absence_reads_as_safety`: a check that never runs lets
    anything through).
    """

    CONN = {"schema_version": "2026-01-01", "document_type": "calendar_connection",
            "connection_id": "c1", "tenant_id": "t1", "status": "connected",
            "calendar_id": "primary", "account_email": "a@b.test", "provider": "google"}

    def _patch(self, wanted, owned):
        repo = mock.Mock()
        repo.get.return_value = dict(self.CONN)
        repo.list_for_tenant.return_value = []
        repo.put.side_effect = lambda d: d
        event = {"httpMethod": "PATCH", "path": "/calendar/connections/c1",
                 "headers": {"X-Tenant-Id": "t1"}, "pathParameters": {"connection_id": "c1"},
                 "body": json.dumps({"calendar_id": wanted})}
        with mock.patch.object(calendar, "owned_calendar_ids", return_value=owned):
            return calendar.handler(event, None, connections_repo=repo)

    def test_a_calendar_they_own_is_accepted(self):
        response = self._patch("mine@b.test", {"mine@b.test", "primary"})
        self.assertEqual(response["statusCode"], 200)

    def test_a_calendar_merely_SHARED_with_them_is_refused(self):
        """THE ONE THAT MATTERS: this is the selection that would have failed at booking time."""
        response = self._patch("boss@b.test", {"mine@b.test"})
        self.assertEqual(response["statusCode"], 409)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "calendar_not_owned")
        self.assertIn("you own", body["message"])

    def test_a_FAILED_lookup_does_not_block_the_choice(self):
        """None means we could not ask. Refusing on a hiccup would be a worse failure than allowing a
        selection the merchant can still correct."""
        self.assertEqual(self._patch("anything@b.test", None)["statusCode"], 200)

    def test_the_scopes_and_the_check_agree(self):
        """If the scope ever widens back to `calendar.events`, this check becomes dead weight -- and if
        it is removed while the scope stays narrow, bookings 403. They move together."""
        from stripe_link.google_calendar import DEFAULT_SCOPES

        narrow = any(s.endswith("calendar.events.owned") for s in DEFAULT_SCOPES)
        import inspect
        checks = "calendar_not_owned" in inspect.getsource(calendar.update_connection_route)
        self.assertEqual(narrow, checks)

    def test_the_requested_scopes_are_one_per_method(self):
        from stripe_link.google_calendar import DEFAULT_SCOPES

        self.assertEqual(sorted(DEFAULT_SCOPES), [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.owned",
            "https://www.googleapis.com/auth/calendar.freebusy",
        ])
        self.assertFalse(any(s.endswith("/calendar.readonly") for s in DEFAULT_SCOPES))
