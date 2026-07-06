"""Map a local Product/Price JSON document to Stripe API params (pure -- no I/O).

Direction is local -> Stripe: the local document is the source of truth. Stripe Prices are
immutable, so a price is created in Stripe only when it has no stripe_price_id yet; changing
an amount means adding a new local price (new price_id), which then gets its own Stripe Price.
"""

from typing import Any

STRIPE_MAX_IMAGES = 8


def _image_urls(images: Any) -> list[str]:
    urls: list[str] = []
    for image in images or []:
        if isinstance(image, str) and image.strip():
            urls.append(image.strip())
        elif isinstance(image, dict) and str(image.get("url") or "").strip():
            urls.append(str(image["url"]).strip())
    return urls[:STRIPE_MAX_IMAGES]


def build_product_params(product: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "name": str(product.get("name") or "Untitled product"),
        "active": str(product.get("status") or "active").lower() != "archived",
    }
    description = str(product.get("description") or "").strip()
    if description:
        params["description"] = description
    images = _image_urls(product.get("images"))
    if images:
        params["images"] = images

    metadata = {
        "tenant_id": str(product.get("tenant_id") or ""),
        "product_id": str(product.get("product_id") or ""),
    }
    for key, value in (product.get("stripe_metadata") or {}).items():
        if value is not None:
            metadata[str(key)] = str(value)
    params["metadata"] = metadata
    return params


def price_differs(local_price: dict[str, Any], stripe_price: dict[str, Any]) -> bool:
    """True if an immutable Stripe field (amount, currency, recurring) changed locally, so the
    Stripe price must be replaced (Stripe prices cannot be edited)."""
    if int(local_price.get("unit_amount") or 0) != int(stripe_price.get("unit_amount") or 0):
        return True
    if str(local_price.get("currency") or "usd").lower() != str(stripe_price.get("currency") or "usd").lower():
        return True
    local_recurring = local_price.get("recurring") if isinstance(local_price.get("recurring"), dict) else {}
    stripe_recurring = stripe_price.get("recurring") if isinstance(stripe_price.get("recurring"), dict) else {}
    if str(local_recurring.get("interval") or "") != str(stripe_recurring.get("interval") or ""):
        return True
    if local_recurring.get("interval") and int(local_recurring.get("interval_count") or 1) != int(stripe_recurring.get("interval_count") or 1):
        return True
    return False


def build_price_params(price: dict[str, Any], stripe_product_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "product": stripe_product_id,
        "currency": str(price.get("currency") or "usd").lower(),
        "unit_amount": int(price.get("unit_amount") or 0),
        "metadata": {"price_id": str(price.get("price_id") or "")},
    }
    nickname = str(price.get("badge") or price.get("nickname") or "").strip()
    if nickname:
        params["nickname"] = nickname

    recurring = price.get("recurring")
    if isinstance(recurring, dict) and recurring.get("interval"):
        params["recurring"] = {"interval": str(recurring["interval"])}
        if recurring.get("interval_count"):
            params["recurring"]["interval_count"] = int(recurring["interval_count"])
    return params
