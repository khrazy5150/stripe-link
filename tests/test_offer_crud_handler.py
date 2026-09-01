import json
import unittest
from pathlib import Path

from handlers.offers import handler
from tests.fakes import FakeDocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OfferCrudHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.offer = load_fixture("offer-creatine-standard.json")
        self.product = load_fixture("product-creatine-gummies.json")
        self.products.put(self.product)

    def test_create_offer_persists_selectable_price_offer(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        item = body["offer"]["items"][0]
        self.assertEqual(item["default_price_id"], "price_2bottle")
        self.assertEqual(len(item["selectable_prices"]), 4)

    def _post(self, offer):
        return handler({"httpMethod": "POST", "body": json.dumps(offer)}, None,
                       repository=self.repository, products_repo=self.products)

    def test_offer_slug_is_sanitized(self):
        resp = self._post({**self.offer, "offer_id": "offer_a", "slug": "Tax Prep!! SVC"})
        self.assertEqual(resp["statusCode"], 201)
        self.assertEqual(json.loads(resp["body"])["offer"]["slug"], "tax-prep-svc")

    def test_offer_slug_uniqueness_suffixes_collisions(self):
        self._post({**self.offer, "offer_id": "offer_a", "slug": "combo"})
        resp = self._post({**self.offer, "offer_id": "offer_b", "slug": "combo"})
        self.assertEqual(json.loads(resp["body"])["offer"]["slug"], "combo-2")

    def test_a_renamed_offer_takes_its_slug_from_the_name(self):
        # The bug: label "Workout Bundle" but slug "dietary-supplement-bundle". A tenant-typed name bypasses
        # the semantic model while the slug still used it, so the two diverged with nothing forcing them
        # to agree. A deliberate rename is the stronger signal.
        resp = self._post({**self.offer, "offer_id": "offer_named", "name": "Workout Bundle", "slug": ""})
        self.assertEqual(resp["statusCode"], 201)
        body = json.loads(resp["body"])["offer"]
        self.assertEqual(body["slug"], "workout-bundle")
        self.assertEqual(body["name"], "Workout Bundle")

    def test_a_typed_slug_still_beats_the_name(self):
        resp = self._post({**self.offer, "offer_id": "offer_both", "name": "Workout Bundle", "slug": "my-url"})
        self.assertEqual(json.loads(resp["body"])["offer"]["slug"], "my-url")

    def test_renaming_an_EXISTING_offer_does_not_move_its_url(self):
        # The whole reason the name is only consulted for a NEW offer: a live slug addresses published
        # pages, ad campaigns and shared links. It must never change itself underneath the tenant.
        self._post({**self.offer, "offer_id": "offer_live", "slug": "original-url"})
        again = self._post({**self.offer, "offer_id": "offer_live", "name": "Totally New Name", "slug": ""})
        self.assertEqual(json.loads(again["body"])["offer"]["slug"], "original-url")

    def test_offer_slug_stable_on_re_save(self):
        first = self._post({**self.offer, "offer_id": "offer_a", "slug": "combo"})
        again = self._post({**self.offer, "offer_id": "offer_a", "slug": "combo"})
        self.assertEqual(json.loads(first["body"])["offer"]["slug"], "combo")
        self.assertEqual(json.loads(again["body"])["offer"]["slug"], "combo")

    def test_no_slug_gets_a_smart_seo_slug_from_products(self):
        offer = {**self.offer, "offer_id": "offer_smart"}
        offer.pop("slug", None)
        slug = json.loads(self._post(offer)["body"])["offer"]["slug"]
        self.assertIn("creatine-gummies", slug)  # keyword-rich from the product, not empty/first-id

    def test_existing_slug_is_preserved_when_none_sent(self):
        # Editing an offer without touching the slug must NOT churn the published-page URL.
        self._post({**self.offer, "offer_id": "offer_x", "slug": "my-custom-slug"})
        offer = {**self.offer, "offer_id": "offer_x"}
        offer.pop("slug", None)
        resp = self._post(offer)
        self.assertEqual(json.loads(resp["body"])["offer"]["slug"], "my-custom-slug")

    def test_no_name_gets_a_smart_label_from_the_model(self):
        # The offer label is server-derived from the same semantic model as the slug (so they can't diverge).
        offer = {**self.offer, "offer_id": "offer_label"}
        offer.pop("name", None)
        name = json.loads(self._post(offer)["body"])["offer"]["name"]
        self.assertIn("Creatine", name)  # a representative label, not empty / not the first product-id

    def test_update_offer_status_archives_and_restores(self):
        self.repository.put(self.offer)
        tenant_id = self.offer["tenant_id"]
        offer_id = self.offer["offer_id"]

        def patch(status):
            return handler({
                "httpMethod": "PATCH",
                "pathParameters": {"offer_id": offer_id},
                "body": json.dumps({"status": status, "tenant_id": tenant_id}),
            }, None, repository=self.repository, products_repo=self.products)

        archived = patch("archived")
        self.assertEqual(archived["statusCode"], 200)
        self.assertEqual(self.repository.get(tenant_id, offer_id)["status"], "archived")
        restored = patch("active")
        self.assertEqual(json.loads(restored["body"])["offer"]["status"], "active")

    def test_update_offer_status_rejects_invalid_status(self):
        self.repository.put(self.offer)
        response = handler({
            "httpMethod": "PATCH",
            "pathParameters": {"offer_id": self.offer["offer_id"]},
            "body": json.dumps({"status": "deleted", "tenant_id": self.offer["tenant_id"]}),
        }, None, repository=self.repository, products_repo=self.products)
        self.assertEqual(response["statusCode"], 400)

    def test_get_and_list_offers(self):
        self.repository.put(self.offer)

        get_response = handler({
            "httpMethod": "GET",
            "pathParameters": {"offer_id": "offer_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)
        list_response = handler({
            "httpMethod": "GET",
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(get_response["statusCode"], 200)
        self.assertEqual(json.loads(get_response["body"])["offer"]["offer_id"], "offer_creatine_standard")
        self.assertEqual(json.loads(list_response["body"])["offers"][0]["offer_id"], "offer_creatine_standard")

    def test_delete_offer_removes_document(self):
        self.repository.put(self.offer)

        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"offer_id": "offer_creatine_standard"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["deleted"])
        self.assertIsNone(self.repository.get("tenant_demo", "offer_creatine_standard"))

    def test_delete_offer_returns_404_when_missing(self):
        response = handler({
            "httpMethod": "DELETE",
            "pathParameters": {"offer_id": "missing_offer"},
            "queryStringParameters": {"tenant_id": "tenant_demo"},
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(json.loads(response["body"])["error"], "not_found")

    def test_create_offer_rejects_item_with_fixed_and_selectable_prices(self):
        self.offer["items"][0]["price_id"] = "price_2bottle"
        self.offer["items"][0]["quantity"] = 1

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_offer")

    def test_create_offer_rejects_mixed_product_intents(self):
        lead_product = load_fixture("product-lead-capture-email.json")
        self.products.put(lead_product)
        self.offer["items"].append({
            "product_id": lead_product["product_id"],
            "price_id": lead_product["default_price_id"],
            "quantity": 1,
            "presentation_context": "primary",
        })

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.offer),
        }, None, repository=self.repository, products_repo=self.products)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "invalid_offer")
        self.assertIn("product_intent", body["message"])


if __name__ == "__main__":
    unittest.main()
