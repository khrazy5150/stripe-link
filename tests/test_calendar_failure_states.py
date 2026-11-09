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

    def test_the_ownership_check_survives_the_move_to_an_app_created_calendar(self):
        """Kept, though it now guards less than it did.

        While we requested `calendar.events.owned`, this check was what made that scope safe: a calendar
        merely shared with the merchant would have been accepted and then 403'd at the first booking.
        Bookings now go to a calendar the app creates, so no write reaches a merchant calendar at all and
        the check is belt alongside braces. It stays because `calendar_id` is still settable through the
        API, and a guard that costs nothing is not worth removing to tidy up.
        """
        import inspect

        self.assertIn("calendar_not_owned", inspect.getsource(calendar.update_connection_route))

    def test_no_requested_scope_reaches_a_calendar_we_did_not_create(self):
        """The exact set is pinned in test_bookings_calendar.py, which owns that design. What matters
        here is that nothing in it can write to a calendar the merchant already had."""
        from stripe_link.google_calendar import DEFAULT_SCOPES

        for scope in DEFAULT_SCOPES:
            self.assertFalse(scope.endswith("/calendar.readonly"))
            self.assertFalse(scope.endswith("/calendar.events"))
            self.assertFalse(scope.endswith("/calendar.events.owned"))


class RevocationIsOBSERVEDNotAssumedTests(unittest.TestCase):
    """Google does not tell us when a merchant revokes access.

    Until 2026-11-08 nothing acted on `invalid_grant`: the call failed, the booking did not sync, and the
    dead credential stayed encrypted in our table indefinitely — which made the privacy policy's claim
    that revoking leads to deletion untrue. We now learn of it on first use and delete the token then.
    """

    CONN = {"schema_version": "2026-05-29", "document_type": "calendar_connection", "tenant_id": "t1",
            "connection_id": "c1", "provider": "google", "status": "connected",
            "refresh_token_ref": "ENCRYPTED", "calendar_id": "primary"}

    def test_it_marks_revoked_and_DROPS_the_token(self):
        from stripe_link.calendar_sync import mark_revoked

        repo = mock.Mock()
        repo.get.return_value = dict(self.CONN)
        repo.put.side_effect = lambda d: d
        self.assertTrue(mark_revoked("t1", "c1", repo))
        saved = repo.put.call_args[0][0]
        self.assertEqual(saved["status"], "revoked")
        self.assertFalse(saved["refresh_token_ref"], "a credential Google has refused must not be kept")
        self.assertIn("revoked_at", saved)

    def test_it_is_idempotent(self):
        from stripe_link.calendar_sync import mark_revoked

        repo = mock.Mock()
        repo.get.return_value = {**self.CONN, "status": "revoked"}
        self.assertFalse(mark_revoked("t1", "c1", repo))
        repo.put.assert_not_called()

    def test_a_failure_to_record_does_not_swallow_the_real_error(self):
        """It runs inside an exception path that is about to re-raise. Losing the caller's error to
        report a bookkeeping failure would be the worse trade."""
        from stripe_link.calendar_sync import mark_revoked

        repo = mock.Mock()
        repo.get.side_effect = RuntimeError("table gone")
        self.assertFalse(mark_revoked("t1", "c1", repo))

    def test_a_revoked_connection_stops_resolving(self):
        """So nothing keeps retrying a token Google has already refused."""
        from stripe_link.calendar_sync import resolve_tenant_calendar

        repo = mock.Mock()
        repo.get.return_value = {**self.CONN, "status": "revoked"}
        self.assertIsNone(resolve_tenant_calendar("t1", connections_repo=repo,
                                                  connection={**self.CONN, "status": "revoked"}))

    def test_the_policy_and_the_code_agree_about_revocation(self):
        """The policy says we mark it revoked and delete the token on first use after revocation. If the
        code stops doing that, the policy becomes a false statement rather than a stale one."""
        import inspect

        from stripe_link import calendar_sync
        from stripe_link.domain.legal import default_pages

        source = inspect.getsource(calendar_sync._client_for)
        self.assertIn("GoogleCalendarReauthRequired", source)
        self.assertIn("mark_revoked", source)
        body = next(v for v in [p for p in default_pages() if p["page_id"] == "privacy"][0].values()
                    if isinstance(v, str) and "<h2>" in v)
        self.assertIn("mark it revoked and delete the stored token", body)


class APartialGrantIsNotAConnectionTests(unittest.TestCase):
    """Google shows each scope as its OWN unticked checkbox — granular consent, mandatory for OAuth
    clients created after 2019 and impossible to turn off. So a merchant can approve a subset and still
    complete the flow.

    Before 2026-11-08 the granted list was stored and never compared to what we asked for: the dashboard
    showed a healthy connection, and the first availability check 403'd with a customer waiting.
    """

    def test_the_required_set_is_exactly_what_we_request(self):
        """If DEFAULT_SCOPES changes and this does not, the check silently stops covering a scope."""
        from handlers.calendar import REQUIRED_SCOPE_LABELS
        from stripe_link.google_calendar import DEFAULT_SCOPES

        self.assertEqual(set(REQUIRED_SCOPE_LABELS), set(DEFAULT_SCOPES))

    def test_a_full_grant_passes(self):
        from handlers.calendar import missing_scopes
        from stripe_link.google_calendar import DEFAULT_SCOPES

        self.assertEqual(missing_scopes(DEFAULT_SCOPES), [])

    def test_a_partial_grant_names_what_is_missing(self):
        from handlers.calendar import missing_scopes

        absent = missing_scopes(["https://www.googleapis.com/auth/calendar.calendarlist.readonly"])
        self.assertEqual(len(absent), 2)
        self.assertIn("Make secondary Google calendars, and see, create, change, and delete events on them",
                      absent)

    def test_nothing_granted_reports_all_three(self):
        from handlers.calendar import missing_scopes

        self.assertEqual(len(missing_scopes([])), 3)

    def test_the_labels_are_GOOGLES_words_not_ours(self):
        """The merchant is going back to a screen carrying these exact sentences. 'calendar.freebusy was
        not granted' is not findable there."""
        from handlers.calendar import REQUIRED_SCOPE_LABELS

        for label in REQUIRED_SCOPE_LABELS.values():
            self.assertNotIn("googleapis.com", label)
            self.assertNotIn("calendar.", label)

    def test_the_callback_refuses_before_storing(self):
        """The refusal must come before the connection is written, or a broken connection outlives it."""
        import inspect

        from handlers import calendar

        source = inspect.getsource(calendar.callback_route)
        refusal = source.index("missing_scopes")
        store = source.index("refresh_token_ref")
        self.assertLess(refusal, store, "scope check must precede storing the connection")
