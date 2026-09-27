"""Per-tenant AI provider configuration (pure -- no I/O). AI_AND_COMMERCE §A.1, revised 2026-09-27.

Two paths behind ONE setting, which is the revision: `bedrock` (the platform's bill, gated on plan) and
a BYO key (the tenant's bill, every plan including free). One setting rather than two SKUs so a tenant
can switch direction without changing plan, and so there is one code path instead of two.

Free tenants keep BYO-key deliberately. Page generation is the ACQUISITION feature -- it is the visible
payoff of the JSON-first architecture -- and a free tenant who cannot run it never sees the thing that
would convert them.
"""

from __future__ import annotations

import time
from typing import Any

BEDROCK = "bedrock"
# Providers a tenant can bring a key for. Bedrock is absent on purpose: it has no key, only an IAM role,
# so the whole key surface is missing rather than present-and-empty.
BYOK_PROVIDERS = ("anthropic", "openai", "gemini", "deepseek")
PROVIDERS = (BEDROCK,) + BYOK_PROVIDERS

PLATFORM_PAID = (BEDROCK,)


class AiConfigError(Exception):
    """The tenant's configuration cannot be used. The message is shown to them."""


def needs_key(provider: str) -> bool:
    return str(provider or "").strip().lower() in BYOK_PROVIDERS


def pays_platform(provider: str) -> bool:
    """True when WE are billed for the inference. Decides whether the quota is a bundle or a ceiling."""
    return str(provider or "").strip().lower() in PLATFORM_PAID


def validate(config: dict[str, Any] | None) -> None:
    provider = str((config or {}).get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise AiConfigError(f"Choose an AI provider: {', '.join(PROVIDERS)}.")
    if needs_key(provider) and not str((config or {}).get("api_key_ref") or "").strip():
        raise AiConfigError("That provider needs an API key before it can be used.")
    if not needs_key(provider) and str((config or {}).get("api_key_ref") or "").strip():
        raise AiConfigError("Bedrock uses this platform's own access and takes no API key.")


def config_record(tenant_id: str, *, provider: str, model: str = "", api_key_ref: str = "",
                   at: int = 0) -> dict[str, Any]:
    now = int(at or time.time())
    provider = str(provider or "").strip().lower()
    record = {
        "schema_version": "2026-09-27",
        "document_type": "ai_provider_config",
        "tenant_id": str(tenant_id or ""),
        "provider": provider,
        "model": str(model or "").strip(),
        "verified_at": 0,
        "created_at": now,
        "updated_at": now,
    }
    if needs_key(provider) and api_key_ref:
        record["api_key_ref"] = str(api_key_ref)
    validate(record)
    return record


def redacted(config: dict[str, Any] | None) -> dict[str, Any]:
    """What a browser may see. The ciphertext never leaves the backend.

    Mirrors the Connect OAuth fix: returning the encrypted blob to the browser was shipped and then
    removed (plans/TODO.md, "stop returning the Connect OAuth token ciphertext to the browser"). A
    redaction that says whether a key EXISTS is all any screen has ever needed.
    """
    safe = {k: v for k, v in (config or {}).items() if k != "api_key_ref"}
    safe["has_api_key"] = bool((config or {}).get("api_key_ref"))
    return safe


def is_verified(config: dict[str, Any] | None) -> bool:
    """Has this configuration been proven by a real call?

    Not a lookup -- an INVOCATION. Measured 2026-09-27: `list-foundation-models` lists models an account
    cannot call, and `get-foundation-model-availability` reported four green flags (agreement,
    entitlement, authorization, region all AVAILABLE) for models that still returned AccessDenied. A
    catalogue check proves nothing; only a generation does.
    """
    return int((config or {}).get("verified_at") or 0) > 0
