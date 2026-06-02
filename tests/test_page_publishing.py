import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from handlers.page_publish import handler
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import PublishError, artifact_targets, publish_page_document


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

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
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
                "test": "test/tenant_demo/simple-coffee/index.html",
                "published": "published/tenant_demo/simple-coffee/index.html",
            },
        )

    def test_artifact_targets_include_preview_and_dev_test(self):
        targets = artifact_targets(
            self.page,
            environment="dev",
            pages_bucket="pages",
            preview_bucket="preview",
            pages_domain="pages.example.com",
            preview_domain="preview.example.com",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview", "test"])
        self.assertEqual(targets[0]["key"], "preview/tenant_demo/page_simple_coffee/index.html")
        self.assertEqual(targets[1]["key"], "test/tenant_demo/simple-coffee/index.html")
        self.assertEqual(targets[1]["url"], "https://pages.example.com/test/tenant_demo/simple-coffee/index.html")

    def test_artifact_targets_include_published_when_page_is_published(self):
        page = copy.deepcopy(self.page)
        page["status"] = "published"

        targets = artifact_targets(
            page,
            environment="prod",
            pages_bucket="pages",
            preview_bucket="preview",
        )

        self.assertEqual([target["kind"] for target in targets], ["preview", "test", "published"])
        self.assertEqual(targets[2]["key"], "published/tenant_demo/simple-coffee/index.html")

    def test_publish_page_document_writes_preview_and_test_html(self):
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

        self.assertEqual([put["Key"] for put in self.s3.puts], [
            "preview/tenant_demo/page_simple_coffee/index.html",
            "test/tenant_demo/simple-coffee/index.html",
        ])
        self.assertIn(b"Simple Coffee", self.s3.puts[0]["Body"])
        self.assertIn(b"https://checkout.stripe.com/c/pay/demo", self.s3.puts[0]["Body"])
        self.assertEqual([artifact["kind"] for artifact in result["artifacts"]], ["preview", "test"])
        self.assertIsNone(result["invalidation"])

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
            "test/tenant_demo/simple-coffee/index.html",
            "published/tenant_demo/simple-coffee/index.html",
        ])
        self.assertEqual(result["invalidation"]["paths"], ["/published/tenant_demo/simple-coffee/index.html"])
        self.assertEqual(self.cloudfront.invalidations[0]["DistributionId"], "DIST123")

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
        self.assertEqual(len(self.s3.puts), 2)

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
