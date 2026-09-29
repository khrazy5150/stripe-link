"""Per-tenant AI provider configuration (AI_AND_COMMERCE §A.1).

- GET  /ai/config                      -> the tenant's provider, model, allowance and usage (key redacted)
- POST /ai/connect {provider, model}   -> save it, and PROVE it by running a real generation

The verify step is a real call, not a status lookup, and that is not caution -- it is the only thing
that works. Measured 2026-09-27: `list-foundation-models` lists models an account cannot call;
`get-foundation-model-availability` then reports agreement, entitlement, authorization and region all
positive for those same models; and a model whose agreement says NOT_AVAILABLE invokes perfectly. No
readable field means "this model will answer". Bedrock's own Model access page has since been retired
in favour of "invoke it once to enable it", which makes this call the enabling step as well as the
check.
"""
import time

from stripe_link.ai_byok import BYOK_MODELS
from stripe_link.ai_client import AiError, generate_structured
from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.ai_models import default_model, model, model_names, profile_id
from stripe_link.domain.ai_provider import (AiConfigError, config_record, is_verified, needs_key,
                                            pays_platform, redacted, validate)
from stripe_link.domain.ai_quota import entitlement_for, may_generate, remaining
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (RepositoryError, ai_provider_config_repository,
                                                ai_usage_repository, tenant_profiles_repository)

# The encryption context binds the ciphertext to this tenant and this purpose, so a blob lifted from
# one row cannot be decrypted against another. `mode` is a fixed literal because an AI key has no
# test/live axis -- the field exists in the cipher's signature, not in this problem.
KMS_MODE = "ai"
KMS_FIELD = "ai_api_key"

# The smallest thing that proves a model will answer AND obey a schema. Deliberately tiny: this runs on
# every connect, the platform pays for it on the Bedrock path, and a bigger probe proves nothing more.
PROBE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}}}
PROBE_PROMPT = "Reply with {\"ok\": true} and nothing else."


def handler(event, context, *, config_repo=None, usage_repo=None, tenant_repo=None,
            generator=None, now_fn=None, secret_cipher=None):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    now = int((now_fn or time.time)())
    try:
        config_repo = config_repo or ai_provider_config_repository()
        usage_repo = usage_repo or ai_usage_repository()
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        return _read(tenant_id, config_repo, usage_repo, tenant_repo, now)
    if method == "POST":
        body = parse_json_body(event) or {}
        tenant_id = tenant_id_from_event(event, body)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        return _connect(tenant_id, body, config_repo, usage_repo, tenant_repo,
                        generator or generate_structured, now,
                        secret_cipher if secret_cipher is not None else KmsSecretCipher())
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _configured_allowances():
    """Trial/free allowances from the CONFIG row — the same source the generator reads, so the settings
    screen can never quote a number the generator will not honour."""
    try:
        from stripe_link.domain.platform_billing import (free_ai_generations, platform_billing_mode,
                                                         trial_ai_generations)

        mode = platform_billing_mode()
        return {"trial_allowance": trial_ai_generations(mode), "free_allowance": free_ai_generations(mode)}
    except Exception:  # noqa: BLE001 - a settings row must not break the settings screen
        return {}


def _profile(tenant_id: str, tenant_repo) -> dict:
    """The tenant's plan and exemption. Unreadable profile means the FREE tier, never an open tap."""
    try:
        # TWO arguments. DynamoDocumentRepository.get is (tenant_id, document_id) and a tenant profile is
        # keyed by its own id -- every other handler calls it `get(tenant_id, tenant_id)`. Called with one,
        # it raises TypeError, the except below swallows it, and every tenant looks like they have no
        # profile. That was survivable while a missing profile fell back to a small allowance; once the
        # free tier means ZERO it silently refuses AI to everyone.
        return (tenant_repo or tenant_profiles_repository()).get(tenant_id, tenant_id) or {}
    except Exception:  # noqa: BLE001 - a missing profile must not hand out platform-paid inference
        return {}


def _usage_block(tenant_id, config, usage_repo, tenant_repo, now):
    provider = str((config or {}).get("provider") or "")
    # The screen must read the SAME counter the generator will spend from, period included: showing a trial
    # tenant a monthly period here while the generator spends from the lifetime one would put two different
    # numbers in front of the same person.
    entitlement = entitlement_for(_profile(tenant_id, tenant_repo), provider=provider, now=now,
                                  **_configured_allowances())
    allowance, period = entitlement["allowance"], entitlement["period"]
    try:
        used = usage_repo.used(tenant_id, period)
    except Exception:  # noqa: BLE001 - a counter read must not break the settings screen
        used = 0
    allowed, reason = may_generate(used, allowance, entitlement["source"])
    return {"period": period, "used": used, "allowance": allowance, "source": entitlement["source"],
            "remaining": remaining(used, allowance), "can_generate": allowed, "reason": reason,
            # Who pays. The screen has to say this plainly -- "included" and "billed to your own key"
            # are different products and a tenant should never have to infer which one they are on.
            "billed_to": "platform" if pays_platform(provider) else "tenant"}


def _catalogue():
    """The models a tenant may choose, with what each is for.

    Excludes anything barred from page generation rather than listing it with a warning: a model that
    drifted on facts it was not given (§A.7) should not be one click away from a buyer-facing page.
    """
    out = []
    for name in model_names():
        entry = model(name) or {}
        if entry.get("page_generation") is False:
            continue
        out.append({"name": name, "label": entry.get("label", name),
                    "rate_in": entry.get("rate_in"), "rate_out": entry.get("rate_out"),
                    "rate_confidence": entry.get("rate_confidence", "unknown")})
    return out


def _read(tenant_id, config_repo, usage_repo, tenant_repo, now):
    try:
        config = config_repo.get(tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    return json_response({
        "ai_config": redacted(config) if config else {},
        "verified": is_verified(config),
        "usage": _usage_block(tenant_id, config, usage_repo, tenant_repo, now),
        "models": _catalogue(),
        "default_model": default_model(),
    })


def _connect(tenant_id, body, config_repo, usage_repo, tenant_repo, generator, now, cipher):
    provider = str(body.get("provider") or "").strip().lower()
    byok = needs_key(provider)
    chosen = str(body.get("model") or "").strip() or ("" if byok else default_model())
    # A BYO key names models from the TENANT's account, not our Bedrock registry -- their entitlements,
    # their bill. Still a closed list rather than a passthrough: a typo would otherwise surface as a
    # confusing vendor error, and a wrong id as a surprise charge.
    known = chosen in (BYOK_MODELS.get(provider) or {}) if byok else bool(profile_id(chosen))
    if not known:
        return error_response(f"Unknown model '{chosen}' for {provider or 'that provider'}.",
                              code="unknown_model")
    api_key = str(body.get("api_key") or "").strip()
    if byok and not api_key:
        return error_response("That provider needs an API key.", code="missing_api_key")

    # Prove it BEFORE anything is stored -- with the plaintext key still in hand, so a key that does not
    # work never becomes a saved configuration the tenant has to discover is broken later.
    try:
        probe = generator(prompt=PROBE_PROMPT, json_schema=PROBE_SCHEMA, model=chosen,
                          provider=provider, api_key=api_key, schema_name="probe", max_tokens=64)
    except AiError as exc:
        return error_response(_verify_message(exc, chosen), status_code=502,
                              code=f"verify_{exc.kind}")

    key_ref = ""
    if byok:
        try:
            key_ref = cipher.encrypt(api_key, tenant_id=tenant_id, mode=KMS_MODE, field=KMS_FIELD)
        except Exception as exc:  # noqa: BLE001 - never fall through to storing a key in clear
            return error_response(f"Could not store that key securely: {exc}", code="encrypt_failed")
    try:
        record = config_record(tenant_id, provider=provider, model=chosen, api_key_ref=key_ref, at=now)
    except AiConfigError as exc:
        return error_response(str(exc), code="invalid_ai_config")

    record["verified_at"] = now
    record["verify_usage"] = probe.get("usage", {})
    try:
        validate(record)
        config_repo.put(record)
    except (AiConfigError, RepositoryError) as exc:
        return error_response(str(exc), code="save_failed")
    return json_response({
        "ai_config": redacted(record),
        "verified": True,
        "usage": _usage_block(tenant_id, record, usage_repo, tenant_repo, now),
    })


def _verify_message(exc: AiError, chosen: str) -> str:
    """Say which side the problem is on. A tenant who cannot tell will ask us either way."""
    if exc.kind == "bad_credentials":
        return (f"That API key was rejected by the provider. Check it is correct and still active, and "
                f"that it has access to {chosen}.")
    if exc.kind == "not_entitled":
        return (f"This platform cannot reach {chosen} yet — the model is not enabled for our AWS "
                f"account. Nothing is wrong with your settings.")
    if exc.kind == "throttled":
        return f"{chosen} is busy right now. Try again in a moment."
    if exc.kind == "unusable_output":
        return f"{chosen} answered, but could not follow the required format. Try a different model."
    return f"Could not reach {chosen}: {exc.message}"
