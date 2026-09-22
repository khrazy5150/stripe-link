"""POST /experiments/{experiment_id}/view — count one assignment.

The edge assigns a visitor to a variant (plans/AB_TESTING.md A1) and cannot write to DynamoDB, so it pings
this. Called from the Worker inside `waitUntil`, so the visitor's response is never waiting on it.

Public and unauthenticated, because the caller is an edge worker with no tenant credentials. Two things
therefore matter more than usual:

  - The page_id is validated against the experiment's OWN variants. `increment_view` builds an
    ExpressionAttributeName from it, so an unchecked value would let anyone create arbitrary keys inside
    the stats map of a document they do not own.
  - Only a RUNNING experiment counts. A completed one is a historical record and must not keep moving.

Inflating a competitor's view count is the remaining abuse, and it is deliberately accepted for now: it
dilutes a conversion rate, it cannot read or destroy anything, and rate limiting belongs at the edge.
"""
import json
import os

from stripe_link.common import error_response, json_response, parse_json_body, path_params, resolve_stripe_mode
from stripe_link.repositories.documents import RepositoryError, experiments_repository


def handler(event, context, *, repository=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    experiment_id = str(path_params(event).get("experiment_id") or "").strip()
    if not experiment_id:
        return error_response("experiment_id is required.", code="missing_experiment")

    try:
        body = parse_json_body(event)
    except (ValueError, json.JSONDecodeError):
        return error_response("Body must be JSON.", code="invalid_body")
    page_id = str((body or {}).get("page_id") or "").strip()
    if not page_id:
        return error_response("page_id is required.", code="missing_page")

    # Mode-scoped, like every other reader of this table. The table is partitioned by KEY -- the mode is
    # baked into the SK and GSI1PK -- so a mode-agnostic repo does not read the wrong document, it reads
    # nothing, and every ping 404s. The resolver puts `?mode=` on the view_url it hands the edge; absent,
    # `resolve_stripe_mode` defaults to test, which is the fail-safe direction.
    mode = resolve_stripe_mode(event, body)
    repository = repository or (
        experiments_repository(mode=mode) if os.environ.get("EXPERIMENTS_TABLE") else None
    )
    if repository is None:
        return json_response({"counted": False, "reason": "experiments_table_unset"})

    try:
        experiment = repository.find_by_id(experiment_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    if not experiment:
        return error_response("Experiment not found.", status_code=404, code="not_found")

    if str(experiment.get("status") or "") != "running":
        # Not an error: an experiment can be paused between the edge assigning and this ping arriving.
        return json_response({"counted": False, "reason": "not_running"})

    variant_page_ids = {str(v.get("page_id") or "") for v in experiment.get("variants") or []}
    if page_id not in variant_page_ids:
        # The guard that matters: page_id becomes a DynamoDB attribute NAME downstream.
        return error_response("page_id is not a variant of this experiment.", code="unknown_variant")

    try:
        repository.increment_view(str(experiment.get("tenant_id") or ""), experiment_id, page_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    return json_response({"counted": True})
