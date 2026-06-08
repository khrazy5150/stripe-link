import io
import json
import unittest
from urllib import error

from handlers import upload


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class UploadHandlerTests(unittest.TestCase):
    def test_options_returns_cors_response(self):
        response = upload.handler({"httpMethod": "OPTIONS"}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")

    def test_create_upload_proxies_request(self):
        calls = []

        def opener(req, timeout):
            calls.append((req.full_url, req.get_method(), json.loads(req.data.decode("utf-8")), timeout))
            return FakeResponse({"id": "image_123", "upload": {"url": "https://s3.example/upload"}})

        response = upload.handler({
            "httpMethod": "POST",
            "body": json.dumps({"fileName": "product.webp", "contentType": "image/webp"}),
        }, None, opener=opener)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["id"], "image_123")
        self.assertEqual(calls[0][1], "POST")
        self.assertTrue(calls[0][0].endswith("/upload/multiple"))

    def test_get_upload_status_proxies_by_image_id(self):
        calls = []

        def opener(req, timeout):
            calls.append((req.full_url, req.get_method(), timeout))
            return FakeResponse({"status": "complete", "urls": {"medium": {"webp": "https://images.example/image.webp"}}})

        response = upload.handler({
            "httpMethod": "GET",
            "pathParameters": {"image_id": "image_123"},
        }, None, opener=opener)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["status"], "complete")
        self.assertEqual(calls[0][1], "GET")
        self.assertTrue(calls[0][0].endswith("/upload/status/image_123"))

    def test_upstream_error_returns_bad_gateway(self):
        def opener(req, timeout):
            raise error.HTTPError(
                req.full_url,
                502,
                "Bad Gateway",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"upstream failed"}'),
            )

        response = upload.handler({
            "httpMethod": "POST",
            "body": json.dumps({"fileName": "product.webp"}),
        }, None, opener=opener)

        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["message"], "upstream failed")


if __name__ == "__main__":
    unittest.main()
