"""Digital-product downloads.

POST /downloads/upload-url  (tenant)  -> presigned S3 PUT for the media bucket + the
                                         digital_asset metadata to store on the product.
GET  /download              (public)  -> verify the session's order is paid and owns the
                                         product, then 302 to a short-lived presigned GET.
"""

import os
import secrets
import time

from stripe_link.common import error_response, json_response, parse_json_body, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.downloads import asset_bucket_key, sanitize_filename
from stripe_link.domain.lead_magnets import COLLECTABLE_FIELDS, download_offer, find_ribbon, missing_fields
from stripe_link.domain.leads import build_lead_submission, is_spam, lead_id_for
from stripe_link.ids import generate_id
from stripe_link.repositories.documents import RepositoryError, leads_repository, orders_repository, pages_repository, products_repository

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
    # A file belongs to a PRODUCT (a digital product's asset) or to a PAGE (a Page Ribbon's lead magnet).
    # Scoping page assets keeps the two id spaces from colliding, and leaves product keys byte-identical.
    product_id = str(body.get("product_id") or "").strip()
    page_id = str(body.get("page_id") or "").strip()
    filename = sanitize_filename(body.get("filename") or "")
    if not product_id and not page_id:
        return error_response("product_id or page_id is required.", code="missing_owner")
    if not body.get("filename"):
        return error_response("filename is required.", code="missing_filename")

    asset_id = str((id_fn or generate_id)() or "").strip()
    bucket_key = (
        asset_bucket_key(tenant_id, page_id, asset_id, filename, scope="page")
        if page_id and not product_id
        else asset_bucket_key(tenant_id, product_id, asset_id, filename)
    )
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

    mode = resolve_stripe_mode(event)
    orders_repo = orders_repo or orders_repository(mode=mode)
    products_repo = products_repo or products_repository(mode=mode)
    downloadable_statuses = {"paid", "partially_refunded", "completed"}
    try:
        order = orders_repo.get(tenant_id, f"order_{session_id}")
        status = str((order or {}).get("payment_status") or (order or {}).get("status") or "")
        if not order or status not in downloadable_statuses:
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


def lead_download_handler(
    event,
    context,
    *,
    pages_repo=None,
    leads_repo=None,
    s3_client=None,
    now_fn=lambda: int(time.time()),
):
    """Public: hand a visitor a Page Ribbon's file, capturing a lead first when the ribbon asks for one.

    The PAGE decides what is required, never the request. A browser sends whatever it likes, so "was email
    required?" can only be answered by reading the published section — otherwise a visitor skips the form by
    omitting a field, which is the whole point of the gate.

    Spam handling differs from POST /leads on purpose. There, a honeypot hit is accepted-and-dropped so the
    bot learns nothing. Here, dropping it would deny a real visitor their file on a false positive. The file
    is a lead MAGNET — it is meant to be given away — so a flagged request still gets the download and
    simply does not write a lead. The thing worth protecting is the tenant's leads list, not the PDF.
    """
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    bucket = _media_bucket()
    if not bucket:
        return error_response("Media bucket is not configured.", status_code=500, code="bucket_not_configured")

    try:
        payload = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")

    tenant_id = str(payload.get("tenant_id") or "").strip()
    page_id = str(payload.get("page_id") or "").strip()
    section_id = str(payload.get("section_id") or "").strip()
    if not (tenant_id and page_id and section_id):
        return error_response("tenant_id, page_id, and section_id are required.", code="missing_params")

    mode = resolve_stripe_mode(event)
    pages_repo = pages_repo or pages_repository(mode=mode)
    try:
        page = pages_repo.get(tenant_id, page_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="lookup_failed")
    section = find_ribbon(page or {}, section_id)
    offer = download_offer(section or {})
    if not offer:
        return error_response("No download is available here.", status_code=404, code="not_found")

    submitted = {field: str((payload.get("fields") or {}).get(field) or "").strip() for field in COLLECTABLE_FIELDS}
    missing = missing_fields(offer["required"], submitted)
    if missing:
        return error_response(
            f"{' and '.join(missing)} required.", code="missing_fields", status_code=400,
        )

    now = int(now_fn())
    if offer["required"] and not is_spam(payload):
        leads_repo = leads_repo or leads_repository(mode=mode)
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        offer_id = str((page or {}).get("offer_id") or "")
        lead_id = lead_id_for(tenant_id, offer_id, idempotency_key, now=now, token=secrets.token_hex(8))
        fields = {field: value for field, value in submitted.items() if value}
        lead = build_lead_submission(
            tenant_id=tenant_id,
            lead_id=lead_id,
            offer_id=offer_id,
            page_id=page_id,
            fields=fields,
            consent={},
            provenance={"source": "page_ribbon", "section_id": section_id, "submitted_at": now},
            idempotency_key=idempotency_key,
            now=now,
        )
        try:
            leads_repo.put(lead)
        except (RepositoryError, ValueError):
            # A lead that fails to store must not cost the visitor their download — they held up their end.
            pass

    asset = offer["asset"]
    filename = sanitize_filename(asset.get("filename") or "download")
    url = (s3_client or _s3_client()).generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": str(asset.get("bucket_key")),
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )
    return json_response({"url": url, "filename": filename})
