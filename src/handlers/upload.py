import json
import os
from urllib import error, request

from stripe_link.common import error_response, json_response, parse_json_body, path_params


DEFAULT_IMAGE_UPLOAD_API_BASE = "https://dph4d1c6p8.execute-api.us-west-2.amazonaws.com/v3"


def handler(event, context, opener=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return create_upload(event, opener=opener)
    if method == "GET":
        image_id = path_params(event).get("image_id")
        if image_id:
            return get_upload_status(image_id, opener=opener)
        return error_response("image_id is required.", code="missing_image_id")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_upload(event, opener=None):
    try:
        body = parse_json_body(event)
        upstream = call_image_service("/upload/multiple", method="POST", body=body, opener=opener)
        return json_response(upstream)
    except (ValueError, UpstreamUploadError) as exc:
        return error_response(str(exc), status_code=getattr(exc, "status_code", 400), code="upload_failed")


def get_upload_status(image_id: str, opener=None):
    try:
        upstream = call_image_service(f"/upload/status/{image_id}", method="GET", opener=opener)
        return json_response(upstream)
    except UpstreamUploadError as exc:
        return error_response(str(exc), status_code=exc.status_code, code="upload_status_failed")


def call_image_service(path: str, *, method: str, body: dict | None = None, opener=None) -> dict:
    opener = opener or request.urlopen
    url = f"{image_upload_api_base()}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener(req, timeout=15) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8")
        raise UpstreamUploadError(message_from_body(raw_body) or exc.reason, status_code=exc.code) from exc
    except error.URLError as exc:
        raise UpstreamUploadError(str(exc.reason), status_code=502) from exc
    try:
        parsed = json.loads(raw_body or "{}")
    except json.JSONDecodeError as exc:
        raise UpstreamUploadError("Image service returned invalid JSON.", status_code=502) from exc
    if not isinstance(parsed, dict):
        raise UpstreamUploadError("Image service returned an invalid response.", status_code=502)
    return parsed


def image_upload_api_base() -> str:
    return os.environ.get("IMAGE_UPLOAD_API_BASE", DEFAULT_IMAGE_UPLOAD_API_BASE).rstrip("/")


def message_from_body(raw_body: str) -> str:
    try:
        parsed = json.loads(raw_body or "{}")
    except json.JSONDecodeError:
        return raw_body
    return str(parsed.get("message") or parsed.get("error") or "").strip()


class UpstreamUploadError(Exception):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code
