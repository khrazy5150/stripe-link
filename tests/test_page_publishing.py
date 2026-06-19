import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from handlers.page_publish import handler
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import PublishError, artifact_targets, delete_page_artifacts, publish_page_document


ROOT = Path(__file__).resolve().parents[1]
_serializer = TypeSerializer()


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def stream_image(document: dict):
    return {
        key: _serializer.serialize(value)
        for key, value in document.items()
    }


class FakeRepository:
    def __init__(self, id_field: str, documents: list[dict]):
        self.id_field = id_field
        self.documents = {
            (document["tenant_id"], document[id_field]): document
            for document in documents
        }

    def get(self, tenant_id: str, document_id: str):
        document = self.documents.get((tenant_id, document_id))
        return copy.deepcopy(document) if document else None


class FakeS3Client:
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {}

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)
        return {}


class FakeCloudFrontClient:
    def __init__(self):
        self.invalidations = []

    def create_invalidation(self, **kwargs):
        self.invalidations.append(kwargs)
        return {"Invalidation": {"Id": "INV123"}}


class PagePublishingTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-simple-coffee.json")
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.offers_repo = FakeRepository("offer_id", [self.offer])
        self.products_repo = FakeRepository("product_id", [self.product])
        self.s3 = FakeS3Client()
        self.cloudfront = FakeCloudFrontClient()

    def test_artifact_paths_are_shared(self):
        self.assertEqual(
            artifact_paths("tenant_demo", "page_simple_coffee", "simple-coffee"),
            {
                "preview": "preview/tenant_demo/page_simple_coffee/index.html",
                "test": "page_simple_coffee/index.html",
                "published": "page_simple_coffee/index.html",
            },
        )

    def test_artifact_paths_use_page_id_for_public_key(self):
        self.assertNotEqual(
            artifact_paths("tenant_demo", "page_first", "same-slug")["test"],
            artifact_paths("tenant_demo", "page_second", "same-slug")["test"],
        )

    def test_artifact_targets_include_preview_only_for_draft(self):
        targets = artifact_targets(
            self.page,
            environment="dev",
            pages_bucket="pages",
            preview_bucket="preview",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview"])
        self.assertEqual(targets[0]["key"], "preview/tenant_demo/page_simple_coffee/index.html")

    def test_artifact_targets_include_published_when_page_is_published(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"

        targets = artifact_targets(
            page,
            environment="prod",
            pages_bucket="pages",
            preview_bucket="preview",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview", "published"])
        self.assertEqual(targets[1]["key"], "page_simple_coffee/index.html")

    def test_delete_page_artifacts_removes_preview_and_public_keys(self):
        result = delete_page_artifacts(
            self.page,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            cloudfront_client=self.cloudfront,
            pages_distribution_id="DIST123",
        )

        self.assertEqual(
            [(item["Bucket"], item["Key"]) for item in self.s3.deletes],
            [
                ("preview", "preview/tenant_demo/page_simple_coffee/index.html"),
                ("pages", "page_simple_coffee/index.html"),
            ],
        )
        self.assertEqual(result["invalidation"]["paths"], ["/page_simple_coffee/index.html"])

    def test_publish_page_document_writes_preview_html_for_draft(self):
        result = publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
            checkout_url="https://checkout.stripe.com/c/pay/demo",
        )

        self.assertEqual([put["Key"] for put in self.s3.puts], ["preview/tenant_demo/page_simple_coffee/index.html"])
        self.assertIn(b"Simple Coffee", self.s3.puts[0]["Body"])
        self.assertIn(b"https://checkout.stripe.com/c/pay/demo", self.s3.puts[0]["Body"])
        self.assertEqual([artifact["kind"] for artifact in result["artifacts"]], ["preview"])
        self.assertIsNone(result["invalidation"])

    def test_publish_page_document_uses_offer_mode_checkout_base(self):
        result = publish_page_document(
            self.page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        self.assertEqual([artifact["kind"] for artifact in result["artifacts"]], ["preview"])
        html = self.s3.puts[0]["Body"].decode("utf-8")
        self.assertIn("https://dev.juniorbay.com/checkout?", html)
        self.assertIn("clientID=tenant_demo", html)
        self.assertIn("offer=offer_simple_coffee", html)
        self.assertIn("page_id=page_simple_coffee", html)

    def test_publish_page_document_filters_landing_page_price_contexts_in_offer_order(self):
        product = copy.deepcopy(self.product)
        product["prices"] = [
            {
                "price_id": "price_standard",
                "currency": "usd",
                "unit_amount": 1800,
                "quantity": 1,
                "context": "standard",
            },
            {
                "price_id": "price_sale",
                "currency": "usd",
                "unit_amount": 1400,
                "quantity": 1,
                "context": "sale",
            },
            {
                "price_id": "price_upsell",
                "currency": "usd",
                "unit_amount": 900,
                "quantity": 1,
                "context": "upsell",
            },
            {
                "price_id": "price_flash",
                "currency": "usd",
                "unit_amount": 1200,
                "quantity": 1,
                "context": "flash_sale",
            },
        ]
        product["default_price_id"] = "price_standard"

        offer = copy.deepcopy(self.offer)
        offer["items"][0]["selectable_prices"] = [
            {"price_id": "price_sale", "quantity": 1, "label": "Sale Price"},
            {"price_id": "price_upsell", "quantity": 1, "label": "Upsell Price"},
            {"price_id": "price_standard", "quantity": 1, "label": "Standard Price"},
            {"price_id": "price_flash", "quantity": 1, "label": "Flash Sale Price"},
        ]
        offer["items"][0]["default_price_id"] = "price_standard"

        s3 = FakeS3Client()
        publish_page_document(
            self.page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", [product]),
            s3_client=s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        html = s3.puts[0]["Body"].decode("utf-8")
        self.assertNotIn("Upsell Price", html)
        self.assertLess(html.index("Sale Price"), html.index("Standard Price"))
        self.assertLess(html.index("Standard Price"), html.index("Flash Sale Price"))

    def test_publish_page_document_sorts_landing_page_prices_by_quantity(self):
        product = copy.deepcopy(self.product)
        product["prices"] = [
            {
                "price_id": "price_one",
                "currency": "usd",
                "unit_amount": 3709,
                "quantity": 1,
                "context": "standard",
            },
            {
                "price_id": "price_two",
                "currency": "usd",
                "unit_amount": 6694,
                "quantity": 2,
                "context": "sale",
            },
            {
                "price_id": "price_three",
                "currency": "usd",
                "unit_amount": 8990,
                "quantity": 3,
                "context": "flash_sale",
            },
            {
                "price_id": "price_upsell",
                "currency": "usd",
                "unit_amount": 2217,
                "quantity": 1,
                "context": "upsell",
            },
        ]
        product["default_price_id"] = "price_two"

        offer = copy.deepcopy(self.offer)
        offer["eligibility"] = {
            "allowed_price_contexts": ["standard", "sale", "flash_sale"],
        }
        offer["items"][0]["selectable_prices"] = [
            {"price_id": "price_three", "quantity": 3, "label": "3 Containers"},
            {"price_id": "price_one", "quantity": 1, "label": "1 Container"},
            {"price_id": "price_upsell", "quantity": 1, "label": "1 Container Upsell"},
            {"price_id": "price_two", "quantity": 2, "label": "2 Containers"},
        ]
        offer["items"][0]["default_price_id"] = "price_two"

        s3 = FakeS3Client()
        publish_page_document(
            self.page,
            offers_repository=FakeRepository("offer_id", [offer]),
            products_repository=FakeRepository("product_id", [product]),
            s3_client=s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
        )

        html = s3.puts[0]["Body"].decode("utf-8")
        self.assertNotIn("1 Container Upsell", html)
        self.assertLess(html.index("1 Container"), html.index("2 Containers"))
        self.assertLess(html.index("2 Containers"), html.index("3 Containers"))

    def test_publish_page_document_writes_published_html_and_invalidates_cloudfront(self):
        page = copy.deepcopy(self.page)
        page.update({
            "status": "published",
            "PK": "TENANT#tenant_demo",
            "SK": "PAGE#page_simple_coffee",
            "GSI1PK": "PAGE#page_simple_coffee",
        })

        result = publish_page_document(
            page,
            offers_repository=self.offers_repo,
            products_repository=self.products_repo,
            s3_client=self.s3,
            pages_bucket="pages",
            preview_bucket="preview",
            environment="dev",
            cloudfront_client=self.cloudfront,
            pages_distribution_id="DIST123",
        )

        self.assertEqual([put["Key"] for put in self.s3.puts], [
            "preview/tenant_demo/page_simple_coffee/index.html",
            "page_simple_coffee/index.html",
        ])
        self.assertEqual(result["invalidation"]["paths"], ["/page_simple_coffee/index.html"])
        self.assertEqual(self.cloudfront.invalidations[0]["DistributionId"], "DIST123")
        invalidation_batch = self.cloudfront.invalidations[0]["InvalidationBatch"]
        self.assertEqual(invalidation_batch["Paths"], {
            "Quantity": 1,
            "Items": ["/page_simple_coffee/index.html"],
        })
        self.assertTrue(invalidation_batch["CallerReference"].startswith("page_simple_coffee:publish:"))

    def test_publish_page_document_rejects_missing_offer(self):
        missing_offers = FakeRepository("offer_id", [])

        with self.assertRaisesRegex(PublishError, "Offer 'offer_simple_coffee'"):
            publish_page_document(
                self.page,
                offers_repository=missing_offers,
                products_repository=self.products_repo,
                s3_client=self.s3,
                pages_bucket="pages",
                preview_bucket="preview",
                environment="dev",
            )

    def test_stream_handler_publishes_page_records(self):
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {"NewImage": stream_image(self.page)},
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "pages",
            "PAGES_PREVIEW_BUCKET": "preview",
            "PAGES_DISTRIBUTION_DOMAIN": "pages.example.com",
            "PREVIEW_DISTRIBUTION_DOMAIN": "preview.example.com",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(len(self.s3.puts), 1)
        self.assertEqual(self.s3.puts[0]["Key"], "preview/tenant_demo/page_simple_coffee/index.html")

    def test_stream_handler_unpublish_deletes_public_artifact_and_writes_preview(self):
        old_page = copy.deepcopy(self.page)
        old_page["status"] = "published"
        new_page = copy.deepcopy(self.page)
        new_page["status"] = "draft"
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {
                        "OldImage": stream_image(old_page),
                        "NewImage": stream_image(new_page),
                    },
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "pages",
            "PAGES_PREVIEW_BUCKET": "preview",
            "PAGES_DISTRIBUTION_ID": "DIST123",
            "PAGES_DISTRIBUTION_DOMAIN": "pages.example.com",
            "PREVIEW_DISTRIBUTION_DOMAIN": "preview.example.com",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(
            [(item["Bucket"], item["Key"]) for item in self.s3.deletes],
            [
                ("preview", "preview/tenant_demo/page_simple_coffee/index.html"),
                ("pages", "page_simple_coffee/index.html"),
            ],
        )
        self.assertEqual([put["Key"] for put in self.s3.puts], ["preview/tenant_demo/page_simple_coffee/index.html"])

    def test_stream_handler_reports_failed_records(self):
        event = {
            "Records": [
                {
                    "eventID": "record-1",
                    "eventName": "MODIFY",
                    "dynamodb": {"NewImage": stream_image(self.page)},
                }
            ]
        }

        with patch.dict(os.environ, {
            "ENVIRONMENT": "dev",
            "PAGES_BUCKET": "",
            "PAGES_PREVIEW_BUCKET": "",
        }, clear=False):
            result = handler(
                event,
                None,
                offers_repo=self.offers_repo,
                products_repo=self.products_repo,
                s3_client=self.s3,
                cloudfront_client=self.cloudfront,
            )

        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "record-1"}]})


if __name__ == "__main__":
    unittest.main()
