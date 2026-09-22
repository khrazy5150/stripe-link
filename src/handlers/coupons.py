import os
import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_document
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import RepositoryError, coupons_repository, stripe_keys_repository
from stripe_link.stripe_coupons import StripeCouponError, create_coupon_in_stripe, set_promotion_code_active
from stripe_link.stripe_platform_secrets import checkout_credentials

# The fields Stripe freezes once a Coupon exists: percent_off, amount_off and duration cannot be changed,
# and neither can a Promotion Code's code. That is also the platform's own rule -- a coupon is immutable
# until it expires, because a tenant who makes a discount promise keeps it (author, 2026-09-22). So the
# constraint needs enforcing, not inventing.
IMMUTABLE_AFTER_CREATION = ("code", "discount")


def handler(event, context, repository=None, stripe_repo=None, secret_cipher=None, opener=None):
    repository = repository or coupons_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    coupon_id = path_params(event).get("coupon_id")
    if method == "POST":
        return create_coupon(event, repository, stripe_repo, secret_cipher, opener)
    if method == "PUT" and coupon_id:
        return update_coupon(event, repository, coupon_id, stripe_repo, secret_cipher, opener)
    if method == "GET":
        if coupon_id:
            return get_coupon(event, repository, coupon_id)
        return list_coupons(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def stripe_credentials_for(event, tenant_id, mode, stripe_repo=None, secret_cipher=None):
    """The (api_key, stripe_account) pair to create this tenant's coupon with, or ("", "") when unconfigured."""
    stripe_repo = stripe_repo or (stripe_keys_repository() if os.environ.get("STRIPE_KEYS_TABLE") else None)
    if stripe_repo is None:
        return "", ""
    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    return checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher or KmsSecretCipher())


def create_coupon(event, repository, stripe_repo=None, secret_cipher=None, opener=None):
    """Create the coupon AT STRIPE, then store it.

    The schema has always said "Coupons are persisted only after Stripe sync succeeds" -- and until now
    nothing synced anything: the ids were synthesised in the browser and `sync.status` was the literal
    string "synced". A document whose Stripe objects do not exist is a promise the platform cannot keep, so
    a failed Stripe call writes NOTHING and returns Stripe's own words.
    """
    try:
        document = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_coupon")

    tenant_id = str(document.get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    mode = resolve_stripe_mode(event, document)

    # Validate BEFORE calling Stripe: a coupon we would refuse must not be created there first and left
    # orphaned. The Stripe ids do not exist yet, so stand them up as "pending" purely to satisfy the
    # validator -- they are overwritten with the real ones below and never reach storage. The CLIENT no
    # longer invents them, which is what made sync.status a fiction for so long.
    document["stripe_coupon_id"] = "pending"
    document["stripe_promo_code_id"] = "pending"
    document["sync"] = {"status": "synced", "last_synced_at": int(time.time()), "error": None}
    try:
        validate_coupon_document(document)
    except (DocumentValidationError, ValueError) as exc:
        return error_response(str(exc), code="invalid_coupon")

    api_key, stripe_account = stripe_credentials_for(event, tenant_id, mode, stripe_repo, secret_cipher)
    if not api_key:
        return error_response(
            f"Connect Stripe in {mode} mode before creating a coupon — the code has to exist at Stripe for "
            "a buyer to be able to use it.",
            status_code=400, code="stripe_not_configured",
        )

    try:
        stripe_coupon_id, stripe_promo_code_id = create_coupon_in_stripe(
            coupon_id=str(document.get("coupon_id") or ""),
            code=str(document.get("code") or ""),
            name=str(document.get("name") or ""),
            discount=document.get("discount") or {},
            restrictions=document.get("restrictions") or {},
            api_key=api_key, stripe_account=stripe_account, opener=opener,
        )
    except StripeCouponError as exc:
        return error_response(str(exc), status_code=400, code="stripe_coupon_failed")

    # The REAL ids, replacing whatever the client proposed. sync.status stops being a claim.
    document["stripe_coupon_id"] = stripe_coupon_id
    document["stripe_promo_code_id"] = stripe_promo_code_id
    document["stripe_mode"] = mode
    document["sync"] = {"status": "synced", "last_synced_at": int(time.time()), "error": None}

    try:
        validate_coupon_document(document)
        saved = repository.put(document)
        return json_response({"coupon": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_coupon")


def coupon_edit_conflict(existing: dict, incoming: dict) -> str:
    """Which frozen field an edit is trying to change, or "".

    Stripe freezes a Coupon's percent_off/amount_off/duration and a Promotion Code's code once they exist.
    The platform's own rule says the same thing for a better reason: a discount promised to somebody must
    survive until it expires. Comparing the STORED document rather than trusting the client means a tenant
    cannot edit around it by posting a different value.
    """
    if str(existing.get("code") or "") != str(incoming.get("code") or ""):
        return "code"
    was, now = existing.get("discount") or {}, incoming.get("discount") or {}
    for field in ("type", "value", "currency", "duration", "duration_months"):
        if str(was.get(field) or "") != str(now.get(field) or ""):
            return f"discount.{field}"
    return ""


def update_coupon(event, repository, coupon_id: str, stripe_repo=None, secret_cipher=None, opener=None):
    """Rename it, or turn it off. Never change what it is worth.

    Disabling also deactivates the promotion code AT STRIPE, so the two can never disagree about whether a
    code still works -- the disagreement is how a buyer types a code the tenant retired and still gets the
    discount, or the reverse.
    """
    try:
        document = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_coupon")
    if document.get("coupon_id") != coupon_id:
        return error_response("Coupon ID in path must match coupon_id in body.", code="invalid_coupon")

    tenant_id = str(document.get("tenant_id") or "").strip() or tenant_id_from_event(event)
    existing = repository.get(tenant_id, coupon_id) if tenant_id else None
    if existing:
        conflict = coupon_edit_conflict(existing, document)
        if conflict:
            return error_response(
                "A coupon can't be changed once it exists — customers may already be holding this one. "
                "Turn it off and create a new coupon instead.",
                status_code=409, code="coupon_immutable",
            )

    # Ordered like creation: change Stripe first, and store nothing if that fails. A record saying
    # "inactive" while the code still works at Stripe is the more dangerous of the two disagreements.
    if existing and str(existing.get("status")) != str(document.get("status")):
        mode = resolve_stripe_mode(event, document)
        api_key, stripe_account = stripe_credentials_for(event, tenant_id, mode, stripe_repo, secret_cipher)
        promo_id = str(existing.get("stripe_promo_code_id") or "")
        if api_key and promo_id:
            try:
                set_promotion_code_active(
                    promo_id, document.get("status") == "active",
                    api_key=api_key, stripe_account=stripe_account, opener=opener,
                )
            except StripeCouponError as exc:
                return error_response(str(exc), status_code=400, code="stripe_coupon_failed")

    try:
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
