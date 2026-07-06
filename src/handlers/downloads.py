"""Digital-product downloads.

POST /downloads/upload-url  (tenant)  -> presigned S3 PUT for the media bucket + the
                                         digital_asset metadata to store on the product.
GET  /download              (public)  -> verify the session's order is paid and owns the
                                         product, then 302 to a short-lived presigned GET.
"""

import os
import time

from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.downloads import asset_bucket_key, sanitize_filename
from stripe_link.ids import generate_id
from stripe_link.repositories.documents import RepositoryError, orders_repository, products_repository

DOWNLOAD_URL_TTL_SECONDS = 300


def _s3_client():
    import boto3

    return boto3.client("s3")


def _media_bucket() -> str:
    return os.environ.get("MEDIA_BUCKET", "")


def upload_url_handler(event, context, *, s3_client=None, now_fn=lambda: int(time.time()), id_fn=None):
    """Tenant: mint a presigned PUT URL for a digital-product file."""
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    bucket = _media_bucket()
    if not bucket:
        return error_response("Media bucket is not configured.", status_code=500, code="bucket_not_configured")

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    body = parse_json_body(event)
    product_id = str(body.get("product_id") or "").strip()
    filename = sanitize_filename(body.get("filename") or "")
    if not product_id:
        return error_response("product_id is required.", code="missing_product")
    if not body.get("filename"):
        return error_response("filename is required.", code="missing_filename")

    asset_id = str((id_fn or generate_id)() or "").strip()
    bucket_key = asset_bucket_key(tenant_id, product_id, asset_id, filename)
    content_type = str(body.get("content_type") or "application/octet-stream")

    params = {"Bucket": bucket, "Key": bucket_key, "ContentType": content_type}
    upload_url = (s3_client or _s3_client()).generate_presigned_url(
        "put_object", Params=params, ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )

    digital_asset = {
        "asset_id": asset_id,
        "bucket_key": bucket_key,
        "filename": filename,
        "content_type": content_type,
        "uploaded_at": int(now_fn()),
    }
    if body.get("size_bytes") not in (None, ""):
        digital_asset["size_bytes"] = int(body["size_bytes"])
    return json_response({"upload_url": upload_url, "digital_asset": digital_asset})


def serve_handler(event, context, *, products_repo=None, orders_repo=None, s3_client=None):
    """Public: verify the paid order owns the product, then redirect to a presigned download."""
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    bucket = _media_bucket()
    if not bucket:
        return error_response("Media bucket is not configured.", status_code=500, code="bucket_not_configured")

    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip()
    session_id = str(params.get("session_id") or "").strip()
    product_id = str(params.get("product_id") or "").strip()
    if not (tenant_id and session_id and product_id):
        return error_response("tenant_id, session_id, and product_id are required.", code="missing_params")

    orders_repo = orders_repo or orders_repository()
    products_repo = products_repo or products_repository()
    try:
        order = orders_repo.get(tenant_id, f"order_{session_id}")
        if not order or str(order.get("status")) != "paid":
            return error_response("No paid order found for this download.", status_code=403, code="not_purchased")
        if str((order.get("product") or {}).get("product_id") or "") != product_id:
            return error_response("This order does not include that product.", status_code=403, code="product_mismatch")
        product = products_repo.get(tenant_id, product_id)
    except RepositoryError as exc:
        return error_response(str(exc), status_code=500, code="repository_error")

    asset = (product or {}).get("digital_asset")
    if not isinstance(asset, dict) or not asset.get("bucket_key"):
        return error_response("This product has no downloadable file.", status_code=404, code="no_asset")

    download_url = (s3_client or _s3_client()).generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": asset["bucket_key"],
            "ResponseContentDisposition": f'attachment; filename="{sanitize_filename(asset.get("filename") or "download")}"',
        },
        ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )
    return {
        "statusCode": 302,
        "headers": {"Location": download_url, "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        "body": "",
    }
