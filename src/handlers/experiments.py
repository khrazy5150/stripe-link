import os
import time

from stripe_link.common import error_response, json_response, normalize_stripe_mode, parse_json_body, path_params, resolve_stripe_mode, tenant_id_from_event
from handlers.routes import short_url_for_code
from stripe_link.domain.experiments import SHORT_CODE_ENTRY_ENABLED, repoint_to_winner
from stripe_link.domain.experiment_stats import summarize
from stripe_link.runtime.publishing import site_page_slug, site_serving_origin
from stripe_link.domain.documents import DocumentValidationError, validate_experiment, validate_route
from stripe_link.entitlement_gate import require_capability
from stripe_link.ids import generate_id
from stripe_link.repositories.documents import (
    RepositoryError,
    experiments_repository,
    orders_repository,
    pages_repository,
    routes_repository,
    sites_repository,
)

SCHEMA_VERSION = "2026-05-29"
# Shared with the landing-page summaries: both answer "which orders count?" about the same table, so a
# status added to one must not be missing from the other.
from stripe_link.domain.page_analytics import PAID_ORDER_STATUSES  # noqa: E402


def handler(
    event,
    context,
    *,
    repository=None,
    routes=None,
    orders=None,
    pages=None,
    sites=None,
    now_fn=lambda: int(time.time()),
    id_fn=lambda: f"exp_{generate_id()}",
    code_fn=None,
    tenant_repo=None,
):
    mode = resolve_stripe_mode(event)
    repository = repository or experiments_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    experiment_id = path_params(event).get("experiment_id")
    action = _action_from_event(event)
    try:
        if method == "GET" and not experiment_id:
            return list_experiments(event, repository, sites=sites, mode=mode)
        if method == "GET" and experiment_id:
            return get_experiment(event, repository, experiment_id, orders, mode=mode, now_fn=now_fn, sites=sites)
        if method == "POST" and not experiment_id:
            gate = require_capability(event, "ab_testing", tenant_repo)
            if gate is not None:
                return gate
            return create_experiment(event, repository, routes, now_fn, id_fn, code_fn, mode=mode)
        if method == "PUT" and experiment_id and not action:
            return update_experiment(event, repository, experiment_id, now_fn)
        if method == "DELETE" and experiment_id and not action:
            return delete_experiment(event, repository, routes, experiment_id)
        if method == "POST" and experiment_id and action == "start":
            return start_experiment(event, repository, pages, now_fn, mode=mode, sites=sites)
        if method == "POST" and experiment_id and action == "pause":
            return set_status(event, repository, experiment_id, "paused", now_fn)
        if method == "POST" and experiment_id and action == "complete":
            return complete_experiment(event, repository, experiment_id, now_fn, sites=sites, mode=mode)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _action_from_event(event):
    resource = str((event or {}).get("resource") or "")
    tail = resource.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail in {"start", "pause", "complete"} else ""


def with_short_url(experiment):
    # Omitted while the short-code entry point is disabled, so nothing downstream can show a tenant a link
    # that no longer enters the experiment.
    if not SHORT_CODE_ENTRY_ENABLED:
        return dict(experiment)
    return {**experiment, "short_url": short_url_for_code(experiment.get("short_code", ""))}


def _load(repository, tenant_id, experiment_id):
    experiment = repository.get(tenant_id, experiment_id)
    if not experiment:
        return None, error_response("Experiment not found.", status_code=404, code="not_found")
    return experiment, None


def list_experiments(event, repository, sites=None, mode="test"):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiments = [with_short_url(item) for item in repository.list_for_tenant(tenant_id)]
    experiments.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    # The control's own URL is where a visitor enters the test -- there is no separate test link any more
    # (A1c), so without this the screen shows a running experiment and no way to go and look at it. Sites
    # are read once for the whole listing rather than per experiment.
    sites = sites or (sites_repository(mode=mode) if os.environ.get("SITES_TABLE") else None)
    cache = {}
    for item in experiments:
        page_id = str(item.get("control_page_id") or "")
        if page_id not in cache:
            cache[page_id] = control_url(tenant_id, page_id, sites)
        item["control_url"] = cache[page_id]
    return json_response({"experiments": experiments, "count": len(experiments)})


def get_experiment(event, repository, experiment_id, orders, mode="test", now_fn=None, sites=None):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    experiment, missing = _load(repository, tenant_id, experiment_id)
    if missing:
        return missing
    orders = orders or orders_repository(mode=mode)
    tenant_orders = orders.list_for_tenant(tenant_id)
    results = compute_results(experiment, tenant_orders)
    # A3: the numbers alone invite the classic mistake -- reading a big lift on 50 views as a result. The
    # comparison says whether the gap is bigger than the noise and what is left to run. It gates nothing:
    # when to stop is the tenant's call.
    comparisons = summarize(
        results, experiment.get("control_page_id"), days_elapsed=_days_elapsed(experiment, now_fn),
    )
    enriched = with_short_url(experiment)
    enriched["control_url"] = control_url(
        tenant_id,
        experiment.get("control_page_id"),
        sites or (sites_repository(mode=mode) if os.environ.get("SITES_TABLE") else None),
    )
    return json_response({
        "experiment": enriched, "results": results, "comparisons": comparisons,
    })


def _days_elapsed(experiment, now_fn):
    """Days the test has been collecting, 0.0 when it has not started.

    Measured to `completed_at` once finished, so a result read weeks later does not claim the test ran for
    weeks and dilute the rate it was actually collecting at.
    """
    started_at = int(experiment.get("started_at") or 0)
    if started_at <= 0:
        return 0.0
    end = int(experiment.get("completed_at") or 0) or int((now_fn or time.time)())
    return max(0.0, (end - started_at) / 86400.0)


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


def control_url(tenant_id, control_page_id, sites_repo):
    """The address visitors actually enter the test on — the CONTROL's own public URL. "" when it has none.

    Derived here rather than in the dashboard because choosing the host is a rule, not a formatting
    concern: a verified custom domain wins, else the free platform host, else the page has no public
    address at all (`site_serving_origin`). Duplicating that in Vue would drift the moment the rule changes.

    "" is a real answer and the screen must handle it: a tested page that is attached to no Site, or whose
    Site is not served anywhere yet, genuinely has no URL to copy.
    """
    if not sites_repo or not control_page_id:
        return ""
    try:
        for site in sites_repo.list_for_tenant(tenant_id) or []:
            slug = site_page_slug(site, control_page_id)
            if not slug:
                continue
            origin = site_serving_origin(site, slug)
            if not origin:
                return ""
            path = "" if slug in ("", "/") else slug.lstrip("/")
            return f"{origin}/{path}"
        return ""
    except Exception:  # noqa: BLE001 - a missing link must not fail the listing
        return ""


def _page_name(pages_repo, tenant_id, page_id):
    """A page's display name, falling back to its id. Best-effort: this is used to make an error message
    legible, and a lookup failure must not replace a useful error with a different one."""
    try:
        page = pages_repo.get(tenant_id, page_id) if pages_repo else None
    except Exception:  # noqa: BLE001
        page = None
    return str((page or {}).get("name") or page_id)


def attached_variant_slugs(tenant_id, variants, control_page_id, sites_repo):
    """Where non-control variants are publicly routable: {page_id: slug}. Empty when none are.

    A variant is an alternative rendering of the page under test, served behind THAT page's URL. Give it a
    slug of its own and it becomes a second public URL showing near-identical content, competing with the
    very page being tested (plans/AB_TESTING.md, Option A).

    Fails OPEN: if the Sites table cannot be read the check is skipped rather than blocking a start. The
    resolver already stamps noindex on an attached variant's own URL and publishing gives its artifact the
    tested page's canonical, so this is the third layer, not the only one.
    """
    if sites_repo is None:
        return {}
    wanted = {str(variant.get("page_id") or "") for variant in variants or []}
    wanted.discard(str(control_page_id or ""))
    wanted.discard("")
    if not wanted:
        return {}
    try:
        found = {}
        for site in sites_repo.list_for_tenant(tenant_id) or []:
            for slug, entry in ((site or {}).get("pages") or {}).items():
                if isinstance(entry, dict) and str(entry.get("page_id") or "") in wanted:
                    found[str(entry.get("page_id"))] = str(slug)
        return found
    except Exception:  # noqa: BLE001 - a check that cannot run must not block starting a test
        return {}


def _variant_fingerprint(variants):
    """Variants reduced to comparable scalars.

    Weights come back from DynamoDB as Decimal and from a request body as int, so comparing the raw lists
    reports "changed" for a save that changed nothing -- and this comparison GATES an error, so a false
    positive would block a legitimate rename.
    """
    return [
        (
            str(variant.get("page_id") or ""),
            int(variant.get("weight") or 0),
            str(variant.get("label") or ""),
            str(variant.get("key") or ""),
        )
        for variant in variants or []
    ]


def create_experiment(event, repository, routes, now_fn, id_fn, code_fn, mode="test"):
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
        # Isolation is already structural -- DynamoDocumentRepository bakes the mode into the SK and GSI1PK,
        # so a test experiment and a live one cannot see each other. This stamp is for READING: without it a
        # dumped experiment document cannot say which mode it belongs to, which is exactly the question
        # asked when something looks wrong.
        "stripe_mode": normalize_stripe_mode(mode),
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
    short_code = ""
    if SHORT_CODE_ENTRY_ENABLED:
        short_code = _allocate_experiment_route(routes, tenant_id, experiment_id, code_fn)
        if not short_code:
            return error_response("Could not allocate a unique short code.", status_code=500, code="code_generation_failed")
        experiment["short_code"] = short_code

    try:
        validate_experiment(experiment)
        saved = repository.put(experiment)
    except (DocumentValidationError, ValueError) as exc:
        if short_code:
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
    # An experiment's SHAPE is frozen once it has ever started. Changing which arm is the control moves the
    # entry point to a different URL mid-flight (assignment is matched on control_page_id), while
    # `stats.views_by_page` is one cumulative, untimestamped map -- so counts gathered from two different
    # entry points merge into the same counters with nothing recording which regime they came from. That is
    # unrecoverable rather than merely skewed, and it silently redefines the baseline the results are
    # measured against. Changing the control is not an edit to an experiment; it is a different experiment.
    #
    # Keyed on `started_at`, not on status == running: pausing does not make the data already collected
    # compatible with a different control. A draft that has never started stays fully editable -- there are
    # no results to invalidate.
    started = bool(experiment.get("started_at"))
    if "name" in body:
        experiment["name"] = str(body.get("name") or "").strip()
    if "control_page_id" in body:
        requested_control = str(body.get("control_page_id") or "").strip()
        if started and requested_control != str(experiment.get("control_page_id") or ""):
            return error_response(
                "The control page can't be changed once a test has started, because the results collected "
                "so far were measured against it. Stop this test and start a new one with the right control.",
                code="experiment_started",
            )
        experiment["control_page_id"] = requested_control
    if "variants" in body:
        requested_variants = normalize_variants(body.get("variants"), experiment.get("control_page_id"))
        if started and _variant_fingerprint(requested_variants) != _variant_fingerprint(experiment.get("variants")):
            return error_response(
                "Variants can't be changed once a test has started: the views and conversions already "
                "recorded belong to the arms as they were. Stop this test and start a new one.",
                code="experiment_started",
            )
        experiment["variants"] = requested_variants
    experiment["updated_at"] = int(now_fn())

    try:
        validate_experiment(experiment)
        saved = repository.put(experiment)
    except (DocumentValidationError, ValueError) as exc:
        return error_response(str(exc), code="invalid_experiment")
    return json_response({"experiment": with_short_url(saved)})


def start_experiment(event, repository, pages, now_fn, mode="test", sites=None):
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

    pages = pages or pages_repository(mode=mode)
    for variant in variants:
        page = pages.get(tenant_id, variant.get("page_id"))
        if not page:
            return error_response(f"Variant page {variant.get('page_id')} was not found.", code="variant_page_missing")
        if page.get("status") != "published":
            return error_response("All variant pages must be published before starting.", code="variant_not_published")

    sites = sites or (sites_repository(mode=mode) if os.environ.get("SITES_TABLE") else None)
    attached = attached_variant_slugs(tenant_id, variants, experiment.get("control_page_id"), sites)
    if attached:
        # Name the PAGE as well as the slug. A variant is usually a duplicate of the page being tested, so
        # the two share a name AND a slug, and a message that says only "remove /foo" leaves the tenant
        # guessing which of two identical-looking pages it means.
        where = ", ".join(
            f"“{_page_name(pages, tenant_id, page_id)}” at {slug}"
            for page_id, slug in sorted(attached.items(), key=lambda item: item[1])
        )
        return error_response(
            "A variant can't have a public address of its own while it's being tested — it would compete "
            f"in search with the page you're testing. Detach {where} from its site, then start the test. "
            "The variant is still served during the test, behind the tested page's own URL.",
            code="variant_attached",
        )

    now = int(now_fn())
    experiment["status"] = "running"
    experiment["started_at"] = now
    experiment["updated_at"] = now
    # A run starts from zero. Nothing else ever clears these counters, so without this a tenant who stops a
    # test, fixes something and starts it again gets results contaminated by the previous run -- and
    # "stop, edit, restart" would be the way around the shape freeze above.
    experiment["stats"] = {"views_by_page": {}}
    saved = repository.put(experiment)

    # Re-render the variants, and only AFTER the experiment is saved as running -- `identity_page_id` keys
    # off a RUNNING experiment, so a re-render ordered before this line would resolve nothing and change
    # nothing.
    #
    # A2 applies at publish time, but the order a tenant actually works in is build the variant, publish
    # it, THEN start the test. So the artifact was rendered while the experiment did not yet exist and it
    # baked its OWN identity: an interim canonical pointing at the raw artifact URL, and -- on a live
    # custom domain -- noindex, because an unattached page is not on a custom domain. Served behind the
    # tested page's URL that de-indexes the very page the test exists to improve. Found in QA on dev
    # 2026-09-21, where test-mode noindex hid half of it.
    _rerender_variants(tenant_id, experiment, pages, now)
    return json_response({"experiment": with_short_url(saved)})


def _rerender_variants(tenant_id, experiment, pages_repo, now):
    """Re-put each non-control variant page so the publish stream re-renders it with the tested page's
    identity (plans/AB_TESTING.md A2).

    Best-effort per page: a variant that cannot be re-rendered keeps its previous artifact, which is the
    state it was already in. Failing the START over it would be worse -- the tenant would be blocked from
    testing by a transient write, and the artifacts are still servable.
    """
    control_page_id = str(experiment.get("control_page_id") or "")
    for variant in experiment.get("variants") or []:
        page_id = str(variant.get("page_id") or "")
        if not page_id or page_id == control_page_id:
            continue
        try:
            page = pages_repo.get(tenant_id, page_id) if pages_repo else None
            if page:
                page["updated_at"] = int(now)
                pages_repo.put(page)  # a MODIFY fires page_publish, which re-runs publish_page_document
        except Exception:  # noqa: BLE001 - the artifact it already has is still servable
            continue


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


def complete_experiment(event, repository, experiment_id, now_fn, sites=None, mode="test"):
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

    # Promote BEFORE recording the result. Completing is what stops assignment, so if the route move fails
    # after it, the tested URL quietly reverts to the LOSER while the tenant is told the winner is live.
    # Refusing here leaves the experiment running and retryable, which is the recoverable order.
    promotion, failure = _promote_winner(tenant_id, experiment, winner_page_id, sites, mode=mode)
    if failure:
        return failure

    now = int(now_fn())
    experiment["status"] = "completed"
    experiment["winner_page_id"] = winner_page_id
    experiment["completed_at"] = now
    experiment["updated_at"] = now
    # Durable, so the screen can say what actually happened instead of asserting it.
    experiment["promotion"] = promotion
    saved = repository.put(experiment)
    return json_response({"experiment": with_short_url(saved)})


def _promote_winner(tenant_id, experiment, winner_page_id, sites, mode="test"):
    """Re-point the tested slug at the winner. Returns `(promotion, failure_response)`.

    `promotion.status` is one of:
      not_needed — the control won; it already holds the slug
      moved      — the slug now serves the winner
      no_route   — the control held no slug on any Site, so there was nothing to move. Not an error: a Site
                   is optional, and an experiment on an unrouted page is a legitimate (if odd) thing to run.
    """
    control_page_id = str(experiment.get("control_page_id") or "")
    if not control_page_id or control_page_id == winner_page_id:
        return {"status": "not_needed", "slug": ""}, None

    sites = sites or (sites_repository(mode=mode) if os.environ.get("SITES_TABLE") else None)
    if sites is None:
        return {"status": "no_route", "slug": ""}, None
    try:
        for site in sites.list_for_tenant(tenant_id) or []:
            pages, slug = repoint_to_winner(site, control_page_id, winner_page_id)
            if not slug:
                continue
            site["pages"] = pages
            sites.put(site)
            return {"status": "moved", "slug": slug}, None
        return {"status": "no_route", "slug": ""}, None
    except Exception:  # noqa: BLE001 - reported, never swallowed: the tenant is about to be told it is live
        return None, error_response(
            "The winner was chosen, but the site address could not be moved to it, so nothing has changed. "
            "The test is still running — try completing it again.",
            code="promotion_failed",
        )


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
