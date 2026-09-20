"""Reporting an abusive page.

plans/CREATOR_LINK_POLICY.md §6, the last unbuilt step of the policy that gates `jbay.page` -- and it was
still unbuilt when the domain went live on 2026-09-19, which §8 explicitly ordered the other way round
("Report + takedown. Before jbay.page serves anything, not after.").

The doc's framing is the test list: "A registrar does not ask whether you have an interstitial. It asks what
you do when someone abuses the domain."
"""
import pathlib
import unittest

from handlers.abuse_reports import handler
from stripe_link.domain.abuse_reports import (
    HONEYPOT_FIELD, MAX_REASON_LEN, REPORT_REASONS, ReportValidationError, build_abuse_report,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeRepo:
    def __init__(self, page=None):
        self.written = []
        self._page = page

    def put(self, doc):
        self.written.append(doc)
        return doc

    def find_by_id(self, _id):
        return self._page


PAGE = {"page_id": "page_1", "tenant_id": "t1", "status": "published"}


def _post(body, repo=None, pages=None):
    return handler({"httpMethod": "POST", "body": __import__("json").dumps(body)}, None,
                   repository=repo or FakeRepo(), pages_repo=pages or FakeRepo(PAGE), now=1)


class SubmissionTests(unittest.TestCase):
    def test_a_report_is_recorded(self):
        repo = FakeRepo()
        resp = _post({"page_id": "page_1", "reason": "spam", "detail": "links to malware"}, repo=repo)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(len(repo.written), 1)
        self.assertEqual(repo.written[0]["reason"], "spam")
        self.assertEqual(repo.written[0]["status"], "open")

    def test_the_tenant_is_resolved_from_the_page_never_from_the_payload(self):
        """A reporter who could name the tenant could file reports against anyone."""
        repo = FakeRepo()
        _post({"page_id": "page_1", "reason": "spam", "tenant_id": "someone-else"}, repo=repo)
        self.assertEqual(repo.written[0]["tenant_id"], "t1")

    def test_a_reason_is_required_and_must_be_one_we_can_act_on(self):
        resp = _post({"page_id": "page_1", "reason": "vibes"})
        self.assertEqual(resp["statusCode"], 400)

    def test_other_needs_words(self):
        # The catch-all is useless without them, and it is the only reason that carries the whole complaint.
        self.assertEqual(_post({"page_id": "page_1", "reason": "other"})["statusCode"], 400)
        self.assertEqual(_post({"page_id": "page_1", "reason": "other", "detail": "sells my photos"})["statusCode"], 200)

    def test_the_reason_list_is_served_rather_than_duplicated_in_the_page(self):
        resp = handler({"httpMethod": "GET"}, None, repository=FakeRepo(), pages_repo=FakeRepo(PAGE))
        body = __import__("json").loads(resp["body"])
        self.assertEqual({r["value"] for r in body["reasons"]}, set(REPORT_REASONS))


class AbuseSurfaceTests(unittest.TestCase):
    """The report endpoint is itself public, so it is guarded like POST /leads."""

    def test_a_bot_that_fills_the_honeypot_is_answered_normally_and_stored_nowhere(self):
        repo = FakeRepo()
        resp = _post({"page_id": "page_1", "reason": "spam", HONEYPOT_FIELD: "http://x"}, repo=repo)
        self.assertEqual(resp["statusCode"], 200)          # telling a bot it was caught teaches the bot
        self.assertEqual(repo.written, [])

    def test_an_unknown_page_is_answered_exactly_like_a_known_one(self):
        repo = FakeRepo()
        resp = handler({"httpMethod": "POST", "body": '{"page_id":"nope","reason":"spam"}'}, None,
                       repository=repo, pages_repo=FakeRepo(None))
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(repo.written, [])

    def test_free_text_is_capped(self):
        report = build_abuse_report({"reason": "other", "detail": "x" * 9000},
                                    page_id="p", tenant_id="t", host="h", now=1)
        self.assertEqual(len(report["detail"]), MAX_REASON_LEN)

    def test_the_response_hands_back_no_identifier(self):
        # Nothing for the reporter to do with it, and ids invite probing for other people's.
        import json

        body = json.loads(_post({"page_id": "page_1", "reason": "spam"})["body"])
        self.assertEqual(body, {"received": True})

    def test_the_endpoint_is_throttled_at_the_api(self):
        """Handler-side limiting still pays for the invocation it rejects."""
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = template.split("ResourcePath: /report", 1)[1].split("\n\n", 1)[0]
        self.assertIn("ThrottlingRateLimit", block)
        self.assertIn("ThrottlingBurstLimit", block)

    def test_it_cannot_write_to_the_pages_table(self):
        # It reads a page to learn whose it is; anything more would make a public endpoint a write surface.
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = template.split("AbuseReportsFunction:", 1)[1].split("PagesFunction:", 1)[0]
        self.assertIn("DynamoDBReadPolicy", block)
        self.assertNotIn("DynamoDBCrudPolicy:\n            TableName: !Ref PagesTable", block)


class FooterLinkTests(unittest.TestCase):
    def setUp(self):
        from stripe_link.runtime import html as html_module

        self.html = html_module
        self.state = dict(html_module._RENDER_STATE)

    def tearDown(self):
        self.html._RENDER_STATE.clear()
        self.html._RENDER_STATE.update(self.state)

    def test_a_link_hub_on_our_domain_carries_one(self):
        self.html._RENDER_STATE["report_page_id"] = "page_1"
        self.assertIn("Report this page", self.html.report_link("https://api.example"))

    def test_and_nothing_else_does(self):
        """Set only for a link hub not on the tenant's own verified domain -- their page, their reputation."""
        self.html._RENDER_STATE["report_page_id"] = ""
        self.assertEqual(self.html.report_link("https://api.example"), "")

    def test_the_decision_is_made_once_where_the_page_shape_is_known(self):
        source = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        block = source.split('_RENDER_STATE["report_page_id"] = (', 1)[1].split("    )", 1)[0]
        self.assertIn('composition_key(offer or {}) == "lead_social"', block)
        self.assertIn('not _RENDER_STATE["own_domain"]', block)


if __name__ == "__main__":
    unittest.main()
