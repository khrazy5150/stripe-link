from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    query_params,
    tenant_id_from_event,
)
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_config
from stripe_link.domain.refund_policy import (
    RefundPolicyError,
    build,
    stored_policies,
    tenant_policies,
    vocabulary as refund_policy_vocabulary,
)
from stripe_link.repositories.documents import RepositoryError, platform_config_repository


def handler(event, context, repository=None):
    repository = repository or platform_config_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method in {"POST", "PUT"}:
        return save_config(event, repository)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        config = repository.get(tenant_id)
        extras = _refund_payload(config or {}, event)
        if not config:
            # The document is genuinely absent, so the 404 stands -- but the refund vocabulary and the
            # PLATFORM's default terms do not depend on it existing, and a tenant with no config row is
            # exactly the one who needs the pickers populated. Withholding them here left the settings screen
            # with empty dropdowns for every tenant, since the config table starts empty.
            return error_response("Tenant config not found.", status_code=404, code="not_found",
                                  extra=extras)
        payload = {
            "config": config,
            # Resolved, so a caller can see what each class promises TODAY and a platform fallback is
            # labelled as what it is rather than dressed up as the tenant's own setting. Three small
            # objects, so every caller gets them.
        }
        payload.update(extras)
        return json_response(payload)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def save_config(event, repository):
    try:
        document = parse_json_body(event)
        _generate_refund_copy(document)
        validate_tenant_config(document)
        saved = repository.put(document)
        return json_response({"config": saved, "refund_policies": tenant_policies(saved)},
                             status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_config")


def _refund_payload(config, event):
    """The refund half of a /config answer: resolved defaults, and optionally the pickers' vocabulary.

    Separated so the NOT-FOUND path can return it too. Three small objects for every caller; the 20KB of
    generated previews only when asked, so no other screen reading /config pays for the pickers.
    """
    payload = {
        # Resolved, so a caller sees what each class promises TODAY and a platform fallback is labelled as
        # what it is rather than dressed up as the tenant's own setting.
        "refund_policies": tenant_policies(config),
    }
    # The vocabulary carries a generated sentence for all 126 class/window/condition combinations, because the
    # server must stay the only thing that can author a commercial promise -- a JavaScript copy of that
    # template is exactly how the literal in stores/products.js came to be published.
    if str(query_params(event).get("refund_options") or "").strip() in {"1", "true", "yes"}:
        payload["refund_policy_options"] = refund_policy_vocabulary()
    return payload


def _generate_refund_copy(document):
    """Fill in `short_label` and `full_policy` for any refund policy that arrived without them.

    SERVER-SIDE, which is the entire correction. The dashboard sends the three structured choices; the
    sentence a buyer reads is composed here, from one template, in one place. A client may still send its own
    wording -- a business with a legally-reviewed sentence must be able to keep it -- and `build` preserves
    whatever it is given.

    Raises nothing on its own: a policy `build` refuses (an unknown window, a custom window with no prose) is
    left exactly as it came in, so `validate_tenant_config` reports it as the input error it is rather than
    this function failing with a less useful message.
    """
    policies = stored_policies(document)
    for policy_class, policy in list(policies.items()):
        if not isinstance(policy, dict):
            continue
        try:
            policies[policy_class] = build(
                policy_class,
                refund_window=str(policy.get("refund_window") or ""),
                condition=str(policy.get("condition") or ""),
                return_method=str(policy.get("return_method") or ""),
                short_label=str(policy.get("short_label") or ""),
                full_policy=str(policy.get("full_policy") or ""),
                return_note=str(policy.get("return_note") or ""),
                keep_it_below=policy.get("keep_it_below"),
                source="tenant_default",
            )
            # `source` belongs to a RESOLVED policy, not to a stored default: the stored map already means
            # "the tenant's default for this class", and a stored source would be a second place for that
            # fact to be wrong.
            policies[policy_class].pop("source", None)
        except RefundPolicyError:
            # Narrow on purpose. `except Exception` here would swallow a genuine bug in `build` and hand the
            # tenant a validation message about their input instead -- the failure shape this repo has been
            # bitten by four times (a reasonable fallback, a silent failure, a symptom somewhere unrelated).
            continue
