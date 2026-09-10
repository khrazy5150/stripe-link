"""The store's avatar: GET|PUT /tenant/avatar

Stored on the TENANT PROFILE, not the user profile, for exactly the reasons load_tenant_preferences gives
for the store's font: pages carry no owner, publish runs from a DynamoDB stream holding only the page, and
the avatar is a property of the STORE customers see rather than of a staff login. Two people editing one
store must not produce pages with different faces on them.

Kept narrow on purpose. A general "write the tenant profile" endpoint would let the browser touch billing
status and entitlements; this one reads the profile, changes one field, and writes it back.
"""
from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_profile
from stripe_link.repositories.documents import RepositoryError, tenant_profiles_repository

MAX_AVATAR_URL = 2048


def handler(event, context, repository=None):
    event = event or {}
    method = str(event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return json_response({})
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    repository = repository or tenant_profiles_repository()
    try:
        profile = repository.get(tenant_id, tenant_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="tenant_unavailable")
    if not profile:
        return error_response("Tenant profile not found.", status_code=404, code="not_found")

    if method == "GET":
        return json_response({"avatar_url": str(profile.get("avatar_url") or "")})
    if method != "PUT":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_avatar")
    url = str((body or {}).get("avatar_url") or "").strip()
    if url and not url.startswith("https://"):
        # The avatar renders on the tenant's own published pages; an http:// image would make every one of
        # them mixed-content, which browsers block silently.
        return error_response("The avatar must be an https:// URL.", code="invalid_avatar")
    if len(url) > MAX_AVATAR_URL:
        return error_response("That image URL is too long.", code="invalid_avatar")

    if url:
        profile["avatar_url"] = url
    else:
        profile.pop("avatar_url", None)   # cleared, not stored empty -- absent means "no store avatar"
    try:
        validate_tenant_profile(profile)
        saved = repository.put(profile)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_avatar")
    return json_response({"avatar_url": str(saved.get("avatar_url") or "")})
