"""The guard that stops the test suite emailing real people (incident 2026-11-04).

5,678 Delivery Status Notifications accumulated in the platform's support mailbox. Two were opened: a
webinar registration confirmation to `jane@example.com` and a subscription cancellation to
`sam@example.com` — the fixtures in `test_webinar_registration.py` and `test_purchase_self_service.py`.
The suite had been sending real mail through SES for as long as those tests have existed, because a
handler that is given no mailer falls through to `mailer.send_email`, which with no `client` builds a real
boto3 client from the developer's own AWS credentials.

`tests/conftest.py` closes it. This file is the guard on the guard: conftest is easy to delete, reorder or
override, and the failure mode is silent — mail simply starts going out again, and nobody learns until a
mailbox fills up two weeks later.
"""
import unittest

import pytest

from stripe_link import mailer, sms


class TheDefaultClientIsNEVERBoto3Tests(unittest.TestCase):
    """The single fact everything else rests on."""

    def test_the_mailers_default_client_is_a_recorder(self):
        client = mailer._ses_client()
        self.assertEqual(type(client).__name__, "RecordingClient",
                         "tests/conftest.py is not in effect — the suite can email real people")
        self.assertFalse(hasattr(client, "meta"), "a boto3 client would carry .meta")

    def test_the_sms_default_client_is_a_recorder_too(self):
        self.assertEqual(type(sms._sms_client()).__name__, "RecordingClient")


class ASendWithNOClientIsRecordedNotSentTests(unittest.TestCase):
    """The exact shape of the bug: nothing injected anywhere."""

    def test_send_email_with_no_client_reaches_no_network(self):
        result = mailer.send_email(to="someone@acme.co", subject="s", html="<p>h</p>")
        self.assertEqual(result["MessageId"], "test-message-id")


def test_the_registration_path_records_instead_of_sending(sent_emails):
    """End to end through the handler that actually did this, with no mailer injected — exactly as
    `test_webinar_registration.py` calls it."""
    from handlers.leads import _send_registration_confirmation

    event = {"title": "Live training", "timezone": "UTC",
             "occurrences": [{"occurrence_id": "o1", "starts_at": 1_900_000_000, "duration_minutes": 60}]}
    _send_registration_confirmation(event, "o1", {"email": "jane@example.com", "name": "Jane"}, "t1")

    # Nothing left the process. The address is refused by `send_email`'s own gate before the client is
    # even reached, which is why this records zero rather than one — both protections are live, and this
    # asserts the OUTCOME they share.
    assert sent_emails == [], "a registration test must not reach the network"


def test_a_deliverable_address_is_recorded_so_a_test_can_assert_on_it(sent_emails):
    """The fixture is useful, not just defensive: a test can check what WOULD have gone out."""
    mailer.send_email(to="buyer@acme.co", subject="Your receipt", text="thanks")
    assert len(sent_emails) == 1
    assert sent_emails[0]["Destination"]["ToAddresses"] == ["buyer@acme.co"]


@pytest.mark.parametrize("address", ["jane@example.com", "sam@example.com"])
def test_the_two_addresses_from_the_incident_can_never_be_mailed(address):
    """Named explicitly. These are the two that actually bounced, and a regression on either is the
    incident repeating."""
    with pytest.raises(mailer.EmailError):
        mailer.send_email(to=address, subject="s", text="t")


if __name__ == "__main__":
    unittest.main()
