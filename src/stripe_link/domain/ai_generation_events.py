"""The durable record of what the AI was authorized to assert, and what it cost (pure -- no I/O).

AI_AND_COMMERCE_ARCHITECTURE.md §A.9. Third of three AI record types, and the boundaries are the point:

    ai_usage              how much quota has this tenant consumed?        expires with the period
    ai_jobs               what work is happening right now?               expires after 7 days
    ai_generation_events  what was the AI authorized to generate,         NEVER expires
                          and what did it cost?

The rule that separates them (author, 2026-09-29): **if deleting a record would lose evidence of what Junior
Bay charged, generated, or authorized, it does not belong in an expiring operational table.**

Two things forced this apart rather than one. Cost history cannot live on the quota counter, whose rows expire
at 90 days by design -- a counter that accumulated forever would be the wrong shape for a quota. And the brief
snapshot, decided in AI_PAGE_BRIEF v2 as "an immutable record of what the AI was licensed to assert", was going
onto the JOB, whose rows expire after seven days. A record that answers "why did the model say that?" is
worthless if it is gone before anyone thinks to ask.

**The event owns its own evidence.** `job_id` is a reference, never a dependency: everything needed to read the
record -- the brief it was grounded on, the model, the source, the cost -- is copied onto the event, so a job
vanishing after a week leaves the history perfectly intelligible.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "2026-09-29"
DOCUMENT_TYPE = "ai_generation_event"

# Who paid, snapshotted rather than derived later: a tenant's plan changes, and the question this answers is
# always "what was true when we spent it?"
SOURCE_TRIAL = "trial"
SOURCE_PLAN = "plan"
SOURCE_BYOK = "byok"
SOURCE_EXEMPT = "exempt"

# What the generation produced. One value today; the quota is deliberately counted in GENERATIONS rather than
# pages so that ad copy, SEO metadata and product descriptions can share this ledger without reshaping it.
OPERATION_PAGE_GENERATION = "page_generation"

STATUS_STARTED = "started"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_RELEASED = "released"


def source_for(*, provider: str, plan_key: str = "", exempt: bool = False, trial: bool = False) -> str:
    """Which allowance this generation was drawn from."""
    if str(provider or "").strip().lower() not in ("bedrock", ""):
        return SOURCE_BYOK  # their key, their bill -- the platform spent nothing
    if exempt:
        return SOURCE_EXEMPT
    return SOURCE_TRIAL if trial else SOURCE_PLAN


def event_key(created_at: int, generation_id: str) -> str:
    """The sort key: zero-padded epoch, then the id.

    Time-first because `new_id` is random, so the id alone cannot answer "this tenant's generations in
    October" without a secondary index. Padded to 10 digits so string ordering IS chronological ordering --
    unpadded epochs sort "9..." after "10..." and the range query silently returns the wrong window.
    """
    return f"{int(created_at):010d}#{str(generation_id or '')}"


def started(*, generation_id: str, tenant_id: str, job_id: str, created_at: int, source: str, model: str,
            provider: str, brief: dict[str, Any] | None, operation: str = OPERATION_PAGE_GENERATION,
            stripe_mode: str = "", period: str = "") -> dict[str, Any]:
    """The record written when the slot is spent -- BEFORE the model runs.

    Written at spend time, not on success, because the question the ledger answers is "what did we charge this
    tenant for?", and a generation that failed still consumed a slot until something releases it. A ledger
    that only recorded successes could never explain a counter that disagreed with it.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": DOCUMENT_TYPE,
        "tenant_id": str(tenant_id or ""),
        "event_key": event_key(created_at, generation_id),
        "generation_id": str(generation_id or ""),
        # A reference, deliberately not a dependency -- the job is gone in seven days.
        "job_id": str(job_id or ""),
        "period": str(period or ""),
        "source": str(source or ""),
        "operation": str(operation or OPERATION_PAGE_GENERATION),
        "model": str(model or ""),
        "provider": str(provider or ""),
        "stripe_mode": str(stripe_mode or ""),
        # What the model was allowed to ground on. The whole reason this table outlives the job.
        "brief_snapshot": dict(brief or {}),
        "status": STATUS_STARTED,
        "input_tokens": 0,
        "output_tokens": 0,
        # Integer micro-dollars, never a float: DynamoDB ADD on floats accumulates rounding error, and
        # Decimal-from-DynamoDB has already cost this repo a production bug.
        "estimated_cost_micros": 0,
        "actual_cost_micros": 0,
        "rate_confidence": "",
        "created_at": int(created_at),
        "updated_at": int(created_at),
        # NO `expires_at`. Its absence is the design: TTL is per item, so this row sitting in a table with a
        # TTL attribute configured would still live forever -- but this table has none either, so that nobody
        # can enable one without reading this.
    }


def completion(*, status: str, at: int, input_tokens: int = 0, output_tokens: int = 0,
               estimated_usd: float = 0.0, rate_confidence: str = "", error: str = "") -> dict[str, Any]:
    """The fields to merge onto the event once the call has returned (or failed)."""
    patch: dict[str, Any] = {
        "status": str(status or STATUS_SUCCEEDED),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "estimated_cost_micros": to_micros(estimated_usd),
        "rate_confidence": str(rate_confidence or ""),
        "updated_at": int(at),
    }
    if error:
        patch["error"] = str(error)[:500]
    return patch


def to_micros(usd: float | int | None) -> int:
    """USD to integer micro-dollars. One generation costs fractions of a cent, so cents would round to zero."""
    return int(round(float(usd or 0.0) * 1_000_000))


def to_usd(micros: int | None) -> float:
    return round(int(micros or 0) / 1_000_000, 6)
