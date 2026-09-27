"""The AI model registry -- what we may call, how to address it, what it costs (pure, no I/O).

Reads `ai_models.json`, which ships with the code rather than being uploaded separately. That is a
deliberate reaction to the fee table that sat three weeks stale on dev AND prod because the deployed
S3 config outranked the code default and nobody could see the divergence (plans/TODO.md, "the DEPLOYED
fee table was three weeks stale"). One source, travelling with the deploy that reads it.

Costs are estimates by construction: AWS publishes no machine-readable rates for any current-generation
model, so `rate_confidence` is carried on every entry and `estimate_cost` reports it rather than hiding
it behind a number that looks authoritative.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "ai_models.json"
_CACHE: dict[str, Any] | None = None


def _registry() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return _CACHE


def model_names() -> list[str]:
    return sorted((_registry().get("models") or {}).keys())


def model(name: str) -> dict[str, Any] | None:
    return (_registry().get("models") or {}).get(str(name or "").strip()) or None


def default_model() -> str:
    return str(_registry().get("default_model") or "")


def profile_id(name: str) -> str:
    """The inference-profile id to put on the wire.

    Never a bare model id: `us-west-2` has no In-Region inference for this generation, so
    `anthropic.claude-sonnet-4-6` is rejected where `us.anthropic.claude-sonnet-4-6` is served.
    """
    return str((model(name) or {}).get("profile") or "")


def allows_page_generation(name: str) -> bool:
    """False for a model barred from writing buyer-facing copy.

    Haiku 4.5 is the measured case (§A.7): cheapest of the four tested and the only one that drifted on
    facts, inventing dosing and an efficacy claim from a brief that contained neither. Cheapness is not
    the axis that matters when the output is a commercial page.
    """
    entry = model(name)
    return bool(entry) and entry.get("page_generation", True) is not False


def estimate_cost(name: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """Estimated USD for one call, with the confidence attached.

    `confidence` is part of the return, not a footnote: these rates are hand-maintained because AWS
    exposes none of them, and a caller that renders this to a tenant must be able to say so.
    """
    entry = model(name) or {}
    rate_in = float(entry.get("rate_in") or 0.0)
    rate_out = float(entry.get("rate_out") or 0.0)
    cost = (int(input_tokens or 0) * rate_in + int(output_tokens or 0) * rate_out) / 1_000_000
    return {
        "usd": round(cost, 6),
        "confidence": str(entry.get("rate_confidence") or "unknown"),
        "known": bool(entry),
    }


def cache_checkpoint_worthwhile(name: str, prompt_tokens: int) -> bool:
    """Is this prompt long enough for a cache checkpoint to be accepted?

    The system prompt is byte-identical across generations and grows with the section catalog and the
    blueprint library, which makes caching a larger lever on cost than model choice -- but Bedrock
    refuses a checkpoint below the model's minimum, so asking is cheaper than guessing.
    """
    minimum = int(((model(name) or {}).get("prompt_cache") or {}).get("min_tokens") or 0)
    return bool(minimum) and int(prompt_tokens or 0) >= minimum
