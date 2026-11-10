"""Losing a calendar connection must be said out loud.

Google never tells us a merchant or delegate removed the app; we find out the first time we try to use
the connection. Until 2026-11-10 that moment produced a status change and a log line and nothing else,
so the only symptom was that bookings had quietly stopped reaching a calendar -- and, worse, that the
delegate's busy times had stopped blocking slots, which keeps selling appointments to someone who has
left. The bell alone is not enough: this is invisible unless you are already looking at the dashboard.
"""
import unittest
from unittest import mock

from stripe_link import calendar_sync
from stripe_link.domain.notifications_content import (calendar_revoked_email,
                                                      calendar_revoked_notification)
from tests.fakes import FakeDocumentRepository

CONN = {"schema_version": "2026-05-29", "document_type": "calendar_connection", "tenant_id": "t1",
        "connection_id": "cal_1", "provider": "google", "status": "connected",
        "display_name": "Dana's calendar", "account_email": "dana@example.com",
        "refresh_token_ref": "enc:rt"}


class TheContentNamesTheCalendarAndTheConsequenceTests(unittest.TestCase):
    def test_the_notification_is_actionable(self):
        n = calendar_revoked_notification("t1", CONN, 1000)
        self.assertIn("Dana's calendar", n["message"])
        self.assertIn("block slots", n["message"])
        self.assertTrue(n["action"]["label"])
        self.assertEqual(n["notification_id"], "notif_calrevoked_cal_1",
                         "keyed on the connection so a repeating failure cannot repeat the alarm")

    def test_the_email_says_what_stopped_working_and_what_it_costs(self):
        c = calendar_revoked_email(CONN, business_name="Poliaxis", dashboard_url="https://d/services")
        self.assertIn("Dana's calendar", c["subject"])
        self.assertIn("block slots", c["text"])
        self.assertIn("https://d/services", c["html"])

    def test_it_falls_back_to_the_account_email_when_unnamed(self):
        c = calendar_revoked_email({"account_email": "dana@example.com"})
        self.assertIn("dana@example.com", c["subject"])


class MarkRevokedAnnouncesItTests(unittest.TestCase):
    def _revoke(self, **kw):
        repo = FakeDocumentRepository("connection_id")
        repo.put(dict(CONN))
        notes = FakeDocumentRepository("notification_id")
        sent = []
        with mock.patch.object(calendar_sync, "sending_identity", create=True), \
             mock.patch("stripe_link.sender_identity.sending_identity",
                        return_value={"reply_to": "owner@example.com", "business_name": "Poliaxis"}):
            result = calendar_sync.mark_revoked(
                "t1", "cal_1", connections_repo=repo, notifications_repo=notes,
                mailer_send=lambda **k: sent.append(k), **kw)
        return result, repo, notes, sent

    def test_the_token_is_dropped_the_status_set_and_the_tenant_told(self):
        ok, repo, notes, sent = self._revoke()
        self.assertTrue(ok)
        stored = repo.get("t1", "cal_1")
        self.assertEqual(stored["status"], "revoked")
        self.assertEqual(stored["refresh_token_ref"], "", "the dead credential must not be kept")
        self.assertEqual(len(notes.list_for_tenant("t1")), 1)
        self.assertEqual(len(sent), 1, "the bell alone is not enough")
        self.assertEqual(sent[0]["to"], "owner@example.com")

    def test_a_second_pass_does_not_alarm_again(self):
        """The sweep that uses a dead connection runs repeatedly; the tenant must be told once."""
        _ok, repo, notes, sent = self._revoke()
        again = calendar_sync.mark_revoked("t1", "cal_1", connections_repo=repo,
                                           notifications_repo=notes, mailer_send=lambda **k: sent.append(k))
        self.assertFalse(again, "already revoked")
        self.assertEqual(len(sent), 1)

    def test_a_failure_to_notify_never_breaks_the_revocation(self):
        """This runs inside an exception path that is about to re-raise. Recording the revocation is
        what stops us retrying a dead token, and must not be lost to a mail problem."""
        repo = FakeDocumentRepository("connection_id")
        repo.put(dict(CONN))

        def boom(**_kw):
            raise RuntimeError("SES is down")

        with mock.patch("stripe_link.sender_identity.sending_identity",
                        return_value={"reply_to": "owner@example.com", "business_name": "P"}):
            ok = calendar_sync.mark_revoked("t1", "cal_1", connections_repo=repo,
                                            notifications_repo=None, mailer_send=boom)
        self.assertTrue(ok)
        self.assertEqual(repo.get("t1", "cal_1")["status"], "revoked")


if __name__ == "__main__":
    unittest.main()


class WhoIsStillBookableTests(unittest.TestCase):
    """The distinction that must not be got backwards: a delegate with NO Google account is supported
    and fully bookable. Only a delegate whose LINKED calendar has broken is dangerous, because their
    busy times silently stop blocking and the platform keeps selling time they will not keep."""

    CONNS = [{"connection_id": "c_ok", "status": "connected"},
             {"connection_id": "c_dead", "status": "revoked"},
             {"connection_id": "c_off", "status": "disconnected"}]

    def _broken(self, fulfiller):
        from stripe_link.domain.calendar_routing import fulfiller_calendar_is_broken

        return fulfiller_calendar_is_broken(fulfiller, self.CONNS)

    def test_a_delegate_with_no_calendar_is_NOT_broken(self):
        self.assertFalse(self._broken({"fulfiller_id": "f1"}))
        self.assertFalse(self._broken({"fulfiller_id": "f1", "calendar_connection_id": ""}))

    def test_a_working_calendar_is_not_broken(self):
        self.assertFalse(self._broken({"fulfiller_id": "f2", "calendar_connection_id": "c_ok"}))

    def test_a_revoked_or_disconnected_link_is_broken(self):
        self.assertTrue(self._broken({"fulfiller_id": "f3", "calendar_connection_id": "c_dead"}))
        self.assertTrue(self._broken({"fulfiller_id": "f4", "calendar_connection_id": "c_off"}))

    def test_a_link_to_a_connection_that_no_longer_exists_is_broken(self):
        self.assertTrue(self._broken({"fulfiller_id": "f5", "calendar_connection_id": "c_gone"}))

    def test_the_filter_preserves_order_and_keeps_the_unlinked(self):
        from stripe_link.domain.calendar_routing import bookable_fulfiller_ids

        people = [{"fulfiller_id": "f1"},
                  {"fulfiller_id": "f2", "calendar_connection_id": "c_ok"},
                  {"fulfiller_id": "f3", "calendar_connection_id": "c_dead"}]
        self.assertEqual(bookable_fulfiller_ids(["f1", "f2", "f3"], people, self.CONNS), ["f1", "f2"])
