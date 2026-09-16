"""POST /tip-jar — one click, a working tip jar page.

plans/PAY_WHAT_YOU_WANT.md §5c. The builder's tip_jar element can point at a Junior Bay tip jar; this is
what makes there be one to point at. It writes a Product, an Offer, a Site and a published Page, and hands
all four back so the element can select the page immediately.

**A resumable state machine, not a transaction** (DIGITAL_MARKETPLACE.md §4.2). DynamoDB transactions do not
span the tables this repo uses, so there is no way to make four writes atomic. Instead the SITE is written
first and carries the caller's `request_id`; every later step records itself on that anchor. A retry finds
the anchor, skips what is already done, and finishes the rest -- so a click that times out half way through
leaves a resumable job rather than a duplicate set of catalogue rows.

The anchor is a real Site rather than a row in a table invented for the purpose: it is the one document that
must exist anyway, the tenant can see it, and it is deletable by hand if anything goes badly wrong.
"""

from __future__ import annotations

import time

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    resolve_stripe_mode,
    tenant_id_from_event,
)
from stripe_link.domain import tip_jar_provision as seed
from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_site,
)
from stripe_link.domain.fees import cached_billing_config, normalize_tier_id
from stripe_link.entitlement_gate import require_capability
from stripe_link.ids import generate_id, generate_local_id, generate_short_url_code
from stripe_link.repositories.documents import (
    RepositoryError,
    offers_repository,
    pages_repository,
    products_repository,
    sites_repository,
    subdomain_registry,
    tenant_profiles_repository,
    user_profiles_repository,
)

# The Site handler owns subdomain reservation and hostname derivation; this reuses them rather than
# re-implementing the rules about what a platform label may be.
from handlers.sites import _ensure_platform_hostname, _reserve_subdomain, generate_site_id


def handler(event, context, **repos):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
    gate = require_capability(event, "landing_pages", repos.get("tenant_repo"))
    if gate is not None:
        return gate
    try:
        return provision(event, **repos)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="provision_failed")


def provision(event, **repos):
    mode = resolve_stripe_mode(event)
    try:
        body = parse_json_body(event) if (event or {}).get("body") else {}
    except ValueError:
        body = {}
    tenant_id = tenant_id_from_event(event, body if isinstance(body, dict) else {})
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = body if isinstance(body, dict) else {}

    sites = repos.get("sites_repo") or sites_repository(mode=mode)
    products = repos.get("products_repo") or products_repository(mode=mode)
    offers = repos.get("offers_repo") or offers_repository(mode=mode)
    pages = repos.get("pages_repo") or pages_repository(mode=mode)
    tenants = repos.get("tenant_repo") or tenant_profiles_repository()
    users = repos.get("users_repo") or user_profiles_repository()
    registry = repos.get("registry") or subdomain_registry()

    now = int(time.time())
    # The caller's key, so a double-click or a retried request resumes one job instead of starting a second.
    # Absent, we mint one -- which makes the request non-resumable, which is the caller's choice to make.
    request_id = str(body.get("request_id") or "").strip()[:64] or f"tj_{now}_{generate_id()}"
    currency = str(body.get("currency") or "usd").strip().lower()[:3] or "usd"

    tenant_profile = _safe_get(tenants, tenant_id) or {}
    user_profile = _safe_get(users, tenant_id) or {}

    existing_sites = _tenant_sites(sites, tenant_id)
    anchor = _find_anchor(existing_sites, request_id)

    # --- 1. the anchor -----------------------------------------------------------------------------
    if anchor is None:
        anchor = _create_site(
            sites, registry,
            tenant_id=tenant_id, mode=mode, now=now, request_id=request_id,
            display_name=_display_name(user_profile, tenant_profile),
            existing=_tip_jar_site_count(existing_sites),
        )
    state = dict(anchor.get("provision") or {})

    # --- 2. the product ----------------------------------------------------------------------------
    product = _resume(products, tenant_id, state.get("product_id"))
    if product is None:
        plan = normalize_tier_id(tenant_profile.get("tier_id"))
        presets, charges = seed.preset_pairs(currency, plan, cached_billing_config(repos.get("billing_config_loader")))
        product = seed.product_document(
            tenant_id=tenant_id, product_id=generate_local_id(), price_id=f"price_{generate_id()}",
            mode=mode, currency=currency, presets=presets, preset_charges=charges,
            refund_policy=_default_refund_policy(tenant_profile),
            now=now, provenance=seed.provenance_block(request_id, now),
        )
        validate_product_document(product)
        product = products.put(product)
        state["product_id"] = product["product_id"]
        anchor = _record(sites, anchor, state)

    # --- 3. the offer ------------------------------------------------------------------------------
    offer = _resume(offers, tenant_id, state.get("offer_id"))
    if offer is None:
        offer = seed.offer_document(
            tenant_id=tenant_id, offer_id=f"offer_{generate_id()}",
            product_id=product["product_id"], price_id=product["default_price_id"],
            mode=mode, now=now, provenance=seed.provenance_block(request_id, now),
        )
        validate_offer_document(offer)
        offer = offers.put(offer)
        state["offer_id"] = offer["offer_id"]
        anchor = _record(sites, anchor, state)

    # --- 4. the page, as a DRAFT -------------------------------------------------------------------
    page = _resume(pages, tenant_id, state.get("page_id"))
    if page is None:
        page = seed.page_document(
            tenant_id=tenant_id, page_id=f"page_{generate_id()}", offer_id=offer["offer_id"],
            mode=mode, short_code=generate_short_url_code(),
            has_avatar=bool(str(tenant_profile.get("avatar_url") or "").strip()),
            now=now, provenance=seed.provenance_block(request_id, now),
        )
        validate_page_document(page)
        page = pages.put(seed.as_draft(page))
        state["page_id"] = page["page_id"]
        anchor = _record(sites, anchor, state)

    # --- 5. attach it to the Site ------------------------------------------------------------------
    # BEFORE publishing, and that ordering is the whole point. Attaching writes the SITE, never the page, so
    # the Pages stream does not fire and the artifact keeps whatever identity it was rendered with. A page
    # published a moment before its attach has no store name and no Organization graph -- measured on a real
    # page on 2026-09-11, artifact at 21:12:50 and attach at 21:13:14 (`_republish_page` in handlers/sites.py
    # exists to repair exactly that). Publishing last means there is nothing to repair.
    if not state.get("attached"):
        site_pages = dict(anchor.get("pages") or {})
        site_pages[f"/{seed.PAGE_SLUG}"] = {
            "page_id": page["page_id"],
            "offer_id": offer["offer_id"],
            "page_type": "landing",
            "enabled": True,
        }
        anchor["pages"] = site_pages
        state["attached"] = True
        anchor = _record(sites, anchor, state)

    # --- 6. publish, and close the job -------------------------------------------------------------
    # The last write, because it is the one with an outside effect: it fires the stream that renders the
    # artifact and puts a real URL into the world. Everything it needs already exists by now.
    if state.get("status") != "complete":
        page = pages.put(seed.as_published(page, int(time.time())))
        state["status"] = "complete"
        anchor = _record(sites, anchor, state)

    return json_response(
        {"site": anchor, "product": product, "offer": offer, "page": page},
        status_code=201,
    )


# --- the anchor -------------------------------------------------------------------------------------

def _create_site(sites, registry, *, tenant_id, mode, now, request_id, display_name, existing):
    document = seed.site_document(
        tenant_id=tenant_id, site_id=generate_site_id(),
        name=seed.site_name(display_name, existing), mode=mode, now=now,
        provenance=seed.provenance_block(request_id, now),
    )
    document["provision"]["status"] = "provisioning"
    _ensure_platform_hostname(document)
    validate_site(document)
    # The subdomain is a GLOBAL first-claim-wins reservation, so this is the step that can genuinely fail on
    # a name collision. It runs before the put for that reason: a Site row whose hostname belongs to someone
    # else is worse than no Site row.
    _reserve_subdomain(registry, document)
    return sites.put(document)


def _find_anchor(sites: list[dict], request_id: str) -> dict | None:
    for site in sites:
        provision = site.get("provision") or {}
        if str(provision.get("source") or "") == "tip_jar" and str(provision.get("request_id") or "") == request_id:
            return dict(site)
    return None


def _tip_jar_site_count(sites: list[dict]) -> int:
    """How many tip jars this tenant already has, which is what `v{n}` counts.

    Counted rather than stored: a tenant who deletes v2 and presses the button again gets v3, not a second
    v2 whose subdomain is still reserved by the row they deleted.
    """
    return sum(1 for site in sites if str((site.get("provision") or {}).get("source") or "") == "tip_jar")


def _record(sites, anchor: dict, state: dict) -> dict:
    """Write the job's progress onto the anchor after each step, so a retry knows where it got to."""
    anchor = dict(anchor)
    anchor["provision"] = {**(anchor.get("provision") or {}), **state}
    anchor["updated_at"] = int(time.time())
    return sites.put(anchor)


# --- small readers ----------------------------------------------------------------------------------

def _resume(repository, tenant_id: str, document_id) -> dict | None:
    """The document a previous attempt wrote, or None when this step has not run.

    A recorded id that no longer reads back (deleted by hand between attempts) counts as not run: rebuilding
    it is recoverable, and pointing the page at a product that is gone is not.
    """
    if not document_id:
        return None
    return _safe_get(repository, tenant_id, str(document_id))


def _safe_get(repository, tenant_id: str, document_id: str | None = None):
    try:
        return repository.get(tenant_id, document_id if document_id is not None else tenant_id)
    except Exception:  # noqa: BLE001 - an unreadable row is "not there yet", never a 500
        return None


def _tenant_sites(sites, tenant_id: str) -> list[dict]:
    try:
        return list(sites.list_for_tenant(tenant_id) or [])
    except Exception:  # noqa: BLE001
        return []


def _display_name(user_profile: dict, tenant_profile: dict) -> str:
    """What to call this Site. The USER profile's display name is the canonical one -- it is what the Profile
    screen edits -- and the tenant profile's signup-time owner name is the fallback, exactly as
    `attach_owner_display_name` treats them at render."""
    name = str(user_profile.get("display_name") or "").strip()
    if name:
        return name
    owner = tenant_profile.get("owner") or {}
    return " ".join(part for part in [
        str(owner.get("first_name") or "").strip(),
        str(owner.get("last_name") or "").strip(),
    ] if part).strip()


def _default_refund_policy(tenant_profile: dict) -> dict:
    """The tenant's own default where they have set one.

    A tip jar has nothing to ship and nothing to revoke, so a silent empty policy would leave the refund
    page with nothing to say on the one page that most needs to say it.
    """
    stored = tenant_profile.get("refund_policy")
    if isinstance(stored, dict) and stored:
        return dict(stored)
    return {
        "source": "tip_jar_default",
        "refund_window": "non_refundable",
        "short_label": "Non-refundable",
        "condition": "any",
        "return_method": "digital_revoke_access",
        "full_policy": (
            "Tips are gifts and are non-refundable. If something has gone wrong, contact us and we will "
            "make it right."
        ),
    }
