import base64
import hashlib
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from handlers.ai_video import JOB_TYPE, VideoServiceError, handler
from stripe_link.domain.video_gallery import MIGRATION, PREFIX

JOB_ID = "7dc9db6d-b4e2-4951-a0a6-46d2fa0eb586"
REQUEST_ID = "ca0dc897-d5dc-4ab0-bbf7-68d8c14aa535"


class AiVideoTests(TestCase):
    def setUp(self):
        self.base = "https://example.lambda-url.us-west-2.on.aws"
        self.enterContext(patch.dict("os.environ", {"MEDIA_ENGINE_API_URL": self.base + "/"}))
        self.repo = Mock()
        self.caller = Mock()

    def call(self, method, path, body=None, *, tenant="tenant-a", params=None):
        event = {
            "httpMethod": method,
            "pathParameters": {"proxy": path},
            "body": json.dumps(body or {}),
            "queryStringParameters": params,
            "headers": {"X-Tenant-Id": "claimed-tenant"},
        }
        if tenant:
            event["requestContext"] = {"authorizer": {"claims": {"custom:client_id": tenant}}}
        return handler(event, None, repo=self.repo, caller=self.caller)

    def test_request_requires_verified_identity(self):
        response = self.call("GET", "models", tenant=None)
        self.assertEqual(response["statusCode"], 401)
        self.caller.assert_not_called()

    def test_missing_engine_is_unavailable(self):
        with patch.dict("os.environ", {"MEDIA_ENGINE_API_URL": ""}):
            self.assertEqual(self.call("GET", "models")["statusCode"], 503)
        self.caller.assert_not_called()

    def test_model_catalog_uses_the_engine(self):
        catalog = {"models": [{"id": "seedance", "durations": [4, 5]}], "image_models": []}
        self.caller.return_value = catalog, 200
        self.assertEqual(json.loads(self.call("GET", "models")["body"]), catalog)
        self.caller.assert_called_once_with(self.base, "GET", "/console-models")

    def test_quote_records_owner_and_namespaces_idempotency(self):
        self.caller.return_value = {"id": JOB_ID, "state": "quoted", "quoted_usd": "0.308", "quote_expires_at": 1600,
                                    "viewer_url": "public", "input": {"prompt": "studio"}}, 201
        response = self.call("POST", "quote", {
            "request_id": REQUEST_ID, "model": "seedance", "duration": 8, "prompt": "A studio",
            "tenant_id": "tenant-b", "title": "Studio shoot", "tags": ["Test", " test "],
        })
        self.assertEqual(response["statusCode"], 201)
        key = hashlib.sha256(f"tenant-a:{REQUEST_ID}".encode()).hexdigest()
        self.caller.assert_called_once_with(
            self.base, "POST", "/jobs/quote", data={"model": "seedance", "duration": 8, "prompt": "A studio"},
            headers={"Idempotency-Key": key},
        )
        self.repo.put.assert_called_once_with(
            {"tenant_id": "tenant-a", "job_id": JOB_ID, "document_type": JOB_TYPE, "video_created_at": 1000000},
        )
        projection = self.repo.put_if_current.call_args.args[0]
        self.assertEqual((projection["title"], projection["tags"], projection["availability"]),
                         ("Studio shoot", ["Test"], "pending"))
        payload = json.loads(response["body"])
        self.assertEqual(payload["quoted_usd"], "0.308")
        self.assertNotIn("viewer_url", payload)
        self.assertNotIn("input", payload)

    def test_tenants_cannot_use_unowned_provider_jobs(self):
        self.repo.get.return_value = None
        for method, suffix in (("GET", ""), ("POST", "/approve"), ("GET", "/video-link")):
            with self.subTest(suffix=suffix):
                response = self.call(method, f"jobs/{JOB_ID}{suffix}", tenant="tenant-b")
                self.assertEqual(response["statusCode"], 404)
                self.repo.get.assert_called_with("tenant-b", JOB_ID, consistent=True)
        self.caller.assert_not_called()

    def test_approval_sends_the_exact_decimal(self):
        self.repo.get.return_value = {"document_type": JOB_TYPE, "video_created_at": 1000000}
        self.caller.return_value = {"id": JOB_ID, "state": "waiting"}, 202
        response = self.call("POST", f"jobs/{JOB_ID}/approve", {"approved_usd": "0.308"})
        self.assertEqual(response["statusCode"], 202)
        self.assertEqual(json.loads(response["body"])["state"], "waiting")
        self.caller.assert_called_once_with(
            self.base, "POST", f"/jobs/{JOB_ID}/approve", data={"approved_usd": "0.308"},
        )

    def test_video_link_is_requested_after_owner_check(self):
        self.repo.get.return_value = {"document_type": JOB_TYPE}
        self.caller.return_value = {"url": "https://video.example/signed"}, 200
        response = self.call("GET", f"jobs/{JOB_ID}/video-link", params={"download": "true"})
        self.assertEqual(json.loads(response["body"]), {"url": "https://video.example/signed"})
        self.repo.get.assert_called_once_with("tenant-a", JOB_ID, consistent=True)
        self.caller.assert_called_once_with(self.base, "GET", f"/jobs/{JOB_ID}/video-link?download=true")

    def test_reference_image_forwards_bytes_and_validates_length(self):
        self.caller.return_value = {"image_url": "https://reference.example/image.png"}, 201
        image = b"reference"
        encoded = base64.b64encode(image).decode()
        response = self.call("POST", "reference-image", {"content_type": "image/png", "image_base64": encoded})
        self.assertEqual(response["statusCode"], 201)
        self.caller.assert_called_once_with(
            self.base, "POST", "/jobs/reference-image", data=image, headers={"Content-Type": "image/png"},
        )
        with patch("handlers.ai_video.MAX_IMAGE_BYTES", 4):
            self.assertEqual(self.call("POST", "reference-image", {
                "content_type": "image/png", "image_base64": encoded,
            })["statusCode"], 413)
        self.assertEqual(self.caller.call_count, 1)

    def test_upstream_quote_errors_are_readable(self):
        self.caller.side_effect = VideoServiceError("Select a supported video model", 422)
        response = self.call("POST", "quote", {"request_id": REQUEST_ID})
        self.assertEqual(response["statusCode"], 422)
        self.assertEqual(json.loads(response["body"])["message"], "Select a supported video model")
        self.repo.put.assert_not_called()

    def test_existing_videos_are_indexed_before_the_first_page(self):
        self.repo.get.return_value = None
        self.repo.page_for_tenant.return_value = [{"job_id": JOB_ID}], ""
        self.caller.return_value = {
            "id": JOB_ID, "state": "completed", "video_available": True,
            "quote_expires_at": 1600, "model": "seedance",
            "input": {"prompt": "A lamp on a desk", "resolution": "1080p"},
        }, 200
        payload = json.loads(self.call("GET", "gallery")["body"])
        self.assertEqual(payload, {"videos": [], "next_cursor": "start", "indexing": True})
        self.repo.page_for_tenant.assert_called_once_with("tenant-a", limit=15, cursor="", legacy_type=JOB_TYPE)
        projection, marker = [call.args[0] for call in self.repo.put_if_current.call_args_list]
        self.assertEqual(projection["title"], "A lamp on a desk")
        self.assertEqual(projection["tags"], ["1080p"])
        self.assertEqual(projection["availability"], "ready")
        self.assertEqual(marker, {"tenant_id": "tenant-a", "job_id": MIGRATION, "cursor": "done"})

    def test_gallery_filters_each_tenant_page_and_only_shows_archived_results(self):
        self.repo.get.return_value = {"cursor": "done"}
        cursor = f"{PREFIX}{1000000:016d}#{JOB_ID}"
        self.repo.page_for_tenant.return_value = [
            {"video_id": "96202327-bcd3-4e9d-aa6b-c3135d44c041", "title": "Studio kitchen", "tags": ["warm"],
             "model": "seedance", "availability": "ready", "video_created_at": 3000000},
            {"video_id": JOB_ID, "title": "Studio light", "tags": ["warm"], "model": "seedance",
             "availability": "pending", "video_created_at": 2000000},
            {"video_id": "ae802fa9-97c9-4908-9186-83af1a0eafde", "title": "Cold studio", "tags": ["blue"],
             "model": "seedance", "availability": "ready", "video_created_at": 1000000},
        ], cursor
        self.caller.return_value = {"id": JOB_ID, "state": "archiving", "video_available": False}, 200
        payload = json.loads(self.call("GET", "gallery", params={"q": "STUDIO warm", "cursor": "start"})["body"])
        self.assertEqual([video["title"] for video in payload["videos"]], ["Studio kitchen"])
        self.assertEqual(payload["next_cursor"], cursor)
        self.repo.page_for_tenant.assert_called_once_with("tenant-a", limit=15, cursor="", prefix=PREFIX)
        self.caller.assert_called_once_with(self.base, "GET", f"/jobs/{JOB_ID}")
