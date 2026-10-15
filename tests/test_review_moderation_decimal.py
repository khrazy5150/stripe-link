"""Approve refused to re-validate a review the software had itself written.

Reported 2026-10-14: the buyer's review arrived and sat in the dashboard as Pending; clicking Approve did
nothing visible. The server was answering 400, "Review rating must be an integer from 1 to 5", about a
review rated 5.

DynamoDB hands every number back as a `Decimal`, so a stored `rating: 5` reads as `Decimal('5')` and
`isinstance(rating, int)` is False. `moderate_review` is a read-modify-write -- get, set the status,
re-validate, put -- so it is exactly the shape that trips on it. `require_positive_int` next door in the
same module already knew this; the rating check did not.

The lesson is older than this bug (memory: "Decimal from DynamoDB" -- it 404'd published pages once).
These tests therefore use Decimal fixtures, because an int fixture passes while the real document fails.
"""
import json
import unittest
from decimal import Decimal

from handlers.reviews import handler
from stripe_link.domain.documents import DocumentValidationError, validate_review

STORED = {
    "schema_version": "2026-07-23", "document_type": "review", "tenant_id": "t1",
    "review_id": "review_q2vQ0JkpQ9Dz0v", "target": {"type": "product", "id": "local_vwwhS4DSabx"},
    # As DynamoDB returns them, which is the only shape this bug has ever appeared in.
    "rating": Decimal("5"), "created_at": Decimal("1792027511"), "updated_at": Decimal("1792027511"),
    "author": "Keith Harris", "title": "Entrepreneur", "body": "Fantastic presentation.",
    "status": "pending", "source": "first_party", "verified_purchase": True, "order_id": "order_1",
}


class FakeReviews:
    def __init__(self, review):
        self.review = dict(review)
        self.put_calls = []

    def get(self, tenant_id, review_id):
        return dict(self.review) if review_id == self.review["review_id"] else None

    def put(self, document):
        self.put_calls.append(dict(document))
        self.review = dict(document)
        return dict(document)


class ValidationTests(unittest.TestCase):
    def test_a_rating_read_back_from_storage_is_valid(self):
        validate_review(dict(STORED))

    def test_it_is_normalised_to_a_plain_int(self):
        """So a round-tripped review is stored the way it was first written instead of carrying a Decimal
        onward through every later read."""
        document = dict(STORED)
        validate_review(document)
        self.assertIsInstance(document["rating"], int)
        self.assertEqual(document["rating"], 5)

    def test_a_fractional_rating_is_still_refused(self):
        """Accepting Decimal must not become accepting 4.5. The check is about the VALUE being whole, not
        about which Python type carried it."""
        with self.assertRaises(DocumentValidationError):
            validate_review({**STORED, "rating": Decimal("4.5")})

    def test_out_of_range_and_nonsense_are_still_refused(self):
        for rating in (Decimal("0"), Decimal("6"), 0, 6, "5", True):
            with self.assertRaises(DocumentValidationError, msg=repr(rating)):
                validate_review({**STORED, "rating": rating})


class ModerationTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeReviews(STORED)

    def patch(self, status="approved", review_id="review_q2vQ0JkpQ9Dz0v"):
        return handler({
            "httpMethod": "PATCH", "resource": "/reviews/{review_id}/status",
            "pathParameters": {"review_id": review_id},
            "body": json.dumps({"tenant_id": "t1", "status": status}),
        }, None, repository=self.repo)

    def test_approving_a_stored_review_succeeds(self):
        response = self.patch()
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["review"]["status"], "approved")

    def test_the_change_is_persisted(self):
        self.patch()
        self.assertEqual(self.repo.put_calls[-1]["status"], "approved")

    def test_rejecting_works_the_same_way(self):
        self.assertEqual(self.patch(status="rejected")["statusCode"], 200)
        self.assertEqual(self.repo.review["status"], "rejected")

    def test_nothing_else_about_the_review_is_disturbed(self):
        """Moderation changes the status and the timestamp. A verified purchase stays verified."""
        self.patch()
        saved = self.repo.put_calls[-1]
        self.assertTrue(saved["verified_purchase"])
        self.assertEqual(saved["order_id"], "order_1")
        self.assertEqual(saved["body"], STORED["body"])

    def test_an_unknown_review_is_still_404(self):
        self.assertEqual(self.patch(review_id="review_nope")["statusCode"], 404)

    def test_an_invalid_status_is_still_refused(self):
        response = self.patch(status="published")
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(self.repo.put_calls, [])


class ReportingTests(unittest.TestCase):
    """A failed Approve must say so where the click was."""

    SOURCE = None

    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.SOURCE = (pathlib.Path(__file__).resolve().parents[1]
                      / "dashboard" / "src" / "stores" / "reviews.js").read_text(encoding="utf-8")

    def test_moderation_failures_raise_a_toast(self):
        """The page-level banner sits above "Add a review", a screen-height above the buttons -- so a
        failed Approve read as a button that did nothing at all."""
        body = self.SOURCE.split("async moderate(", 1)[1].split("async remove(", 1)[0]
        self.assertIn("reportFailure(this.error)", body)

    def test_deletion_failures_do_too(self):
        body = self.SOURCE.split("async remove(", 1)[1]
        self.assertIn("reportFailure(this.error)", body)

    def test_the_banner_is_still_set(self):
        """The toast is transient; the banner remains the thing you can go back and read."""
        self.assertIn('this.error = error.message || "Failed to update the review."', self.SOURCE)


if __name__ == "__main__":
    unittest.main()


class SameTrapElsewhereTests(unittest.TestCase):
    """The rating check was not the only one asking the wrong question.

    Every validator used on a read-modify-write path has to accept a Decimal, because that is what the
    document it is re-validating is made of. Two of these were live bugs nobody had hit yet; the cart one
    only because no cart has ever held two lines.
    """

    def test_a_second_add_to_cart_validates(self):
        """`POST /cart` LOADS the cart and adds a line, so from the second item on every stored qty and
        amount is a Decimal. The bare check rejected the whole cart with "Cart line qty must be an
        integer from 1 to 99"."""
        from stripe_link.domain.documents import validate_cart

        validate_cart({
            "schema_version": "2026-07-23", "document_type": "cart", "tenant_id": "t1", "cart_id": "c1",
            "offer_id": "o1", "created_at": Decimal("1792027511"),
            "line_items": [
                {"product_id": "p1", "price_id": "pr1", "qty": Decimal("1"), "unit_amount": Decimal("2900")},
                {"product_id": "p2", "price_id": "pr2", "qty": 2, "unit_amount": 1500},
            ],
        })

    def test_a_cart_line_with_a_fractional_qty_is_still_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_cart

        with self.assertRaises(DocumentValidationError):
            validate_cart({
                "schema_version": "2026-07-23", "document_type": "cart", "tenant_id": "t1", "cart_id": "c1",
                "offer_id": "o1", "created_at": Decimal("1"),
                "line_items": [{"product_id": "p1", "price_id": "pr1",
                                "qty": Decimal("1.5"), "unit_amount": Decimal("2900")}],
            })

    def test_editing_a_stored_experiment_validates(self):
        """`PUT /experiments/{id}` reads the experiment, changes it and re-validates -- so the weights are
        Decimals by then."""
        from stripe_link.domain.documents import validate_experiment

        validate_experiment({
            "schema_version": "2026-07-23", "document_type": "experiment", "tenant_id": "t1",
            "experiment_id": "exp_1", "name": "Headline test", "status": "running",
            "control_page_id": "p1",
            "variants": [{"key": "a", "page_id": "p1", "weight": Decimal("50")},
                         {"key": "b", "page_id": "p2", "weight": Decimal("50")}],
        })

    def test_the_helper_rejects_what_it_always_rejected(self):
        from stripe_link.domain.documents import whole_number

        for value in (Decimal("5"), 5, Decimal("-3"), 0):
            self.assertIsInstance(whole_number(value), int, msg=repr(value))
        for value in (True, False, "5", None, 4.5, Decimal("4.5")):
            self.assertIsNone(whole_number(value), msg=repr(value))


class TheSameTrapInFloatsTests(unittest.TestCase):
    """The integer sweep missed every check that ALLOWS fractions.

    `isinstance(x, (int, float))` is False for a Decimal just as `isinstance(x, int)` is, so the two
    float-allowing validators had the identical bug and were not caught by looking for the integer form.
    Found by hitting it: writing a page that carries a `rating` element and saving it again (2026-10-15).
    """

    def test_a_page_with_a_rating_can_be_saved_twice(self):
        from stripe_link.domain.documents import validate_page_document

        page = {
            "schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
            "page_id": "p1", "name": "Sample", "offer_id": "o1",
            # As the page comes back out of DynamoDB on the second save.
            "route": {"slug": "sample"},
            "sections": [{"type": "rating", "id": "r", "value": Decimal("4.5"), "count": Decimal("128")}],
        }
        validate_page_document(page)

    def test_a_site_with_coordinates_can_be_saved_twice(self):
        """A Site with geo is re-validated on every save from the Sites editor, so this one was live."""
        from stripe_link.domain.documents import validate_site

        validate_site({
            "schema_version": "2026-07-20", "document_type": "site", "site_id": "site_ABC123",
            "tenant_id": "t1", "environment": "live", "name": "Axel Mart", "status": "active",
            "hosting": {"type": "platform", "platform_hostname": "axel-mart.jbay.uk", "custom_domain": None},
            "organization": {"name": "Axel Mart", "entity_type": "OnlineStore",
                             # As they come back out of DynamoDB.
                             "geo": {"latitude": Decimal("47.6062"), "longitude": Decimal("-122.3321")}},
            "indexing": {"eligibility": "blocked"},
            "pages": {"/": {"page_id": "page_home01", "page_type": "landing", "enabled": True}},
            "created_at": 1, "updated_at": 1,
        })

    def test_nonsense_is_still_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_page_document, real_number

        for value in (True, "4.5", None):
            self.assertIsNone(real_number(value), msg=repr(value))
        for bad in (Decimal("5.5"), 6, -1):
            with self.assertRaises(DocumentValidationError, msg=repr(bad)):
                validate_page_document({
                    "schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t1",
                    "page_id": "p1", "name": "Sample", "offer_id": "o1",
                    "route": {"slug": "sample"},
                    "sections": [{"type": "rating", "id": "r", "value": bad}]})
