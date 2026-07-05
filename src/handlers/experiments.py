import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from handlers.routes import short_url_for_code
from stripe_link.domain.documents import DocumentValidationError, validate_experiment, validate_route
from stripe_link.ids import generate_id
from stripe_link.repositories.documents import (
    RepositoryError,
    experiments_repository,
    orders_repository,
    pages_repository,
    routes_repository,
)

SCHEMA_VERSION = "2026-05-29"
PAID_ORDER_STATUSES = {"paid", "complete", "completed"}


def handler(
    event,
    context,
    *,
    repository=None,
    routes=None,
    orders=None,
    pages=None,
    now_fn=lambda: int(time.time()),
    id_fn=lambda: f"exp_{generate_id()}",
    code_fn=None,
):
    repository = repository or experiments_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    experiment_id = path_params(event).get("experiment_id")
    action = _action_from_event(event)
    try:
        if method == "GET" and not experiment_id:
            return list_experiments(event, repository)
        if method == "GET" and experiment_id:
            return get_experiment(event, repository, experiment_id, orders)
        if method == "POST" and not experiment_id:
            return create_experiment(event, repository, routes, now_fn, id_fn, code_fn)
        if method == "PUT" and experiment_id and not action:
            return update_experiment(event, repository, experiment_id, now_fn)
        if method == "DELETE" and experiment_id and not action:
            return delete_experiment(event, repository, routes, experiment_id)
        if method == "POST" and experiment_id and action == "start":
            return start_experiment(event, repository, pages, now_fn)
        if method == "POST" and experiment_id and action == "pause":
            return set_status(event, repository, experiment_id, "paused", now_fn)
        if method == "POST" and experiment_id and action == "complete":
            return complete_experiment(event, repository, experiment_id, now_fn)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _action_from_event(event):
    resource = str((event or {}).get("resource") or "")
    tail = resource.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail in {"start", "pause", "complete"} else ""


def with_short_url(experiment):
    return {**experiment, "short_url": short_url_for_code(experiment.get("short_code", ""))}


def _load(repository, tenant_id, experiment_id):
    experiment = repository.get(tenant_id, experiment_id)
    if not experiment:
        return None, error_response("Experiment not found.", status_code=404, code="not_found")
    return experiment, None


def list_experiments(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiments = [with_short_url(item) for item in repository.list_for_tenant(tenant_id)]
    experiments.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return json_response({"experiments": experiments, "count": len(experiments)})


def get_experiment(event, repository, experiment_id, orders):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id)
    if missing:
        return missing
    orders = orders or orders_repository()
    tenant_orders = orders.list_for_tenant(tenant_id)
    results = compute_results(experiment, tenant_orders)
    return json_response({"experiment": with_short_url(experiment), "results": results})


def normalize_variants(raw_variants, control_page_id):
    """Assign stable keys: the control page's variant gets 'control', others variant_a, variant_b, ..."""
    variants = []
    letters = iter("abcdefghijklmnopqrstuvwxyz")
    for raw in raw_variants if isinstance(raw_variants, list) else []:
        if not isinstance(raw, dict):
            continue
        page_id = str(raw.get("page_id") or "").strip()
        if not page_id:
            continue
        variant = {
            "page_id": page_id,
            "weight": int(raw.get("weight") or 0),
        }
        label = str(raw.get("label") or "").strip()
        if label:
            variant["label"] = label
        if page_id == control_page_id:
            variant["key"] = "control"
        else:
            variant["key"] = f"variant_{next(letters)}"
        variants.append(variant)
    return variants


def create_experiment(event, repository, routes, now_fn, id_fn, code_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    body = parse_json_body(event)
    control_page_id = str(body.get("control_page_id") or "").strip()
    variants = normalize_variants(body.get("variants"), control_page_id)
    experiment_id = _allocate_experiment_id(repository, id_fn)
    now = int(now_fn())
    experiment = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "experiment",
        "tenant_id": tenant_id,
        "experiment_id": experiment_id,
        "name": str(body.get("name") or "").strip(),
        "status": "draft",
        "control_page_id": control_page_id,
        "winner_page_id": None,
        "variants": variants,
        "cookie_name": f"jb_ab_{experiment_id}",
        "stats": {"views_by_page": {}},
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
    }

    routes = routes or routes_repository()
    short_code = _allocate_experiment_route(routes, tenant_id, experiment_id, code_fn)
    if not short_code:
        return error_response("Could not allocate a unique short code.", status_code=500, code="code_generation_failed")
    experiment["short_code"] = short_code

    try:
        validate_experiment(experiment)
        saved = repository.put(experiment)
    except (DocumentValidationError, ValueError) as exc:
        routes.delete(tenant_id, short_code)
        return error_response(str(exc), code="invalid_experiment")
    return json_response({"experiment": with_short_url(saved)}, status_code=201)


def _allocate_experiment_id(repository, id_fn):
    for _ in range(5):
        candidate = str(id_fn() or "").strip()
        if candidate and not repository.find_by_id(candidate):
            return candidate
    return str(id_fn() or "").strip()


def _allocate_experiment_route(routes, tenant_id, experiment_id, code_fn):
    from handlers.routes import allocate_short_code
    from stripe_link.ids import generate_short_url_code

    short_code = allocate_short_code(routes, code_fn or generate_short_url_code)
    if not short_code:
        return ""
    route = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "route",
        "tenant_id": tenant_id,
        "short_code": short_code,
        "target_type": "experiment",
        "target_experiment_id": experiment_id,
    }
    validate_route(route)
    routes.put(route)
    return short_code


def update_experiment(event, repository, experiment_id, now_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id)
    if missing:
        return missing
    if experiment.get("status") == "completed":
        return error_response("A completed experiment cannot be edited.", code="experiment_completed")

    body = parse_json_body(event)
    if "name" in body:
        experiment["name"] = str(body.get("name") or "").strip()
    if "control_page_id" in body:
        experiment["control_page_id"] = str(body.get("control_page_id") or "").strip()
    if "variants" in body:
        experiment["variants"] = normalize_variants(body.get("variants"), experiment.get("control_page_id"))
    experiment["updated_at"] = int(now_fn())

    try:
        validate_experiment(experiment)
        saved = repository.put(experiment)
    except (DocumentValidationError, ValueError) as exc:
        return error_response(str(exc), code="invalid_experiment")
    return json_response({"experiment": with_short_url(saved)})


def start_experiment(event, repository, pages, now_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id=path_params(event).get("experiment_id"))
    if missing:
        return missing

    variants = experiment.get("variants") or []
    total_weight = sum(int(variant.get("weight") or 0) for variant in variants)
    if total_weight != 100:
        return error_response("Variant weights must total 100 before starting.", code="invalid_weights")

    pages = pages or pages_repository()
    for variant in variants:
        page = pages.get(tenant_id, variant.get("page_id"))
        if not page:
            return error_response(f"Variant page {variant.get('page_id')} was not found.", code="variant_page_missing")
        if page.get("status") != "published":
            return error_response("All variant pages must be published before starting.", code="variant_not_published")

    now = int(now_fn())
    experiment["status"] = "running"
    experiment["started_at"] = now
    experiment["updated_at"] = now
    saved = repository.put(experiment)
    return json_response({"experiment": with_short_url(saved)})


def set_status(event, repository, experiment_id, status, now_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id)
    if missing:
        return missing
    experiment["status"] = status
    experiment["updated_at"] = int(now_fn())
    saved = repository.put(experiment)
    return json_response({"experiment": with_short_url(saved)})


def complete_experiment(event, repository, experiment_id, now_fn):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id)
    if missing:
        return missing

    body = parse_json_body(event)
    winner_page_id = str(body.get("winner_page_id") or "").strip()
    variant_page_ids = {variant.get("page_id") for variant in experiment.get("variants") or []}
    if not winner_page_id or winner_page_id not in variant_page_ids:
        return error_response("winner_page_id must be one of the experiment variants.", code="invalid_winner")

    now = int(now_fn())
    experiment["status"] = "completed"
    experiment["winner_page_id"] = winner_page_id
    experiment["completed_at"] = now
    experiment["updated_at"] = now
    saved = repository.put(experiment)
    return json_response({"experiment": with_short_url(saved)})


def delete_experiment(event, repository, routes, experiment_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment = repository.get(tenant_id, experiment_id)
    if not experiment:
        return error_response("Experiment not found.", status_code=404, code="not_found")
    short_code = str(experiment.get("short_code") or "")
    repository.delete(tenant_id, experiment_id)
    if short_code:
        (routes or routes_repository()).delete(tenant_id, short_code)
    return json_response({"deleted": True, "experiment_id": experiment_id})


def compute_results(experiment, orders):
    views_by_page = ((experiment.get("stats") or {}).get("views_by_page")) or {}
    conversions_by_page: dict[str, int] = {}
    revenue_by_page: dict[str, int] = {}
    for order in orders or []:
        if str(order.get("status") or "") not in PAID_ORDER_STATUSES:
            continue
        page_id = str((order.get("attribution") or {}).get("page_id") or "")
        if not page_id:
            continue
        conversions_by_page[page_id] = conversions_by_page.get(page_id, 0) + 1
        revenue_by_page[page_id] = revenue_by_page.get(page_id, 0) + int(order.get("amount_total") or 0)

    results = []
    for variant in experiment.get("variants") or []:
        page_id = variant.get("page_id")
        views = int(views_by_page.get(page_id) or 0)
        conversions = conversions_by_page.get(page_id, 0)
        revenue = revenue_by_page.get(page_id, 0)
        results.append({
            **variant,
            "views": views,
            "conversions": conversions,
            "revenue": revenue,
            "conversion_rate": (conversions / views) if views else 0.0,
            "is_winner": experiment.get("winner_page_id") == page_id,
        })
    return results
