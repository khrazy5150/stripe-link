"""Brief -> Product + Offer, deterministically (pure -- no I/O). AI_AND_COMMERCE §A.3 step 2.

The rule this module exists to enforce: **the platform owns every id.** The AI assists copy and
nothing else. Letting a model emit a `product_id` or a `price_id` produces references that do not
resolve, and a page whose buy button points at nothing is worse than no page.

Shaped after `tip_jar_provision.py`, which solved the same problem first, and follows its two rules:

  - **These are ORDINARY catalogue rows.** Same schemas, same validators, same builder screens. A
    generated product must be indistinguishable from a hand-made one the moment it exists, apart from
    its `provision` provenance. Anything else doubles the surface area forever.
  - **It builds documents and hands them back.** No repository, no API call, no Stripe. The handler
    writes and syncs, which is what makes all of this testable without AWS.

Everything here is derived from the brief or from a resolver. Nothing is invented.
"""

from __future__ import annotations

import re
from typing import Any

from stripe_link.domain.page_brief import DIGITAL, PHYSICAL, SERVICE, kind_block

SCHEMA_VERSION = "2026-05-29"
ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# The brief's `kind` in the product's own vocabulary. A service brief does NOT become a Product with
# product_type "service" -- plans/SERVICE_WIZARD.md §3 settled that a service is its own document with
# a fulfillment_mode, and `Products.vue` already hands off on that basis. `service_handoff` exists so
# the caller is forced to notice rather than quietly creating a third path to a Service.
PRODUCT_TYPE_FOR_KIND = {PHYSICAL: "physical", DIGITAL: "digital"}


def _number(value: Any) -> float | None:
    """A real measurement or None. Never a guess.

    The wizard asks for length, width, height and weight as separate numbers rather than one free-text
    box, because these ARE the packer's inputs -- `fulfillment.dimensions` and `weight_lb` are what
    `label_readiness` gates label buying on. A parsed "about 4x4x6 inches" would be a confident guess,
    and a wrong shipping quote is worse than no quote (plans/SHIPPING_PROVIDERS.md).
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def new_id(prefix: str, randomiser) -> str:
    """`local_xxxxxxxxxxx` and friends -- the format the dashboard already mints, so a generated row
    sorts and reads exactly like a hand-made one."""
    return f"{prefix}_" + "".join(randomiser(ID_ALPHABET) for _ in range(11))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:60] or "offer"


def needs_service_handoff(brief: dict[str, Any] | None) -> bool:
    """A service brief is the Service wizard's job, not this module's.

    Three wizards that each create services slightly differently is exactly the two-worlds confusion
    SERVICE_WIZARD.md was written to dissolve, so this says no rather than guessing.
    """
    return str((brief or {}).get("kind") or "").strip().lower() == SERVICE


def provenance_block(brief_id: str, now: int) -> dict[str, Any]:
    """What this row is and where it came from.

    A product and an offer appearing from one click is the kind of thing a tenant finds a month later
    and does not recognise. This is what answers them when they look.
    """
    return {"source": "ai_page", "brief_id": str(brief_id), "created_at": int(now)}


def price_document(brief: dict[str, Any], *, price_id: str) -> dict[str, Any]:
    """The price, straight from the brief. The AI never touches an amount."""
    price = (brief or {}).get("price") or {}
    out: dict[str, Any] = {
        "price_id": price_id,
        "currency": str(price.get("currency") or "usd").lower(),
        "quantity": 1,
        "unit_amount": int(price.get("unit_amount") or 0),
        "pricing_model": str(price.get("pricing_model") or "one_time"),
        "stripe_price_id": None,
    }
    if out["pricing_model"] == "recurring":
        # `recurring: {interval}`, NOT the flat `recurring_interval` -- that field means "an interval
        # this price may be taken at" (the tip jar's opt-in), while THIS is the price actually being
        # charged on a schedule. The validator refuses the flat form for a recurring price precisely
        # because the two were once conflated and a subscription charged exactly once
        # (plans/TODO.md, "Recurring pricing saves cleanly and then charges ONCE").
        out["recurring"] = {"interval": str(price.get("recurring_interval") or "month"),
                            "interval_count": 1}
    return out


def product_document(brief: dict[str, Any], *, tenant_id: str, product_id: str, price_id: str,
                     mode: str, now: int, provenance: dict[str, Any]) -> dict[str, Any]:
    """An ordinary catalogue row, built from the brief.

    `status: active`, not draft -- Product.schema.json has no draft status, only active and archived.
    The brief note's §5 proposed "create everything as draft" and it is not available here. It is also
    not needed: the PAGE is the gate. A product that exists with no published page is for sale
    nowhere, and this matches what `products.py` already does on the ordinary path -- save, then fire
    an async Stripe sync and let `sync.status` carry the outcome. A generated row that behaved
    differently from a hand-made one would be the exact divergence this module is written to avoid.
    """
    kind = str(brief.get("kind") or "").strip().lower()
    if kind not in PRODUCT_TYPE_FOR_KIND:
        raise ValueError(f"{kind!r} does not become a Product here -- see needs_service_handoff.")
    block = kind_block(brief)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "product",
        "tenant_id": tenant_id,
        "product_id": product_id,
        "stripe_mode": mode,
        "stripe_product_id": None,
        "canonical": True,
        "status": "active",
        "name": str(brief.get("name") or "").strip(),
        "description": str(brief.get("what_it_is") or "").strip(),
        "product_type": PRODUCT_TYPE_FOR_KIND[kind],
        "product_intent": "transaction",
        "product_category": str(brief.get("category") or "").strip(),
        "prices": [price_document(brief, price_id=price_id)],
        "default_price_id": price_id,
        # requires_shipping follows the KIND, never a separate question: asking a download whether it
        # ships is the fulfilment question asked twice (author, 2026-09-27).
        #
        # ship_from, weight and dimensions are present-and-null rather than absent or guessed. The
        # schema requires the keys and permits nulls, and that is exactly right here: a tenant who has
        # not measured their parcel yet still has a valid product. `label_readiness` gates buying a
        # label on those numbers, never validation -- a tenant who walks to the post office stays
        # first-class (plans/SHIPPING_PROVIDERS.md). Inventing a weight to satisfy a validator would
        # produce a confidently wrong shipping quote, which is worse than no quote.
        "fulfillment": {
            "requires_shipping": kind == PHYSICAL,
            "ship_from": None,
            "weight_lb": _number(block.get("weight_lb")),
            "dimensions": {"length_in": _number(block.get("length_in")),
                           "width_in": _number(block.get("width_in")),
                           "height_in": _number(block.get("height_in"))},
        },
        "sync": {"status": "pending"},
        "tags": [],
        "images": list(brief.get("images") or []),
        "provision": provenance,
        "created_at": int(now),
        "updated_at": int(now),
    }
    return document


def offer_document(brief: dict[str, Any], *, tenant_id: str, offer_id: str, product_id: str,
                   price_id: str, slug: str, mode: str, now: int,
                   provenance: dict[str, Any]) -> dict[str, Any]:
    """The offer that points at the product. Both ids are the platform's own.

    `status: active`, even though the schema permits draft. `domain/pricing.py` refuses to price a
    non-active offer at all, so a draft offer makes the page unpreviewable AND uneditable -- the
    builder reports "Offer ... is not active" and shows nothing. The PAGE's draft status is the real
    gate, exactly as it is for the product: an active offer behind an unpublished page is for sale
    nowhere.
    """
    name = str(brief.get("name") or "").strip()
    # Checkout mode follows the PRICE, and getting this wrong is a bug this repo has shipped before:
    # a recurring price behind a "payment" session charges once and never again (plans/TODO.md,
    # "Recurring pricing saves cleanly and then charges ONCE"). Derived, never defaulted.
    recurring = str(((brief or {}).get("price") or {}).get("pricing_model") or "") == "recurring"
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "offer",
        "tenant_id": tenant_id,
        "offer_id": offer_id,
        "slug": slug,
        "name": name,
        "status": "active",
        "stripe_mode": mode,
        "product_intent": "transaction",
        "offer_type": "single",
        "items": [{"product_id": product_id, "price_id": price_id, "quantity": 1}],
        "purchase_opportunities": [{
            "opportunity_id": "opp_landing_primary_0",
            "stage": "landing",
            "product_id": product_id,
            "price_id": price_id,
            "quantity": 1,
            "placement": {"surface": "primary", "group": "main_offer", "order": 0},
        }],
        "discount": {"mode": "none"},
        "checkout": {"mode": "subscription" if recurring else "payment",
                     "metadata": {"offer_id": offer_id}},
        # Presentation carries only what the BRIEF said. The generated headline and subheadline are
        # page sections, written by the model and floored -- they do not belong on the offer, which is
        # the commercial record.
        "presentation": {"cta": {"type": "buy", "label": "Buy Now"}},
        "sync": {"status": "pending"},
        "provision": provenance,
        "created_at": int(now),
        "updated_at": int(now),
    }


def seed_hero_images(sections: list[dict[str, Any]] | None,
                     product: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Write the product's image onto `hero_media` rather than leaving it to be inferred later.

    The renderer CAN fall back -- `hero_media_images` walks section images, then the offer's hero image,
    then the product's -- but that fallback needs whoever renders to have resolved the product, and
    `page_render` takes products from the REQUEST. A page opened before its product is to hand rendered
    with no hero image, and only looked fixed after an edit, because saving materialises the image into
    the section and the fallback is never consulted again (author, 2026-09-29).

    The fork knows the product: it is the input. So put the image on the page and let the document say what
    it shows, rather than depending on the renderer's caller to supply the thing we already had.

    Only fills an EMPTY hero_media. A section that already names images is the tenant's choice.
    """
    seeded: list[dict[str, Any]] = []
    image = ""
    for candidate in (product or {}).get("images") or []:
        if isinstance(candidate, str) and candidate.strip():
            image = candidate.strip()
            break
    for section in sections or []:
        if (isinstance(section, dict) and section.get("type") == "hero_media"
                and not (section.get("images") or []) and image):
            seeded.append({**section, "images": [image]})
        else:
            seeded.append(section)
    return seeded


def page_document(brief: dict[str, Any], *, tenant_id: str, page_id: str, offer_id: str, slug: str,
                  sections: list[dict[str, Any]], preset: str, mode: str, now: int,
                  provenance: dict[str, Any]) -> dict[str, Any]:
    """A DRAFT page. Never published -- §A.3 step 7 and the plan's human-in-the-loop principle.

    The tenant reviews in the builder and publishes deliberately. A generated page that published
    itself would put unreviewed copy on a live storefront, which is the one outcome the whole floor
    exists to make impossible.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "page",
        "tenant_id": tenant_id,
        "page_id": page_id,
        "name": str(brief.get("name") or "").strip(),
        "status": "draft",
        "published_at": None,
        "stripe_mode": mode,
        "route": {"slug": slug},
        "offer_id": offer_id,
        "theme": {"preset": preset},
        "sections": list(sections or []),
        "provision": provenance,
        "created_at": int(now),
        "updated_at": int(now),
    }
