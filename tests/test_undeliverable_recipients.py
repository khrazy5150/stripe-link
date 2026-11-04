"""We do not send to an address that can never receive (reported 2026-11-04).

The report: thousands of `Delivery Status Notification (Failure)` in the platform's own support mailbox,
every one of them for a webinar registration confirmation addressed to `jane@example.com`.

`example.com` is reserved by RFC 2606. It has no MX record and never will, so SES accepts the message,
retries for **840 minutes**, and returns a DSN. Nothing was wrong with the sender, the content or the
credentials — the recipient simply did not exist, and nothing in the path asked whether it could.

Lead capture validates NO email at all: `normalize_email` lowercases and strips. The address a visitor
types on a public form becomes a real SES send with a 14-hour retry budget. The business-email flow has
had `looks_like_email`, `is_disposable` and a Debounce check since it was written; the path that mails
STRANGERS had none of it.

So the gate goes at `send_email`, the single choke point every message already passes through — the same
reasoning that put the platform signature there: *"the next feature that mails something would forget,
and the whole point is that it is on everything."*
"""
import unittest

from stripe_link.domain.business_email import is_undeliverable
from stripe_link.mailer import EmailError, send_email


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m1"}


class ReservedDomainsCanNeverReceiveTests(unittest.TestCase):
    def test_the_address_from_the_report(self):
        self.assertTrue(is_undeliverable("jane@example.com"))

    def test_every_RFC_2606_reserved_name(self):
        for address in ("a@example.com", "a@example.net", "a@example.org", "a@example.edu",
                        "a@host.test", "a@host.invalid", "a@host.localhost", "a@box.local"):
            with self.subTest(address=address):
                self.assertTrue(is_undeliverable(address))

    def test_a_SUBDOMAIN_of_a_reserved_name_is_reserved_too(self):
        """RFC 2606 reserves the whole tree, not just the apex."""
        self.assertTrue(is_undeliverable("a@mail.example.com"))
        self.assertTrue(is_undeliverable("a@deep.sub.example.org"))

    def test_a_REAL_domain_that_merely_LOOKS_reserved_is_not(self):
        """The sharp edge. `examples.com` and `myexample.com` are domains somebody owns, and refusing
        their mail would be a worse bug than the one this fixes — a customer who never hears from us."""
        for address in ("b@examples.com", "c@myexample.com", "d@example.com.co", "e@exampleshop.com"):
            with self.subTest(address=address):
                self.assertFalse(is_undeliverable(address))

    def test_ordinary_addresses_are_untouched(self):
        for address in ("real@gmail.com", "ok@juniorbay.net", "a.b+tag@sub.company.co.uk"):
            with self.subTest(address=address):
                self.assertFalse(is_undeliverable(address))

    def test_something_that_is_not_an_address_at_all(self):
        """Nothing can be delivered to it either, and a typo should not buy a 14-hour retry."""
        for junk in ("notanemail", "", "   ", "@nodomain", "two@@at.com", "no-at-sign.com"):
            with self.subTest(junk=junk):
                self.assertTrue(is_undeliverable(junk))


class TheGateIsAtTheCHOKEPOINTTests(unittest.TestCase):
    """Not in lead capture, because this protects EVERY sender — receipts, invites, reminders, the
    lead-magnet download — and a per-caller check is one the next caller forgets."""

    def _send(self, to):
        client = FakeSes()
        send_email(to=to, subject="s", html="<p>h</p>", from_name="Quill", client=client)
        return client

    def test_a_reserved_recipient_is_REFUSED_before_SES_is_called(self):
        client = FakeSes()
        with self.assertRaises(EmailError) as caught:
            send_email(to="jane@example.com", subject="s", html="<p>h</p>", client=client)
        self.assertIn("cannot receive email", str(caught.exception))
        self.assertEqual(client.sent, [], "nothing may reach SES")

    def test_it_RAISES_rather_than_silently_dropping(self):
        """A caller that believes it sent something is how a tenant comes to think a customer was
        emailed. Every caller already treats a failed send as a failed send."""
        with self.assertRaises(EmailError):
            send_email(to="x@host.invalid", subject="s", text="t", client=FakeSes())

    def test_a_real_recipient_still_sends(self):
        self.assertEqual(len(self._send("buyer@gmail.com").sent), 1)

    def test_the_empty_recipient_message_is_unchanged(self):
        """It was already refused, for its own reason, and that reason still reads better than the new
        one for a caller that passed nothing at all."""
        with self.assertRaises(EmailError) as caught:
            send_email(to="", subject="s", html="<p>h</p>", client=FakeSes())
        self.assertIn("Recipient email is required", str(caught.exception))


class TheREGISTRATIONPathSurvivesTheRefusalTests(unittest.TestCase):
    """The lead is the tenant's asset; the confirmation is the thing that bounced. Refusing the send must
    not lose the registration — which is already how that path is written, and this checks it still is."""

    def test_a_failed_confirmation_is_caught_and_logged(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "leads.py").read_text(encoding="utf-8")
        block = source.split("def _send_registration_confirmation", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("except Exception as exc:", block)
        self.assertIn("logger.warning", block)
        self.assertIn("registration stored but confirmation not sent", block)


if __name__ == "__main__":
    unittest.main()
