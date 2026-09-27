"""Bring-your-own-key provider clients: the tenant's own account, billed to them (§A.1).

Raw urllib, the `stripe_client.py` pattern, so `src/requirements.txt` stays empty -- no vendor SDK is
worth ~20MB in every function package when the surface is one POST.

Each vendor reaches structured output differently, and the shapes genuinely differ rather than being
cosmetic variants:
  - OpenAI has `response_format: {type: json_schema, strict: true}`, which GUARANTEES conformance.
  - Anthropic has tool-use: offer exactly one tool and force it, and the arguments are the object.
Both normalize to the same return so `generate_structured` -- and every caller above it -- cannot tell
which one answered.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SECONDS = 300

# What a tenant's own key is allowed to name. A BYO key does NOT get our registry's model list -- their
# account, their entitlements -- but it cannot be a free-text passthrough either, or a typo becomes a
# confusing vendor error and a wrong id becomes a surprise bill.
BYOK_MODELS = {
    "anthropic": {"claude-sonnet-4-6": "claude-sonnet-4-6",
                  "claude-opus-4-6": "claude-opus-4-6",
                  "claude-haiku-4-5": "claude-haiku-4-5"},
    "openai": {"gpt-5.6": "gpt-5.6", "gpt-6": "gpt-6", "gpt-5.6-mini": "gpt-5.6-mini"},
}


class ByokError(Exception):
    def __init__(self, message: str, *, kind: str = "provider_error", status: int = 0):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status = status


def _kind_for_status(status: int) -> str:
    if status in (401, 403):
        return "bad_credentials"   # THEIR key -- say so, or they hunt through our settings
    if status == 429:
        return "throttled"
    if status in (400, 422):
        return "invalid_request"
    return "provider_error"


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")[:500]
        except Exception:  # noqa: BLE001 - the status is the useful part; a body is a bonus
            pass
        message = body
        try:
            parsed = json.loads(body)
            message = (parsed.get("error") or {}).get("message") or body
        except Exception:  # noqa: BLE001
            pass
        raise ByokError(message or f"HTTP {exc.code}", kind=_kind_for_status(exc.code), status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ByokError(f"Could not reach the provider: {exc.reason}", kind="provider_error") from exc


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode's extra demands, applied recursively.

    Every object must close `additionalProperties` and list EVERY property in `required` -- optionality
    is expressed by allowing null, not by omission. Left unapplied the API rejects the whole request,
    so this is a normalization rather than a nicety.
    """
    if not isinstance(schema, dict):
        return schema
    out = {k: _strict(v) if isinstance(v, (dict, list)) else v for k, v in schema.items()}
    for key in ("properties", "$defs", "definitions"):
        if isinstance(schema.get(key), dict):
            out[key] = {k: _strict(v) for k, v in schema[key].items()}
    if isinstance(schema.get("items"), dict):
        out["items"] = _strict(schema["items"])
    for key in ("anyOf", "allOf", "oneOf"):
        if isinstance(schema.get(key), list):
            out[key] = [_strict(v) for v in schema[key]]
    if out.get("type") == "object":
        out["additionalProperties"] = False
        if isinstance(out.get("properties"), dict):
            out["required"] = sorted(out["properties"].keys())
    return out


def generate(provider: str, *, api_key: str, model: str, prompt: str, json_schema: dict[str, Any],
             system: str = "", schema_name: str = "result", max_tokens: int = 4096,
             temperature: float = 1.0, poster=None) -> dict[str, Any]:
    """One structured generation on the TENANT's account. Returns `{"text", "usage", "stop_reason"}`."""
    provider = str(provider or "").strip().lower()
    send = poster or _post
    resolved = (BYOK_MODELS.get(provider) or {}).get(str(model or "").strip())
    if not resolved:
        raise ByokError(f"{model!r} is not a model we support on {provider or 'that provider'}.",
                        kind="invalid_request")
    if not str(api_key or "").strip():
        raise ByokError("No API key is configured for that provider.", kind="bad_credentials")

    if provider == "anthropic":
        payload: dict[str, Any] = {
            "model": resolved, "max_tokens": int(max_tokens), "temperature": float(temperature),
            "messages": [{"role": "user", "content": prompt}],
            # One tool, forced. Anthropic has no strict-JSON mode, so the tool's input_schema IS the
            # output contract and tool_choice removes the model's option to answer in prose instead.
            "tools": [{"name": schema_name, "description": "Return the result.",
                       "input_schema": json_schema}],
            "tool_choice": {"type": "tool", "name": schema_name},
        }
        if system:
            payload["system"] = system
        data = send(ANTHROPIC_URL, {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}, payload)
        blocks = [b for b in (data.get("content") or []) if b.get("type") == "tool_use"]
        if not blocks:
            raise ByokError("The model answered without using the required format.", kind="unusable_output")
        usage = data.get("usage") or {}
        return {"text": json.dumps(blocks[0].get("input") or {}),
                "usage": {"input": int(usage.get("input_tokens") or 0),
                          "output": int(usage.get("output_tokens") or 0),
                          "cache_read": int(usage.get("cache_read_input_tokens") or 0)},
                "stop_reason": str(data.get("stop_reason") or "")}

    if provider == "openai":
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload = {
            "model": resolved, "messages": messages, "max_completion_tokens": int(max_tokens),
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": _strict(json_schema)}},
        }
        data = send(OPENAI_URL, {"Authorization": f"Bearer {api_key}"}, payload)
        choices = data.get("choices") or []
        if not choices:
            raise ByokError("The model returned no answer.", kind="unusable_output")
        usage = data.get("usage") or {}
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        return {"text": str((choices[0].get("message") or {}).get("content") or ""),
                "usage": {"input": int(usage.get("prompt_tokens") or 0),
                          "output": int(usage.get("completion_tokens") or 0), "cache_read": cached},
                "stop_reason": str(choices[0].get("finish_reason") or "")}

    raise ByokError(f"{provider!r} is not a supported provider.", kind="invalid_request")
