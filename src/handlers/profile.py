
from stripe_link.common import error_response, json_response, parse_json_body, query_params, tenant_id_from_event
from stripe_link.domain.store_timezone import suggest_timezone
from stripe_link.domain.documents import DocumentValidationError, validate_user_profile
from stripe_link.repositories.documents import RepositoryError, user_profiles_repository


def handler(event, context, repository=None):
    repository = repository or user_profiles_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        # The account-level business-email verification routes are RETIRED
        # (plans/SITE_AS_BUSINESS_IDENTITY.md §P4, 2026-11-04). A business's reply address belongs to the
        # Site that IS the business, verified per Site by /sites/{site_id}/business-email/* (§P3).
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
        # THE SUGGESTED TIMEZONE TRAVELS WITH THE PROFILE, derived rather than stored. The screen needs a
        # sensible default in the picker and the inference lives in one place -- a JS copy of the state
        # table would be a second answer to "where is this store", and the two would drift. Never written
        # back: a suggestion the tenant has not looked at must not become a value they appear to have
        # chosen (plans/THANK_YOU_PAGE.md P1).
        return json_response({"profile": profile,
                              "timezone_suggested": suggest_timezone((profile.get("business") or {}).get("address"))})
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
