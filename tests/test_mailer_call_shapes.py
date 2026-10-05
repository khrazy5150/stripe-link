"""Every mailer call must fit the real `send_email`.

A tenant marked two orders shipped and neither buyer heard anything. The shipments recorded why:

    notify_error: send_email() got an unexpected keyword argument 'to_address'

`shipment_notice.notify_buyer` had been calling `to_address` / `html_body` / `text_body`; the mailer takes
`to` / `html` / `text`. Every tracking email ever attempted died on a TypeError, which the caller caught
and stored as `notify_error` — correct behaviour that also meant nothing ever surfaced it.

**No test caught it because every test passes a `mailer_send` double that accepts anything.** That is the
same shape as the repository mismatch earlier in this work, where 5381 tests passed while a `put` was
being called with two arguments on a repository whose `put` takes one: a double written from the caller's
assumption can only ever confirm the assumption.

So this binds what the caller actually passes against the signature it will actually meet.
"""
import inspect
import unittest

from stripe_link.mailer import send_email

SIGNATURE = inspect.signature(send_email)


def _capture(send):
    """Run `send(spy)` and return the kwargs it tried to mail with."""
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)

    send(spy)
    return captured


class TheShipmentNoticeFitsTheMailerTests(unittest.TestCase):
    ORDER = {"customer": {"email": "buyer@example.com"}, "order_id": "order_1",
             "line_items": [{"name": "Workout Bundle"}]}
    SHIPMENT = {"carrier": "usps", "service": "ground_advantage", "tracking_number": "94001",
                "tracking_url": "https://example.test/94001"}

    def _kwargs(self, **extra):
        from stripe_link.domain.shipment_notice import notify_buyer

        return _capture(lambda spy: notify_buyer(self.ORDER, self.SHIPMENT, "t1", has_tracking=True,
                                                 mailer_send=spy, **extra))

    def test_it_binds_against_the_real_signature(self):
        SIGNATURE.bind(**self._kwargs())

    def test_it_uses_the_mailers_own_parameter_names(self):
        # Named explicitly, so a rename on either side fails here rather than in a tenant's inbox.
        self.assertEqual(sorted(self._kwargs()), ["html", "subject", "tenant_id", "text", "to"])

    def test_it_still_binds_with_an_arrival_line_and_a_note(self):
        SIGNATURE.bind(**self._kwargs(arrival_line="It should reach you on Monday, October 12.",
                                      tenant_note="We ran out of stock."))

    def test_the_old_names_are_gone(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "stripe_link" / "domain"
                  / "shipment_notice.py").read_text()
        for dead in ("to_address=", "html_body=", "text_body="):
            self.assertNotIn(dead, source)

    def test_a_buyer_with_no_email_is_reported_not_mailed(self):
        from stripe_link.domain.shipment_notice import notify_buyer

        out = notify_buyer({"customer": {}}, self.SHIPMENT, "t1", mailer_send=lambda **k: None)
        self.assertEqual(out["reason"], "no_customer_email")


class EveryOtherMailerCallerFitsTooTests(unittest.TestCase):
    """The same mistake is available to every caller, and the ones that work today only prove they were
    written while someone was looking at the signature."""

    def test_the_purchase_manage_senders_use_the_real_names(self):
        import pathlib
        import re

        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
                  / "purchase_manage.py").read_text()
        calls = re.findall(r"\(mailer_send or send_email\)\(([^)]*)", source, re.S)
        self.assertTrue(calls, "no mailer calls found; this test is watching nothing")
        for call in calls:
            self.assertIn("to=", call)
            self.assertNotIn("to_address=", call)

    def test_no_source_file_calls_the_mailer_with_the_wrong_names(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "src"
        offenders = []
        for path in sorted(root.rglob("*.py")):
            source = path.read_text()
            if "send_email" not in source:
                continue
            for dead in ("to_address=", "html_body=", "text_body="):
                if dead in source:
                    offenders.append(f"{path.relative_to(root.parent)}: {dead}")
        self.assertEqual(offenders, [], "\n".join(offenders))
