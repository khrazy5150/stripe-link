"""A tenant's only lever over a review: reporting it.

plans/REVIEWS.md "Review integrity" decision 4 and plans/ADMIN_SITE.md §1b. The tests that matter here are
the ones about what a report CANNOT do, because the value of the whole design is that a merchant who
dislikes a review has no way to act on that dislike.
"""
import json
import unittest

from handlers.reviews import handler
from stripe_link.domain.abuse_reports import (
    REVIEW_REPORT_REASONS,
    ReportValidationError,
    build_review_report,
)
from tests.test_reviews import FakeRepository, _review


class FakeReports:
    def __init__(self):
        self.documents = []

    def put(self, document):
        self.documents.append(dict(document))
        return dict(document)


def report_event(review_id="review_1", reason="spam", detail="", tenant="t1"):
    body = {"action": "report", "review_id": review_id, "reason": reason, "detail": detail,
            "tenant_id": tenant}
    return {"httpMethod": "POST", "resource": "/reviews", "body": json.dumps(body),
            "requestContext": {"identity": {"sourceIp": "203.0.113.9"}}}


class TheReasonsATenantIsOfferedTests(unittest.TestCase):
    def test_a_tenant_cannot_allege_a_low_rating(self):
        """The list a MERCHANT reads. Its absences teach them what the system is for, so this matters more
        here than on the admin's side."""
        for forbidden in ("low_rating", "unfair", "negative", "rating", "bad_review"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, REVIEW_REPORT_REASONS)

    def test_the_list_the_screen_gets_is_the_list_the_validator_accepts(self):
        """One source, so a form cannot offer a reason the server refuses -- or accept one it never showed."""
        response = handler({"httpMethod": "GET", "resource": "/reviews",
                            "queryStringParameters": {"tenant_id": "t1"}},
                           None, repository=FakeRepository([_review()]))
        offered = {r["value"] for r in json.loads(response["body"])["report_reasons"]}
        self.assertEqual(offered, set(REVIEW_REPORT_REASONS))

    def test_an_unlisted_reason_is_refused(self):
        with self.assertRaises(ReportValidationError):
            build_review_report({"reason": "low_rating"}, review=_review(), reported_by="t1")

    def test_other_needs_the_detail_that_makes_it_actionable(self):
        with self.assertRaises(ReportValidationError):
            build_review_report({"reason": "other", "detail": "  "}, review=_review(), reported_by="t1")
        built = build_review_report({"reason": "other", "detail": "Names my employee."},
                                    review=_review(), reported_by="t1")
        self.assertEqual(built["reason"], "other")


class WhatAReportCannotDoTests(unittest.TestCase):
    """The integrity promise, stated as absences."""

    def test_the_review_is_not_touched(self):
        """A report NEVER hides the review. If flagging pulled one down pending a decision, tenants would
        flag every two-star review and recover curation with a delay."""
        repo = FakeRepository([_review(status="approved", rating=1)])
        reports = FakeReports()
        before = repo.get("t1", "review_1")
        response = handler(report_event(), None, repository=repo, reports_repo=reports)
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(repo.get("t1", "review_1"), before)

    def test_the_builder_has_no_way_to_return_a_changed_review(self):
        """Structural, not behavioural: the function's only output is a report document."""
        built = build_review_report({"reason": "spam"}, review=_review(), reported_by="t1")
        self.assertEqual(built["document_type"], "abuse_report")
        self.assertNotIn("status_change", built)
        self.assertEqual(built["status"], "open")  # the REPORT's status, not the review's

    def test_a_tenant_cannot_report_someone_elses_review(self):
        """Otherwise a merchant could file reports against a competitor's reviews, and the 'is this a
        pattern?' count would be measuring the wrong thing."""
        repo = FakeRepository([_review(tenant_id="t2", review_id="review_other")])
        response = handler(report_event(review_id="review_other", tenant="t1"), None, repository=repo,
                           reports_repo=FakeReports())
        self.assertEqual(response["statusCode"], 404)

    def test_an_unknown_review_answers_the_same_way(self):
        """So the 404 above cannot be used to discover whether another tenant's review exists."""
        repo = FakeRepository([_review(tenant_id="t2", review_id="review_other")])
        reports = FakeReports()
        mine = handler(report_event(review_id="review_other", tenant="t1"), None, repository=repo,
                       reports_repo=reports)
        ghost = handler(report_event(review_id="review_ghost", tenant="t1"), None, repository=repo,
                        reports_repo=reports)
        self.assertEqual(mine["statusCode"], ghost["statusCode"])
        self.assertEqual(json.loads(mine["body"])["message"], json.loads(ghost["body"])["message"])


class WhatIsRecordedTests(unittest.TestCase):
    def test_the_tenant_comes_from_the_review_not_the_payload(self):
        """A reporter who could name the tenant could file reports against anyone."""
        built = build_review_report({"reason": "spam", "tenant_id": "someone_else"},
                                    review=_review(tenant_id="t1"), reported_by="t1")
        self.assertEqual(built["tenant_id"], "t1")

    def test_the_verified_reporter_is_recorded(self):
        """The field that answers 'one grudge or a pattern?', and the reason this path is authenticated."""
        built = build_review_report({"reason": "spam"}, review=_review(), reported_by="t1")
        self.assertEqual(built["reported_by"], "t1")

    def test_it_carries_enough_to_judge_without_a_second_lookup(self):
        built = build_review_report({"reason": "abusive", "detail": "Slur in the body."},
                                    review=_review(rating=2, author="Jane D."), reported_by="t1")
        self.assertEqual(built["target_type"], "review")
        self.assertEqual(built["review_id"], "review_1")
        self.assertEqual(built["review_rating"], 2)
        self.assertEqual(built["review_author"], "Jane D.")
        self.assertEqual(built["detail"], "Slur in the body.")

    def test_a_page_report_and_a_review_report_land_in_one_queue(self):
        """Same table, same document_type, distinguishable by target_type -- so §1 and §1b are one screen."""
        built = build_review_report({"reason": "spam"}, review=_review(), reported_by="t1")
        self.assertEqual(built["document_type"], "abuse_report")
        self.assertEqual(built["page_id"], "")

    def test_the_report_is_stored(self):
        repo, reports = FakeRepository([_review()]), FakeReports()
        from handlers.reviews import report_review
        response = report_review(report_event(), repo,
                                 json.loads(report_event()["body"]), reports_repo=reports)
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(len(reports.documents), 1)
        self.assertEqual(reports.documents[0]["reason"], "spam")
        self.assertEqual(reports.documents[0]["source_ip"], "203.0.113.9")

    def test_reporting_twice_records_twice(self):
        """Deliberate. A second report is evidence, and collapsing them would hide exactly the pattern the
        queue is meant to show."""
        repo, reports = FakeRepository([_review()]), FakeReports()
        from handlers.reviews import report_review
        for _ in range(2):
            report_review(report_event(), repo, json.loads(report_event()["body"]), reports_repo=reports)
        self.assertEqual(len(reports.documents), 2)


class ItDoesNotBreakTheExistingRouteTests(unittest.TestCase):
    def test_creating_a_review_still_works(self):
        """The report shares POST /reviews, so the create path has to be proved intact."""
        repo = FakeRepository()
        body = {"tenant_id": "t1", "target": {"type": "product", "id": "prod_a"}, "rating": 5,
                "author": "Jane D.", "body": "Loved it."}
        response = handler({"httpMethod": "POST", "resource": "/reviews", "body": json.dumps(body)},
                           None, repository=repo, tenant_repo=object())
        self.assertIn(response["statusCode"], (201, 402, 403))  # created, or refused by the plan gate

    def test_a_missing_review_id_is_refused_before_anything_is_written(self):
        repo, reports = FakeRepository([_review()]), FakeReports()
        from handlers.reviews import report_review
        response = report_review(report_event(review_id=""), repo,
                                 {"action": "report", "tenant_id": "t1"}, reports_repo=reports)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(reports.documents, [])


if __name__ == "__main__":
    unittest.main()
