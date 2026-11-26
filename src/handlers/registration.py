import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.domain.billing_status import TRIAL_PERIOD_SECONDS
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_profile
from stripe_link.repositories.documents import (
    RepositoryError,
    tenant_profiles_registration_repositories,
    tenant_profiles_repository,
)


def handler(event, context, repository=None, registration_repositories=None):
    provided_repository = repository is not None
    repository = repository or tenant_profiles_repository()
    if registration_repositories is None:
        registration_repositories = (
            [repository]
            if provided_repository
            else tenant_profiles_registration_repositories()
        )
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return register_tenant(event, registration_repositories)
    if method == "GET":
        tenant_id = path_params(event).get("tenant_id") or tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        profile = repository.get(tenant_id, tenant_id)
        if not profile:
            return error_response("Tenant not found.", status_code=404, code="not_found")
        return json_response({"tenant": profile})
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def register_tenant(event, repositories):
    try:
        document = parse_json_body(event)
        document.pop("password", None)
        if (
            "ads_subscription" in document or "ads_pilot_expires_at" in document
            or any(isinstance(document.get(field), (list, dict)) and "ads" in document[field]
                   for field in ("beta", "entitlements"))
        ):
            return error_response("Ads access is managed by Junior Bay.", code="invalid_tenant")
        document["tier_id"] = str(document.get("tier_id") or "free")
        document["billing_status"] = str(document.get("billing_status") or "trial")
        # Start the free platform trial clock (trial-first onboarding, plans/SAAS_BILLING_PAYWALL.md).
        if not document.get("trial_ends_at"):
            document["trial_ends_at"] = int(time.time()) + TRIAL_PERIOD_SECONDS
        validate_tenant_profile(document)
        for repository in repositories:
            if not repository.put_if_absent(document):
                return error_response("Tenant already exists.", status_code=409, code="tenant_exists")
        return json_response({"tenant": document}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_tenant")
