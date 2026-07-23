import unittest
from urllib.parse import urlencode

from handlers.reviews_public import handler


class FakeReviews:
    def __init__(self):
        self.saved = []

    def put(self, doc):
        self.saved.append(dict(doc))
        return dict(doc)


class FakeProducts:
    def __init__(self, products):
        self.by_key = {(p["tenant_id"], p["product_id"]): p for p in products}

    def get(self, tenant_id, product_id):
        return self.by_key.get((tenant_id, product_id))


class FakeSites:
    def list_for_tenant(self, tenant_id):
        return [{"tenant_id": tenant_id, "organization": {"name": "Axel Mart"}}]


PRODUCT = {"tenant_id": "t1", "product_id": "prod_a", "name": "Creatine Gummies"}


class PublicReviewFormTests(unittest.TestCase):
    def setUp(self):
        self.reviews = FakeReviews()
        self.products = FakeProducts([PRODUCT])
        self.sites = FakeSites()

    def _get(self, params):
        return handler({"httpMethod": "GET", "queryStringParameters": params}, None,
                       reviews_repo=self.reviews, products_repo=self.products, sites_repo=self.sites)

    def _post(self, values):
        return handler({"httpMethod": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                        "body": urlencode(values), "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}}, None,
                       reviews_repo=self.reviews, products_repo=self.products, sites_repo=self.sites)

    def test_get_renders_form_with_product_and_business(self):
        resp = self._get({"tenant_id": "t1", "product_id": "prod_a"})
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("text/html", resp["headers"]["Content-Type"])
        self.assertIn("Creatine Gummies", resp["body"])
        self.assertIn("Axel Mart", resp["body"])
        self.assertIn("<form method=post>", resp["body"])

    def test_get_unknown_product_is_404(self):
        self.assertEqual(self._get({"tenant_id": "t1", "product_id": "nope"})["statusCode"], 404)

    def test_submit_creates_pending_first_party_review(self):
        resp = self._post({"tenant_id": "t1", "product_id": "prod_a", "rating": "5",
                           "author": "Jane", "title": "Great", "body": "Loved it.", "company_website": ""})
        self.assertEqual(resp["statusCode"], 200)
        self.assertIn("Thank you", resp["body"])
        self.assertEqual(len(self.reviews.saved), 1)
        review = self.reviews.saved[0]
        self.assertEqual(review["status"], "pending")
        self.assertEqual(review["source"], "first_party")
        self.assertEqual(review["target"], {"type": "product", "id": "prod_a"})
        self.assertEqual(review["rating"], 5)
        self.assertEqual(review["provenance"]["ip"], "1.2.3.4")

    def test_honeypot_drops_silently(self):
        resp = self._post({"tenant_id": "t1", "product_id": "prod_a", "rating": "5",
                           "author": "Bot", "body": "spam", "company_website": "http://spam"})
        self.assertEqual(resp["statusCode"], 200)  # thanked
        self.assertEqual(self.reviews.saved, [])   # but not stored

    def test_submit_bad_rating_re_renders_form_with_error(self):
        resp = self._post({"tenant_id": "t1", "product_id": "prod_a", "rating": "9",
                           "author": "Jane", "body": "x", "company_website": ""})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("<form", resp["body"])
        self.assertEqual(self.reviews.saved, [])

    def test_submit_unknown_product_rejected(self):
        resp = self._post({"tenant_id": "t1", "product_id": "nope", "rating": "5", "author": "J", "body": "x"})
        self.assertEqual(resp["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
