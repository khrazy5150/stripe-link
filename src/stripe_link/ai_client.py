"""The AI provider adapter -- one normalized `generate_structured` (AI_AND_COMMERCE §A.2).

Bedrock first, and boto3 rather than the raw-urllib pattern `stripe_client.py` uses: `bedrock-runtime`
is already in the runtime's boto3, so this adds no dependency (`src/requirements.txt` stays empty) and
SigV4 is signed for us. A BYO-key provider will be a sibling in this module, behind the same function,
so callers never learn which one answered.

Structured output is Bedrock's FIRST-CLASS feature here (`outputConfig.textFormat.structure.jsonSchema`)
rather than tool-use bolted into the shape of one. Measured 2026-09-27 across four Claude models: all
four returned schema-valid, renderable JSON on the first attempt, zero repairs. The repair loop below
still exists because one entitled model -- `openai.gpt-oss-120b` -- array-wrapped its object and then
emitted malformed JSON with `stopReason: end_turn`, and a provider-agnostic adapter cannot assume the
good case.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from stripe_link.ai_byok import ByokError, generate as byok_generate
from stripe_link.domain.ai_models import allows_page_generation, cache_checkpoint_worthwhile, profile_id

DEFAULT_REGION = "us-west-2"
MAX_REPAIRS = 2  # bounded: a model that cannot satisfy the schema twice will not on the third try


class AiError(Exception):
    """A generation failed. `kind` is what the CALLER should do about it, not what went wrong."""

    def __init__(self, message: str, *, kind: str = "provider_error", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.kind = kind          # not_entitled | bad_credentials | invalid_request | throttled |
                                  # unusable_output | provider_error
        self.detail = detail


# Bedrock says "not available for this account" for a model whose Marketplace agreement is missing.
# It is worth its own kind because it is the ONE failure a tenant cannot fix and an operator can.
_KIND_BY_BYOK = {"bad_credentials": "bad_credentials", "throttled": "throttled",
                 "invalid_request": "invalid_request", "unusable_output": "unusable_output"}

_KIND_BY_EXCEPTION = {
    "AccessDeniedException": "not_entitled",
    "ValidationException": "invalid_request",
    "ThrottlingException": "throttled",
    "ServiceQuotaExceededException": "throttled",
    "ModelTimeoutException": "throttled",
    "ModelNotReadyException": "throttled",
}


def _client(region: str = DEFAULT_REGION):
    import boto3  # deferred: keeps import cost off every Lambda that merely imports this module
    from botocore.config import Config

    return boto3.client("bedrock-runtime", region_name=region,
                        config=Config(read_timeout=300, retries={"max_attempts": 2}))


def _strip_fence(text: str) -> str:
    """Undo a model that wrapped JSON in a markdown fence despite being asked for raw JSON."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    return raw.strip()


def _coerce(text: str) -> Any:
    """Parse the model's text, forgiving the two shapes that are wrong but recoverable.

    A fence is cosmetic. A single-element array wrapping the object is the real one: `gpt-oss-120b`
    returned `[{...}]` for a schema whose root is an object. Both are recovered rather than re-prompted,
    because a repair round costs a whole request to fix punctuation.
    """
    parsed = json.loads(_strip_fence(text))
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        return parsed[0]
    return parsed


def generate_structured(
    *,
    prompt: str,
    json_schema: dict[str, Any],
    model: str,
    provider: str = "bedrock",
    api_key: str = "",
    system: str = "",
    schema_name: str = "result",
    validate: Callable[[Any], None] | None = None,
    max_tokens: int = 4096,
    temperature: float = 1.0,
    region: str = DEFAULT_REGION,
    client: Any = None,
    byok_sender: Any = None,
    for_page: bool = False,
) -> dict[str, Any]:
    """Ask `model` for an object conforming to `json_schema`. Returns
    `{"value", "usage": {"input","output","cache_read"}, "model", "repairs", "stop_reason"}`.

    `validate` is the caller's own checker (e.g. the repo's `check_schema`) and is what drives the
    repair loop: the provider guarantees the SHAPE, never the meaning, and "5 sections in the catalog
    order" is not expressible in a JSON Schema the provider will accept.

    `for_page=True` refuses a model barred from buyer-facing copy. That check lives here rather than in
    the caller because §A.7's whole point is that the floor must not depend on being remembered.
    """
    provider = str(provider or "bedrock").strip().lower()
    if provider != "bedrock":
        return _byok_loop(provider=provider, api_key=api_key, model=model, prompt=prompt,
                          json_schema=json_schema, system=system, schema_name=schema_name,
                          validate=validate, max_tokens=max_tokens, temperature=temperature,
                          sender=byok_sender)
    if for_page and not allows_page_generation(model):
        raise AiError(f"Model {model!r} may not generate buyer-facing page copy.",
                      kind="invalid_request",
                      detail="Barred by the registry (AI_AND_COMMERCE §A.7): it drifted on facts it was not given.")
    profile = profile_id(model)
    if not profile:
        raise AiError(f"Unknown model {model!r}.", kind="invalid_request",
                      detail="Not in ai_models.json -- add it there rather than passing a raw profile id.")

    runtime = client or _client(region)
    system_blocks: list[dict[str, Any]] = []
    if system:
        system_blocks.append({"text": system})
        # The system prompt is byte-identical across generations and grows with the section catalog, so
        # a checkpoint here is the single biggest cost lever -- bigger than model choice. Bedrock
        # rejects one below the model's minimum, hence the ask rather than a guess.
        if cache_checkpoint_worthwhile(model, len(system) // 4):
            system_blocks.append({"cachePoint": {"type": "default"}})

    request: dict[str, Any] = {
        "modelId": profile,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": int(max_tokens), "temperature": float(temperature)},
        "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
            "name": schema_name, "schema": json.dumps(json_schema)}}}},
    }
    if system_blocks:
        request["system"] = system_blocks

    totals = {"input": 0, "output": 0, "cache_read": 0}
    complaint = ""
    for attempt in range(MAX_REPAIRS + 1):
        messages = list(request["messages"])
        if complaint:
            # Hand back WHAT was wrong, not just "try again" -- an unexplained retry reliably
            # reproduces the same output.
            messages = messages + [{"role": "user", "content": [{"text": complaint}]}]
        try:
            response = runtime.converse(**{**request, "messages": messages})
        except Exception as exc:  # noqa: BLE001 - normalized below; botocore types vary by model
            name = type(exc).__name__
            raise AiError(str(exc), kind=_KIND_BY_EXCEPTION.get(name, "provider_error"), detail=name) from exc

        usage = response.get("usage") or {}
        totals["input"] += int(usage.get("inputTokens") or 0)
        totals["output"] += int(usage.get("outputTokens") or 0)
        totals["cache_read"] += int(usage.get("cacheReadInputTokens") or 0)
        text = "".join(b.get("text", "") for b in (response.get("output", {})
                                                   .get("message", {}).get("content") or []))
        try:
            value = _coerce(text)
            if validate:
                validate(value)
            return {"value": value, "usage": totals, "model": model, "repairs": attempt,
                    "stop_reason": response.get("stopReason", "")}
        except json.JSONDecodeError as exc:
            complaint = (f"That was not valid JSON ({exc}). Return ONLY the JSON object, with no prose "
                         f"and no markdown fence.")
        except Exception as exc:  # noqa: BLE001 - the caller's validator raising is the repair signal
            complaint = f"That did not satisfy the contract: {exc}. Return a corrected JSON object."

    raise AiError("The model could not produce output matching the schema.",
                  kind="unusable_output", detail=complaint[:400])


def _byok_loop(*, provider, api_key, model, prompt, json_schema, system, schema_name, validate,
               max_tokens, temperature, sender=None) -> dict[str, Any]:
    """The same repair loop, against the tenant's own account.

    Deliberately a sibling rather than a shared generic: the two paths differ in what they may assume.
    Bedrock gives us a registry, a cost table and a §A.7 page-generation bar -- none of which apply to
    a key we do not own. A tenant's own model list is theirs, and so is the bill.
    """
    send = sender or byok_generate
    totals = {"input": 0, "output": 0, "cache_read": 0}
    complaint = ""
    for attempt in range(MAX_REPAIRS + 1):
        body = prompt if not complaint else f"{prompt}\n\n{complaint}"
        try:
            reply = send(provider, api_key=api_key, model=model, prompt=body, json_schema=json_schema,
                         system=system, schema_name=schema_name, max_tokens=max_tokens,
                         temperature=temperature)
        except ByokError as exc:
            raise AiError(exc.message, kind=_KIND_BY_BYOK.get(exc.kind, "provider_error"),
                          detail=f"{provider} HTTP {exc.status}" if exc.status else provider) from exc
        for key in totals:
            totals[key] += int((reply.get("usage") or {}).get(key) or 0)
        try:
            value = _coerce(reply.get("text") or "")
            if validate:
                validate(value)
            return {"value": value, "usage": totals, "model": model, "repairs": attempt,
                    "stop_reason": reply.get("stop_reason", ""), "provider": provider}
        except json.JSONDecodeError as exc:
            complaint = f"That was not valid JSON ({exc}). Return ONLY the JSON object."
        except Exception as exc:  # noqa: BLE001 - the caller's validator raising is the repair signal
            complaint = f"That did not satisfy the contract: {exc}. Return a corrected JSON object."
    raise AiError("The model could not produce output matching the schema.",
                  kind="unusable_output", detail=complaint[:400])
