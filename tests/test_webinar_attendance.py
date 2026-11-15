"""Who actually watched, and how far they got (plans/AUTO_WEBINAR.md P4).

Two things here are easy to get subtly wrong and impossible to notice afterwards, because the only symptom
is a number a tenant believes.

**Position is not attendance.** An auto-webinar seats a late arrival at the live edge, so somebody joining
forty minutes in starts at 2400 seconds having watched nothing at all. Crediting position as watch time
would report the latest arrivals as the most engaged audience in the room.

**The first beacon of a sitting measures nothing.** There is no interval yet, so crediting one would hand
every drive-by visitor a free chunk of attendance.
"""
import secrets
import unittest

from stripe_link.domain.leads import (
    ATTENDANCE_GAP_SECONDS,
    attendance_token,
    build_lead_submission,
    record_attendance,
)

NOW = 1_800_000_000


def _lead(**overrides):
    base = build_lead_submission(
        tenant_id="ten_1", lead_id="lead_1", offer_id="off_1", page_id="page_1",
        fields={"email": "jane@example.com"}, consent={}, provenance={},
        idempotency_key="idem_1", now=NOW, event_id="evt_1", occurrence_id="occ_1",
    )
    base.update(overrides)
    return base


class WhatCountsAsWatchingTests(unittest.TestCase):
    def test_the_first_beacon_credits_nothing(self):
        lead = record_attendance(_lead(), position=0, now=NOW)
        self.assertEqual(lead["attendance"]["watched_seconds"], 0)
        self.assertEqual(lead["attendance"]["first_seen_at"], NOW)

    def test_the_second_beacon_credits_the_interval(self):
        lead = record_attendance(_lead(), position=0, now=NOW)
        lead = record_attendance(lead, position=30, now=NOW + 30)
        self.assertEqual(lead["attendance"]["watched_seconds"], 30)

    def test_a_late_arrival_is_not_credited_for_the_part_they_missed(self):
        # Joining forty minutes in: position 2400, watched 0. The whole trap in one test.
        lead = record_attendance(_lead(), position=2400, now=NOW)
        self.assertEqual(lead["attendance"]["watched_seconds"], 0)
        self.assertEqual(lead["attendance"]["furthest_position"], 2400)

    def test_a_gap_longer_than_the_tolerance_is_not_credited(self):
        # They closed the tab and came back an hour later. The hour is not watch time.
        lead = record_attendance(_lead(), position=0, now=NOW)
        lead = record_attendance(lead, position=60, now=NOW + ATTENDANCE_GAP_SECONDS + 1)
        self.assertEqual(lead["attendance"]["watched_seconds"], 0)

    def test_an_ordinary_hiccup_is_forgiven(self):
        lead = record_attendance(_lead(), position=0, now=NOW)
        lead = record_attendance(lead, position=60, now=NOW + ATTENDANCE_GAP_SECONDS - 1)
        self.assertEqual(lead["attendance"]["watched_seconds"], ATTENDANCE_GAP_SECONDS - 1)

    def test_furthest_position_never_goes_backwards(self):
        # They seek back to re-hear something. How deep they got does not un-happen.
        lead = record_attendance(_lead(), position=1800, now=NOW)
        lead = record_attendance(lead, position=600, now=NOW + 30)
        self.assertEqual(lead["attendance"]["furthest_position"], 1800)

    def test_it_never_mutates_the_lead_it_was_given(self):
        original = _lead()
        record_attendance(original, position=99, now=NOW)
        self.assertNotIn("attendance", original)


class TheTokenTests(unittest.TestCase):
    def test_every_registration_gets_one(self):
        self.assertTrue(attendance_token(_lead()))

    def test_two_registrations_do_not_share_one(self):
        self.assertNotEqual(attendance_token(_lead()), attendance_token(_lead()))

    def test_a_lead_without_one_cannot_be_written_to(self):
        self.assertEqual(attendance_token({"lead_id": "lead_old"}), "")


class _FakeRepo:
    def __init__(self, lead=None):
        self.lead = lead
        self.written = None

    def get(self, tenant_id, lead_id):
        return self.lead

    def put(self, document):
        self.written = document


def _beacon(**body):
    import json

    return {"httpMethod": "POST", "body": json.dumps(body)}


class TheBeaconTests(unittest.TestCase):
    def setUp(self):
        from handlers.leads import record_attendance_beacon

        self.call = record_attendance_beacon
        self.lead = _lead()
        self.token = attendance_token(self.lead)

    def test_a_good_beacon_is_recorded(self):
        repo = _FakeRepo(self.lead)
        response = self.call(_beacon(tenant_id="ten_1", lead_id="lead_1", attend_token=self.token,
                                     position=120), leads_repo=repo, now=NOW + 30)
        self.assertEqual(response["statusCode"], 202)
        self.assertEqual(repo.written["attendance"]["furthest_position"], 120)

    def test_a_wrong_token_writes_nothing_and_says_nothing(self):
        repo = _FakeRepo(self.lead)
        response = self.call(_beacon(tenant_id="ten_1", lead_id="lead_1",
                                     attend_token=secrets.token_urlsafe(16), position=120),
                             leads_repo=repo, now=NOW)
        self.assertEqual(response["statusCode"], 202)
        self.assertIsNone(repo.written)

    def test_an_unknown_registration_is_indistinguishable_from_a_known_one(self):
        # The endpoint must not become an oracle for which registrations exist.
        missing = _FakeRepo(None)
        known = _FakeRepo(self.lead)
        a = self.call(_beacon(tenant_id="ten_1", lead_id="nope", attend_token=self.token),
                      leads_repo=missing, now=NOW)
        b = self.call(_beacon(tenant_id="ten_1", lead_id="lead_1", attend_token=self.token),
                      leads_repo=known, now=NOW)
        self.assertEqual(a, b)

    def test_a_malformed_body_is_shrugged_off(self):
        repo = _FakeRepo(self.lead)
        response = self.call({"httpMethod": "POST", "body": "{nonsense"}, leads_repo=repo, now=NOW)
        self.assertEqual(response["statusCode"], 202)
        self.assertIsNone(repo.written)

    def test_a_repository_failure_never_reaches_the_viewer(self):
        class Broken(_FakeRepo):
            def get(self, *a):
                raise RuntimeError("table gone")

        response = self.call(_beacon(tenant_id="ten_1", lead_id="lead_1", attend_token=self.token),
                             leads_repo=Broken(), now=NOW)
        self.assertEqual(response["statusCode"], 202)


class ItRidesTheExistingEndpointTests(unittest.TestCase):
    def test_a_registration_post_is_still_a_registration(self):
        from handlers.leads import _is_attendance_beacon

        self.assertFalse(_is_attendance_beacon(_beacon(tenant_id="ten_1", offer_id="off_1")))

    def test_a_beacon_is_told_apart_by_its_payload(self):
        from handlers.leads import _is_attendance_beacon

        self.assertTrue(_is_attendance_beacon(_beacon(attend_token="abc")))

    def test_the_view_beacon_was_left_trivial(self):
        """It was the first design and the grant guard refused it: /t/view is kept deliberately small
        ("the floor matters more than any single handler: it is paid 74 times"), and reaching the leads
        table from there dragged ten tables into it."""
        import pathlib

        page_view = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
                     / "page_view.py").read_text(encoding="utf-8")
        self.assertNotIn("leads", page_view.lower())

class TheConfirmationCarriesWhoYouAreTests(unittest.TestCase):
    """An auto event has no join_url and never will, so without a watch link the confirmation promised a
    link that was never coming -- and the registrant cannot tell that from an oversight until the session
    has already run."""

    def setUp(self):
        from handlers.leads import _watch_url

        self.url = _watch_url
        self.auto = {"delivery": "auto", "title": "The class"}

    def test_an_auto_event_gets_a_watch_link_naming_the_registrant(self):
        self.assertEqual(
            self.url(self.auto, "https://shop.example/webinar", "lead_1", "tok_1"),
            "https://shop.example/webinar?r=lead_1&k=tok_1",
        )

    def test_a_live_event_keeps_its_own_join_link(self):
        self.assertEqual(self.url({"delivery": "live"}, "https://shop.example/w", "lead_1", "tok_1"), "")

    def test_a_half_built_link_is_no_link(self):
        # Promising something that does not work is worse than promising nothing.
        for args in (("https://shop.example/w", "", "tok_1"),
                     ("https://shop.example/w", "lead_1", ""),
                     ("", "lead_1", "tok_1")):
            with self.subTest(args=args):
                self.assertEqual(self.url(self.auto, *args), "")

    def test_the_referer_is_not_trusted_just_because_it_arrived(self):
        # It is attacker-controlled: it decides where a confirmation email points.
        for hostile in ("javascript:alert(1)", "http://shop.example/w", "data:text/html,x", "/relative"):
            with self.subTest(url=hostile):
                self.assertEqual(self.url(self.auto, hostile, "lead_1", "tok_1"), "")

    def test_the_link_is_rebuilt_rather_than_concatenated(self):
        # A query or fragment already on the page URL must not survive into the one we send.
        built = self.url(self.auto, "https://shop.example/w?utm=x#frag", "lead_1", "tok_1")
        self.assertEqual(built, "https://shop.example/w?r=lead_1&k=tok_1")

    def test_the_watch_link_wins_over_a_stale_join_url(self):
        from stripe_link.domain.registration_email import registration_confirmation

        event = {"title": "The class", "join_url": "https://zoom.example/j/1", "duration_minutes": 60}
        sitting = {"occurrence_id": "occ_1", "starts_at": NOW, "timezone": "UTC"}
        message = registration_confirmation(event, sitting, watch_url="https://shop.example/w?r=a&k=b")
        self.assertIn("shop.example", message["text"])
        self.assertNotIn("zoom.example", message["text"])


if __name__ == "__main__":
    unittest.main()
