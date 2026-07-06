import json
import os
import unittest
from unittest.mock import patch

from handlers.downloads import serve_handler, upload_url_handler
from stripe_link.domain.downloads import (
    asset_bucket_key,
    build_download_url,
    digital_download_links,
    sanitize_filename,
)
from tests.fakes import FakeDocumentRepository


class FakeS3:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        self.calls.append({"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn})
        return f"https://s3.example/{operation}/{Params['Key']}?sig=abc"


class DomainTests(unittest.TestCase):
    def test_sanitize_filename_blocks_traversal(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "etc_passwd")
        self.assertEqual(sanitize_filename("My Guide (v2).pdf"), "My_Guide_v2_.pdf")

    def test_asset_bucket_key(self):
        self.assertEqual(
            asset_bucket_key("t1", "prod_1", "asset_9", "guide.pdf"),
            "downloads/t1/prod_1/asset_9/guide.pdf",
        )

    def test_build_download_url(self):
        url = build_download_url("https://api.x/prod", tenant_id="t1", session_id="cs_1", product_id="prod_1")
        self.assertEqual(url, "https://api.x/prod/download?session_id=cs_1&product_id=prod_1&tenant_id=t1")

    def test_digital_download_links_only_for_digital(self):
        order = {"tenant_id": "t1", "session_id": "cs_1"}
        physical = {"product_id": "prod_1"}
        digital = {"product_id": "prod_1", "digital_asset": {"bucket_key": "downloads/x", "filename": "g.pdf"}}
        self.assertEqual(digital_download_links(order, physical, "https://api.x"), [])
        links = digital_download_links(order, digital, "https://api.x")
        self.assertEqual(links[0]["label"], "g.pdf")
        self.assertIn("product_id=prod_1", links[0]["url"])


class UploadUrlTests(unittest.TestCase):
    def test_returns_presigned_put_and_asset(self):
        s3 = FakeS3()
        with patch.dict(os.environ, {"MEDIA_BUCKET": "jb-media-dev"}, clear=False):
            response = upload_url_handler(
                {"httpMethod": "POST", "queryStringParameters": {"tenant_id": "t1"},
                 "body": json.dumps({"product_id": "prod_1", "filename": "guide.pdf", "content_type": "application/pdf"})},
                None, s3_client=s3, now_fn=lambda: 1781230000, id_fn=lambda: "asset_9",
            )
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["digital_asset"]["bucket_key"], "downloads/t1/prod_1/asset_9/guide.pdf")
        self.assertEqual(s3.calls[0]["operation"], "put_object")
        self.assertEqual(s3.calls[0]["Params"]["ContentType"], "application/pdf")
        self.assertIn("upload_url", body)

    def test_requires_bucket_and_fields(self):
        with patch.dict(os.environ, {}, clear=True):
            resp = upload_url_handler({"httpMethod": "POST", "queryStringParameters": {"tenant_id": "t1"},
                                       "body": json.dumps({"product_id": "p", "filename": "f"})}, None, s3_client=FakeS3())
        self.assertEqual(resp["statusCode"], 500)


class ServeTests(unittest.TestCase):
    def setUp(self):
        self.orders = FakeDocumentRepository("order_id")
        self.products = FakeDocumentRepository("product_id")
        self.orders.put({"tenant_id": "t1", "order_id": "order_cs_1", "status": "paid", "product": {"product_id": "prod_1"}})
        self.products.put({"tenant_id": "t1", "product_id": "prod_1",
                           "digital_asset": {"bucket_key": "downloads/t1/prod_1/a/guide.pdf", "filename": "guide.pdf"}})

    def serve(self, **params):
        query = {"tenant_id": "t1", "session_id": "cs_1", "product_id": "prod_1", **params}
        with patch.dict(os.environ, {"MEDIA_BUCKET": "jb-media-dev"}, clear=False):
            return serve_handler(
                {"httpMethod": "GET", "queryStringParameters": query},
                None, products_repo=self.products, orders_repo=self.orders, s3_client=FakeS3(),
            )

    def test_paid_order_redirects_to_presigned_url(self):
        response = self.serve()
        self.assertEqual(response["statusCode"], 302)
        self.assertIn("get_object/downloads/t1/prod_1/a/guide.pdf", response["headers"]["Location"])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_unpaid_order_forbidden(self):
        self.orders.put({"tenant_id": "t1", "order_id": "order_cs_1", "status": "open", "product": {"product_id": "prod_1"}})
        self.assertEqual(self.serve()["statusCode"], 403)

    def test_product_mismatch_forbidden(self):
        response = self.serve(product_id="prod_other")
        self.assertEqual(response["statusCode"], 403)

    def test_missing_order_forbidden(self):
        response = self.serve(session_id="cs_unknown")
        self.assertEqual(response["statusCode"], 403)

    def test_non_digital_product_404(self):
        self.products.put({"tenant_id": "t1", "product_id": "prod_1"})  # no digital_asset
        self.assertEqual(self.serve()["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
