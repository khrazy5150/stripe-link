import json
import unittest

from handlers.reviews import handler
from stripe_link.domain.documents import DocumentValidationError, validate_review
from stripe_link.domain.reviews import aggregate_reviews, markup_eligible


class FakeRepository:
    def __init__(self, documents=None):
        self.documents = {(d["tenant_id"], d["review_id"]): dict(d) for d in (documents or [])}

    def put(self, document):
        self.documents[(document["tenant_id"], document["review_id"])] = dict(document)
        return dict(document)

    def get(self, tenant_id, review_id):
        doc = self.documents.get((tenant_id, review_id))
        return dict(doc) if doc else None

    def delete(self, tenant_id, review_id):
        return self.documents.pop((tenant_id, review_id), None)

    def list_for_tenant(self, tenant_id):
        return [dict(d) for (t, _), d in self.documents.items() if t == tenant_id]


def _review(**overrides):
    base = {
        "schema_version": "2026-07-23", "document_type": "review", "tenant_id": "t1",
        "review_id": "review_1", "target": {"type": "product", "id": "prod_a"},
        "rating": 5, "author": "Jane D.", "body": "Loved it.", "status": "approved", "source": "manual",
    }
    base.update(overrides)
    return base


class ReviewValidationTests(unittest.TestCase):
    def test_valid_review_passes(self):
        validate_review(_review())

    def test_rating_must_be_1_to_5_int(self):
        for bad in (0, 6, 4.5, True, "5"):
            with self.assertRaises(DocumentValidationError):
                validate_review(_review(rating=bad))

    def test_target_requires_type_and_id(self):
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(target={"type": "product"}))
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(target={"type": "planet", "id": "x"}))

    def test_author_and_body_required(self):
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(author=""))
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(body=""))

    def test_status_and_source_enums(self):
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(status="live"))
        with self.assertRaises(DocumentValidationError):
            validate_review(_review(source="yelp"))


class ReviewAggregateTests(unittest.TestCase):
    def test_only_approved_first_party_are_eligible(self):
        reviews = [
            _review(review_id="a", rating=5),
            _review(review_id="b", rating=4),
            _review(review_id="c", rating=1, status="pending"),
            _review(review_id="d", rating=1, status="rejected"),
            _review(review_id="e", rating=1, source="gbp"),  # GBP never in markup
        ]
        self.assertEqual(len(markup_eligible(reviews)), 2)
        self.assertEqual(aggregate_reviews(reviews), {"rating_value": 4.5, "review_count": 2})

    def test_no_eligible_reviews_returns_none(self):
        self.assertIsNone(aggregate_reviews([_review(status="pending")]))
        self.assertIsNone(aggregate_reviews([]))

    def test_low_ratings_are_included_no_cherry_picking(self):
        reviews = [_review(review_id="a", rating=5), _review(review_id="b", rating=1)]
        self.assertEqual(aggregate_reviews(reviews), {"rating_value": 3.0, "review_count": 2})


class ReviewHandlerTests(unittest.TestCase):
    def _post(self, body):
        return handler({"httpMethod": "POST", "body": json.dumps(body)}, None, repository=self.repo)

    def setUp(self):
        self.repo = FakeRepository()

    def test_create_mints_id_and_defaults_pending_manual(self):
        resp = self._post({"tenant_id": "t1", "target": {"type": "product", "id": "prod_a"},
                           "rating": 5, "author": "Jane", "body": "Great."})
        self.assertEqual(resp["statusCode"], 201)
        review = json.loads(resp["body"])["review"]
        self.assertTrue(review["review_id"].startswith("review_"))
        self.assertEqual(review["status"], "pending")
        self.assertEqual(review["source"], "manual")

    def test_create_rejects_invalid_rating(self):
        resp = self._post({"tenant_id": "t1", "target": {"type": "product", "id": "p"},
                           "rating": 9, "author": "J", "body": "x"})
        self.assertEqual(resp["statusCode"], 400)

    def test_moderate_changes_status(self):
        self.repo.put(_review(status="pending"))
        resp = handler({"httpMethod": "PATCH", "resource": "/reviews/{review_id}/status",
                        "pathParameters": {"review_id": "review_1"},
                        "body": json.dumps({"tenant_id": "t1", "status": "approved"})}, None, repository=self.repo)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["review"]["status"], "approved")

    def test_list_filters_by_target_and_status(self):
        self.repo.put(_review(review_id="a", target={"type": "product", "id": "p1"}, status="approved"))
        self.repo.put(_review(review_id="b", target={"type": "product", "id": "p2"}, status="pending"))
        resp = handler({"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", "target_id": "p1"}}, None, repository=self.repo)
        reviews = json.loads(resp["body"])["reviews"]
        self.assertEqual([r["review_id"] for r in reviews], ["a"])

    def test_delete_removes_review(self):
        self.repo.put(_review())
        resp = handler({"httpMethod": "DELETE", "pathParameters": {"review_id": "review_1"},
                        "queryStringParameters": {"tenant_id": "t1"}}, None, repository=self.repo)
        self.assertEqual(resp["statusCode"], 200)
        self.assertNotIn(("t1", "review_1"), self.repo.documents)


if __name__ == "__main__":
    unittest.main()
