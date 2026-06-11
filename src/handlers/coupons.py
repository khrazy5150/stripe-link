import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_document
from stripe_link.repositories.documents import RepositoryError, coupons_repository


def handler(event, context, repository=None):
    repository = repository or coupons_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    coupon_id = path_params(event).get("coupon_id")
    if method == "POST":
        return create_coupon(event, repository)
    if method == "PUT" and coupon_id:
        return update_coupon(event, repository, coupon_id)
    if method == "GET":
        if coupon_id:
            return get_coupon(event, repository, coupon_id)
        return list_coupons(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_coupon(event, repository):
    try:
        document = parse_json_body(event)
        validate_coupon_document(document)
        saved = repository.put(document)
        return json_response({"coupon": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_coupon")


def update_coupon(event, repository, coupon_id: str):
    try:
        document = parse_json_body(event)
        if document.get("coupon_id") != coupon_id:
            return error_response("Coupon ID in path must match coupon_id in body.", code="invalid_coupon")
        validate_coupon_document(document)
        saved = repository.put(document)
        return json_response({"coupon": saved})
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_coupon")


def get_coupon(event, repository, coupon_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    coupon = repository.get(tenant_id, coupon_id)
    if not coupon:
        return error_response("Coupon not found.", status_code=404, code="not_found")
    return json_response({"coupon": coupon})


def list_coupons(event, repository):
    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    status = str(params.get("status") or "usable").strip()
    coupons = repository.list_for_tenant(tenant_id)
    if status == "usable":
        now = int(time.time())
        coupons = [
            coupon for coupon in coupons
            if coupon_is_usable(coupon, now)
        ]
    elif status != "all":
        coupons = [coupon for coupon in coupons if coupon.get("status") == status]
    return json_response({"coupons": coupons})


def coupon_is_usable(coupon: dict, now: int) -> bool:
    if coupon.get("status") != "active":
        return False
    restrictions = coupon.get("restrictions") or {}
    expires_at = restrictions.get("expires_at")
    if expires_at is not None and int(expires_at) <= now:
        return False
    max_redemptions = restrictions.get("max_redemptions")
    if max_redemptions is not None and int(coupon.get("redemption_count") or 0) >= int(max_redemptions):
        return False
    return True
