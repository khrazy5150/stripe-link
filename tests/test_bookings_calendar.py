"""Bookings live in a calendar the APP created (plans/GOOGLE_CALENDAR_APP_CREATED.md).

The point of the design is that `calendar.app.created` cannot reach a calendar the merchant already had,
so "we only touch our own events" stops being a promise a reviewer must trust and becomes a property of
the API. These tests pin the three things that make it work: the scopes, resolution by stored id, and the
two meanings of a 404.
"""
import unittest
from unittest import mock

from stripe_link.calendar_sync import BOOKINGS_CALENDAR_SUMMARY, resolve_bookings_calendar
from stripe_link.google_calendar import (DEFAULT_SCOPES, GoogleCalendarClient, GoogleCalendarError,
                                         GoogleCalendarNotFound)

CONN = {"schema_version": "2026-05-29", "document_type": "calendar_connection", "tenant_id": "t1",
        "connection_id": "c1", "provider": "google", "status": "connected"}


class TheScopesCannotReachTheirOtherCalendarsTests(unittest.TestCase):
    def test_the_three_scopes(self):
        self.assertEqual(sorted(DEFAULT_SCOPES), [
            "https://www.googleapis.com/auth/calendar.app.created",
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.freebusy",
        ])

    def test_no_scope_can_write_to_a_calendar_we_did_not_create(self):
        """THE POINT OF THE DESIGN. `calendar.events.owned` and `calendar.events` both reach calendars
        the merchant already had; `app.created` cannot."""
        for forbidden in ("calendar.events.owned", "calendar.events", "/auth/calendar.readonly",
                          "/auth/calendar\"", "calendar.calendars"):
            for scope in DEFAULT_SCOPES:
                self.assertFalse(scope.endswith(forbidden.strip('"')), f"{scope} is too broad")


class TheCalendarIsFoundByIdNotByNameTests(unittest.TestCase):
    def test_a_stored_id_that_still_exists_is_reused(self):
        client = mock.Mock()
        client.get_calendar.return_value = {"id": "cal-1"}
        self.assertEqual(resolve_bookings_calendar(client, {**CONN, "bookings_calendar_id": "cal-1"}),
                         ("cal-1", False))
        client.create_calendar.assert_not_called()

    def test_no_stored_id_creates_one_without_asking_google_first(self):
        client = mock.Mock()
        client.create_calendar.return_value = {"id": "cal-new"}
        calendar_id, created = resolve_bookings_calendar(client, dict(CONN))
        self.assertEqual((calendar_id, created), ("cal-new", True))
        client.get_calendar.assert_not_called()

    def test_a_deleted_calendar_is_replaced_and_the_new_id_stored(self):
        """The merchant deleted it outside the software. Nothing to clean up — it is already gone."""
        client = mock.Mock()
        client.get_calendar.side_effect = GoogleCalendarNotFound("gone")
        client.create_calendar.return_value = {"id": "cal-2"}
        repo = mock.Mock()
        calendar_id, created = resolve_bookings_calendar(
            client, {**CONN, "bookings_calendar_id": "cal-1"}, repo)
        self.assertEqual((calendar_id, created), ("cal-2", True))
        self.assertEqual(repo.put.call_args[0][0]["bookings_calendar_id"], "cal-2")

    def test_the_name_is_never_used_to_find_it(self):
        """A merchant who renames it to 'Appointments' must not end up with two calendars and bookings
        split across them."""
        import inspect

        source = inspect.getsource(resolve_bookings_calendar)
        self.assertNotIn("summary", source.split('"""')[2])

    def test_the_summary_is_human_readable(self):
        self.assertEqual(BOOKINGS_CALENDAR_SUMMARY, "Junior Bay Bookings")
        self.assertNotIn("-", BOOKINGS_CALENDAR_SUMMARY)

    def test_a_failure_to_store_does_not_lose_the_calendar(self):
        """It exists in Google now. Reporting a bookkeeping failure would strand it."""
        client = mock.Mock()
        client.create_calendar.return_value = {"id": "cal-3"}
        repo = mock.Mock()
        repo.put.side_effect = RuntimeError("table gone")
        self.assertEqual(resolve_bookings_calendar(client, dict(CONN), repo), ("cal-3", True))

    def test_a_create_that_returns_no_id_is_an_error(self):
        client = mock.Mock()
        client.create_calendar.return_value = {}
        with self.assertRaises(GoogleCalendarError):
            resolve_bookings_calendar(client, dict(CONN))


class AvailabilitySpansRealCalendarsTests(unittest.TestCase):
    def test_free_busy_accepts_several_calendars_in_one_query(self):
        """Querying only the bookings calendar would see our own appointments and none of the merchant's
        real commitments — the opposite of the point."""
        sent = {}

        def transport(method, url, headers, body):
            sent["body"] = body
            return 200, "{}"

        client = GoogleCalendarClient("tok", calendar_id="bookings")
        with mock.patch.object(client, "_request",
                               side_effect=lambda m, p, body=None, base=None: sent.update(body=body)):
            client.free_busy("a", "b", ["primary", "work", "bookings"])
        self.assertEqual([i["id"] for i in sent["body"]["items"]], ["primary", "work", "bookings"])

    def test_it_falls_back_to_the_connection_calendar(self):
        sent = {}
        client = GoogleCalendarClient("tok", calendar_id="bookings")
        with mock.patch.object(client, "_request",
                               side_effect=lambda m, p, body=None, base=None: sent.update(body=body)):
            client.free_busy("a", "b")
        self.assertEqual([i["id"] for i in sent["body"]["items"]], ["bookings"])


class TheTwoMeaningsOfA404Tests(unittest.TestCase):
    def test_a_cancelled_event_that_is_already_gone_is_success(self):
        from stripe_link.calendar_sync import sync_appointment_event

        client = mock.Mock()
        client.delete_event.side_effect = GoogleCalendarNotFound("gone")
        client.calendar_id = "bookings"
        appt = {"tenant_id": "t1", "external_calendar_events": [
            {"provider": "google", "connection_id": "c1", "event_id": "e1"}]}
        with mock.patch("stripe_link.calendar_sync._client_for", return_value=(client, "c1", "bookings")):
            self.assertEqual(sync_appointment_event(appt, action="delete"), [])

    def test_a_reschedule_recreates_an_event_that_vanished(self):
        """The thing it meant to move is missing; put the appointment back rather than fail."""
        from stripe_link.calendar_sync import sync_appointment_event

        client = mock.Mock()
        client.update_event.side_effect = GoogleCalendarNotFound("gone")
        client.create_event.return_value = {"id": "e2"}
        client.calendar_id = "bookings"
        appt = {"tenant_id": "t1", "start_at": "2026-11-09T18:00:00Z", "end_at": "2026-11-09T19:00:00Z",
                "external_calendar_events": [
                    {"provider": "google", "connection_id": "c1", "event_id": "e1"}]}
        with mock.patch("stripe_link.calendar_sync._client_for", return_value=(client, "c1", "bookings")):
            result = sync_appointment_event(appt, action="upsert")
        client.create_event.assert_called_once()
        self.assertEqual([e["event_id"] for e in result], ["e2"])


if __name__ == "__main__":
    unittest.main()


class ALegacyConnectionIsNotDraggedIntoTheNewDesignTests(unittest.TestCase):
    """A connection granted before this change holds `calendar.events.owned` and NOT
    `calendar.app.created`. Asking it to create a calendar gets a 403, and `sync_appointment_event`
    swallows its own failures -- so its bookings would stop reaching any calendar at all, with nothing
    anywhere saying so. It keeps writing to `calendar_id` until the merchant reconnects.
    """

    def _client_for(self, scopes):
        from stripe_link import calendar_sync

        conn = {**CONN, "calendar_id": "me@gmail.com", "refresh_token_ref": "enc:rt", "scopes": scopes}
        creds = {"connection_id": "c1", "client_id": "cid", "client_secret": "sec", "refresh_token": "rt",
                 "calendar_id": "me@gmail.com", "bookings_calendar_id": "", "connection": conn}
        with mock.patch.object(calendar_sync, "resolve_tenant_calendar", return_value=creds), \
             mock.patch.object(calendar_sync, "fetch_access_token", return_value="ya29"), \
             mock.patch.object(calendar_sync, "resolve_bookings_calendar") as resolve:
            resolve.return_value = ("cal-new", True)
            client, _, bookings = calendar_sync._client_for(
                "t1", connections_repo=mock.Mock(), secret_cipher=None, google_secret={}, opener=None)
        return client, bookings, resolve

    def test_without_the_app_created_scope_no_calendar_is_created(self):
        client, bookings, resolve = self._client_for(
            ["https://www.googleapis.com/auth/calendar.events.owned"])
        resolve.assert_not_called()
        self.assertEqual(bookings, "")
        self.assertEqual(client.calendar_id, "me@gmail.com")

    def test_scopes_absent_entirely_also_counts_as_not_granted(self):
        """`feedback_absence_reads_as_safety`: the oldest records have no `scopes` at all, and absence
        must not read as permission."""
        _client, bookings, resolve = self._client_for([])
        resolve.assert_not_called()
        self.assertEqual(bookings, "")

    def test_with_the_app_created_scope_writes_move_to_the_bookings_calendar(self):
        client, bookings, resolve = self._client_for(
            ["https://www.googleapis.com/auth/calendar.app.created"])
        resolve.assert_called_once()
        self.assertEqual(bookings, "cal-new")
        self.assertEqual(client.calendar_id, "cal-new")


class AnEventIsAddressedWhereItLivesTests(unittest.TestCase):
    """Moving the write target redirects every update and delete of an event created before the move.
    The call then reports success against a calendar the event was never in, and the real event stays in
    the merchant's calendar forever."""

    def _sync(self, action, appt_entry):
        from stripe_link.calendar_sync import sync_appointment_event

        client = mock.Mock()
        client.calendar_id = "cal-bookings"
        client.create_event.return_value = {"id": "e9"}
        appt = {"tenant_id": "t1", "start_at": "2026-11-09T18:00:00Z", "end_at": "2026-11-09T19:00:00Z",
                "external_calendar_events": [appt_entry]}
        with mock.patch("stripe_link.calendar_sync._client_for",
                        return_value=(client, "c1", "cal-bookings")):
            sync_appointment_event(appt, action=action)
        return client

    def test_a_cancellation_deletes_from_the_old_calendar(self):
        client = self._sync("delete", {"provider": "google", "connection_id": "c1",
                                       "calendar_id": "me@gmail.com", "event_id": "e1"})
        self.assertEqual(client.delete_event.call_args.kwargs["calendar_id"], "me@gmail.com")

    def test_a_reschedule_updates_in_the_old_calendar(self):
        client = self._sync("upsert", {"provider": "google", "connection_id": "c1",
                                      "calendar_id": "me@gmail.com", "event_id": "e1"})
        self.assertEqual(client.update_event.call_args.args[2]
                         if len(client.update_event.call_args.args) > 2
                         else client.update_event.call_args.kwargs["calendar_id"], "me@gmail.com")

    def test_an_entry_with_no_calendar_id_falls_back_to_the_current_one(self):
        client = self._sync("delete", {"provider": "google", "connection_id": "c1", "event_id": "e1"})
        self.assertEqual(client.delete_event.call_args.kwargs["calendar_id"], "")


class AvailabilityCoversBothHalvesTests(unittest.TestCase):
    """Without the merchant's real calendars we offer slots they are committed for; without the bookings
    calendar two customers take the same slot. Querying only the bookings calendar -- the naive reading of
    "bookings live in their own calendar" -- gets the second half and loses the first."""

    def _ids(self, items, bookings="cal-bookings"):
        from stripe_link.calendar_sync import availability_calendar_ids

        client = mock.Mock()
        client.calendar_list.return_value = {"items": items}
        return availability_calendar_ids(client, bookings)

    def test_owned_and_writable_calendars_block_slots(self):
        ids = self._ids([{"id": "me@gmail.com", "accessRole": "owner"},
                         {"id": "shop@gmail.com", "accessRole": "writer"}])
        self.assertEqual(ids, ["me@gmail.com", "shop@gmail.com", "cal-bookings"])

    def test_a_subscribed_holiday_calendar_does_NOT_close_the_business(self):
        """All-day events on "Holidays in United States" would otherwise mark every public holiday fully
        busy -- a read-only calendar the merchant WATCHES, not a commitment of their time."""
        ids = self._ids([{"id": "me@gmail.com", "accessRole": "owner"},
                         {"id": "en.usa#holiday@group.v.calendar.google.com", "accessRole": "reader"},
                         {"id": "moon@group.v.calendar.google.com", "accessRole": "freeBusyReader"}])
        self.assertEqual(ids, ["me@gmail.com", "cal-bookings"])

    def test_the_bookings_calendar_is_appended_even_when_calendarlist_omits_it(self):
        """Whether an app-created calendar appears in `calendarList` under these scopes is not something
        to discover from a double booking."""
        self.assertIn("cal-bookings", self._ids([{"id": "me@gmail.com", "accessRole": "owner"}]))

    def test_it_is_not_listed_twice_when_calendarlist_does_include_it(self):
        ids = self._ids([{"id": "cal-bookings", "accessRole": "owner"}])
        self.assertEqual(ids, ["cal-bookings"])

    def test_a_failed_list_still_blocks_on_our_own_bookings(self):
        client = mock.Mock()
        client.calendar_list.side_effect = GoogleCalendarError("boom")
        from stripe_link.calendar_sync import availability_calendar_ids
        self.assertEqual(availability_calendar_ids(client, "cal-bookings"), ["cal-bookings"])


class TheReadPathNeverCreatesACalendarTests(unittest.TestCase):
    def test_availability_does_not_create(self):
        """The slot picker is a PUBLIC page. Creating a calendar is a write, and two customers opening it
        at once with nothing stored yet would create two."""
        from stripe_link import calendar_sync

        calls = {}
        with mock.patch.object(calendar_sync, "_client_for", return_value=(None, None, "")) as cf:
            calendar_sync.tenant_busy_intervals("t1", "a", "b")
            calls.update(cf.call_args.kwargs)
        self.assertIs(calls["create_bookings_calendar"], False)

    def test_a_cancellation_does_not_create_one_either(self):
        """If there is no bookings calendar there is no event in one to remove."""
        from stripe_link import calendar_sync

        with mock.patch.object(calendar_sync, "_client_for", return_value=(None, None, "")) as cf:
            calendar_sync.sync_appointment_event({"tenant_id": "t1"}, action="delete")
        self.assertIs(cf.call_args.kwargs["create_bookings_calendar"], False)

    def test_an_upsert_DOES_create(self):
        from stripe_link import calendar_sync

        with mock.patch.object(calendar_sync, "_client_for", return_value=(None, None, "")) as cf:
            calendar_sync.sync_appointment_event({"tenant_id": "t1"}, action="upsert")
        self.assertIs(cf.call_args.kwargs["create_bookings_calendar"], True)


class ASettingThatChangesNothingIsRefusedTests(unittest.TestCase):
    """There is no calendar to pick any more: the only calendar our scopes can write to is the one the
    app created. Accepting `calendar_id` would store a value that reads back correctly and does nothing.
    """

    def _patch(self, conn):
        import json

        from handlers.calendar import handler
        from tests.fakes import FakeDocumentRepository

        repo = FakeDocumentRepository("connection_id")
        repo.put(conn)
        return handler({"httpMethod": "PATCH", "path": "/calendar/connections/c1",
                        "queryStringParameters": {"tenant_id": "t1"},
                        "pathParameters": {"connection_id": "c1"},
                        "body": json.dumps({"calendar_id": "someone-else@gmail.com"})},
                       None, connections_repo=repo)

    def test_a_current_connection_refuses_the_redirect(self):
        import json

        resp = self._patch({**CONN, "bookings_calendar_id": "cal-1", "calendar_id": "me@gmail.com"})
        self.assertEqual(resp["statusCode"], 409)
        self.assertEqual(json.loads(resp["body"])["error"], "calendar_not_selectable")

    def test_display_name_still_works_on_a_current_connection(self):
        import json

        from handlers.calendar import handler
        from tests.fakes import FakeDocumentRepository

        repo = FakeDocumentRepository("connection_id")
        repo.put({**CONN, "bookings_calendar_id": "cal-1", "account_email": "me@gmail.com"})
        resp = handler({"httpMethod": "PATCH", "path": "/calendar/connections/c1",
                        "queryStringParameters": {"tenant_id": "t1"},
                        "pathParameters": {"connection_id": "c1"},
                        "body": json.dumps({"display_name": "Salon"})}, None, connections_repo=repo)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["connection"]["display_name"], "Salon")


class ALegacyConnectionsAvailabilityIsLeftAloneTests(unittest.TestCase):
    """Moving to the new design must not quietly start closing slots on a tenant who has not reconnected:
    their events are in `calendar_id` and that is the whole picture."""

    def test_only_the_stored_calendar_is_queried(self):
        from stripe_link import calendar_sync

        client = mock.Mock()
        client.calendar_id = "me@gmail.com"
        client.free_busy.return_value = {"calendars": {"me@gmail.com": {"busy": [{"start": "a", "end": "b"}]}}}
        with mock.patch.object(calendar_sync, "_client_for", return_value=(client, "c1", "")):
            busy = calendar_sync.tenant_busy_intervals("t1", "a", "b")
        self.assertEqual(client.free_busy.call_args.args[2], ["me@gmail.com"])
        client.calendar_list.assert_not_called()
        self.assertEqual(busy, [{"start": "a", "end": "b"}])

    def test_a_current_connection_queries_both_halves(self):
        from stripe_link import calendar_sync

        client = mock.Mock()
        client.calendar_id = "cal-bookings"
        client.calendar_list.return_value = {"items": [{"id": "me@gmail.com", "accessRole": "owner"}]}
        client.free_busy.return_value = {"calendars": {
            "me@gmail.com": {"busy": [{"start": "09:00", "end": "10:00"}]},
            "cal-bookings": {"busy": [{"start": "14:00", "end": "15:00"}]}}}
        with mock.patch.object(calendar_sync, "_client_for", return_value=(client, "c1", "cal-bookings")):
            busy = calendar_sync.tenant_busy_intervals("t1", "a", "b")
        self.assertEqual(client.free_busy.call_args.args[2], ["me@gmail.com", "cal-bookings"])
        self.assertEqual(len(busy), 2)


class ARescheduleAcrossTheMigrationTests(unittest.TestCase):
    def _reschedule(self, lives_in, error):
        from stripe_link.calendar_sync import sync_appointment_event

        client = mock.Mock()
        client.calendar_id = "cal-bookings"
        client.update_event.side_effect = error
        client.create_event.return_value = {"id": "e2"}
        appt = {"tenant_id": "t1", "start_at": "2026-11-09T18:00:00Z", "end_at": "2026-11-09T19:00:00Z",
                "external_calendar_events": [{"provider": "google", "connection_id": "c1",
                                              "calendar_id": lives_in, "event_id": "e1"}]}
        with mock.patch("stripe_link.calendar_sync._client_for",
                        return_value=(client, "c1", "cal-bookings")):
            return client, sync_appointment_event(appt, action="upsert")

    def test_an_unreachable_old_calendar_recreates_the_booking_where_we_can_write(self):
        """A pre-migration event sits in the merchant's primary calendar, which our only grant can no
        longer touch. A silent no-op would leave their calendar showing the OLD time while the platform
        shows the new one, and they turn up at the wrong one."""
        client, result = self._reschedule("me@gmail.com", GoogleCalendarError("403"))
        client.create_event.assert_called_once()
        self.assertEqual([e["event_id"] for e in result], ["e2"])
        self.assertEqual(result[0]["calendar_id"], "cal-bookings")

    def test_a_failure_on_the_CURRENT_calendar_is_not_papered_over_with_a_duplicate(self):
        """Same calendar, so retrying as a create would just add a second event beside the first."""
        client, result = self._reschedule("cal-bookings", GoogleCalendarError("500"))
        client.create_event.assert_not_called()
        self.assertIsNone(result)


class TheTokenCarriesONLYWhatWeAskForTests(unittest.TestCase):
    """`include_granted_scopes=true` makes Google issue a token covering every scope the account ever
    granted this app. A merchant who connected before the narrowing kept handing us
    `calendar.events.owned` on every reconnect -- a scope we do not request and the console does not
    declare -- so the API-level guarantee quietly became a promise about our code again."""

    def _url(self):
        from stripe_link.google_calendar import build_consent_url

        return build_consent_url("cid", "https://example.com/cb", "state123")

    def test_include_granted_scopes_is_not_requested(self):
        self.assertNotIn("include_granted_scopes", self._url())

    def test_the_url_asks_for_exactly_the_three(self):
        from urllib.parse import parse_qs, urlparse

        from stripe_link.google_calendar import DEFAULT_SCOPES

        asked = parse_qs(urlparse(self._url()).query)["scope"][0].split()
        self.assertEqual(sorted(asked), sorted(DEFAULT_SCOPES))
        self.assertNotIn("https://www.googleapis.com/auth/calendar.events.owned", asked)

    def test_consent_is_still_forced_so_a_refresh_token_comes_back(self):
        """Removing one parameter must not take `prompt=consent` with it: without it Google withholds
        the refresh token on a repeat authorisation and the connection dies at the first renewal."""
        url = self._url()
        self.assertIn("prompt=consent", url)
        self.assertIn("access_type=offline", url)


class ADisconnectIsRecoverableTests(unittest.TestCase):
    """Disconnect used to delete the whole connection, which cost two things at once: an accidental
    disconnect could not be undone, and the stored `bookings_calendar_id` went with it -- so reconnecting
    had nothing to match on and built a SECOND "Junior Bay Bookings" calendar beside the first,
    identically named and distinguishable only by id (observed on a live account 2026-11-09).
    """

    def _connect(self, connections, calendar):
        from tests.test_calendar import _connect as connect_once

        return connect_once(connections, "a@gmail.com", calendar=calendar)

    def _disconnect(self, connections, connection_id):
        from handlers.calendar import handler

        return handler({"httpMethod": "DELETE", "path": "/calendar/connections/x",
                        "queryStringParameters": {"tenant_id": "t1"},
                        "pathParameters": {"connection_id": connection_id}},
                       None, connections_repo=connections)

    def test_reconnecting_after_a_disconnect_reuses_the_SAME_calendar(self):
        import os

        from tests.fakes import FakeDocumentRepository

        os.environ["CALENDAR_REDIRECT_URI"] = "https://dev.example.com/calendar/callback"
        connections = FakeDocumentRepository("connection_id")
        first = self._connect(connections, {"id": "cal_original@group.calendar.google.com"})
        self.assertEqual(first["bookings_calendar_id"], "cal_original@group.calendar.google.com")

        self._disconnect(connections, first["connection_id"])
        # A second calendar is offered; it must NOT be taken, because the stored one still resolves.
        again = self._connect(connections, {"id": "cal_SHOULD_NOT_BE_USED@group.calendar.google.com"})

        self.assertEqual(again["bookings_calendar_id"], "cal_original@group.calendar.google.com")
        self.assertEqual(again["connection_id"], first["connection_id"],
                         "the same Google account must reuse its row, not mint a new one")
        self.assertEqual(again["status"], "connected")
        self.assertEqual(len(connections.list_for_tenant("t1")), 1, "no duplicate connection")

    def test_the_credential_really_is_gone_while_disconnected(self):
        """Recoverable must not mean 'still usable'. The token is what grants access, and it is
        destroyed at the moment of disconnect."""
        import os

        from stripe_link.calendar_sync import resolve_tenant_calendar
        from tests.fakes import FakeDocumentRepository
        from tests.test_calendar import FakeCipher, GOOGLE_SECRET

        os.environ["CALENDAR_REDIRECT_URI"] = "https://dev.example.com/calendar/callback"
        connections = FakeDocumentRepository("connection_id")
        conn = self._connect(connections, {"id": "cal_x@group.calendar.google.com"})
        self._disconnect(connections, conn["connection_id"])

        stored = connections.get("t1", conn["connection_id"])
        self.assertEqual(stored["refresh_token_ref"], "")
        self.assertIsNone(resolve_tenant_calendar("t1", connections_repo=connections,
                                                  secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET))
