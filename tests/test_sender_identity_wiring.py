"""The three emitters that resolved the sender from DEAD FIELDS, now wired to the resolver.

`TenantProfile.business_name` and `TenantProfile.support_email` are empty on every tenant and in every
environment — measured 2026-09-23, when the receipt was moved off them. Three senders were never moved and
kept reading them, so they went out with no business name and no reply address at all:

- the INVOICE email,
- the staff DELEGATION notice (the person being assigned work was told about it by nobody in particular),
- the lead-magnet DOWNLOAD email, which read the profile directly rather than asking anything.

These tests patch the resolver and assert on what each emitter asks it, because none of the three has a
repository injection seam for Sites — so the question "did it ask, and with what?" is the one a test can
answer without a live table (plans/SITE_AS_BUSINESS_IDENTITY.md §4).
"""
import json
import unittest
from unittest import mock

QUILL = {"business_name": "Quill", "reply_to": "hi@quill.test", "organization": {"name": "Quill"},
         "source": "site"}


class TheInvoiceAsksTheResolverTests(unittest.TestCase):
    def test_the_invoice_email_is_signed_by_the_resolver_not_the_profile(self):
        """The fixture profile still carries `business_name: Acme` in the dead field. If the handler were
        still reading it, "Acme" would appear instead of "Quill"."""
        import handlers.invoices as invoices_handler
        from tests.test_invoicing import FakeCipher, SendInvoiceHandlerTests, _FakeOpener

        env = SendInvoiceHandlerTests()
        invoices, stripe_repo, tenant_repo = env._env()
        opener = _FakeOpener({"id": "cus_1"}, {"id": "ii_1"}, {"id": "in_1"},
                             {"id": "in_1", "hosted_invoice_url": "https://pay.stripe.com/x"})
        sent = {}
        seen = {}

        def resolver(tenant_id, **kwargs):
            seen.update({"tenant_id": tenant_id, **kwargs})
            return dict(QUILL)

        with mock.patch.object(invoices_handler, "sending_identity", resolver):
            response = invoices_handler.handler(
                env._event(), None, repository=invoices, stripe_repo=stripe_repo, tenant_repo=tenant_repo,
                secret_cipher=FakeCipher(), opener=opener,
                mailer_send=lambda **kw: sent.update(kw) or {"MessageId": "m1"},
                billing_config_loader=lambda: {})

        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertEqual(sent["from_name"], "Quill")
        self.assertEqual(sent["reply_to"], "hi@quill.test")
        self.assertIn("Quill", sent["subject"])
        self.assertEqual(seen["tenant_id"], "t1")
        self.assertEqual(seen["mode"], "test")

    def test_it_asks_with_NO_page_because_an_invoice_is_raised_in_the_dashboard(self):
        """Stated so the absence is a decision rather than an omission: there is no page to narrow it, so a
        single-Site tenant gets their Site and a multi-Site tenant gets the tenant-level answer."""
        import handlers.invoices as invoices_handler
        from tests.test_invoicing import FakeCipher, SendInvoiceHandlerTests, _FakeOpener

        env = SendInvoiceHandlerTests()
        invoices, stripe_repo, tenant_repo = env._env()
        seen = {}
        with mock.patch.object(invoices_handler, "sending_identity",
                               lambda tenant_id, **kw: seen.update(kw) or dict(QUILL)):
            invoices_handler.handler(
                env._event(), None, repository=invoices, stripe_repo=stripe_repo, tenant_repo=tenant_repo,
                secret_cipher=FakeCipher(),
                opener=_FakeOpener({"id": "cus_1"}, {"id": "ii_1"}, {"id": "in_1"},
                                   {"id": "in_1", "hosted_invoice_url": "https://p/x"}),
                mailer_send=lambda **kw: {"MessageId": "m"}, billing_config_loader=lambda: {})
        self.assertNotIn("page_id", seen)


class TheDelegationNoticeAsksTheResolverTests(unittest.TestCase):
    def _run(self, appointment_extra=None):
        import stripe_link.delegation as delegation
        from tests.test_delegation import GOOGLE_SECRET, ApplyDelegationTests, FakeCipher, _FakeOpener

        env = ApplyDelegationTests()
        appt, appointments, services, fulfillers, tenants, conns = env._env()
        appt.update(appointment_extra or {})
        sent, seen = {}, {}

        def resolver(tenant_id, **kwargs):
            seen.update({"tenant_id": tenant_id, **kwargs})
            return dict(QUILL)

        with mock.patch.object(delegation, "sending_identity", resolver):
            delegation.apply_delegation(
                appt, action="upsert", change="booked", appointments_repo=appointments,
                services_repo=services, fulfillers_repo=fulfillers, connections_repo=conns,
                tenant_repo=tenants, mailer_send=lambda **kw: sent.update(kw),
                secret_cipher=FakeCipher(), google_secret=GOOGLE_SECRET,
                opener=_FakeOpener({"access_token": "ya29"}, {"id": "evt_1"}))
        return sent, seen

    def test_the_staff_notice_carries_a_business_name_at_all(self):
        sent, _seen = self._run()
        self.assertEqual(sent["from_name"], "Quill")
        self.assertEqual(sent["reply_to"], "hi@quill.test")

    def test_a_booking_taken_through_CHECKOUT_names_its_page(self):
        """The webhook's booking record stamps `page_id` and `stripe_mode` from the checkout metadata, so a
        booking bought on a page resolves to that page's business."""
        _sent, seen = self._run({"page_id": "page_qui", "stripe_mode": "test"})
        self.assertEqual(seen["page_id"], "page_qui")
        self.assertEqual(seen["mode"], "test")

    def test_a_booking_taken_any_other_way_resolves_LIVE_with_no_page(self):
        _sent, seen = self._run()
        self.assertEqual(seen["page_id"], "")
        self.assertEqual(seen["mode"], "live")


class TheLeadMagnetDownloadAsksTheResolverTests(unittest.TestCase):
    """This one keeps its own Reply-To gate: the email may only go out from a VERIFIED address, and that
    gate is the whole reason the block exists. Only the NAME comes from the Site."""

    def _call(self, organization):
        import handlers.downloads as downloads
        from tests.test_lead_download import ASSET, FakeMailer, VERIFIED_PROFILE, call, page

        mailer = FakeMailer()
        seen = {}

        def resolver(tenant_id, **kwargs):
            seen.update({"tenant_id": tenant_id, **kwargs})
            return dict(organization)

        with mock.patch.object(downloads, "site_organization", resolver):
            response = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb",
                             "fields": {"email": "visitor@example.com"}},
                            doc=page({"action": "email_file", "asset": ASSET}), mailer=mailer,
                            profile=VERIFIED_PROFILE)
        return response, mailer, seen

    def test_the_SITE_names_the_delivery_email(self):
        """The profile says "Poliaxis Nutrition"; the page belongs to Quill, and Quill is who delivers."""
        response, mailer, _seen = self._call({"name": "Quill"})
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertEqual(mailer.sent[0]["from_name"], "Quill")

    def test_the_REPLY_ADDRESS_is_still_the_gated_verified_one(self):
        _response, mailer, _seen = self._call({"name": "Quill", "email": "anyone@quill.test"})
        self.assertEqual(mailer.sent[0]["reply_to"], "owner@poliaxis.co")

    def test_it_asks_about_THIS_PAGE(self):
        _response, _mailer, seen = self._call({"name": "Quill"})
        self.assertEqual(seen["page_id"], "p1")
        self.assertEqual(seen["tenant_id"], "t1")

    def test_a_page_with_no_site_falls_back_to_the_profile_name(self):
        _response, mailer, _seen = self._call({})
        self.assertEqual(mailer.sent[0]["from_name"], "Poliaxis Nutrition")


class NoEmitterReadsTheDeadFieldsAnyMoreTests(unittest.TestCase):
    """The fields are still ON the profile until §P4 removes them, so nothing stops a new sender reading
    them again. This is what notices."""

    ALLOWED = {
        # The dashboard's own profile screens, which still EDIT the fields §P4 will remove.
        "src/handlers/profile.py",
        # The receipt's last-resort fallback, kept deliberately: "it is where a business name WOULD live
        # if one were ever written there, and preferring it over an empty answer costs nothing".
        "src/handlers/stripe_webhook.py",
    }

    # Names that hold the RESOLVER's answer rather than a profile document. `identity["business_name"]`
    # is the whole point of this work; `profile.get("business_name")` is the bug.
    RESOLVED = {"identity", "context", "content", "kw", "kwargs", "seen", "QUILL"}

    def test_no_sender_resolves_its_name_from_TenantProfile_business_name(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        pattern = re.compile(r"(\w+)\.get\(\"(business_name|support_email)\"")
        offenders = []
        for path in sorted((root / "src").rglob("*.py")):
            rel = str(path.relative_to(root))
            if rel in self.ALLOWED:
                continue
            source = path.read_text()
            # Any tenant-authored MESSAGE, not just email: the appointment reminder is an SMS, and it
            # read the dead field for as long as it existed.
            if not any(w in source for w in ("send_email", "mailer_send", "send_sms", "sms_send")):
                continue
            for receiver, field in pattern.findall(source):
                if receiver not in self.RESOLVED:
                    offenders.append(f"{rel}: {receiver}.get({field!r})")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_guard_is_watching_something(self):
        """It would pass vacuously if the pattern matched nothing — the failure mode the env-var guard
        actually had."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        pattern = re.compile(r"(\w+)\.get\(\"(business_name|support_email)\"")
        hits = [m for p in (root / "src").rglob("*.py") for m in pattern.findall(p.read_text())]
        self.assertTrue(hits, "the pattern matches nothing; the guard is watching nothing")


if __name__ == "__main__":
    unittest.main()
