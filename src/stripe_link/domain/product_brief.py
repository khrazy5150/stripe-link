"""Project a page brief from a Product the tenant already has (pure -- no I/O).

plans/AI_PAGE_BRIEF.md v2 §5. This is the piece that makes "Build with AI" a FORK off the product wizard
rather than a second wizard: v1 asked nine questions, and measured against `Products.vue` almost every one of
them had already been answered -- kind, name, description, category, price. The author's verdict on seeing it
built was that it duplicated the product wizard, and it did.

So the brief is no longer posted by a wizard. It is PROJECTED, from three sources:

    the Product         name, description, category, price, kind, measurements
    tenant config       refund policy, shipping -- READ, never re-asked
    Product.ai_context  audience, facts, evidence, tone, must_say, must_not_say

Projected fresh on every generation rather than stored, so a tenant who corrects their refund policy gets a
page that reflects it next time. The generation JOB keeps a snapshot for evidence (§A.9); this function is
where the live one comes from.

**Nothing here invents.** Every value is copied or absent. A field the Product does not carry is a sentence
`ai_floor` will refuse to let the page contain, which is the entire organising rule -- a thin brief makes a
cautious page, not a shorter one.
"""

from __future__ import annotations

from typing import Any

from stripe_link.domain.page_brief import DIGITAL, PHYSICAL, SERVICE

# `product_type` in the brief's vocabulary. A service is NOT projected here: services are their own document
# with their own wizard (plans/SERVICE_WIZARD.md §3), and v1 of the fork is products only.
KIND_FOR_PRODUCT_TYPE = {"physical": PHYSICAL, "digital": DIGITAL, "service": SERVICE}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _whole(value: Any) -> Any:
    """A money amount as a real int, or the value untouched when it is not a number at all.

    Untouched rather than zeroed on failure: a price we cannot read must reach the brief validator and be
    refused there with a message, not silently become a free product.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _measure(value: Any) -> float | None:
    """A real measurement, or None.

    `isinstance(x, (int, float))` is FALSE for a Decimal, and DynamoDB returns every number as one -- so the
    obvious check silently dropped every dimension and weight the tenant had actually entered. Coerced to
    float here because these are measurements for a packer, not money: the amount-as-int rule is about
    currency, where a rounded cent is a wrong price.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _listed(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(entry) for entry in value if _text(entry)]


def kind_for(product: dict[str, Any] | None) -> str:
    """The brief `kind` this product implies. Empty when we cannot tell rather than guessed."""
    return KIND_FOR_PRODUCT_TYPE.get(_text((product or {}).get("product_type")).lower(), "")


def _price_from(product: dict[str, Any]) -> dict[str, Any]:
    """The product's default price, in the brief's shape.

    The DEFAULT price specifically, not the first in the list: a product with a sale price and a full price
    carries both, and generating a page around whichever happens to be first would put the wrong number in
    the copy. `default_price_id` is the one the buy button uses.
    """
    prices = product.get("prices")
    if not isinstance(prices, list) or not prices:
        return {}
    default_id = _text(product.get("default_price_id"))
    chosen = next((p for p in prices if isinstance(p, dict) and _text(p.get("price_id")) == default_id), None)
    if chosen is None:
        chosen = next((p for p in prices if isinstance(p, dict)), None)
    if not chosen:
        return {}
    price: dict[str, Any] = {
        # int(), and not decoration: DynamoDB returns numbers as Decimal, so a stored price arrives as
        # 3900.0 and `isinstance(amount, int)` in the brief validator is FALSE for it. That exact mismatch
        # has already 404'd published pages in this repo once -- fixtures pass, stored documents do not.
        "unit_amount": _whole(chosen.get("unit_amount")),
        "currency": _text(chosen.get("currency")).lower() or "usd",
    }
    # The recurring shape is NESTED on a price and flat on a brief, and conflating the two once made a
    # subscription charge exactly one time. Read the nested form; write the flat one.
    recurring = chosen.get("recurring")
    interval = _text(recurring.get("interval")) if isinstance(recurring, dict) else ""
    if interval:
        price["pricing_model"] = "recurring"
        price["recurring_interval"] = interval
    return price


def _physical_block(product: dict[str, Any], shipping_config: dict[str, Any] | None) -> dict[str, Any]:
    """Measurements the packer uses, plus shipping READ from config rather than re-asked.

    Measurements license no claim -- a tenant who gave us a weight has not thereby authorised a sentence
    about shipping -- so they are copied for completeness and the shipping SENTENCE comes from the tenant's
    own policy or not at all.
    """
    block: dict[str, Any] = {}
    fulfilment = product.get("fulfillment")
    dimensions = fulfilment.get("dimensions") if isinstance(fulfilment, dict) else None
    if isinstance(dimensions, dict):
        # The product already stores these under the brief's own names, so this is a copy, not a mapping.
        for key in ("length_in", "width_in", "height_in"):
            value = _measure(dimensions.get(key))
            if value is not None:
                block[key] = value
    if isinstance(fulfilment, dict):
        weight = _measure(fulfilment.get("weight_lb"))
        if weight is not None:
            block["weight_lb"] = weight
    blurb = _text((shipping_config or {}).get("policy_summary"))
    if blurb:
        block["shipping"] = blurb
    return block


def _digital_block(product: dict[str, Any]) -> dict[str, Any]:
    asset = product.get("digital_asset")
    if not isinstance(asset, dict):
        return {}
    block: dict[str, Any] = {}
    fmt = _text(asset.get("content_type"))
    if fmt:
        block["format"] = fmt
    return block


def _policy_sentence(policy: Any) -> str:
    """The refund policy as a sentence the AI may ground a guarantee claim on.

    `refund_policy` is an OBJECT on both the product and the tenant -- `short_label`, `full_policy`,
    `refund_window`, `return_method` -- not a string. Prefer the full prose the tenant actually wrote, fall
    back to the short label, and never assemble one from the structured parts: a sentence we composed is a
    sentence the tenant never agreed to, and `guarantee` licenses a CLAIM under the field floor.
    """
    if not isinstance(policy, dict):
        return _text(policy)
    return _text(policy.get("full_policy")) or _text(policy.get("short_label"))


def brief_from_product(product: dict[str, Any] | None, *, tenant_profile: dict[str, Any] | None = None,
                       shipping_config: dict[str, Any] | None = None,
                       overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The brief for this product, as it stands right now.

    `overrides` is the fork's one step, applied on top so a tenant can answer in the moment without having
    saved to `Product.ai_context` yet -- the step writes there too, but the generation must not depend on
    that write having landed first.
    """
    product = product or {}
    context = product.get("ai_context") if isinstance(product.get("ai_context"), dict) else {}
    # A BLANK override means "unchanged", never "erase". The fork's step shows a partial form, so an
    # untouched field arrives as "" -- and letting that win over stored context stripped the audience out of
    # the brief and failed validation before anything ran. Same rule the save path applies; they have to
    # agree or the page is generated from different facts than the ones that get kept.
    supplied = {key: value for key, value in (overrides or {}).items() if value not in (None, "", [])}
    merged = {**context, **supplied}

    brief: dict[str, Any] = {
        "source": "existing_product",
        "kind": kind_for(product),
        "name": _text(product.get("name")),
        "what_it_is": _text(product.get("description")),
        "category": _text(product.get("product_category")),
        "price": _price_from(product),
    }

    for key in ("audience", "evidence", "tone"):
        value = _text(merged.get(key))
        if value:
            brief[key] = value
    for key in ("facts", "certifications", "must_say", "must_not_say"):
        listed = _listed(merged.get(key))
        if listed:
            brief[key] = listed

    # READ, never re-asked (author, 2026-09-29). `ai_floor` already declared refund_policy a governed class
    # -- "a refund window is a contract term; it comes from the tenant's policy" -- so the v1 brief asking
    # the tenant to retype it contradicted the floor, and the floor was right. Product-level policy wins over
    # the tenant default, because a product can carry its own.
    policy = _policy_sentence(product.get("refund_policy")) or _policy_sentence(
        (tenant_profile or {}).get("refund_policy"))
    if policy:
        brief["guarantee"] = policy

    kind = brief["kind"]
    if kind == PHYSICAL:
        block = _physical_block(product, shipping_config)
        if block:
            brief[PHYSICAL] = block
    elif kind == DIGITAL:
        block = _digital_block(product)
        if block:
            brief[DIGITAL] = block
    return brief


def missing_for_generation(brief: dict[str, Any] | None) -> list[str]:
    """What the fork's one step still has to collect. Drives the step's required fields and its review line.

    Only the two the tenant can answer: a missing name or price is a broken PRODUCT, which belongs in the
    product wizard rather than being patched over here.
    """
    brief = brief or {}
    missing = []
    if not _text(brief.get("audience")):
        missing.append("audience")
    if not _listed(brief.get("facts")):
        missing.append("facts")
    return missing
