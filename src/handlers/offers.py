import os
import re

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.domain.offer_index import offer_index_entry
from stripe_link.domain.opportunities import STAGE_LANDING, stage_opportunities
from stripe_link.domain.pricing import PricingError, expand_offer, resolve_offer
from stripe_link.domain.semantic import analyze_offer, label_from_model, slug_from_model
from stripe_link.domain.slugs import sanitize_slug, unique_slug
from stripe_link.repositories.documents import RepositoryError, offers_repository, products_repository, services_repository


def smart_offer_slug(offer: dict, products_by_id: dict, services_by_id: dict | None = None) -> str:
    """SEO slug BASE from the offer's semantic model (plans/OFFER_SEMANTIC_ANALYZER.md — the slug is the pilot
    consumer). Thin wrapper: the OfferSemanticModel is the single source of meaning (shared with the label so
    they can't diverge); NOT deduped — the caller runs unique_offer_slug for the `-N` net."""
    return slug_from_model(analyze_offer(offer, products_by_id, services_by_id))


def unique_offer_slug(desired: str, *, tenant_id: str, offer_id: str, repository) -> str:
    """Sanitize the desired slug and make it unique within the tenant. Slugs address published pages,
    so two offers off the same item must not collide — append -2, -3, … when taken."""
    try:
        existing = repository.list_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 - if we can't check, fall back to the sanitized slug
        return sanitize_slug(desired)
    # Exclude THIS offer's own slug, or re-saving would collide with itself and renumber its live URL.
    taken = {str(offer.get("slug") or "") for offer in existing if str(offer.get("offer_id") or "") != offer_id}
    return unique_slug(desired, taken)


def handler(event, context, repository=None, products_repo=None, services_repo=None):
    # Stripe-mode scoping: offers + the products they reference are read/written in the request's mode so a
    # test-mode dashboard only ever sees test records (plans/STRIPE_MODE_DECOUPLING.md P2).
    mode = resolve_stripe_mode(event)
    repository = repository or offers_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return create_offer(event, repository, products_repo, mode=mode, services_repo=services_repo)
    if method == "GET":
        offer_id = path_params(event).get("offer_id")
        if offer_id:
            return get_offer(event, repository, offer_id, products_repo=products_repo, mode=mode)
        return list_offers(event, repository)
    if method == "PATCH":
        offer_id = path_params(event).get("offer_id")
        if not offer_id:
            return error_response("offer_id is required.", code="missing_offer")
        return update_offer_status(event, repository, offer_id)
    if method == "DELETE":
        offer_id = path_params(event).get("offer_id")
        if not offer_id:
            return error_response("offer_id is required.", code="missing_offer")
        return delete_offer(event, repository, offer_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _landing_products(offer: dict, products_repo) -> dict:
    """Load the offer's landing products keyed by product_id (for smart-slug keywords)."""
    tenant_id = str(offer.get("tenant_id") or "")
    out = {}
    for opp in stage_opportunities(offer, STAGE_LANDING):
        product_id = str((opp or {}).get("product_id") or "")
        if product_id and product_id not in out:
            product = products_repo.get(tenant_id, product_id)
            if product:
                out[product_id] = product
    return out


def _landing_services(offer: dict, services_repo) -> dict:
    """Load the offer's landing services keyed by service_id — the naming half a service-only offer needs."""
    tenant_id = str(offer.get("tenant_id") or "")
    out = {}
    for opp in stage_opportunities(offer, STAGE_LANDING):
        service_id = str((opp or {}).get("service_id") or "")
        if service_id and service_id not in out:
            try:
                service = services_repo.get(tenant_id, service_id)
            except Exception:  # noqa: BLE001 - naming must never block a save
                service = None
            if service:
                out[service_id] = service
    return out


def create_offer(event, repository, products_repo=None, mode="test", services_repo=None):
    try:
        document = parse_json_body(event)
        products_repo = products_repo or products_repository(mode=mode)
        # Server owns the offer's LABEL and SLUG — both from ONE OfferSemanticModel so they can't diverge
        # (plans/OFFER_SEMANTIC_ANALYZER.md; slug is the pilot consumer). Precedence for each: an explicit client
        # value wins (tenant override / legacy client); else an EXISTING offer keeps its value so published URLs +
        # naming stay stable across edits; else a NEW offer gets the smart semantic default. The slug then runs
        # the -N uniqueness net.
        tenant_id = str(document.get("tenant_id") or "")
        offer_id = str(document.get("offer_id") or "")
        existing = repository.get(tenant_id, offer_id) if offer_id else None
        _cache: dict = {}

        def _services_for_naming(doc):
            """Services are needed ONLY to name a service-backed offer. Skip the lookup when there are none
            (the common case), and never let it raise — a naming nicety must not fail a save."""
            if not any(str((o or {}).get("service_id") or "") for o in stage_opportunities(doc, STAGE_LANDING)):
                return {}
            try:
                return _landing_services(doc, services_repo or services_repository(mode=mode))
            except Exception:  # noqa: BLE001
                return {}


        def _model():
            if "m" not in _cache:
                _cache["m"] = analyze_offer(document, _landing_products(document, products_repo),
                                            _services_for_naming(document))
            return _cache["m"]

        # Capture what the CLIENT actually sent before defaulting fills it in — a tenant-typed name has to
        # stay distinguishable from a derived one, because it steers the slug below.
        sent_name = str(document.get("name") or "").strip()
        if not sent_name:
            document["name"] = (str(existing["name"]) if existing and str(existing.get("name") or "").strip()
                                else label_from_model(_model()))

        sent_slug = str(document.get("slug") or "").strip()
        if sent_slug:
            desired = sent_slug
        elif existing and str(existing.get("slug") or "").strip():
            desired = str(existing["slug"])
        elif sent_name:
            # The tenant RENAMED the offer but left the slug alone. The label and slug are supposed to come
            # from one model so they cannot diverge — but a typed name bypasses the model, and deriving the
            # slug from products anyway produced "Workout Bundle" -> dietary-supplement-bundle. A deliberate
            # rename is the stronger signal, so the slug follows it. Only reachable for a NEW offer: an
            # existing one is caught by the branch above, so published URLs still never move on their own.
            desired = sent_name
        else:
            desired = slug_from_model(_model())
        document["slug"] = unique_offer_slug(desired, tenant_id=tenant_id, offer_id=offer_id, repository=repository)
        validate_offer_document(document)
        validate_offer_product_compatibility(document, products_repo or products_repository(mode=mode))
        saved = repository.put(document)
        return json_response({"offer": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_offer")


def validate_offer_product_compatibility(document: dict, products_repo) -> None:
    tenant_id = str(document.get("tenant_id") or "").strip()
    offer_intent = str(document.get("product_intent") or "").strip()
    if not tenant_id or not offer_intent:
        return

    product_ids = []
    for item in document.get("items") or []:
        product_id = str((item or {}).get("product_id") or "").strip()
        if product_id and product_id not in product_ids:
            product_ids.append(product_id)

    for product_id in product_ids:
        product = products_repo.get(tenant_id, product_id)
        if not product:
            raise DocumentValidationError(f"Offer item product_id '{product_id}' does not reference an existing product.")
        product_intent = str(product.get("product_intent") or "transaction").strip()
        if product_intent != offer_intent:
            raise DocumentValidationError(
                f"Offer product_intent '{offer_intent}' cannot include product '{product_id}' with product_intent '{product_intent}'."
            )


def get_offer(event, repository, offer_id: str, products_repo=None, services_repo=None, mode="test"):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    offer = repository.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")
    # ?expand=1 returns the ExpandedOffer (per-item product/service snapshots) the renderers consume
    # without lookups — storage stays normalized (plans/CONVERSION_CONTEXT.md).
    if str(query_params(event).get("expand") or "").strip() in {"1", "true"}:
        return json_response({"offer": _expand(tenant_id, offer, products_repo, services_repo, mode=mode)})
    return json_response({"offer": offer})


def _expand(tenant_id: str, offer: dict, products_repo=None, services_repo=None, mode="test") -> dict:
    products_repo = products_repo or products_repository(mode=mode)
    products_by_id = {}
    services_by_id = {}
    for item in stage_opportunities(offer, STAGE_LANDING):
        product_id = str((item or {}).get("product_id") or "").strip()
        service_id = str((item or {}).get("service_id") or "").strip()
        if product_id and product_id not in products_by_id:
            product = products_repo.get(tenant_id, product_id)
            if product:
                products_by_id[product_id] = product
        if service_id and service_id not in services_by_id:
            repo = services_repo or (services_repository() if os.environ.get("SERVICES_TABLE") else None)
            service = repo.get(tenant_id, service_id) if repo else None
            if service:
                services_by_id[service_id] = service
    return expand_offer(offer, products_by_id, services_by_id)


# Ceiling on a single page, so a client cannot ask for a response that breaches the 6MB Lambda limit. Offer
# documents run ~2.9KB, so 500 is roughly 1.5MB — comfortably inside it with room for growth.
MAX_OFFERS_PAGE = 500


def _page_params(event) -> tuple[int | None, str]:
    """(limit, cursor) from the query string. No limit means "everything", which is what every client sends
    today — the paged shape exists so the CONTRACT is in place before anything depends on the unbounded
    one, not to change behaviour now."""
    params = query_params(event)
    raw_limit = str(params.get("limit") or "").strip()
    cursor = str(params.get("cursor") or "").strip()
    if not raw_limit:
        return None, cursor
    try:
        limit = int(raw_limit)
    except ValueError:
        return None, cursor
    if limit <= 0:
        return None, cursor
    return min(limit, MAX_OFFERS_PAGE), cursor


def list_offers(event, repository):
    """The offer list. Three shapes, all on one route:

    * default — every full document, exactly as before, for clients that do not paginate.
    * `?view=index` — the slim list projection (~10% of a full document), small enough to load WHOLE.
      That is what keeps client-side search instant AND complete: a paginated full list would leave search
      covering only the pages already fetched, which is worse than the payload problem it solves.
    * `?limit=&cursor=` — a page of whichever shape was asked for.
    """
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    as_index = str(query_params(event).get("view") or "").strip().lower() == "index"
    limit, cursor = _page_params(event)

    if limit is None and not cursor:
        offers = repository.list_for_tenant(tenant_id)
        next_cursor = ""
    else:
        offers, next_cursor = repository.list_page_for_tenant(tenant_id, limit=limit, cursor=cursor)

    if as_index:
        offers = [offer_index_entry(offer) for offer in offers]
    body: dict = {"offers": offers}
    # Only present when there IS more, so "no next_cursor" is an unambiguous end-of-list.
    if next_cursor:
        body["next_cursor"] = next_cursor
    return json_response(body)


def update_offer_status(event, repository, offer_id: str):
    """Archive/restore an offer (soft) without a full re-save. Preserves referential integrity for
    published landing pages that reference the offer — unlike delete, which the UI guards."""
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_offer_status")
    status = str(body.get("status") or "").strip()
    if status not in {"active", "archived"}:
        return error_response("Offer status must be one of: active, archived.", code="invalid_offer_status")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    offer = repository.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")
    offer["status"] = status
    if body.get("updated_at") is not None:
        offer["updated_at"] = body.get("updated_at")
    try:
        saved = repository.put(offer)
        return json_response({"offer": saved})
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_offer_status")


def delete_offer(event, repository, offer_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, offer_id)
    if not deleted:
        return error_response("Offer not found.", status_code=404, code="not_found")
    return json_response({"deleted": True, "offer": deleted})


def resolve_handler(event, context):
    try:
        body = parse_json_body(event)
        offer = body.get("offer")
        products = body.get("products")
        services = body.get("services") or []
        if not isinstance(offer, dict):
            return error_response("Field 'offer' must be an object.")
        if not isinstance(products, list):
            return error_response("Field 'products' must be an array.")
        if not isinstance(services, list):
            return error_response("Field 'services' must be an array when provided.")
        selected_prices = body.get("selected_prices") or {}
        if not isinstance(selected_prices, dict):
            return error_response("Field 'selected_prices' must be an object when provided.")

        products_by_id = {
            product.get("product_id"): product
            for product in products
            if isinstance(product, dict) and product.get("product_id")
        }
        services_by_id = {
            service.get("service_id"): service
            for service in services
            if isinstance(service, dict) and service.get("service_id")
        }
        return json_response({
            "resolved_offer": resolve_offer(offer, products_by_id, selected_prices, services_by_id=services_by_id),
        })
    except PricingError as exc:
        return error_response(str(exc), code="pricing_error")
    except ValueError as exc:
        return error_response(str(exc), code="invalid_json")
