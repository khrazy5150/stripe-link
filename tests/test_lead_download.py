"""A Page Ribbon's downloadable file, and the gate in front of it.

The property that matters: the PAGE decides what a visitor must provide, never the request. A browser
sends whatever it likes, so a gate that trusts the payload is not a gate — a visitor would skip the form by
omitting the field it asks for.
"""

import json
import os
import unittest

os.environ.setdefault("MEDIA_BUCKET", "test-media-bucket")

from stripe_link.domain.lead_magnets import download_offer, find_ribbon, missing_fields
from stripe_link.domain.leads import HONEYPOT_FIELD
from handlers.downloads import lead_download_handler

ASSET = {"bucket_key": "downloads/t1/page/p1/a1/guide.pdf", "filename": "guide.pdf"}


def page(cta):
    return {"page_id": "p1", "offer_id": "off1",
            "sections": [{"id": "rb", "type": "page_ribbon", "cta": cta}]}


class FakeRepo:
    def __init__(self, doc=None):
        self.doc, self.puts = doc, []

    def get(self, *_args):
        return self.doc

    def put(self, item):
        self.puts.append(item)


class FakeS3:
    def generate_presigned_url(self, *_a, **kw):
        return "https://signed/" + kw["Params"]["Key"]


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, **kw):
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kw)
        return {"MessageId": "m1"}


def call(body, *, doc, leads=None, s3=None, mailer=None):
    return lead_download_handler(
        {"httpMethod": "POST", "body": json.dumps(body)}, None,
        pages_repo=FakeRepo(doc), leads_repo=leads or FakeRepo(), s3_client=s3 or FakeS3(),
        mailer_send=mailer or FakeMailer(), now_fn=lambda: 1700000000,
    )


class DomainTests(unittest.TestCase):
    def test_a_section_of_another_type_is_not_a_download(self):
        # section_id is client-supplied; pointing it at a content block must not reach the download path.
        doc = {"sections": [{"id": "rb", "type": "content_block"}]}
        self.assertIsNone(find_ribbon(doc, "rb"))

    def test_a_ribbon_with_another_action_offers_nothing(self):
        self.assertIsNone(download_offer({"cta": {"action": "redirect", "asset": ASSET}}))

    def test_a_download_ribbon_with_no_file_offers_nothing(self):
        self.assertIsNone(download_offer({"cta": {"action": "download"}}))

    def test_whitespace_is_not_an_answer(self):
        self.assertEqual(missing_fields(["email"], {"email": "   "}), ["email"])


class GateTests(unittest.TestCase):
    def test_ungated_download_needs_nothing(self):
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb"},
                   doc=page({"action": "download", "asset": ASSET}))
        self.assertEqual(res["statusCode"], 200)
        self.assertIn("signed/", res["body"])

    def test_a_required_field_cannot_be_skipped_by_omitting_it(self):
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb"},
                   doc=page({"action": "download", "collect_email": True, "asset": ASSET}))
        self.assertEqual(res["statusCode"], 400)
        self.assertIn("email", res["body"])

    def test_both_fields_are_enforced_when_both_are_asked_for(self):
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb",
                    "fields": {"email": "a@b.co"}},
                   doc=page({"action": "download", "collect_email": True, "collect_phone": True, "asset": ASSET}))
        self.assertEqual(res["statusCode"], 400)
        self.assertIn("phone", res["body"])

    def test_a_satisfied_gate_records_a_lead_and_returns_the_file(self):
        leads = FakeRepo()
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb",
                    "fields": {"email": "a@b.co"}},
                   doc=page({"action": "download", "collect_email": True, "asset": ASSET}), leads=leads)
        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(len(leads.puts), 1)
        self.assertEqual(leads.puts[0]["fields"]["email"], "a@b.co")

    def test_an_ungated_download_records_no_lead(self):
        leads = FakeRepo()
        call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb"},
             doc=page({"action": "download", "asset": ASSET}), leads=leads)
        self.assertEqual(leads.puts, [], "nothing was asked for, so there is nothing to record")

    def test_a_missing_page_or_section_is_a_404_not_a_signed_url(self):
        for doc in (None, {"sections": []}):
            with self.subTest(doc=doc):
                res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb"}, doc=doc)
                self.assertEqual(res["statusCode"], 404)


class WiringTests(unittest.TestCase):
    """The tests above inject fake repositories, so they never call the real constructors — which is how
    `leads_repository(mode=...)` reached production and failed with a TypeError on every gated download.
    Injecting a dependency proves the logic and proves nothing about the wiring."""

    def test_the_repository_constructors_accept_what_the_handler_passes(self):
        import inspect
        from stripe_link.repositories.documents import leads_repository, pages_repository
        # pages IS mode-scoped; leads is NOT. The handler must not assume they are alike.
        self.assertIn("mode", inspect.signature(pages_repository).parameters)
        self.assertNotIn("mode", inspect.signature(leads_repository).parameters)

    def test_the_handler_calls_them_the_way_they_are_declared(self):
        import inspect
        from handlers import downloads
        src = inspect.getsource(downloads.lead_download_handler)
        self.assertIn("leads_repository()", src)
        self.assertIn("pages_repository(mode=mode)", src)


class EmailDeliveryTests(unittest.TestCase):
    """Same asset, same signed URL, same lead — the section decides whether a browser follows the link now
    or an inbox does later. A LINK, never an attachment: SES caps a message at 40MB including base64, which
    inflates binary by about a third, so a 30MB file cannot be attached at all."""

    CTA = {"action": "email_file", "asset": ASSET}

    def test_an_email_address_is_always_required_whatever_the_checkboxes_say(self):
        # There is nowhere to send it otherwise. A property of the delivery, not a tenant preference.
        self.assertEqual(download_offer({"cta": self.CTA})["required"], ["email"])
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb"}, doc=page(self.CTA))
        self.assertEqual(res["statusCode"], 400)

    def test_it_emails_a_link_and_returns_no_url(self):
        mailer = FakeMailer()
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb", "fields": {"email": "a@b.co"}},
                   doc=page(self.CTA), mailer=mailer)
        self.assertEqual(res["statusCode"], 200)
        self.assertIn("sent", res["body"])
        self.assertNotIn("signed/", res["body"], "the browser must not be handed the file directly")
        self.assertEqual(mailer.sent[0]["to"], "a@b.co")
        self.assertIn("signed/", mailer.sent[0]["html"], "the link goes in the email")

    def test_the_email_carries_no_attachment(self):
        mailer = FakeMailer()
        call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb", "fields": {"email": "a@b.co"}},
             doc=page(self.CTA), mailer=mailer)
        self.assertNotIn("attachment", str(mailer.sent[0].keys()))
        self.assertIn("24 hours", mailer.sent[0]["text"])

    def test_the_lead_is_recorded_before_the_send(self):
        leads, mailer = FakeRepo(), FakeMailer()
        call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb", "fields": {"email": "a@b.co"}},
             doc=page(self.CTA), leads=leads, mailer=mailer)
        self.assertEqual(leads.puts[0]["fields"]["email"], "a@b.co")

    def test_a_failed_send_tells_the_visitor(self):
        # Unlike a download, they have no way to notice nothing arrived — so this must not fail quietly.
        leads = FakeRepo()
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb", "fields": {"email": "a@b.co"}},
                   doc=page(self.CTA), leads=leads, mailer=FakeMailer(fail=True))
        self.assertEqual(res["statusCode"], 502)
        self.assertEqual(len(leads.puts), 1, "the tenant keeps the contact either way")


class SpamTests(unittest.TestCase):
    """Deliberately unlike POST /leads, which accepts-and-drops. Dropping here would deny a real visitor
    their file on a false positive — and the file is a lead MAGNET, meant to be given away. The leads list
    is what is worth protecting."""

    def test_a_flagged_request_still_gets_the_file_but_writes_no_lead(self):
        leads = FakeRepo()
        res = call({"tenant_id": "t1", "page_id": "p1", "section_id": "rb",
                    "fields": {"email": "a@b.co"}, HONEYPOT_FIELD: "http://spam.example"},
                   doc=page({"action": "download", "collect_email": True, "asset": ASSET}), leads=leads)
        self.assertEqual(res["statusCode"], 200)
        self.assertIn("signed/", res["body"])
        self.assertEqual(leads.puts, [])


if __name__ == "__main__":
    unittest.main()
