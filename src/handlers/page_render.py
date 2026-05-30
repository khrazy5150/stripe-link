from stripe_link.common import error_response, json_response, parse_json_body
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.domain.pricing import PricingError
from stripe_link.runtime.html import render_page


def handler(event, context):
    try:
        body = parse_json_body(event)
        page = body.get("page")
        offer = body.get("offer")
        products = body.get("products")
        selected_prices = body.get("selected_prices") or {}
        if not isinstance(page, dict):
            return error_response("Field 'page' must be an object.")
        if not isinstance(offer, dict):
            return error_response("Field 'offer' must be an object.")
        if not isinstance(products, list):
            return error_response("Field 'products' must be an array.")
        if not isinstance(selected_prices, dict):
            return error_response("Field 'selected_prices' must be an object when provided.")
        validate_page_document(page)
        products_by_id = {
            product.get("product_id"): product
            for product in products
            if isinstance(product, dict) and product.get("product_id")
        }
        html = render_page(page, offer, products_by_id, selected_prices)
        return json_response({"html": html})
    except (DocumentValidationError, PricingError, ValueError) as exc:
        return error_response(str(exc), code="render_error")
