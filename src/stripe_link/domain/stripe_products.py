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


ORDER_BUMP_CONTEXT = "order_bump"


def charged_unit_amount(price: dict[str, Any]) -> int:
    """What Stripe should charge for this price: the listed amount PLUS any postage folded into it.

    An order bump is opted into on Stripe's own hosted Checkout page, via `optional_items`, which is
    strictly after `shipping_options` are fixed at session creation. Stripe cannot re-rate shipping when
    an optional item is ticked, so a bump's size and weight never reach the postage quote: the buyer is
    quoted for a parcel that does not include it, and the tenant eats the difference when the bigger box
    turns out to cost more. Measured on a real order 2026-10-05 -- a cart quoted at 620c shipped at 669c
    once the bump was added, and the same cart with five bump units cost 1354c against the same 620c
    quote.

    `shipping_surcharge` is the tenant's answer to that: a flat postage amount folded into the price
    Stripe charges, so only the buyers who TAKE the bump pay it and the ones who decline are untouched.
    Flat rather than live because `optional_items` require a pre-synced Stripe Price -- there is no
    per-destination hook at the moment the buyer ticks the box.

    Every place that writes an amount to Stripe or compares one back goes through here, because the
    comparison is what keeps it stable: a sync that CREATED price+surcharge but COMPARED bare unit_amount
    would find a difference on every run and replace the Stripe Price forever.
    """
    return int(price.get("unit_amount") or 0) + int(price.get("shipping_surcharge") or 0)


def price_differs(local_price: dict[str, Any], stripe_price: dict[str, Any]) -> bool:
    """True if an immutable Stripe field (amount, currency, recurring) changed locally, so the
    Stripe price must be replaced (Stripe prices cannot be edited)."""
    if charged_unit_amount(local_price) != int(stripe_price.get("unit_amount") or 0):
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
        "unit_amount": charged_unit_amount(price),
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
