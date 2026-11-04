"""The test suite may not reach a real outbound channel. Ever.

**What this is for, measured 2026-11-04.** 5,678 `Delivery Status Notification (Failure)` had piled up in
the platform's own support mailbox. Two of them, opened: a webinar registration confirmation to
`jane@example.com`, and a subscription cancellation to `sam@example.com`. Those are not customer
addresses — they are the fixtures in `test_webinar_registration.py` and `test_purchase_self_service.py`.

**The test suite was sending real email through SES.** `tests/test_webinar_registration.py` posts to the
leads handler injecting every repository but no mailer, so `leads._send_registration_confirmation` falls
through to `mailer.send_email`, which with no `client` builds a real boto3 SES client from whatever AWS
credentials the developer happens to have. Each one then cost SES 840 minutes of retries and returned a
DSN. One day's traffic was 201 sent and 153 bounced — a 76% bounce rate, against a 10% suspension line.

Everything about the pattern fits and nothing else did: sends only during waking hours and never between
06:00 and 18:00 UTC; bursts of 3, 12, 24, 60 rather than a sweep's even cadence; no Lambda invocation
correlating; and no stored record anywhere in dev or prod carrying either address.

So the guard is here, autouse, at the only place that cannot be forgotten: a test that does not inject a
client gets a recorder instead of the network. It RECORDS rather than raising, because several handlers
deliberately swallow a failed send — raising would be indistinguishable from the behaviour they are
asserting, and would hide the thing it is meant to reveal.

`sent_emails` / `sent_texts` are exposed so a test can assert on what WOULD have gone out.
"""
import pytest

from stripe_link import mailer, sms


class RecordingClient:
    """Stands in for a boto3 client. Records the call and returns a plausible response."""

    def __init__(self, log, response):
        self._log = log
        self._response = dict(response)

    def send_email(self, **kwargs):
        self._log.append(kwargs)
        return dict(self._response)

    def send_text_message(self, **kwargs):
        self._log.append(kwargs)
        return dict(self._response)


@pytest.fixture(autouse=True)
def no_real_outbound(monkeypatch):
    """Replace the DEFAULT clients only.

    A test that passes `client=` of its own is untouched — that is how the mailer's own tests drive the
    real `send_email` against a fake, and they must keep working. This closes the path where nothing was
    passed at all, which is the one that reached AWS.
    """
    emails, texts = [], []
    monkeypatch.setattr(mailer, "_ses_client",
                        lambda: RecordingClient(emails, {"MessageId": "test-message-id"}))
    monkeypatch.setattr(sms, "_sms_client",
                        lambda: RecordingClient(texts, {"MessageId": "test-text-id"}))
    yield {"emails": emails, "texts": texts}


@pytest.fixture
def sent_emails(no_real_outbound):
    """What a test WOULD have emailed, for a test that wants to assert on it."""
    return no_real_outbound["emails"]


@pytest.fixture
def sent_texts(no_real_outbound):
    return no_real_outbound["texts"]
