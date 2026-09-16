"""The documents behind "Create your free Tip Jar page" — built here, written by the handler.

plans/PAY_WHAT_YOU_WANT.md §5c. A first-party tip jar needs a Product, an Offer, a Site and a Page. Sending
someone off to build four documents and then come back and link them is exactly the friction that makes
pasting a Ko-fi URL the obvious choice instead, so the button builds them. It is far easier to edit a page
that exists than to build one that does not.

Two rules shape everything below.

**These are ORDINARY catalogue rows** (DIGITAL_MARKETPLACE.md §4.3). Same schemas, same validators, same
builder screens -- a seeded product must be indistinguishable from a hand-made one the moment it exists,
apart from the `provision` provenance block. Anything else doubles the surface area forever. So this module
builds plain documents and hands them back; it opens no repository and calls no API.

**The seeds are defaults, not decisions.** Every value here is the tenant's to change five seconds later.
What matters is that the page works, looks deliberate, and says something true before they touch it.
"""

from __future__ import annotations

import re
from typing import Any

from stripe_link.domain import tips
from stripe_link.domain.fees import calculate_price

# The seeded copy. Generic on purpose: it has to read as deliberate for a musician, a charity and a podcast
# alike, and it is the first thing the tenant will edit if it does not suit them.
HEADLINE = "Support the Cause"
SUBHEADLINE = "Your support is greatly appreciated."
PAGE_SLUG = "support-cause"
CTA_LABEL = "Buy Now"

# A platform-owned hero, so a page exists to look at before the tenant has uploaded anything. The alternative
# -- a page with an empty frame -- reads as broken rather than as unfinished, and a tenant who sees broken
# does not go on to edit it. Referenced by URL rather than copied per tenant: it is served from the public
# image CDN already, and one shared object is one object to replace when the artwork changes.
HERO_IMAGE = "https://images.juniorbay.com/offers/0XLo0j4dqS0/medium.webp"
HERO_IMAGE_BASE = "https://images.juniorbay.com/offers/0XLo0j4dqS0"
HERO_IMAGE_DIMS = [1080, 1440]
# Warm, high-contrast, and it carries the hero's own colours. A seeded page that clashes with its own
# photograph is the sort of thing a tenant fixes by deleting the page.
THEME_PRESET = "coral-sunrise"

# Net-guaranteed IS the pitch (§5c): "everywhere else the fees come out of your tip; here your customer can
# cover them". A default that contradicted the sentence that sold it would be strange. The trade-off is
# honest and visible -- the buyer sees a slightly higher number -- and the tenant can change it.
FEE_HANDLING = "net_guaranteed"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def site_name(display_name: str, existing: int = 0) -> str:
    """`{display name} tip-jar v{n}`.

    The version suffix is what lets a tenant press the button twice and get two working pages instead of one
    error: Sites claim a globally-unique platform subdomain, so two sites called the same thing is a
    collision, not a duplicate. `create_site` slugifies this name into that subdomain, which is where the
    hyphenated shape in the spec actually lands -- `keith-de-costa-tip-jar-v1`.
    """
    label = str(display_name or "").strip() or "My"
    return f"{label} tip-jar v{int(existing) + 1}"


def slugify(value: str) -> str:
    return _SLUG_RE.sub("-", str(value or "").lower()).strip("-")


def preset_pairs(currency: str, plan: str, billing_config: dict[str, Any] | None) -> tuple[list[int], list[int]]:
    """The seeded ladder: what the tenant keeps, and what the buyer is charged for each.

    Both halves are stored because they answer different questions and neither can be re-derived from the
    other later without the fee table as it stood that day (§5e). The charged column is computed by the SAME
    `calculate_price` the authoring form and the page's live estimate call, so the three never disagree.
    """
    keyed = tips.recommended_presets(currency, recurring=False, allow_custom=True)
    charges = []
    for amount in keyed:
        priced = calculate_price(
            tenant_keyed_amount=amount,
            currency=currency,
            product_type="digital",
            fee_handling=FEE_HANDLING,
            pricing_model="customer_chooses",
            tenant_plan=plan,
            billing_config=billing_config,
        )
        charges.append(int(priced.get("unit_amount") or 0))
    return keyed, charges


def product_document(
    *,
    tenant_id: str,
    product_id: str,
    price_id: str,
    mode: str,
    currency: str,
    presets: list[int],
    preset_charges: list[int],
    refund_policy: dict[str, Any] | None,
    now: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """A one-time tip jar.

    ONE-TIME, not repeating, and that is a deliberate narrowing rather than an oversight: a seeded page the
    tenant has not read yet should not be able to sign their supporters up to a recurring charge. Turning
    repeating on is one checkbox away in the builder, and it is theirs to turn on knowingly.
    """
    return {
        "schema_version": "2026-05-29",
        "document_type": "product",
        "tenant_id": tenant_id,
        "product_id": product_id,
        "stripe_mode": mode,
        "stripe_product_id": None,
        "canonical": True,
        "status": "active",
        "name": HEADLINE,
        "description": SUBHEADLINE,
        "images": [HERO_IMAGE],
        "image_dims": {HERO_IMAGE_BASE: HERO_IMAGE_DIMS},
        "product_type": "digital",
        "product_category": "tip",
        "product_intent": "transaction",
        "condition": "new",
        "prices": [{
            "price_id": price_id,
            # No stripe_price_id, ever: a tip is priced per buyer, so checkout builds the line inline and
            # explicitly drops any synced id it finds. Recording one here would be a number waiting to be
            # charged instead of the one the buyer picked.
            "currency": currency,
            "quantity": 1,
            "context": "standard",
            "pricing_model": "customer_chooses",
            "fee_handling": FEE_HANDLING,
            "tenant_keyed_amount": 0,
            "min_amount": tips.MIN_AMOUNT,
            "max_amount": tips.MAX_AMOUNT,
            "presets": list(presets),
            "preset_charges": list(preset_charges),
            "allow_custom": True,
            "allow_recurring": False,
            "created_at": now,
            "updated_at": now,
        }],
        "default_price_id": price_id,
        "fulfillment": {
            "requires_shipping": False,
            "ship_from": None,
            "weight_lb": None,
            "dimensions": {"length_in": None, "width_in": None, "height_in": None},
        },
        "refund_policy": refund_policy or {},
        "variants": {"sizes": [], "colors": [], "size_enabled": False, "color_enabled": False},
        "sync": {"status": "pending", "last_synced_at": None, "error": None},
        "tags": ["support the cause", "tip"],
        "provision": dict(provenance),
        "created_at": now,
        "updated_at": now,
    }


def offer_document(
    *,
    tenant_id: str,
    offer_id: str,
    product_id: str,
    price_id: str,
    mode: str,
    now: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "2026-05-29",
        "document_type": "offer",
        "tenant_id": tenant_id,
        "offer_id": offer_id,
        "slug": PAGE_SLUG,
        "name": HEADLINE,
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
        "presentation": {
            "headline": HEADLINE,
            "subheadline": SUBHEADLINE,
            "cta_label": CTA_LABEL,
            "cta": {"type": "buy", "label": CTA_LABEL},
            "hero_image_url": HERO_IMAGE,
        },
        "checkout": {
            "mode": "payment",
            "allow_promotion_codes": False,
            "phone_number_collection": "inherit",
            "metadata": {"offer_id": offer_id},
        },
        "eligibility": {
            "starts_at": None,
            "ends_at": None,
            "requires_prior_purchase": False,
            "allowed_price_contexts": ["standard"],
        },
        "sync": {"status": "pending", "last_synced_at": None, "error": None},
        "provision": dict(provenance),
        "created_at": now,
        "updated_at": now,
    }


def site_document(
    *,
    tenant_id: str,
    site_id: str,
    name: str,
    mode: str,
    now: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """A Site of its own, rather than a page hung off whichever one the tenant already had.

    A tip jar is not part of a storefront's sales path, and attaching it to one would put it in that store's
    navigation and its sitemap. Its own Site keeps the seeded page free-standing and disposable -- delete it
    and nothing else changes.
    """
    return {
        "schema_version": "2026-07-20",
        "document_type": "site",
        "tenant_id": tenant_id,
        "site_id": site_id,
        # `environment` is the Stripe MODE this Site's documents belong to, which is what every other Site
        # in these tables records here.
        "environment": "live" if str(mode) == "live" else "test",
        "stripe_mode": "live" if str(mode) == "live" else "test",
        "name": name,
        "status": "active",
        "hosting": {"type": "platform", "platform_subdomain": slugify(name)},
        "organization": {"name": name},
        "pages": {},
        "provision": dict(provenance),
        "created_at": now,
        "updated_at": now,
    }


def page_document(
    *,
    tenant_id: str,
    page_id: str,
    offer_id: str,
    mode: str,
    short_code: str,
    has_avatar: bool,
    now: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """The page itself, seeded already PUBLISHED.

    Published, because a draft tip jar is not a tip jar -- the button's whole promise is a working link to
    paste, and "now go and publish it" is the step that loses people. The publish stream renders it the same
    way it renders every other page.

    `goal: minimal` plus the two overrides strip the storefront furniture a support page has no use for: no
    breadcrumb to a store it is not part of, and no brand label above a hero that already carries the
    creator's face.
    """
    return {
        "schema_version": "2026-05-29",
        "document_type": "page",
        "tenant_id": tenant_id,
        "page_id": page_id,
        "stripe_mode": mode,
        "name": f"{HEADLINE} Landing Page",
        "status": "published",
        "published_at": now,
        "short_code": short_code,
        "route": {"slug": PAGE_SLUG},
        "offer_id": offer_id,
        "goal": "minimal",
        "chrome": {"breadcrumb": False},
        "composition": {"overrides": {"brand_label": {"enabled": False}}},
        "theme": {"template": "universal_bundle", "preset": THEME_PRESET},
        "seo": {"title": HEADLINE, "description": SUBHEADLINE, "image": HERO_IMAGE},
        "image_dims": {HERO_IMAGE_BASE: HERO_IMAGE_DIMS},
        "sections": [
            {
                "id": "hero-media",
                "type": "hero_media",
                "images": [HERO_IMAGE],
                # The avatar is resolved BY REFERENCE at render from the tenant profile, so there is nothing
                # to copy here -- only the decision of whether to show it. A tenant with no picture would get
                # an empty ring on an otherwise finished page, which looks like a bug rather than a blank, so
                # the seed hides it and they can switch it on the moment they upload one.
                "avatar_placement": "overlay" if has_avatar else "hidden",
                "autoplay": False,
                "brand_overlay": False,
                "brand_position": "top-right",
            },
            {"id": "hero", "type": "hero", "headline": HEADLINE, "subheadline": SUBHEADLINE},
            {"id": "offer-selector", "type": "offer_price_selector", "offer_id": offer_id},
            {"id": "checkout-cta", "type": "checkout_cta", "label": CTA_LABEL},
            # Money changed hands, so the policy is on the page. It also carries the "Manage a purchase"
            # entry point, which is the only self-serve route a tip buyer has.
            {"id": "refund-policy", "type": "refund_policy", "heading": "Refund Policy", "enabled": True},
            {"id": "legal-footer", "type": "legal_footer", "copyright": "© {{current_year}} All rights reserved."},
        ],
        "legal": {},
        "analytics": {},
        "provision": dict(provenance),
        "revision": 1,
        "created_at": now,
        "updated_at": now,
    }


def as_draft(page: dict[str, Any]) -> dict[str, Any]:
    """The same page, not yet live.

    It is written as a draft first and published last, because attaching a page to a Site writes the SITE and
    never the page -- so an artifact rendered before the attach carries no store identity and nothing
    re-renders it. See the handler's step 5.
    """
    draft = dict(page)
    draft["status"] = "draft"
    draft["published_at"] = None
    return draft


def as_published(page: dict[str, Any], now: int) -> dict[str, Any]:
    published = dict(page)
    published["status"] = "published"
    published["published_at"] = int(now)
    published["updated_at"] = int(now)
    return published


def provenance_block(request_id: str, now: int) -> dict[str, Any]:
    """What this row is and where it came from.

    §4.3 says a provisioned row must be indistinguishable from a hand-made one -- apart from exactly this.
    Three catalogue rows appearing from one click is the kind of thing a tenant finds a month later and does
    not recognise; this is what answers them when they look.
    """
    return {"source": "tip_jar", "request_id": str(request_id), "created_at": int(now)}
