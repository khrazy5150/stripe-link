from stripe_link.common import error_response, json_response, parse_json_body
from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
)
from stripe_link.domain.pricing import PricingError
from stripe_link.runtime.html import RenderError, render_page


def handler(event, context):
    try:
        body = parse_json_body(event)
        page = body.get("page")
        offer = body.get("offer")
        products = body.get("products")
        selected_prices = body.get("selected_prices") or {}
        checkout_url = body.get("checkout_url")
        api_base_url = body.get("api_base_url") or ""
        if not isinstance(page, dict):
            return error_response("Field 'page' must be an object.")
        if not isinstance(offer, dict):
            return error_response("Field 'offer' must be an object.")
        if not isinstance(products, list):
            return error_response("Field 'products' must be an array.")
        if not isinstance(selected_prices, dict):
            return error_response("Field 'selected_prices' must be an object when provided.")
        if checkout_url is not None and not isinstance(checkout_url, str):
            return error_response("Field 'checkout_url' must be a string when provided.")
        if not isinstance(api_base_url, str):
            return error_response("Field 'api_base_url' must be a string when provided.")
        validate_page_document(page)
        validate_offer_document(offer)
        if page.get("tenant_id") != offer.get("tenant_id"):
            return error_response("Page and offer tenant_id must match.", code="render_error")
        if page.get("offer_id") != offer.get("offer_id"):
            return error_response("Page offer_id must match offer offer_id.", code="render_error")

        for product in products:
            if not isinstance(product, dict):
                return error_response("Each product must be an object.", code="render_error")
            validate_product_document(product)
            if product.get("tenant_id") != page.get("tenant_id"):
                return error_response("Product tenant_id must match page tenant_id.", code="render_error")

        products_by_id = {
            product.get("product_id"): product
            for product in products
            if isinstance(product, dict) and product.get("product_id")
        }
        html = render_page(page, offer, products_by_id, selected_prices, checkout_url, api_base_url)
        return json_response({"html": html})
    except (DocumentValidationError, PricingError, RenderError, ValueError) as exc:
        return error_response(str(exc), code="render_error")
