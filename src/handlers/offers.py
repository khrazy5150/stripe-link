from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.domain.pricing import PricingError, resolve_offer
from stripe_link.repositories.documents import RepositoryError, offers_repository, products_repository


def handler(event, context, repository=None, products_repo=None):
    repository = repository or offers_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "POST":
        return create_offer(event, repository, products_repo)
    if method == "GET":
        offer_id = path_params(event).get("offer_id")
        if offer_id:
            return get_offer(event, repository, offer_id)
        return list_offers(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def create_offer(event, repository, products_repo=None):
    try:
        document = parse_json_body(event)
        validate_offer_document(document)
        validate_offer_product_compatibility(document, products_repo or products_repository())
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


def get_offer(event, repository, offer_id: str):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    offer = repository.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")
    return json_response({"offer": offer})


def list_offers(event, repository):
    tenant_id = str(query_params(event).get("tenant_id") or "").strip() or tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    return json_response({"offers": repository.list_for_tenant(tenant_id)})


def resolve_handler(event, context):
    try:
        body = parse_json_body(event)
        offer = body.get("offer")
        products = body.get("products")
        if not isinstance(offer, dict):
            return error_response("Field 'offer' must be an object.")
        if not isinstance(products, list):
            return error_response("Field 'products' must be an array.")
        selected_prices = body.get("selected_prices") or {}
        if not isinstance(selected_prices, dict):
            return error_response("Field 'selected_prices' must be an object when provided.")

        products_by_id = {
            product.get("product_id"): product
            for product in products
            if isinstance(product, dict) and product.get("product_id")
        }
        return json_response({
            "resolved_offer": resolve_offer(offer, products_by_id, selected_prices),
        })
    except PricingError as exc:
        return error_response(str(exc), code="pricing_error")
    except ValueError as exc:
        return error_response(str(exc), code="invalid_json")
