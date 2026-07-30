"""Multi-line cart checkout (plans/LISTICLE_AND_CART.md L2 Slice C).

POST /cart/checkout turns a whole server-side cart into ONE Stripe Checkout session with a line item per
cart line. It reuses the single-offer checkout's payload + session builders (handlers.checkout) so there is
one Stripe integration, and re-resolves every line's price server-side (domain.cart) — the client never
sets amounts. Returns the Stripe URL as JSON; the browser redirects to it.
"""
from urllib.request import urlopen

from handlers.checkout import build_checkout_payload, create_stripe_checkout_session
from stripe_link.common import error_response, json_response, parse_json_body
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain.cart import CartError, resolved_items_for_checkout
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.opportunities import STAGE_CHECKOUT, stage_opportunities
from stripe_link.domain.pricing import PricingError, load_offer_products, load_offer_services
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    carts_repository,
    offers_repository,
    pages_repository,
    products_repository,
    services_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials


def handler(
    event,
    context,
    *,
    carts_repo=None,
    offers_repo=None,
    products_repo=None,
    services_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    pages_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
):
    method = (event or {}).get("httpMethod", "POST").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="checkout_error")

    tenant_id = str(body.get("tenant_id") or "").strip()
    cart_id = str(body.get("cart_id") or "").strip()
    success_url = str(body.get("success_url") or "").strip()
    cancel_url = str(body.get("cancel_url") or "").strip()
    page_id = str(body.get("page_id") or "").strip()
    if not tenant_id or not cart_id:
        return error_response("tenant_id and cart_id are required.", code="invalid_cart")
    if not success_url or not cancel_url:
        return error_response("success_url and cancel_url are required.", code="missing_redirect_url")

    carts_repo = carts_repo or carts_repository()
    offers_repo = offers_repo or offers_repository()
    products_repo = products_repo or products_repository()
    if services_repo is None:
        try:
            services_repo = services_repository()
        except Exception:  # noqa: BLE001 - services table optional
            services_repo = None
    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen

    try:
        assert_billing_in_good_standing(tenant_repo.get(tenant_id, tenant_id))

        # Transactions are only allowed from a published page (same guard as the single-offer checkout): a draft
        # or unknown page_id cannot start a cart checkout even if the API is called directly.
        if page_id:
            pages_repo = pages_repo or pages_repository()
            page = pages_repo.get(tenant_id, page_id)
            if not page or page.get("status") != "published":
                return error_response(
                    "This page is not published. Transactions are only available on published pages.",
                    status_code=403, code="page_not_published",
                )

        cart = carts_repo.get(tenant_id, cart_id)
        if not cart or not (cart.get("line_items") or []):
            return error_response("Cart not found or empty.", status_code=404, code="not_found")
        offer = offers_repo.get(tenant_id, cart.get("offer_id") or "")
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        # Order bumps (checkout-stage opportunities) reference products that aren't landing items, so load them
        # too for build_checkout_payload to emit their synced price as an optional_item (SALES_FUNNELS.md P2).
        for bump in stage_opportunities(offer, STAGE_CHECKOUT):
            bump_product_id = str(bump.get("product_id") or "")
            if bump_product_id and bump_product_id not in products_by_id:
                bump_product = products_repo.get(tenant_id, bump_product_id)
                if bump_product:
                    products_by_id[bump_product_id] = bump_product
        services_by_id = load_offer_services(tenant_id, offer, services_repo)
        items = resolved_items_for_checkout(cart, offer, products_by_id, services_by_id)
        # subtotal + currency feed the platform-fee calc (build_fee_context) just like resolve_offer's output.
        resolved = {
            "items": items,
            "subtotal": sum(int(i["unit_amount"]) * int(i["quantity"]) for i in items),
            "currency": items[0]["currency"] if items else "usd",
        }

        mode = "live" if offer.get("stripe_mode") == "live" else "test"
        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
        api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
        if not api_key:
            return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

        fee_context = build_fee_context(
            tenant_id=tenant_id, offer=offer, products_by_id=products_by_id,
            resolved=resolved, tenant_repo=tenant_repo, billing_config_loader=billing_config_loader,
        )
        payload = build_checkout_payload(
            tenant_id=tenant_id, offer=offer, products_by_id=products_by_id, resolved=resolved,
            success_url=success_url, cancel_url=cancel_url, page_id=page_id,
            fee_context=fee_context, apply_application_fee=bool(stripe_account),
        )
        payload["metadata[cart_id]"] = cart_id  # tie the resulting order back to the cart (attribution)

        stripe_response = create_stripe_checkout_session(
            payload, api_key=api_key, stripe_account=stripe_account, opener=opener,
        )
        checkout_url = stripe_response.get("url")
        if not checkout_url:
            return error_response("Stripe did not return a checkout URL.", status_code=502, code="checkout_error")
        return json_response({"url": checkout_url})
    except CartError as exc:
        return error_response(str(exc), code="invalid_cart")
    except BillingStatusError as exc:
        return error_response(str(exc), status_code=402, code="tenant_billing_hold")
    except PricingError as exc:
        return error_response(str(exc), code="checkout_error")
    except Exception as exc:  # noqa: BLE001 - surface a clean error, never a 500 stack to the shopper
        return error_response(str(exc), status_code=500, code="checkout_error")
