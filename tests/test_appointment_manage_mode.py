"""A buyer's appointment-manage link must work whichever books the booking is in.

These routes are PUBLIC: the buyer arrives from a link in their own confirmation, with no session and no
dashboard toggle, so `resolve_stripe_mode` falls back to "test". `find_by_id` is mode-scoped — its
GSI1PK carries the mode — so a LIVE appointment would have answered "Appointment not found" to the
person who booked it.

Nothing links here yet. That is the point: the same mistake was already made twice on links that WERE
live (the receipt's download link, the review invite), and whoever builds this link later has no reason
to know the mode must ride along.
"""
import json
import unittest

from handlers.booking import _authorized_appointment

LIVE_APPOINTMENT = {"appointment_id": "appt_1", "tenant_id": "t1", "stripe_mode": "live",
                    "customer_manage_token": "tok_secret", "status": "confirmed"}


class Repo:
    def __init__(self, mode, rows):
        self.mode = mode
        self.rows = rows

    def find_by_id(self, appointment_id):
        return next((dict(r) for r in self.rows if r["appointment_id"] == appointment_id), None)


class TheLookupTests(unittest.TestCase):
    def test_a_live_appointment_is_found_from_a_test_defaulted_request(self):
        """The regression. The repo is built from the request, which has no mode and defaults to test."""
        found, err = _authorized_appointment(
            Repo("test", []), "appt_1", "tok_secret", other_mode_repo=Repo("live", [LIVE_APPOINTMENT]))
        self.assertIsNone(err)
        self.assertEqual(found["appointment_id"], "appt_1")

    def test_the_first_mode_still_wins_when_it_has_the_record(self):
        found, err = _authorized_appointment(
            Repo("live", [LIVE_APPOINTMENT]), "appt_1", "tok_secret",
            other_mode_repo=Repo("test", []))
        self.assertIsNone(err)
        self.assertEqual(found["stripe_mode"], "live")

    def test_an_unknown_appointment_is_still_a_404(self):
        _, err = _authorized_appointment(Repo("test", []), "ghost", "tok", other_mode_repo=Repo("live", []))
        self.assertEqual(err["statusCode"], 404)

    def test_no_appointment_id_does_not_search_at_all(self):
        _, err = _authorized_appointment(Repo("test", []), "", "tok", other_mode_repo=Repo("live", []))
        self.assertEqual(err["statusCode"], 404)


class TheTokenIsStillTheControlTests(unittest.TestCase):
    """Searching both modes grants nothing on its own: the opaque token is what authorises, and the mode
    was never the security boundary."""

    def test_a_wrong_token_is_refused_even_when_the_record_is_found(self):
        _, err = _authorized_appointment(
            Repo("test", []), "appt_1", "WRONG", other_mode_repo=Repo("live", [LIVE_APPOINTMENT]))
        self.assertEqual(err["statusCode"], 403)
        self.assertEqual(json.loads(err["body"])["error"], "forbidden")

    def test_an_empty_token_is_refused(self):
        _, err = _authorized_appointment(
            Repo("test", []), "appt_1", "", other_mode_repo=Repo("live", [LIVE_APPOINTMENT]))
        self.assertEqual(err["statusCode"], 403)

    def test_a_broken_fallback_does_not_fail_the_request(self):
        class Exploding:
            mode = "live"

            def find_by_id(self, _):
                raise RuntimeError("throttled")

        _, err = _authorized_appointment(Repo("test", []), "appt_1", "tok", other_mode_repo=Exploding())
        self.assertEqual(err["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
