import csv
import io
import os
import time

from stripe_link.common import csv_response, error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.coupon_grants import grant_code, grant_document, normalize_recipients
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_document, validate_coupon_grant_document
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    RepositoryError,
    coupon_grants_repository,
    coupons_repository,
    products_repository,
    stripe_keys_repository,
)
from stripe_link.stripe_coupons import (
    StripeCouponError,
    create_coupon_in_stripe,
    create_targeted_promotion_code,
    find_or_create_customer,
    set_promotion_code_active,
)
from stripe_link.stripe_platform_secrets import checkout_credentials

# The fields Stripe freezes once a Coupon exists: percent_off, amount_off and duration cannot be changed,
# and neither can a Promotion Code's code. That is also the platform's own rule -- a coupon is immutable
# until it expires, because a tenant who makes a discount promise keeps it (author, 2026-09-22). So the
# constraint needs enforcing, not inventing.
IMMUTABLE_AFTER_CREATION = ("code", "discount")


def handler(event, context, repository=None, stripe_repo=None, secret_cipher=None, opener=None,
            grants_repo=None, products_repo=None):
    repository = repository or coupons_repository(mode=resolve_stripe_mode(event))
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    params = path_params(event)
    coupon_id = params.get("coupon_id")
    # The grants sub-resource. Routed on the PATH rather than a flag on the coupon body, because issuing
    # codes to an audience is a different operation from editing the coupon -- and the coupon itself is
    # immutable (plans/COUPONS_COMPLETION.md C5).
    if coupon_id and str((event or {}).get("resource") or (event or {}).get("path") or "").rstrip("/").endswith("/grants"):
        if method == "POST":
            return issue_grants(event, repository, coupon_id, grants_repo, stripe_repo, secret_cipher, opener)
        if method == "GET":
            return list_grants(event, coupon_id, grants_repo)
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
    if method == "POST":
        return create_coupon(event, repository, stripe_repo, secret_cipher, opener, products_repo)
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


class CouponScopeError(ValueError):
    """The coupon names products whose Stripe counterparts cannot be resolved."""


def stripe_product_ids_for(product_ids, tenant_id: str, mode: str, products_repo=None) -> list[str]:
    """Our product ids -> their Stripe product ids, for `applies_to[products][]` (Option A).

    **Refuses rather than degrades.** A product with no `stripe_product_id` has never been synced, so there
    is nothing to name at Stripe. Dropping it would send a SHORTER scope and discount the wrong set;
    dropping them all would send no scope at all, which discounts the ENTIRE cart. Both are silent
    over-discounts on a money path, and the tenant would never see it — Stripe does not echo `applies_to`
    back, so nothing downstream could notice either.
    """
    wanted = [str(pid).strip() for pid in (product_ids or []) if str(pid).strip()]
    if not wanted:
        return []
    repo = products_repo or (products_repository(mode=mode) if os.environ.get("PRODUCTS_TABLE") else None)
    if repo is None:
        raise CouponScopeError("Products are unavailable, so this coupon's product scope cannot be checked.")

    resolved, unresolved = [], []
    for product_id in wanted:
        product = repo.get(tenant_id, product_id)
        stripe_product_id = str((product or {}).get("stripe_product_id") or "").strip()
        if stripe_product_id:
            resolved.append(stripe_product_id)
        else:
            unresolved.append(str((product or {}).get("name") or product_id))
    if unresolved:
        raise CouponScopeError(
            "These products aren't synced to Stripe yet, so the discount can't be limited to them: "
            + ", ".join(unresolved)
            + ". Save the product to sync it, then create the coupon."
        )
    return resolved


def create_coupon(event, repository, stripe_repo=None, secret_cipher=None, opener=None, products_repo=None):
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

    # Product scope is resolved BEFORE the Stripe call, like validation: a coupon we would refuse must not
    # be created at Stripe first and left orphaned.
    try:
        applies_to_product_ids = stripe_product_ids_for(
            document.get("applies_to_product_ids"), tenant_id, mode, products_repo)
    except CouponScopeError as exc:
        return error_response(str(exc), status_code=400, code="coupon_scope_unresolved")

    try:
        stripe_coupon_id, stripe_promo_code_id = create_coupon_in_stripe(
            coupon_id=str(document.get("coupon_id") or ""),
            code=str(document.get("code") or ""),
            name=str(document.get("name") or ""),
            discount=document.get("discount") or {},
            restrictions=document.get("restrictions") or {},
            api_key=api_key, stripe_account=stripe_account, opener=opener,
            applies_to_product_ids=applies_to_product_ids,
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
    # `applies_to` is frozen on the Stripe Coupon exactly like percent_off and duration, so changing which
    # products a discount covers is the same promise-breaking edit as changing its value.
    if list(existing.get("applies_to_product_ids") or []) != list(incoming.get("applies_to_product_ids") or []):
        return "applies_to_product_ids"
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


# API Gateway hangs up at 29 seconds and each recipient costs two or three Stripe round-trips, so an
# audience is issued in BATCHES rather than in one call that would time out halfway and leave the tenant
# unable to tell which codes exist. The client sends the rest; `remaining` is what it sends next.
GRANT_BATCH_LIMIT = 25
GRANT_TIME_BUDGET_SECONDS = 20


def issue_grants(event, repository, coupon_id: str, grants_repo=None, stripe_repo=None,
                 secret_cipher=None, opener=None):
    """Mint one personal code per recipient, all pointing at this coupon (plans/COUPONS_COMPLETION.md C5).

    Every code is scoped to ONE Stripe Customer, which is what makes a targeted coupon targeted: a recipient
    who forwards theirs gives away nothing. The audience is people the tenant already knows by email, so the
    Customer is found by email and created when Stripe has never seen it -- a guest checkout leaves no
    Customer behind, so most past buyers have none.

    Re-posting the same audience is SAFE: an email that already holds an active grant for this coupon is
    returned as-is instead of being given a second code, because two codes in one inbox mean the tenant can
    never tell which one the recipient ignored.
    """
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_grants")

    tenant_id = str(body.get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    mode = resolve_stripe_mode(event, body)

    coupon = repository.get(tenant_id, coupon_id)
    if not coupon:
        return error_response("Coupon not found.", status_code=404, code="not_found")
    now = int(time.time())
    if not coupon_is_usable(coupon, now):
        return error_response(
            "This coupon has ended, so there is nothing to send. Create a new coupon and issue codes from that one.",
            status_code=409, code="coupon_unusable",
        )
    stripe_coupon_id = str(coupon.get("stripe_coupon_id") or "")
    if not stripe_coupon_id:
        return error_response("This coupon was never created at Stripe.", status_code=409, code="coupon_unsynced")

    recipients = normalize_recipients(body.get("recipients"))
    if not recipients:
        return error_response("At least one recipient email is required.", code="invalid_grants")

    grants_repo = grants_repo or coupon_grants_repository(mode=mode)
    # Who already has one. Read once, not per recipient.
    already = {
        str(existing.get("email") or "").lower(): existing
        for existing in grants_for_coupon(grants_repo, tenant_id, coupon_id)
        if existing.get("status") == "active"
    }

    api_key, stripe_account = stripe_credentials_for(event, tenant_id, mode, stripe_repo, secret_cipher)
    if not api_key:
        return error_response(
            f"Connect Stripe in {mode} mode before issuing codes.",
            status_code=400, code="stripe_not_configured",
        )

    landing_url = str(body.get("landing_url") or "").strip()
    # Coerced here rather than trusted: this reaches Stripe as `int()` and reaches the validator as a
    # positive int, and a typed "many" would take the whole request down with a 502.
    try:
        max_redemptions = int(body.get("max_redemptions") or 0) or None
    except (TypeError, ValueError):
        return error_response("Uses per customer must be a whole number.", code="invalid_grants")
    if max_redemptions is not None and max_redemptions < 1:
        return error_response("Uses per customer must be at least 1.", code="invalid_grants")
    expires_at = (coupon.get("restrictions") or {}).get("expires_at")
    prefix = str(coupon.get("code") or coupon_id)

    issued, skipped, failures, remaining = [], [], [], []
    started = time.time()
    attempted = 0
    for recipient in recipients:
        email = recipient["email"]
        if email in already:
            skipped.append(already[email])
            continue
        # The budget counts recipients who actually cost a Stripe call, not the position in the list: an
        # audience whose first 25 already hold codes must not push everybody else into the next batch.
        over_budget = time.time() - started > GRANT_TIME_BUDGET_SECONDS
        if attempted >= GRANT_BATCH_LIMIT or over_budget:
            remaining.append(recipient)
            continue
        attempted += 1
        try:
            customer_id = find_or_create_customer(
                email, api_key=api_key, stripe_account=stripe_account, opener=opener)
            code = grant_code(prefix)
            promo_id = create_targeted_promotion_code(
                stripe_coupon_id=stripe_coupon_id, code=code, customer_id=customer_id,
                max_redemptions=max_redemptions, expires_at=expires_at,
                api_key=api_key, stripe_account=stripe_account, opener=opener,
            )
        except StripeCouponError as exc:
            # One bad address must not cost the tenant the whole audience: the rest keep going and the
            # failures come back named, so they can be re-sent without re-issuing everyone.
            failures.append({"email": email, "error": str(exc)})
            continue
        document = grant_document(
            tenant_id=tenant_id, coupon_id=coupon_id, code=code, email=email,
            name=recipient.get("name", ""), stripe_promo_code_id=promo_id,
            stripe_customer_id=customer_id, stripe_mode=mode,
            max_redemptions=max_redemptions, expires_at=expires_at, now=now,
        )
        if landing_url:
            document["redeem_url"] = redeem_url_for(landing_url, code)
        try:
            validate_coupon_grant_document(document)
            issued.append(grants_repo.put(document))
        except (DocumentValidationError, ValueError, RepositoryError) as exc:
            # The code EXISTS at Stripe now. Say so rather than reporting a clean failure, because a silent
            # orphan is a code somebody could still use that the tenant cannot see.
            failures.append({"email": email, "error": f"{exc} (the code {code} was created at Stripe)"})

    return json_response(
        {"grants": issued, "skipped": skipped, "failures": failures, "remaining": remaining},
        status_code=201 if issued else 200,
    )


def redeem_url_for(landing_url: str, code: str) -> str:
    """The link that goes in the recipient's email: their page, carrying their own code.

    The page's coupon element renders the campaign's shared code; `?coupon=` replaces it with this
    recipient's. A baked artifact cannot hold one code per visitor, so the LINK carries it -- which is also
    why the code has to be unguessable.
    """
    separator = "&" if "?" in landing_url else "?"
    return f"{landing_url}{separator}coupon={code}"


def grants_for_coupon(grants_repo, tenant_id: str, coupon_id: str) -> list:
    """This coupon's grants. Filtered in memory: grants are keyed by CODE so checkout can read one directly,
    which is the access pattern that matters -- the tenant's own list is read once per campaign screen."""
    return [
        grant for grant in (grants_repo.list_for_tenant(tenant_id) or [])
        if str(grant.get("coupon_id") or "") == coupon_id
    ]


def list_grants(event, coupon_id: str, grants_repo=None):
    """The redemption view, and its CSV.

    The CSV is the delivery mechanism: the tenant sends the codes with the email software they already pay
    for, rather than waiting for this platform to grow a sending rail (decision, 2026-09-22). It stays
    useful even after one exists, for tenants who prefer their own.
    """
    params = query_params(event)
    tenant_id = str(params.get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    grants_repo = grants_repo or coupon_grants_repository(mode=resolve_stripe_mode(event))
    grants = sorted(grants_for_coupon(grants_repo, tenant_id, coupon_id),
                    key=lambda grant: str(grant.get("email") or ""))
    if str(params.get("format") or "").lower() == "csv":
        return csv_response(grants_csv(grants), filename=f"{coupon_id}-codes.csv")
    return json_response({"grants": grants})


GRANT_CSV_COLUMNS = ("email", "name", "code", "redeem_url", "status", "redeemed", "expires_at")


def grants_csv(grants: list) -> str:
    """One row per recipient, in the shape a mail-merge expects: the column a tenant drops into their
    template is `redeem_url`, and `code` is there for a plain-text mention of it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(GRANT_CSV_COLUMNS)
    for grant in grants:
        expires_at = grant.get("expires_at")
        writer.writerow([
            grant.get("email") or "",
            grant.get("name") or "",
            grant.get("code") or "",
            grant.get("redeem_url") or "",
            grant.get("status") or "",
            "yes" if int(grant.get("redemption_count") or 0) > 0 else "no",
            time.strftime("%Y-%m-%d", time.gmtime(int(expires_at))) if expires_at else "",
        ])
    return buffer.getvalue()


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
