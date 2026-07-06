"""Push a local Product (and its Prices) to the tenant's Stripe account.

POST /products/{product_id}/sync -- creates/updates the Stripe Product, creates any Prices
that don't have a stripe_price_id yet, records the returned ids + sync status on the document.
Local is the source of truth; Stripe Prices are immutable so amount changes are modeled as
new local prices (which get their own Stripe Price on the next sync).
"""

import copy
import time

from stripe_link.common import error_response, json_response, path_params, query_params, tenant_id_from_event
from stripe_link.domain.stripe_products import build_price_params, build_product_params
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import RepositoryError, products_repository, stripe_keys_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials


def handler(
    event,
    context,
    *,
    repository=None,
    stripe_repo=None,
    secret_cipher=None,
    caller=stripe_request,
    credentials_fn=checkout_credentials,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    product_id = str(path_params(event).get("product_id") or "").strip()
    if not product_id:
        return error_response("product_id is required.", code="missing_product")

    repository = repository or products_repository()
    stripe_repo = stripe_repo or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()

    try:
        product = repository.get(tenant_id, product_id)
        if not product:
            return error_response("Product not found.", status_code=404, code="not_found")

        mode = str(product.get("stripe_mode") or "test")
        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
        api_key, stripe_account = credentials_fn(tenant_id, mode, stripe_keys, secret_cipher)
        if not api_key:
            return error_response(
                f"No Stripe key configured for {mode} mode. Connect Stripe or add keys first.",
                code="stripe_not_configured",
            )

        if _is_check(event):
            drift = check_product_drift(product, api_key=api_key, stripe_account=stripe_account, caller=caller)
            product = _apply_drift_status(product, drift, int(now_fn()))
            repository.put(product)
            return json_response({"product": product, "drift": drift})

        synced, result = run_product_sync(
            product, api_key=api_key, stripe_account=stripe_account, caller=caller, now=int(now_fn()),
        )
        repository.put(synced)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    status_code = 200 if result.get("status") == "success" else 502
    return json_response({"product": synced, "sync": result}, status_code=status_code)


def _is_check(event) -> bool:
    return str(query_params(event).get("check") or "").lower() in {"1", "true", "yes"}


def _apply_drift_status(product, drift, now):
    product = copy.deepcopy(product)
    sync = dict(product.get("sync") or {})
    sync["status"] = "success" if drift.get("in_sync") else "drift"
    sync["error"] = None if drift.get("in_sync") else f"{len(drift.get('differences', []))} difference(s) vs Stripe"
    sync["last_synced_at"] = sync.get("last_synced_at")  # a check does not re-push
    product["sync"] = sync
    return product


def run_product_sync(product, *, api_key, stripe_account, caller, now):
    """Returns (updated_product, result). Never raises for Stripe errors -- records them on
    the document's sync block and in the result so the caller can surface them."""
    product = copy.deepcopy(product)
    call = lambda method, path, data: caller(  # noqa: E731
        method, path, api_key=api_key, stripe_account=stripe_account, data=data,
    )
    try:
        product_params = build_product_params(product)
        existing_id = str(product.get("stripe_product_id") or "").strip()
        if existing_id:
            stripe_product = call("POST", f"/products/{existing_id}", product_params)
        else:
            stripe_product = call("POST", "/products", product_params)
        stripe_product_id = stripe_product.get("id")
        product["stripe_product_id"] = stripe_product_id

        created_prices = 0
        for price in product.get("prices") or []:
            if str(price.get("stripe_price_id") or "").strip():
                continue
            created = call("POST", "/prices", build_price_params(price, stripe_product_id))
            price["stripe_price_id"] = created.get("id")
            created_prices += 1

        default_local = str(product.get("default_price_id") or "").strip()
        if default_local:
            match = next(
                (p for p in (product.get("prices") or [])
                 if p.get("price_id") == default_local and p.get("stripe_price_id")),
                None,
            )
            if match:
                call("POST", f"/products/{stripe_product_id}", {"default_price": match["stripe_price_id"]})

        archived_prices = _archive_orphan_prices(product, stripe_product_id, api_key, stripe_account, caller)

        product["sync"] = {"status": "success", "last_synced_at": now, "error": None}
        return product, {
            "status": "success",
            "stripe_product_id": stripe_product_id,
            "prices_created": created_prices,
            "prices_archived": archived_prices,
        }
    except StripeApiError as exc:
        product["sync"] = {"status": "failed", "last_synced_at": now, "error": exc.message}
        return product, {"status": "failed", "error": exc.message, "stripe_code": exc.stripe_code}


def _list_stripe_prices(stripe_product_id, api_key, stripe_account, caller):
    listing = caller(
        "GET", "/prices",
        api_key=api_key, stripe_account=stripe_account,
        params={"product": stripe_product_id, "limit": 100},
    )
    return listing.get("data") or []


def _archive_orphan_prices(product, stripe_product_id, api_key, stripe_account, caller):
    """Deactivate Stripe prices that no longer have a local counterpart (Stripe prices are
    immutable, so removed/changed local prices leave orphans). Best-effort."""
    kept = {str(p.get("stripe_price_id") or "") for p in (product.get("prices") or []) if p.get("stripe_price_id")}
    archived = 0
    try:
        for stripe_price in _list_stripe_prices(stripe_product_id, api_key, stripe_account, caller):
            if stripe_price.get("active") and str(stripe_price.get("id")) not in kept:
                caller("POST", f"/prices/{stripe_price['id']}",
                       api_key=api_key, stripe_account=stripe_account, data={"active": False})
                archived += 1
    except StripeApiError:
        pass  # archival is best-effort; a listing/deactivate failure must not fail the sync
    return archived


def check_product_drift(product, *, api_key, stripe_account, caller):
    """Read-only comparison of the local product vs its Stripe counterpart. Never mutates Stripe."""
    stripe_product_id = str(product.get("stripe_product_id") or "").strip()
    if not stripe_product_id:
        return {"in_sync": False, "differences": [{"field": "product", "issue": "not_synced"}]}

    differences = []
    try:
        stripe_product = caller("GET", f"/products/{stripe_product_id}", api_key=api_key, stripe_account=stripe_account)
    except StripeApiError as exc:
        return {"in_sync": False, "differences": [{"field": "product", "issue": f"stripe_error: {exc.message}"}]}

    if str(stripe_product.get("name") or "") != str(product.get("name") or ""):
        differences.append({"field": "name", "local": product.get("name"), "stripe": stripe_product.get("name")})
    local_active = str(product.get("status") or "active").lower() != "archived"
    if bool(stripe_product.get("active")) != local_active:
        differences.append({"field": "active", "local": local_active, "stripe": stripe_product.get("active")})

    try:
        stripe_prices = {str(p.get("id")): p for p in _list_stripe_prices(stripe_product_id, api_key, stripe_account, caller)}
    except StripeApiError:
        stripe_prices = {}
    for price in product.get("prices") or []:
        stripe_price_id = str(price.get("stripe_price_id") or "")
        if not stripe_price_id:
            differences.append({"field": "price", "price_id": price.get("price_id"), "issue": "not_synced"})
        elif stripe_price_id not in stripe_prices:
            differences.append({"field": "price", "price_id": price.get("price_id"), "issue": "missing_in_stripe"})
        elif int(stripe_prices[stripe_price_id].get("unit_amount") or 0) != int(price.get("unit_amount") or 0):
            differences.append({
                "field": "price_amount", "price_id": price.get("price_id"),
                "local": price.get("unit_amount"), "stripe": stripe_prices[stripe_price_id].get("unit_amount"),
            })

    return {"in_sync": not differences, "differences": differences}
