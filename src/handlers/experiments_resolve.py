import os
import random

from stripe_link.common import error_response, header_value, json_response, path_params
from stripe_link.repositories.documents import RepositoryError, experiments_repository
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import public_url


def handler(event, context, *, repository=None, pages_domain=None, choose_fn=None):
    """Public endpoint: assign a visitor to a variant and 302 to that variant's published page.

    Reached by the browser (the short-URL Worker 302s here for experiment codes). While the
    experiment is running each visit is assigned by weight and pinned with a sticky cookie so
    refreshes stay on the same variant; draft/paused fall back to the control page and completed
    routes everyone to the winner. Views are counted here, at the single funnel point.
    """
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    repository = repository or experiments_repository()
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")
    choose_fn = choose_fn or (lambda upper: random.randint(0, upper - 1))

    experiment_id = str(path_params(event).get("experiment_id") or "").strip()
    if not experiment_id:
        return error_response("experiment_id is required.", code="missing_experiment")

    try:
        experiment = repository.find_by_id(experiment_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    if not experiment:
        return error_response("Experiment not found.", status_code=404, code="not_found")

    cookie_name = str(experiment.get("cookie_name") or f"jb_ab_{experiment_id}")
    assigned = cookie_value(event, cookie_name)
    page_id, is_running = choose_page(experiment, assigned, choose_fn)
    if not page_id:
        return error_response("Experiment has no destination.", status_code=404, code="no_destination")

    url = public_url(pages_domain, artifact_paths(str(experiment.get("tenant_id") or ""), page_id)["published"])
    if not url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    if is_running:
        try:
            repository.increment_view(str(experiment.get("tenant_id") or ""), experiment_id, page_id)
        except RepositoryError:
            pass  # never fail a redirect over a metrics write

    return redirect_with_cookie(url, cookie_name, page_id)


def choose_page(experiment, assigned_page_id, choose_fn):
    """Return (page_id, count_as_view). Only running experiments assign and count views."""
    variants = experiment.get("variants") or []
    variant_page_ids = {variant.get("page_id") for variant in variants}
    status = experiment.get("status")

    if status == "completed":
        return experiment.get("winner_page_id") or experiment.get("control_page_id"), False
    if status != "running":
        return experiment.get("control_page_id"), False

    if assigned_page_id and assigned_page_id in variant_page_ids:
        return assigned_page_id, True
    return weighted_choice(variants, choose_fn), True


def weighted_choice(variants, choose_fn):
    weights = [max(0, int(variant.get("weight") or 0)) for variant in variants]
    total = sum(weights)
    if total <= 0:
        return variants[0].get("page_id") if variants else ""
    roll = choose_fn(total)
    upto = 0
    for variant, weight in zip(variants, weights):
        upto += weight
        if roll < upto:
            return variant.get("page_id")
    return variants[-1].get("page_id")


def cookie_value(event, name):
    raw = header_value(event, "Cookie")
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def redirect_with_cookie(url, cookie_name, page_id):
    return {
        "statusCode": 302,
        "headers": {
            "Location": url,
            "Set-Cookie": f"{cookie_name}={page_id}; Path=/; Max-Age=2592000; Secure; SameSite=Lax",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": "",
    }
