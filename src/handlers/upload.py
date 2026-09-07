import json
import os
from urllib import error, request
from urllib.parse import quote

from stripe_link.common import error_response, json_response, parse_json_body, path_params


DEFAULT_IMAGE_UPLOAD_API_BASE = "https://dph4d1c6p8.execute-api.us-west-2.amazonaws.com/v3"


def handler(event, context, opener=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        if str((event or {}).get("path") or "").rstrip("/").endswith("/crop"):
            return create_crop(event, opener=opener)
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


# Output box for a baked crop. Large enough that no surface has to upscale it, and capped so a tenant
# cannot ask the service to render something enormous.
CROP_MAX_EDGE = 2048
CROP_MIN_EDGE = 16


def create_crop(event, opener=None):
    """Bake a tenant's crop into a derivative and hand back its URL.

    ASSET images -- product, service, hero -- appear on many surfaces AND in og:image and Product JSON-LD,
    which are URLs in meta tags that CSS can never touch. A CSS crop would leave the uncropped image going
    to Facebook and Google, so for these the crop has to live in the file (plans/IMAGE_CROPPER.md).

    Proxied rather than called from the browser: the resize function's ALLOWED_ORIGINS does not include the
    dashboard, and widening CORS on a public endpoint to save a proxy is the wrong trade.
    """
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")

    image_id = str(body.get("image_id") or "").strip()
    if not image_id:
        return error_response("image_id is required.", code="missing_image_id")

    crop = body.get("crop") or {}
    try:
        rect = [float(crop[key]) for key in ("x", "y", "w", "h")]
    except (KeyError, TypeError, ValueError):
        return error_response("crop must supply x, y, w and h.", code="invalid_crop")
    if rect[2] <= 0 or rect[3] <= 0:
        return error_response("crop width and height must be greater than zero.", code="invalid_crop")

    try:
        width = int(body.get("width") or 0)
        height = int(body.get("height") or 0)
    except (TypeError, ValueError):
        return error_response("width and height must be whole numbers.", code="invalid_size")
    if not (CROP_MIN_EDGE <= width <= CROP_MAX_EDGE and CROP_MIN_EDGE <= height <= CROP_MAX_EDGE):
        return error_response(
            f"width and height must be between {CROP_MIN_EDGE} and {CROP_MAX_EDGE}.", code="invalid_size")

    query = f"?fit=cover&crop={','.join(f'{value:g}' for value in rect)}"
    path = f"/resize/{quote(image_id, safe='')}/{width}x{height}{query}"
    try:
        upstream = call_image_service(path, method="GET", opener=opener)
        return json_response(upstream)
    except UpstreamUploadError as exc:
        return error_response(str(exc), status_code=exc.status_code, code="crop_failed")


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
