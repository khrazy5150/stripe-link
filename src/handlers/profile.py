import secrets
import time

from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.business_email import (
    CODE_DIGITS, check_code, is_disposable, looks_like_email, start_verification,
)
from stripe_link.domain.documents import DocumentValidationError, validate_user_profile
from stripe_link.email_validation import check_email
from stripe_link.mailer import send_email
from stripe_link.repositories.documents import RepositoryError, user_profiles_repository


def handler(event, context, repository=None):
    repository = repository or user_profiles_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        path = str((event or {}).get("path") or "")
        if path.endswith("/business-email/start"):
            return start_business_email_verification(event, repository)
        if path.endswith("/business-email/confirm"):
            return confirm_business_email(event, repository)
        return save_profile(event, repository)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        user_id = str(query_params(event).get("user_id") or "").strip()
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        if not user_id:
            return error_response("user_id is required.", code="missing_user")
        profile = repository.get(tenant_id, user_id)
        if not profile:
            return error_response("Profile not found.", status_code=404, code="not_found")
        return json_response({"profile": profile})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_profile(event, repository):
    try:
        document = parse_json_body(event)
        scrub_password_fields(document)
        validate_user_profile(document)
        saved = repository.put(document)
        return json_response({"profile": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_profile")


def scrub_password_fields(document):
    for field in ["password", "current_password", "new_password", "confirm_password"]:
        document.pop(field, None)


def _profile_for(event, repository):
    """(tenant_id, user_id, profile, error_response). One lookup shared by both verification steps."""
    payload = parse_json_body(event)
    # Pass the body: tenant_id_from_event checks body -> query -> headers, and a POST sends it in the body.
    tenant_id = tenant_id_from_event(event, payload)
    user_id = str(payload.get("user_id") or "").strip()
    if not tenant_id or not user_id:
        return None, None, None, error_response("tenant_id and user_id are required.", code="missing_ids")
    profile = repository.get(tenant_id, user_id)
    if not profile:
        return None, None, None, error_response("Profile not found.", status_code=404, code="not_found")
    return tenant_id, user_id, profile, None


def start_business_email_verification(event, repository, *, mailer_send=None, now_fn=lambda: int(time.time()),
                                      code_fn=None, validator=None):
    """Validate the address, then email a code to it.

    The code goes to the NEW address, which is the whole point: it proves the tenant controls the mailbox
    they are asking us to put in every Reply-To.
    """
    tenant_id, user_id, profile, failure = _profile_for(event, repository)
    if failure:
        return failure
    payload = parse_json_body(event)
    email = str(payload.get("email") or "").strip().lower()

    if not looks_like_email(email):
        return error_response("That does not look like an email address.", code="invalid_email")
    if is_disposable(email):
        return error_response("That looks like a disposable address. Please use your business email.",
                              code="disposable_email")
    # Debounce fails OPEN: an outage must not stop a tenant setting up their business.
    verdict = (validator or check_email)(email)
    if not verdict["allowed"]:
        return error_response(verdict["reason"], code="rejected_email")

    code = str(code_fn() if code_fn else secrets.randbelow(10 ** CODE_DIGITS)).zfill(CODE_DIGITS)
    now = int(now_fn())
    business = dict(profile.get("business") or {})
    business["email_verification"] = start_verification(email, tenant_id=tenant_id, code=code, now=now)
    profile["business"] = business
    try:
        repository.put(profile)
    except (RepositoryError, ValueError) as exc:
        return error_response(str(exc), code="save_failed")

    try:
        (mailer_send or send_email)(
            to=email,
            subject="Your Junior Bay verification code",
            text=f"Your verification code is {code}. It expires in 5 minutes.",
            html=f"<p>Your verification code is <strong>{code}</strong>.</p><p>It expires in 5 minutes.</p>",
        )
    except Exception:  # noqa: BLE001 - tell the tenant; a code they never receive is a dead end
        return error_response("We could not send the code. Please check the address and try again.",
                              status_code=502, code="send_failed")
    # `catch_all` is reported, never blocking — the code is what proves the mailbox exists.
    return json_response({"status": "sent", "catch_all": bool(verdict.get("catch_all"))})


def confirm_business_email(event, repository, *, now_fn=lambda: int(time.time())):
    """Confirm the code, and only then does the address become usable as a Reply-To."""
    tenant_id, user_id, profile, failure = _profile_for(event, repository)
    if failure:
        return failure
    payload = parse_json_body(event)
    business = dict(profile.get("business") or {})
    pending = business.get("email_verification")
    ok, reason = check_code(pending, str(payload.get("code") or ""), tenant_id=tenant_id, now=int(now_fn()))
    if not ok:
        # Count the attempt BEFORE returning, or the cap is advisory.
        if isinstance(pending, dict):
            pending["attempts"] = int(pending.get("attempts") or 0) + 1
            business["email_verification"] = pending
            profile["business"] = business
            try:
                repository.put(profile)
            except (RepositoryError, ValueError):
                pass
        return error_response(reason, code="invalid_code")

    business["email"] = pending["pending_email"]
    business["email_verified"] = True
    business["email_verified_at"] = int(now_fn())
    business.pop("email_verification", None)
    profile["business"] = business
    try:
        repository.put(profile)
    except (RepositoryError, ValueError) as exc:
        return error_response(str(exc), code="save_failed")
    return json_response({"status": "verified", "email": business["email"]})
