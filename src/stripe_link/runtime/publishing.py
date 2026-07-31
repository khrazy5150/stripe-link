import copy
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Cache-Control for a PUBLISHED page artifact. The browser must revalidate every load (max-age=0) so a re-publish
# is visible without a hard refresh — the old `max-age=300` let the browser serve a 5-minute-stale copy. The CDN
# still caches it (s-maxage=300) for speed, and a publish invalidates the CDN, so the browser's revalidation
# (a cheap ETag 304 when unchanged) fetches the new artifact the moment it's live.
PUBLISHED_PAGE_CACHE_CONTROL = "public, max-age=0, s-maxage=300, must-revalidate"
from typing import Any

from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_route,
    validate_site,
)
from stripe_link.runtime.artifacts import artifact_paths, cloudfront_path
from stripe_link.domain.connect_sync import site_domain_verified, site_seo_enabled
from stripe_link.domain.custom_domains import domain_index_record, platform_domain_index_record
from stripe_link.domain.funnels import funnel_slug_entries, post_purchase_plan
from stripe_link.domain.opportunities import STAGE_LANDING, STAGE_POST_PURCHASE, stage_opportunities
from stripe_link.runtime.upsell_pages import (
    synthesize_downsell_carousel_page,
    synthesize_thank_you_page,
    synthesize_upsell_carousel_page,
    synthesize_upsell_page,
    upsell_scaffold,
)
from stripe_link.runtime.html import (
    INDEXABLE_ROBOTS,
    NOINDEX_FOLLOW_ROBOTS,
    NOINDEX_ROBOTS,
    RenderError,
    THIN_CONTENT_MIN_WORDS,
    first_offer_product,
    indexable_word_count,
    page_robots_directive,
    render_page,
)


class PublishError(RuntimeError):
    pass


def page_slug(page: dict[str, Any]) -> str:
    slug = ((page.get("route") or {}).get("slug") or page.get("page_id") or "").strip("/")
    if not slug:
        raise PublishError("Page route.slug or page_id is required for publishing.")
    return slug


def site_page_type(site: dict[str, Any] | None, page_id: str) -> str:
    """The page_type the Site records for this page (drives robots/sitemap eligibility). Defaults to 'landing'
    when the page has no Site entry (legacy pages)."""
    for entry in ((site or {}).get("pages") or {}).values():
        if isinstance(entry, dict) and entry.get("page_id") == page_id:
            return str(entry.get("page_type") or "landing")
    return "landing"


def site_homepage_page_id(site: dict[str, Any] | None) -> str:
    """The page served at the Site root ("/") — the one a verified custom domain shows (homepage-only serving,
    plans/SITE_OBJECT.md §2.6 first slice). "" when the Site has no root page yet."""
    root = ((site or {}).get("pages") or {}).get("/")
    return str(root.get("page_id") or "") if isinstance(root, dict) else ""


def find_site_for_page(sites_repository: Any, tenant_id: str, page_id: str) -> dict[str, Any] | None:
    """Resolve the Site that owns `page_id` (plans/SITE_OBJECT.md §2.2). A page belongs to at most one Site,
    so the first match is authoritative. Returns None when there's no Site yet (legacy pages) — the renderer
    then falls back to its interim identity. Never raises: identity resolution must not block a publish."""
    if sites_repository is None or not tenant_id or not page_id:
        return None
    try:
        for site in sites_repository.list_for_tenant(tenant_id):
            for entry in (site.get("pages") or {}).values():
                if isinstance(entry, dict) and entry.get("page_id") == page_id:
                    return site
    except Exception:
        return None
    return None


def site_page_slug(site: dict[str, Any] | None, page_id: str) -> str:
    """The Site route slug (map key) this page serves at — "/" for the homepage, "/upsell-1" for a funnel
    step. "" when the page isn't attached to the Site (so it isn't served on the custom domain)."""
    for slug, entry in ((site or {}).get("pages") or {}).items():
        if isinstance(entry, dict) and entry.get("page_id") == page_id:
            return str(slug)
    return ""


def platform_serving_enabled() -> bool:
    """Whether Sites are served on their free platform host ({label}.<hosting-domain>). Gated
    (plans/PLATFORM_HOSTNAME_SERVING.md Slice 2) so a platform-only Site doesn't render storefront chrome +
    relative internal links that dead-end before the *.jbay.uk/*.jbay.be edge Worker is wired. Default off;
    flip PLATFORM_SERVING_ENABLED on per environment once the edge route is live (the ops slice)."""
    return str(os.environ.get("PLATFORM_SERVING_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def site_is_served(site: dict[str, Any] | None) -> bool:
    """Whether the Site is reachable at a clean host — a verified custom domain, or (once wired) the free
    platform host — so funnel/context slugs are worth attaching and the resolver route table should carry them
    (plans/PLATFORM_HOSTNAME_SERVING.md Slice 3). Page-independent (cf. site_serving_origin, which needs a slug)."""
    if site_domain_verified(site):
        return True
    platform_hostname = str(((site or {}).get("hosting") or {}).get("platform_hostname") or "").strip()
    return bool(platform_hostname and platform_serving_enabled())


def site_serving_origin(site: dict[str, Any] | None, page_site_slug: str) -> str:
    """The absolute origin the page is served from — the anchor for its canonical/og:url, storefront chrome, and
    breadcrumb root. A verified custom domain (indexed, branded) when the page is routed there; else the free
    platform host (navigable, always noindex) once platform serving is wired. "" when neither applies — the page
    keeps its interim artifact identity and renders no chrome (plans/PLATFORM_HOSTNAME_SERVING.md Slice 2)."""
    hosting = (site or {}).get("hosting") or {}
    custom_domain = str(hosting.get("custom_domain") or "").strip()
    if site_domain_verified(site) and custom_domain and page_site_slug:
        return f"https://{custom_domain}"
    platform_hostname = str(hosting.get("platform_hostname") or "").strip()
    if platform_hostname and page_site_slug and platform_serving_enabled():
        return f"https://{platform_hostname}"
    return ""


def attach_funnel_pages(site: dict[str, Any], page: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Attach the pages a Page's inline funnel references (upsell/downsell/thank-you) to the Site at derived
    slugs so the whole funnel routes on the custom domain (plans/SITE_OBJECT.md §2.6). Idempotent and
    non-destructive: a page already attached at any slug is left in place, and a slug already taken by a
    different page is suffixed. Returns (site, changed)."""
    entries = funnel_slug_entries(page.get("post_checkout") or {})
    if not entries:
        return site, False
    pages = dict(site.get("pages") or {})
    attached_ids = {e.get("page_id") for e in pages.values() if isinstance(e, dict)}
    changed = False
    for entry in entries:
        page_id = entry["page_id"]
        if page_id in attached_ids:
            continue  # already routes somewhere — never move a page the tenant may have placed deliberately
        slug, suffix = entry["slug"], 2
        while slug in pages:
            slug, suffix = f"{entry['slug']}-{suffix}", suffix + 1
        pages[slug] = {"page_id": page_id, "page_type": entry["page_type"], "enabled": True}
        attached_ids.add(page_id)
        changed = True
    if not changed:
        return site, False
    return {**site, "pages": pages}, True


_CONTEXT_VIEW_SLUGS = (("sale", "/sale"), ("flash_sale", "/flash-sale"))


def context_view_contexts(page: dict[str, Any]) -> list[str]:
    """The enabled Sale/Flash-Sale contexts for a page — the context artifacts to publish (P1c)."""
    contexts = []
    if (page.get("sale") or {}).get("enabled"):
        contexts.append("sale")
    if (page.get("flash_sale") or {}).get("enabled"):
        contexts.append("flash_sale")
    return contexts


def attach_context_view_slugs(site: dict[str, Any], page: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Add/remove the reserved `/sale` `/flash-sale` route entries for the Site's ROOT sales page based on its
    toggles (plans/SALES_FUNNELS.md P1c). Each entry points at the same page_id + a `price_context`, so the
    resolver serves the sibling context artifact. Only the page at the Site's "/" gets them. Returns
    (site, changed)."""
    page_id = str(page.get("page_id") or "")
    if str(site_page_slug(site, page_id)) != "/":
        return site, False
    pages = dict(site.get("pages") or {})
    enabled = set(context_view_contexts(page))
    changed = False
    for ctx, slug in _CONTEXT_VIEW_SLUGS:
        entry = {"page_id": page_id, "page_type": "landing", "price_context": ctx, "enabled": True}
        if ctx in enabled:
            if pages.get(slug) != entry:
                pages[slug] = entry
                changed = True
        elif isinstance(pages.get(slug), dict) and pages[slug].get("price_context") == ctx:
            del pages[slug]  # toggled off — retire its route
            changed = True
    return ({**site, "pages": pages}, True) if changed else (site, False)


def attach_funnel_slugs(
    site: dict[str, Any], page: dict[str, Any], offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """Add/remove the reserved post-purchase funnel slugs (`/upsell`, `/downsell`, `/thank-you`) for the Site's
    ROOT sales page so the funnel stays on the custom domain instead of bouncing to the platform host
    (plans/SALES_FUNNELS.md P2b). Each entry points at the base page_id + a `funnel_role` + the offer's
    sequence/carousel `strategy`; the resolver derives the synthetic funnel artifact (`{page_id}__upsell_N`,
    `__upsell_carousel`, `__downsell_carousel`, `__thank_you`) from those + the request's funnel_step.

    Only the page at the Site's "/" owns them, and only when the offer actually has a post-purchase funnel
    (resolvable upsells). `/downsell` gets its own slug ONLY in carousel mode — in sequence mode the downsell is
    an in-place swap on the upsell page, not a separate artifact. Returns (site, changed)."""
    page_id = str(page.get("page_id") or "")
    if str(site_page_slug(site, page_id)) != "/":
        return site, False
    plan = post_purchase_plan(offer, products_by_id)
    upsells = plan.get("upsells") or []
    strategy = str(plan.get("strategy") or "sequence")
    desired: dict[str, dict[str, Any]] = {}
    if upsells:  # a funnel exists only when there are upsells (thank-you is synthesized off them too)
        desired["/upsell"] = {"page_id": page_id, "page_type": "funnel_step", "funnel_role": "upsell", "strategy": strategy, "enabled": True}
        if strategy == "carousel" and any(entry.get("downsell") for entry in upsells):
            desired["/downsell"] = {"page_id": page_id, "page_type": "funnel_step", "funnel_role": "downsell", "strategy": strategy, "enabled": True}
        desired["/thank-you"] = {"page_id": page_id, "page_type": "thank_you", "funnel_role": "thank_you", "strategy": strategy, "enabled": True}
    pages = dict(site.get("pages") or {})
    changed = False
    for slug, entry in desired.items():
        if pages.get(slug) != entry:
            pages[slug] = entry
            changed = True
    # Retire any of OUR funnel slugs (identified by funnel_role) no longer desired — e.g. upsells removed, or a
    # carousel→sequence change that drops /downsell. Never touch a tenant's own same-named page (no funnel_role).
    for slug in ("/upsell", "/downsell", "/thank-you"):
        existing = pages.get(slug)
        if slug not in desired and isinstance(existing, dict) and existing.get("funnel_role"):
            del pages[slug]
            changed = True
    return ({**site, "pages": pages}, True) if changed else (site, False)


def load_page_collections(collections_repository: Any, tenant_id: str, page: dict[str, Any]) -> dict[str, Any]:
    """Load the Collections a page's catalog_grid sections reference (collection-embeds, plans/SITE_COLLECTIONS.md
    P1), keyed by collection_id. Best-effort: a missing collection just leaves that grid to its inline config."""
    if collections_repository is None:
        return {}
    ids = {
        str(s.get("collection_id") or "")
        for s in (page.get("sections") or [])
        if isinstance(s, dict) and s.get("type") == "catalog_grid" and s.get("collection_id")
    }
    ids.discard("")
    out: dict[str, Any] = {}
    for cid in ids:
        try:
            collection = collections_repository.get(tenant_id, cid)
        except Exception:  # noqa: BLE001 - a load failure just falls back to the grid's inline config
            collection = None
        if collection:
            out[cid] = collection
    return out


def _collection_grid_items(collection: dict[str, Any], entries: dict[str, Any],
                           slug_offer_by_page: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    """Resolve a Collection's members to grid items ({offer_id, Site slug}) against the Site route map — the same
    "only real, navigable, published Site pages" guarantee as the other grid modes. `all`/`category` pull from
    the map; `manual` keeps the tenant's ordered page references, dropping any not published on the Site."""
    rule = str(collection.get("rule") or "manual")
    if rule == "all":
        return [{"offer_id": str(e["offer_id"]), "slug": slug}
                for slug, e in entries.items() if isinstance(e, dict) and e.get("offer_id")]
    if rule == "category":
        cat = str(collection.get("category") or "")
        return [{"offer_id": str(e["offer_id"]), "slug": slug}
                for slug, e in entries.items()
                if isinstance(e, dict) and e.get("offer_id") and str(e.get("category") or "") == cat]
    items = []
    for page_id in collection.get("members") or []:
        hit = slug_offer_by_page.get(str(page_id))
        if hit:
            slug, offer_id = hit
            items.append({"offer_id": offer_id, "slug": slug})
    return items


def catalog_grid_to_collection(section: dict[str, Any], site: dict[str, Any] | None, tenant_id: str,
                               collection_id: str) -> dict[str, Any] | None:
    """Convert one inline catalog_grid section into a Collection document, rewriting the section into a
    collection-embed that references it (plans/SITE_COLLECTIONS.md P1d migration). Idempotent: a section that
    already carries a collection_id yields None (already migrated). The Collection's rule is derived from the
    inline config — scope='all' → 'all', a category → 'category', else the curated items → 'manual' with members
    resolved to page_ids via the Site route map (offer_id → page_id). Mutates the section: sets collection_id
    and drops the now-migrated inline scope/category/items. The caller persists the returned Collection FIRST,
    then the rewritten page, so the reference always resolves."""
    if not isinstance(section, dict) or section.get("type") != "catalog_grid" or section.get("collection_id"):
        return None
    heading = str(section.get("heading") or "").strip()
    collection: dict[str, Any] = {
        "document_type": "collection", "tenant_id": tenant_id,
        "site_id": str((site or {}).get("site_id") or ""),
        "collection_id": collection_id, "name": heading or "Products",
    }
    scope = str(section.get("scope") or "").strip()
    category = str(section.get("category") or "").strip()
    if scope == "all":
        collection["rule"] = "all"
    elif category:
        collection["rule"] = "category"
        collection["category"] = category
    else:
        collection["rule"] = "manual"
        page_by_offer = {
            str(e["offer_id"]): str(e["page_id"])
            for e in ((site or {}).get("pages") or {}).values()
            if isinstance(e, dict) and e.get("offer_id") and e.get("page_id")
        }
        collection["members"] = [
            page_by_offer[oid]
            for item in (section.get("items") or [])
            for oid in [str((item or {}).get("offer_id") or "")]
            if oid in page_by_offer
        ]
    if heading:
        collection["presentation"] = {"heading": heading}
    section["collection_id"] = collection_id
    for inline in ("scope", "category", "items"):
        section.pop(inline, None)
    return collection


def backfill_page_collections(pages_repository: Any, sites_repository: Any, collections_repository: Any,
                              tenant_id: str, *, id_factory, dry_run: bool = True) -> dict[str, Any]:
    """Migrate a tenant's inline catalog_grids to Collections (plans/SITE_COLLECTIONS.md P1d). For each page with
    a catalog_grid lacking a collection_id, mint a Collection from its inline config and rewrite the section.
    Persists each Collection FIRST, then the changed page, so the embed always resolves. Idempotent — a re-run
    skips already-migrated grids. `dry_run` reports the plan without writing. Returns a summary."""
    summary: dict[str, Any] = {"pages_scanned": 0, "pages_migrated": 0, "collections_created": 0, "collections": []}
    for stored in pages_repository.list_for_tenant(tenant_id):
        summary["pages_scanned"] += 1
        page_id = str(stored.get("page_id") or "")
        if not any(isinstance(s, dict) and s.get("type") == "catalog_grid" and not s.get("collection_id")
                   for s in (stored.get("sections") or [])):
            continue
        # Work on a copy so the repo's object is never mutated (esp. in dry_run); we only persist our own copy.
        page = copy.deepcopy(stored)
        grids = [s for s in (page.get("sections") or [])
                 if isinstance(s, dict) and s.get("type") == "catalog_grid" and not s.get("collection_id")]
        site = find_site_for_page(sites_repository, tenant_id, page_id)
        new_collections = []
        for section in grids:
            collection = catalog_grid_to_collection(section, site, tenant_id, id_factory())
            if collection:
                collection.setdefault("schema_version", "2026-07-31")
                new_collections.append(collection)
        if not new_collections:
            continue
        if not dry_run:
            for collection in new_collections:
                collections_repository.put(collection)
            pages_repository.put(page)
        summary["pages_migrated"] += 1
        summary["collections_created"] += len(new_collections)
        summary["collections"].extend(
            {"collection_id": c["collection_id"], "page_id": page_id, "rule": c["rule"],
             "members": len(c.get("members") or [])} for c in new_collections)
    return summary


def resolve_category_grids(page: dict[str, Any], site: dict[str, Any] | None,
                           collections_by_id: dict[str, Any] | None = None) -> None:
    """Populate a catalog_grid's items from the Site route map (plans/SITE_OBJECT.md §2.5b Slice 2) so every
    card links to a real, navigable Site page. All modes (re)resolve from the route map (the source of truth) at
    publish: `scope="all"` → EVERY offer page on the Site (a brand-first storefront that fills itself); a
    `category` → offer pages in that category; a CURATED grid → the tenant's picked offers, kept ONLY when the
    offer is a published page on this Site and re-pointed to that page's Site slug (a picked page that isn't on
    the Site — or isn't published — is dropped so the grid never links to a dead path). An entry carries its
    offer_id once the page has published on the Site (_denormalize_page_catalog). Runs before offers load so the
    referenced offers get bundled."""
    if not site:
        return
    entries = (site or {}).get("pages") or {}
    collections_by_id = collections_by_id or {}
    # offer_id -> Site slug, for the offer pages published on this Site (the navigable ones).
    slug_by_offer = {
        str(entry["offer_id"]): slug
        for slug, entry in entries.items()
        if isinstance(entry, dict) and entry.get("offer_id")
    }
    # page_id -> (Site slug, offer_id), for resolving a Collection's ordered page-id members.
    slug_offer_by_page = {
        str(entry["page_id"]): (slug, str(entry["offer_id"]))
        for slug, entry in entries.items()
        if isinstance(entry, dict) and entry.get("page_id") and entry.get("offer_id")
    }
    for section in page.get("sections") or []:
        if section.get("type") != "catalog_grid":
            continue
        # A collection-embed: the grid's items come from the referenced Collection's rule, not its inline config.
        collection = collections_by_id.get(str(section.get("collection_id") or ""))
        if collection is not None:
            section["items"] = _collection_grid_items(collection, entries, slug_offer_by_page)
            if not str(section.get("heading") or "").strip():
                heading = str((collection.get("presentation") or {}).get("heading") or "").strip()
                if heading:
                    section["heading"] = heading
            continue
        scope = str(section.get("scope") or "").strip()
        category = str(section.get("category") or "").strip()
        if scope == "all" or category:
            section["items"] = [
                {"offer_id": str(entry.get("offer_id")), "slug": slug}
                for slug, entry in entries.items()
                if isinstance(entry, dict) and entry.get("offer_id")
                and (scope == "all" or str(entry.get("category") or "") == category)
            ]
        else:  # curated — keep the tenant's order, drop off-Site/unpublished, re-point to the Site slug
            section["items"] = [
                {"offer_id": oid, "slug": slug_by_offer[oid]}
                for item in (section.get("items") or [])
                for oid in [str((item or {}).get("offer_id") or "")]
                if oid in slug_by_offer
            ]


def resolve_related_products(page: dict[str, Any], site: dict[str, Any] | None, category: str, current_page_id: str) -> list[str]:
    """Fill related_products sections with other Site pages in `category` (excluding this page), a same-category
    internal-link rail (plans/SITE_OBJECT.md §2.5b Slice 3 / SEO-13). Returns the offer_ids added so the
    publisher can bundle their offers. Empty when the page has no category or Site."""
    if not site or not category:
        return []
    entries = (site or {}).get("pages") or {}
    added: list[str] = []
    for section in page.get("sections") or []:
        if section.get("type") != "related_products":
            continue
        limit = int(section.get("limit") or 6)
        items: list[dict[str, str]] = []
        for slug, entry in entries.items():
            if not isinstance(entry, dict) or entry.get("page_id") == current_page_id:
                continue
            offer_id = str(entry.get("offer_id") or "")
            if offer_id and str(entry.get("category") or "") == category:
                items.append({"offer_id": offer_id, "slug": slug})
                added.append(offer_id)
                if len(items) >= limit:
                    break
        section["items"] = items
    return added


def _enable_site_route(site: dict[str, Any], page_id: str) -> bool:
    """Flip a page's Site route entry(ies) to enabled. The dashboard sets `enabled = (status == "published")` at
    attach time, so a draft page's route is disabled and the edge resolver 404s it ("store not active"). When a
    page is published server-side (e.g. the collection-draft cascade) with no dashboard round-trip, its route
    must be re-enabled here or the storefront card that links to it dead-ends. Returns whether anything changed."""
    changed = False
    for entry in (site.get("pages") or {}).values():
        if isinstance(entry, dict) and entry.get("page_id") == page_id and entry.get("enabled") is not True:
            entry["enabled"] = True
            changed = True
    return changed


def _denormalize_page_catalog(site: dict[str, Any], page_id: str, offer_id: str, category: str) -> bool:
    """Record a landing page's offer_id + product category on its Site route-map entry so category pages can
    resolve grids off the map. Returns whether anything changed."""
    changed = False
    for entry in (site.get("pages") or {}).values():
        if isinstance(entry, dict) and entry.get("page_id") == page_id:
            if offer_id and entry.get("offer_id") != offer_id:
                entry["offer_id"] = offer_id
                changed = True
            if category and entry.get("category") != category:
                entry["category"] = category
                changed = True
    return changed


def cascade_publish_collection_drafts(page: dict[str, Any], collections_by_id: dict[str, Any],
                                      site: dict[str, Any] | None, *, pages_repository: Any, now: int) -> dict[str, Any]:
    """Auto-publish the never-published draft member pages the tenant selected into any MANUAL collection this
    page embeds (plans/SITE_COLLECTIONS.md). The tenant already picked them into the collection; don't make them
    hunt each draft down and publish it by hand before it shows in the grid. For each such member: flip it to
    published (its own PagesTable write re-enters the publish stream and renders its artifact) and denormalize its
    offer_id onto the in-memory Site route entry, so THIS page's grid includes it in the current render.

    EVERY draft member is published, regardless of whether it was live before: published pages can't be edited, so
    a tenant unpublishes → edits → previews → routinely forgets to re-publish; asking them to remember which pages
    were once live isn't reasonable. An already-published member is not re-written, but its Site route is still
    healed (enabled + offer_id denormalized) so a card can't dead-end on a stale-disabled route. Archived members
    are left alone. Best-effort per member; a bad member never blocks the parent publish. Returns
    {"published": [page_id...], "site_changed": bool}. Terminates: only DRAFT members get a page write, so an
    already-published member's own publish stream can't re-cascade (a route heal is a Site write, not a page write)."""
    published: list[str] = []
    site_changed = False
    if not pages_repository:
        return {"published": published, "site_changed": site_changed}
    tenant_id = str(page.get("tenant_id") or "")
    # The explicitly selected member page_ids across every embedded manual collection (deduped, order-preserving).
    member_ids: list[str] = []
    seen: set[str] = set()
    for section in page.get("sections") or []:
        if not (isinstance(section, dict) and section.get("type") == "catalog_grid"):
            continue
        collection = collections_by_id.get(str(section.get("collection_id") or ""))
        if not collection or collection.get("rule") != "manual":
            continue
        for pid in collection.get("members") or []:
            pid = str(pid)
            if pid and pid not in seen:
                seen.add(pid)
                member_ids.append(pid)
    for pid in member_ids:
        try:
            member = pages_repository.get(tenant_id, pid)
        except Exception:  # noqa: BLE001 — one unreadable member must not block the parent publish
            logger.warning("cascade: could not read collection member %s", pid, exc_info=True)
            member = None
        if not member or member.get("status") == "archived":
            continue  # a gone/archived member has nothing to publish or route
        # Publish a draft member. A once-published, since-unpublished member IS republished (the tenant likely
        # just forgot). The member's own PagesTable write re-renders it; an ALREADY-published member is not
        # re-written (no page write → its own stream can't re-cascade → the cascade terminates).
        if member.get("status") == "draft":
            member["status"] = "published"
            member["published_at"] = now
            member["updated_at"] = now
            try:
                pages_repository.put(member)
            except Exception:  # noqa: BLE001
                logger.warning("cascade: could not publish draft member %s", pid, exc_info=True)
                continue
            published.append(pid)
        # For EVERY live member (just-published or already-published), make sure the Site map lets its card
        # resolve — a Site write only, so it never re-triggers a page stream. Self-heals a stale-disabled route
        # (e.g. a member published outside this cascade whose route the dashboard left disabled from draft time):
        #   - enable its route entry — a disabled route 404s the card ("store not active");
        #   - denormalize its offer_id (needed for grid resolution) — already on the member doc, no extra load.
        if member.get("status") == "published":
            if site and _enable_site_route(site, pid):
                site_changed = True
            if site and member.get("offer_id") and _denormalize_page_catalog(site, pid, str(member.get("offer_id") or ""), ""):
                site_changed = True
    return {"published": published, "site_changed": site_changed}


def load_page_reviews(reviews_repository: Any | None, tenant_id: str, products_by_id: dict[str, Any], site_id: str = "") -> list[dict[str, Any]]:
    """Approved, first-party reviews for this page (plans/REVIEWS.md): product-target reviews for the page's
    products (→ Product aggregateRating/review markup + visible block) AND business-target reviews for the
    owning Site (→ a visible trust block, NO self-serving AggregateRating). Best-effort."""
    if not reviews_repository or not tenant_id:
        return []
    try:
        reviews = reviews_repository.list_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 — reviews are an enhancement; never fail a publish on them
        return []
    out = []
    for r in reviews:
        if not isinstance(r, dict) or r.get("status") != "approved" or r.get("source") == "gbp":
            continue
        target = r.get("target") or {}
        target_id = str(target.get("id") or "")
        if target.get("type") == "product" and target_id in (products_by_id or {}):
            out.append(r)
        elif target.get("type") == "business" and site_id and target_id == str(site_id):
            out.append(r)
    return out


def detach_page_from_sites(sites_repository: Any | None, domains_index_repository: Any | None, tenant_id: str, page_id: str) -> int:
    """Remove page_id from the route map of any Site that references it (a page belongs to at most one Site).
    Called server-side when a page is deleted/archived so no Site is left pointing at a gone page — the
    authoritative backstop for the dashboard's own detach (covers direct-API deletes too). Best-effort;
    returns the number of Sites changed."""
    if not sites_repository or not tenant_id or not page_id:
        return 0
    changed = 0
    for site in sites_repository.list_for_tenant(tenant_id):
        pages = site.get("pages") or {}
        remaining = {slug: entry for slug, entry in pages.items()
                     if not (isinstance(entry, dict) and entry.get("page_id") == page_id)}
        if len(remaining) == len(pages):
            continue
        site["pages"] = remaining
        site["updated_at"] = int(time.time())
        try:
            validate_site(site)
            sites_repository.put(site)
            if (site.get("hosting") or {}).get("custom_domain"):
                _sync_domain_index(site, domains_index_repository)
            changed += 1
        except Exception:  # noqa: BLE001 — one bad Site shouldn't block artifact cleanup
            pass
    return changed


def _sync_domain_index(site: dict[str, Any], domains_index_repository: Any | None) -> None:
    """Rewrite the denormalized domain-index record(s) so the edge resolver sees the Site's new routes right
    away — the custom-domain record (only when one is connected) AND the Site's free platform-hostname record
    (always, for navigable free/test stores, plans/PLATFORM_HOSTNAME_SERVING.md). Uses the injected repository
    in tests; falls back to the real one in the Lambda. Best-effort."""
    repo = domains_index_repository
    if repo is None:
        from stripe_link.repositories.documents import custom_domains_index_repository

        repo = custom_domains_index_repository()
    if ((site.get("hosting") or {}).get("custom_domain") or "").strip():
        repo.put(domain_index_record(site))
    platform = platform_domain_index_record(site)
    if platform:
        repo.put(platform)


def artifact_targets(
    page: dict[str, Any],
    *,
    environment: str,
    pages_bucket: str,
    preview_bucket: str,
    pages_domain: str = "",
    preview_domain: str = "",
) -> list[dict[str, str]]:
    tenant_id = str(page.get("tenant_id") or "").strip()
    page_id = str(page.get("page_id") or "").strip()
    slug = page_slug(page)
    if not tenant_id or not page_id:
        raise PublishError("Page tenant_id and page_id are required for publishing.")
    paths = artifact_paths(tenant_id, page_id, slug)

    targets = [
        {
            "kind": "preview",
            "bucket": preview_bucket,
            "key": paths["preview"],
            "cache_control": "no-cache, no-store, must-revalidate",
            "url": public_url(preview_domain, paths["preview"]),
        }
    ]

    if page.get("status") == "published":
        targets.append({
            "kind": "published",
            "bucket": pages_bucket,
            "key": paths["published"],
            "cache_control": PUBLISHED_PAGE_CACHE_CONTROL,
            "url": public_url(pages_domain, paths["published"]),
        })

    missing_bucket = [target["kind"] for target in targets if not target.get("bucket")]
    if missing_bucket:
        raise PublishError(f"Missing bucket configuration for: {', '.join(missing_bucket)}.")
    return targets


def public_url(domain: str, key: str) -> str:
    if not domain:
        return ""
    return f"https://{domain.rstrip('/')}/{key}"


def register_page_route(routes_repository: Any, page: dict[str, Any]) -> bool:
    """Upsert the code->page route that lets test.juniorbay.com/published/{short_code} resolve to this page
    (plans/SALES_FUNNELS.md Phase B). No-op without a routes repo or a short_code; idempotent on re-publish."""
    if routes_repository is None:
        return False
    short_code = str(page.get("short_code") or "").strip()
    tenant_id = str(page.get("tenant_id") or "").strip()
    page_id = str(page.get("page_id") or "").strip()
    if not (short_code and tenant_id and page_id):
        return False
    existing = routes_repository.find_by_id(short_code)
    if existing and existing.get("target_page_id") == page_id and existing.get("tenant_id") == tenant_id:
        return False
    now = int(time.time())
    document = {
        "schema_version": "2026-05-29",
        "document_type": "route",
        "tenant_id": tenant_id,
        "short_code": short_code,
        "target_type": "page",
        "target_page_id": page_id,
        "created_at": int((existing or {}).get("created_at") or now),
        "updated_at": now,
    }
    validate_route(document)
    routes_repository.put(document)
    return True


def deregister_page_route(routes_repository: Any, page: dict[str, Any]) -> bool:
    """Remove the code->page route so the shareable test link 404s once a page is unpublished / deleted."""
    if routes_repository is None:
        return False
    short_code = str(page.get("short_code") or "").strip()
    tenant_id = str(page.get("tenant_id") or "").strip()
    if not (short_code and tenant_id):
        return False
    return bool(routes_repository.delete(tenant_id, short_code))


def checkout_base_url_for_page(page: dict[str, Any], offer: dict[str, Any], environment: str) -> str:
    configured = str(page.get("checkout_url") or os.environ.get("CHECKOUT_BASE_URL") or "").strip()
    if configured:
        return configured

    stripe_mode = str(offer.get("stripe_mode") or "").strip().lower()
    if not stripe_mode:
        stripe_mode = "live" if environment == "prod" else "test"
    return (
        "https://prod.juniorbay.com/checkout"
        if stripe_mode == "live"
        else "https://dev.juniorbay.com/checkout"
    )


def strip_document_keys(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if key not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"}
    }


def referenced_offer_ids(page: dict[str, Any]) -> list[str]:
    """Offer ids a page references beyond its primary offer: product_carousel slides and catalog_grid cards.
    A storefront/collection page has no primary offer at all and sources every card from here."""
    ids: list[str] = []

    def _add(offer_id: Any) -> None:
        text = str(offer_id or "")
        if text and text not in ids:
            ids.append(text)

    for section in page.get("sections", []):
        if section.get("type") == "product_carousel":
            for offer_id in section.get("offer_ids") or []:
                _add(offer_id)
        elif section.get("type") == "catalog_grid":
            for item in section.get("items") or []:
                _add((item or {}).get("offer_id"))
    return ids


def _load_offer_bundle(
    tenant_id: str,
    offer_id: str,
    *,
    offers_repository: Any,
    products_repository: Any,
    services_repository: Any | None,
    products_by_id: dict[str, dict[str, Any]],
    services_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Load one offer + its products/services into the shared maps. Reused for the page's primary offer
    and each carousel-referenced offer, so a listicle page resolves every slide's price."""
    offer = offers_repository.get(tenant_id, offer_id)
    if not offer:
        raise PublishError(f"Offer '{offer_id}' was not found.")
    validate_offer_document(offer)
    if offer.get("tenant_id") != tenant_id:
        raise PublishError("Page and offer tenant_id must match.")
    for item in stage_opportunities(offer, STAGE_LANDING):
        service_id = str(item.get("service_id") or "")
        if service_id:
            if service_id in services_by_id:
                continue
            if services_repository is None:
                raise PublishError(f"Services repository unavailable for offer '{offer_id}'.")
            service = services_repository.get(tenant_id, service_id)
            if not service:
                raise PublishError(f"Service '{service_id}' was not found for offer '{offer_id}'.")
            if service.get("tenant_id") != tenant_id:
                raise PublishError("Page and service tenant_id must match.")
            services_by_id[service_id] = service
            continue
        product_id = str(item.get("product_id") or "")
        if not product_id or product_id in products_by_id:
            continue
        product = products_repository.get(tenant_id, product_id)
        if not product:
            raise PublishError(f"Product '{product_id}' was not found for offer '{offer_id}'.")
        validate_product_document(product)
        if product.get("tenant_id") != tenant_id:
            raise PublishError("Page and product tenant_id must match.")
        products_by_id[product_id] = product
    # Also load post-purchase (upsell/downsell) products so the funnel's upsell screens can render (P3.2b).
    # Best-effort: a dangling funnel product is skipped by post_purchase_plan, so it must not fail the publish.
    for item in stage_opportunities(offer, STAGE_POST_PURCHASE):
        product_id = str(item.get("product_id") or "")
        if not product_id or product_id in products_by_id:
            continue
        product = products_repository.get(tenant_id, product_id)
        if not product or product.get("tenant_id") != tenant_id:
            continue
        try:
            validate_product_document(product)
        except DocumentValidationError:
            continue
        products_by_id[product_id] = product
    return offer


def load_render_context(
    page: dict[str, Any],
    *,
    offers_repository: Any,
    products_repository: Any,
    services_repository: Any | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    tenant_id = str(page.get("tenant_id") or "")
    products_by_id: dict[str, dict[str, Any]] = {}
    services_by_id: dict[str, dict[str, Any]] = {}
    offers_by_id: dict[str, dict[str, Any]] = {}

    # A storefront/collection page has no primary offer — it renders a grid of other pages' offers. Skip the
    # primary-offer load then; the catalog_grid/carousel offers below are all it needs (plans/SITE_OBJECT §2.5b).
    primary_offer_id = str(page.get("offer_id") or "")
    if primary_offer_id:
        offer = _load_offer_bundle(
            tenant_id, primary_offer_id,
            offers_repository=offers_repository, products_repository=products_repository,
            services_repository=services_repository, products_by_id=products_by_id, services_by_id=services_by_id,
        )
        offers_by_id[str(offer.get("offer_id") or "")] = offer
    else:
        offer = {}

    for referenced_id in referenced_offer_ids(page):
        if referenced_id in offers_by_id:
            continue
        offers_by_id[referenced_id] = _load_offer_bundle(
            tenant_id, referenced_id,
            offers_repository=offers_repository, products_repository=products_repository,
            services_repository=services_repository, products_by_id=products_by_id, services_by_id=services_by_id,
        )

    return offer, products_by_id, services_by_id, offers_by_id


def _prune_unrenderable_landing_items(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Drop legacy landing items that reference a price no longer on their product (a dangling reference from a
    since-edited product). Such an item makes render_offer_price_selector / resolve_offer raise, which fails the
    whole page publish AND — on the DynamoDB stream — jams the shard, blocking route registration for every
    other page. A stale offer must degrade gracefully (render without the dead item), never take down publishing.
    Services and new-model purchase_opportunities are left untouched; a re-save through the offer editor is the
    real cleanup (plans/OFFER_MODEL_REDESIGN.md P4)."""
    items = offer.get("items")
    if not isinstance(items, list) or not items:
        return offer
    kept: list[Any] = []
    changed = False
    for item in items:
        if not isinstance(item, dict) or item.get("service_id"):
            kept.append(item)
            continue
        product = products_by_id.get(str(item.get("product_id") or ""))
        if product is None:
            changed = True  # missing product would raise in the selector — drop it
            continue
        price_ids = {str(p.get("price_id")) for p in (product.get("prices") or []) if isinstance(p, dict)}
        selectable = item.get("selectable_prices")
        if isinstance(selectable, list) and selectable:
            valid = [sp for sp in selectable if isinstance(sp, dict) and str(sp.get("price_id")) in price_ids]
            if not valid:
                changed = True  # no renderable tier remains — drop the item
                continue
            if len(valid) == len(selectable):
                kept.append(item)
                continue
            pruned_item = dict(item)
            pruned_item["selectable_prices"] = valid
            if str(pruned_item.get("default_price_id") or "") not in {str(sp.get("price_id")) for sp in valid}:
                pruned_item["default_price_id"] = valid[0].get("price_id")
            kept.append(pruned_item)
            changed = True
        elif str(item.get("price_id") or "") in price_ids:
            kept.append(item)
        else:
            changed = True  # fixed price is a dangling reference — drop the item
    if not changed:
        return offer
    pruned = dict(offer)
    pruned["items"] = kept
    return pruned


def publish_page_document(
    page: dict[str, Any],
    *,
    offers_repository: Any,
    products_repository: Any,
    services_repository: Any | None = None,
    sites_repository: Any | None = None,
    pages_repository: Any | None = None,
    domains_index_repository: Any | None = None,
    reviews_repository: Any | None = None,
    collections_repository: Any | None = None,
    s3_client: Any,
    pages_bucket: str,
    preview_bucket: str,
    environment: str,
    pages_domain: str = "",
    preview_domain: str = "",
    checkout_url: str | None = None,
    api_base_url: str = "",
    cloudfront_client: Any | None = None,
    pages_distribution_id: str = "",
) -> dict[str, Any]:
    page = strip_document_keys(page)
    validate_page_document(page)
    tenant_id = str(page.get("tenant_id") or "")
    page_id = str(page.get("page_id") or "")
    # The Site supplies the page's public identity (Organization for the entity graph). Optional: legacy pages
    # without a Site still publish, falling back to the interim identity (plans/SITE_OBJECT.md §2.2).
    site = find_site_for_page(sites_repository, tenant_id, page_id)
    # A catalog_grid (including a collection-embed) resolves its cards from the Site route map BEFORE offers
    # load, so the referenced offers get bundled by load_render_context (plans/SITE_OBJECT.md §2.5b Slice 2,
    # plans/SITE_COLLECTIONS.md P1). Collections referenced by the page are loaded here.
    collections_by_id = load_page_collections(collections_repository, tenant_id, page)
    # When this page goes live, auto-publish the never-published draft members the tenant selected into any
    # embedded manual collection, so the grid fills itself instead of the tenant hunting each draft down
    # (plans/SITE_COLLECTIONS.md). Denormalizes them onto the in-memory Site first so THIS render includes them.
    if page.get("status") == "published" and pages_repository is not None:
        cascade = cascade_publish_collection_drafts(
            page, collections_by_id, site, pages_repository=pages_repository, now=int(time.time()))
        if cascade["site_changed"] and site and sites_repository is not None:
            try:
                validate_site(site)
                site = sites_repository.put(site)
                _sync_domain_index(site, domains_index_repository)
            except Exception:  # noqa: BLE001 — the parent artifact must publish even if the Site write fails
                pass
    resolve_category_grids(page, site, collections_by_id)
    offer, products_by_id, services_by_id, offers_by_id = load_render_context(
        page,
        offers_repository=offers_repository,
        products_repository=products_repository,
        services_repository=services_repository,
    )
    # Guard against a stale offer (a landing item pointing at a since-removed price) crashing the render and
    # jamming the publish stream (plans/OFFER_MODEL_REDESIGN.md P4). Prune the primary offer + its map entry.
    offer = _prune_unrenderable_landing_items(offer, products_by_id)
    if offer.get("offer_id"):
        offers_by_id[str(offer["offer_id"])] = offer
    # Denormalize this landing page's offer + product category onto its Site route-map entry (so category
    # pages resolve off the map), then fill any related-products rail from other pages in the same category
    # and bundle their offers. Best-effort — never blocks the artifact publish.
    if site and page.get("offer_id"):
        try:
            category = str(first_offer_product(offer, products_by_id).get("product_category") or "")
            if sites_repository is not None and _denormalize_page_catalog(site, page_id, str(page.get("offer_id") or ""), category):
                validate_site(site)
                site = sites_repository.put(site)
                _sync_domain_index(site, domains_index_repository)
            for related_id in resolve_related_products(page, site, category, page_id):
                if related_id in offers_by_id:
                    continue
                try:
                    offers_by_id[related_id] = _load_offer_bundle(
                        tenant_id, related_id,
                        offers_repository=offers_repository, products_repository=products_repository,
                        services_repository=services_repository, products_by_id=products_by_id, services_by_id=services_by_id,
                    )
                except Exception:
                    pass
        except Exception:
            pass
    # Self-referencing canonical (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01). Interim: the published artifact
    # URL where the page actually lives; clean root-domain paths arrive with the Site object.
    published_paths = artifact_paths(tenant_id, page_id, page_slug(page))
    canonical_url = public_url(pages_domain, published_paths["published"])
    # Serve the whole inline funnel on the Site's clean host (verified custom domain OR the free platform host):
    # attach the funnel's pages at slugs so the edge resolver can route them, and refresh the denormalized route
    # table. Best-effort — a failure here must never block publishing the artifact itself (plans/SITE_OBJECT.md
    # §2.6, PLATFORM_HOSTNAME_SERVING.md Slice 3).
    if site and sites_repository is not None and site_is_served(site) and page.get("post_checkout"):
        try:
            updated_site, changed = attach_funnel_pages(site, page)
            if changed:
                validate_site(updated_site)
                site = sites_repository.put(updated_site)
                _sync_domain_index(site, domains_index_repository)
        except Exception:
            pass
    checkout = checkout_url or checkout_base_url_for_page(page, offer, environment)
    targets = artifact_targets(
        page,
        environment=environment,
        pages_bucket=pages_bucket,
        preview_bucket=preview_bucket,
        pages_domain=pages_domain,
        preview_domain=preview_domain,
    )

    # Render per target so the robots directive is correct per artifact. Only a published artifact in
    # production, on an eligible Site (verified custom domain + Stripe Connect), on an indexable page_type,
    # gets index,follow; everything on platform infrastructure stays noindex (plans/SITE_OBJECT.md §2.2,
    # TP-08, SEO-02). Eligibility is recomputed on the account.updated webhook and stored on the Site.
    page_id = str(page.get("page_id") or "")
    page_type = site_page_type(site, page_id)
    # Canonical + indexing switch to the Site's verified custom domain for any page actually served there —
    # every page with a slug in the Site's route map, at its own slug (homepage at "/", funnel/collection
    # pages at their slugs). Pages not attached to a verified Site keep the interim artifact canonical and
    # stay noindex (plans/SITE_OBJECT.md §2.6).
    page_site_slug = site_page_slug(site, page_id)
    on_custom_domain = bool(site_domain_verified(site) and page_site_slug)
    custom_domain = ((site or {}).get("hosting") or {}).get("custom_domain")
    # The Site's serving origin — a verified custom domain (indexed) or, once wired, the free platform host
    # (navigable, noindex). Drives canonical/og:url AND home_url (the storefront chrome + breadcrumb root), so
    # the two always share an origin — the breadcrumb's home-detection depends on that alignment (Slice 2).
    serving_origin = site_serving_origin(site, page_site_slug)
    canonical_path = "" if page_site_slug in ("", "/") else page_site_slug.lstrip("/")
    page_canonical = f"{serving_origin}/{canonical_path}" if serving_origin else canonical_url
    page_home_url = f"{serving_origin}/" if serving_origin else ""
    eligibility = ((site or {}).get("indexing") or {}).get("eligibility") or "blocked"
    site_archived = (site or {}).get("status") == "archived"
    seo_enabled = site_seo_enabled(site)  # Site-level "discover in search" switch; off → force noindex + no crawl

    page_reviews = load_page_reviews(reviews_repository, tenant_id, products_by_id, str((site or {}).get("site_id") or ""))

    def _render(robots: str) -> str:
        return render_page(
            page, offer, products_by_id, checkout_url=checkout, api_base_url=api_base_url,
            services_by_id=services_by_id, offers_by_id=offers_by_id, canonical_url=page_canonical,
            robots=robots, site=site, page_type=page_type, reviews=page_reviews, home_url=page_home_url,
        )

    artifacts = []
    indexable_words = None
    for target in targets:
        robots = page_robots_directive(
            kind=target["kind"], environment=environment, eligibility=eligibility,
            page_type=page_type, on_custom_domain=on_custom_domain, site_archived=site_archived,
            seo_enabled=seo_enabled,
        )
        html = _render(robots)
        # Thin-content gate (SEO-08): an otherwise-indexable page with too little unique body text is demoted
        # to noindex,follow so a doorway-thin page can't drag the whole Site's ranking down. Body text is
        # robots-invariant, so measure once and re-render only the rare indexable+thin artifact.
        if robots == INDEXABLE_ROBOTS:
            if indexable_words is None:
                indexable_words = indexable_word_count(html)
            if indexable_words < THIN_CONTENT_MIN_WORDS:
                robots = NOINDEX_FOLLOW_ROBOTS
                html = _render(robots)
        s3_client.put_object(
            Bucket=target["bucket"],
            Key=target["key"],
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl=target["cache_control"],
        )
        artifacts.append({
            "kind": target["kind"],
            "bucket": target["bucket"],
            "key": target["key"],
            "url": target["url"],
        })

    # Sale / Flash-Sale context views (plans/SALES_FUNNELS.md P1c): render each enabled context once and write
    # it as a sibling artifact — always noindex (it is duplicate content of "/"). The PREVIEW context artifact
    # is written on every save so test.juniorbay.com/preview/{code}/sale works for drafts too (Phase B); the
    # PUBLISHED context artifact is written only when the page is published. On a verified custom domain root
    # page, attach the reserved /sale //flash-sale slugs so the resolver routes them.
    for ctx in context_view_contexts(page):
        ctx_html = render_page(
            page, offer, products_by_id, checkout_url=checkout, api_base_url=api_base_url,
            services_by_id=services_by_id, offers_by_id=offers_by_id, canonical_url=page_canonical,
            robots=NOINDEX_ROBOTS, site=site, page_type=page_type, reviews=page_reviews, price_context=ctx,
            home_url=page_home_url,
        )
        if preview_bucket:
            pv_key = artifact_paths(tenant_id, page_id, context=ctx)["preview"]
            s3_client.put_object(
                Bucket=preview_bucket, Key=pv_key, Body=ctx_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8", CacheControl="no-cache, no-store, must-revalidate",
            )
            artifacts.append({"kind": f"preview:{ctx}", "bucket": preview_bucket, "key": pv_key, "url": public_url(preview_domain, pv_key)})
        if page.get("status") == "published" and pages_bucket:
            ctx_key = artifact_paths(tenant_id, page_id, context=ctx)["published"]
            s3_client.put_object(
                Bucket=pages_bucket, Key=ctx_key, Body=ctx_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8", CacheControl=PUBLISHED_PAGE_CACHE_CONTROL,
            )
            artifacts.append({"kind": f"published:{ctx}", "bucket": pages_bucket, "key": ctx_key, "url": public_url(pages_domain, ctx_key)})

    # Post-purchase upsell screens (plans/OFFER_MODEL_REDESIGN.md §6, P3.2b): each upsell in the offer's plan
    # is rendered as a Universal Bundle artifact (synthetic page + single-item offer at the upsell price,
    # inheriting this page's theme) so the sequence-indexed post-checkout router can serve it at
    # {page_id}__upsell_{n}. Always noindex — a funnel step is never an organic entry point. Empty for any
    # offer without upsell-context prices, so this is a no-op for ordinary pages.
    def _write_funnel_artifact(fp_page_id: str, fp_html: str, kind: str) -> None:
        if preview_bucket:
            pv_key = artifact_paths(tenant_id, fp_page_id)["preview"]
            s3_client.put_object(
                Bucket=preview_bucket, Key=pv_key, Body=fp_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8", CacheControl="no-cache, no-store, must-revalidate",
            )
            artifacts.append({"kind": f"preview:{kind}", "bucket": preview_bucket, "key": pv_key, "url": public_url(preview_domain, pv_key)})
        if page.get("status") == "published" and pages_bucket:
            pub_key = artifact_paths(tenant_id, fp_page_id)["published"]
            s3_client.put_object(
                Bucket=pages_bucket, Key=pub_key, Body=fp_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8", CacheControl=PUBLISHED_PAGE_CACHE_CONTROL,
            )
            artifacts.append({"kind": f"published:{kind}", "bucket": pages_bucket, "key": pub_key, "url": public_url(pages_domain, pub_key)})

    scaffold = upsell_scaffold(page)
    plan = post_purchase_plan(offer, products_by_id)
    upsell_entries = plan["upsells"]
    if plan["strategy"] == "carousel":
        # Carousel mode (>= MAX_SEQUENTIAL_UPSELLS upsells, §6): ONE grid of ALL upsells at {page_id}__upsell_
        # carousel — never the per-sequence pages — plus, when any upsell product carries a downsell price, ONE
        # downsell carousel at {page_id}__downsell_carousel. The self-contained section needs no product map.
        uc_page, uc_offer = synthesize_upsell_carousel_page(
            plan, source_page=page, source_offer=offer, scaffold=scaffold,
        )
        uc_html = render_page(
            uc_page, uc_offer, {}, checkout_url=checkout, api_base_url=api_base_url,
            robots=NOINDEX_ROBOTS, site=site, page_type="funnel_step",
        )
        _write_funnel_artifact(str(uc_page["page_id"]), uc_html, "upsell_carousel")
        downsell_carousel = synthesize_downsell_carousel_page(
            plan, source_page=page, source_offer=offer, scaffold=scaffold,
        )
        if downsell_carousel:
            dc_page, dc_offer = downsell_carousel
            dc_html = render_page(
                dc_page, dc_offer, {}, checkout_url=checkout, api_base_url=api_base_url,
                robots=NOINDEX_ROBOTS, site=site, page_type="funnel_step",
            )
            _write_funnel_artifact(str(dc_page["page_id"]), dc_html, "downsell_carousel")
    else:
        for entry in upsell_entries:
            up_page, up_offer = synthesize_upsell_page(
                entry, source_page=page, source_offer=offer, scaffold=scaffold,
            )
            up_html = render_page(
                up_page, up_offer, {entry["product_id"]: entry["product"]},
                selected_prices={entry["product_id"]: entry["price_id"]},
                checkout_url=checkout, api_base_url=api_base_url,
                robots=NOINDEX_ROBOTS, site=site, page_type="funnel_step",
                # The upsell product's own reviews surface on its page too (Phase 1b); page_reviews already
                # covers every offer product (it's loaded from products_by_id, which includes the funnel ones).
                reviews=page_reviews,
            )
            _write_funnel_artifact(str(up_page["page_id"]), up_html, f"upsell_{entry['sequence']}")

    # A funnel needs a terminus: synthesize the thank-you screen (Universal Bundle, no price) alongside the
    # upsells so accept-through and decline both land on a real "Thank you" at {page_id}__thank_you instead of
    # the landing page. P3.5 makes its copy editable.
    if upsell_entries:
        ty_page, ty_offer = synthesize_thank_you_page(page, offer)
        ty_html = render_page(
            ty_page, ty_offer, {}, checkout_url=checkout, api_base_url=api_base_url,
            robots=NOINDEX_ROBOTS, site=site, page_type="thank_you",
        )
        _write_funnel_artifact(str(ty_page["page_id"]), ty_html, "thank_you")

    # Remove stale context artifacts for contexts that are no longer enabled (e.g. Sale toggled off) so
    # /sale //flash-sale stop serving. Best-effort — a delete of a missing key is a harmless no-op.
    enabled_ctx = set(context_view_contexts(page))
    for ctx in ("sale", "flash_sale"):
        if ctx in enabled_ctx:
            continue
        stale = artifact_paths(tenant_id, page_id, context=ctx)
        for bucket, key in ((preview_bucket, stale["preview"]), (pages_bucket, stale["published"])):
            if not bucket:
                continue
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:  # noqa: BLE001 - stale-artifact cleanup must never block the publish
                pass

    if site and sites_repository is not None:
        try:
            if serving_origin:
                updated_site, changed_ctx = attach_context_view_slugs(site, page)
                # Post-purchase funnel slugs (/upsell //downsell //thank-you) so the funnel stays on the serving
                # host (custom domain or platform host); derived from the offer's plan, retired when the funnel
                # goes away (P2b, PLATFORM_HOSTNAME_SERVING.md Slice 3).
                updated_site, changed_funnel = attach_funnel_slugs(updated_site, page, offer, products_by_id)
                if changed_ctx or changed_funnel:
                    validate_site(updated_site)
                    site = sites_repository.put(updated_site)
            # Always refresh the denormalized domain-index record(s) — the custom domain (if any) AND the free
            # platform hostname — so the edge resolver reflects the Site's current routes on EVERY publish, not
            # only when a slug was newly attached. Without this, re-publishing a page whose slugs were already
            # attached never (re)writes the platform-host record, so {label}.<hosting-domain> stays unresolvable
            # (plans/PLATFORM_HOSTNAME_SERVING.md). Idempotent; the custom record stays inactive until verified.
            _sync_domain_index(site, domains_index_repository)
        except Exception:  # noqa: BLE001 - route attach/sync must never block the artifact publish
            pass

    # Per-Site crawl files (SEO-14/15): when the served homepage on a verified custom domain publishes, write
    # robots.txt / sitemap.xml / {indexnow_key}.txt next to it (keyed under the homepage page_id so the
    # path-aware resolver can serve them at the domain root) and ping IndexNow with the changed URL.
    crawl = {}
    if environment == "prod" and on_custom_domain and custom_domain:
        crawl = publish_site_crawl_files(
            site=site, homepage_page_id=page_id, custom_domain=custom_domain, page=page,
            image_urls=_homepage_image_urls(offer, products_by_id), s3_client=s3_client, pages_bucket=pages_bucket,
        )

    invalidation = invalidate_published_artifact(
        artifacts,
        cloudfront_client=cloudfront_client,
        distribution_id=pages_distribution_id,
        page_id=str(page.get("page_id") or ""),
    )

    return {
        "page_id": page.get("page_id"),
        "tenant_id": page.get("tenant_id"),
        "status": page.get("status"),
        "artifacts": artifacts,
        "invalidation": invalidation,
        "crawl": crawl,
    }


def render_funnel_step_html(
    step: str,
    page: dict[str, Any],
    offer: dict[str, Any],
    products_by_id: dict[str, dict[str, Any]],
    *,
    checkout_url: str | None = None,
    api_base_url: str = "",
    site: dict[str, Any] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> str:
    """Render ONE post-purchase funnel step to HTML for the dashboard Live Preview (SALES_FUNNELS.md P3.5).

    `step` is 'thank_you', 'upsell:N' (the Nth sequential upsell, 0-based), 'upsell_carousel', or
    'downsell_carousel'. This MIRRORS the publish-time synthesis in publish_page_document — same synthesize_*
    calls, same render_page args — so the preview is byte-identical to the published funnel page (one renderer).
    It only renders; it never writes artifacts. Raises RenderError for an unknown or unavailable step."""
    scaffold = upsell_scaffold(page)
    # Reviews for the upsell product surface on its page too (Phase 1b) — the reviews list is keyed by product,
    # so render_reviews_block shows only the upsell product's; the thank-you page (no product) ignores it.
    common = dict(checkout_url=checkout_url, api_base_url=api_base_url, robots=NOINDEX_ROBOTS, site=site, reviews=reviews)
    if step == "thank_you":
        ty_page, ty_offer = synthesize_thank_you_page(page, offer)
        return render_page(ty_page, ty_offer, {}, page_type="thank_you", **common)
    plan = post_purchase_plan(offer, products_by_id)
    if step == "upsell_carousel" or (step.startswith("upsell:") and plan["strategy"] == "carousel"):
        # More than MAX_SEQUENTIAL_UPSELLS upsells render as ONE grid — there are no per-index upsell pages.
        uc_page, uc_offer = synthesize_upsell_carousel_page(plan, source_page=page, source_offer=offer, scaffold=scaffold)
        return render_page(uc_page, uc_offer, {}, page_type="funnel_step", **common)
    if step == "downsell_carousel":
        result = synthesize_downsell_carousel_page(plan, source_page=page, source_offer=offer, scaffold=scaffold)
        if not result:
            raise RenderError("This funnel has no downsell carousel.")
        dc_page, dc_offer = result
        return render_page(dc_page, dc_offer, {}, page_type="funnel_step", **common)
    if step.startswith("upsell:"):
        try:
            index = int(step.split(":", 1)[1])
        except ValueError as exc:
            raise RenderError(f"Invalid funnel step '{step}'.") from exc
        entries = plan["upsells"]
        if not (0 <= index < len(entries)):
            raise RenderError(f"Upsell step {index} is out of range.")
        entry = entries[index]
        up_page, up_offer = synthesize_upsell_page(entry, source_page=page, source_offer=offer, scaffold=scaffold)
        return render_page(
            up_page, up_offer, {entry["product_id"]: entry["product"]},
            selected_prices={entry["product_id"]: entry["price_id"]}, page_type="funnel_step", **common,
        )
    raise RenderError(f"Unknown funnel step '{step}'.")


def _homepage_image_urls(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[str]:
    from stripe_link.runtime.html import first_offer_product, seo_image_url

    product = first_offer_product(offer, products_by_id) or {}
    return [seo_image_url(image) for image in (product.get("images") or []) if image][:5]


def publish_site_crawl_files(*, site, homepage_page_id, custom_domain, page, image_urls, s3_client, pages_bucket, indexnow_opener=None):
    """Generate + write the Site's crawl files under the homepage artifact key, and submit the homepage URL to
    IndexNow. Best-effort on the IndexNow ping — never fail a publish on it."""
    from stripe_link.domain.sitemap import robots_txt, sitemap_xml

    # An archived Site — or a Site whose tenant turned search visibility OFF (seo_enabled False) — drops its whole
    # domain from crawling: empty sitemap + disallow-all robots (paired with the noindex meta re-rendered onto
    # each page). No IndexNow ping either.
    suppress = (site or {}).get("status") == "archived" or not site_seo_enabled(site)
    root = f"https://{custom_domain}/"
    sitemap = sitemap_xml([] if suppress else [{"loc": root, "lastmod": page.get("updated_at") or page.get("published_at"), "images": image_urls}])
    robots = robots_txt(f"https://{custom_domain}/sitemap.xml", allow=not suppress)
    prefix = f"{homepage_page_id}/"
    cache = "public, max-age=300"
    s3_client.put_object(Bucket=pages_bucket, Key=prefix + "sitemap.xml", Body=sitemap.encode("utf-8"),
                         ContentType="application/xml; charset=utf-8", CacheControl=cache)
    s3_client.put_object(Bucket=pages_bucket, Key=prefix + "robots.txt", Body=robots.encode("utf-8"),
                         ContentType="text/plain; charset=utf-8", CacheControl=cache)
    key = str(((site or {}).get("seo") or {}).get("indexnow_key") or "").strip()
    if key and not suppress:
        s3_client.put_object(Bucket=pages_bucket, Key=prefix + f"{key}.txt", Body=key.encode("utf-8"),
                             ContentType="text/plain; charset=utf-8", CacheControl=cache)
        submit_indexnow(custom_domain, key, [root], opener=indexnow_opener)
    return {"root": root, "sitemap": root + "sitemap.xml", "indexnow_submitted": bool(key) and not suppress}


def submit_indexnow(host: str, key: str, urls: list[str], *, opener=None) -> bool:
    from urllib.request import Request, urlopen

    from stripe_link.domain.sitemap import INDEXNOW_ENDPOINT, indexnow_body

    if not host or not key or not urls:
        return False
    body = json.dumps(indexnow_body(host, key, urls)).encode("utf-8")
    request = Request(INDEXNOW_ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with (opener or urlopen)(request, timeout=10) as response:
            response.read()
        return True
    except Exception:
        return False


def delete_page_artifacts(
    page: dict[str, Any],
    *,
    s3_client: Any,
    pages_bucket: str,
    preview_bucket: str,
    cloudfront_client: Any | None = None,
    pages_distribution_id: str = "",
) -> dict[str, Any]:
    page = strip_document_keys(page)
    tenant_id = str(page.get("tenant_id") or "").strip()
    page_id = str(page.get("page_id") or "").strip()
    slug = page_slug(page)
    if not tenant_id or not page_id:
        raise PublishError("Page tenant_id and page_id are required for artifact deletion.")
    paths = artifact_paths(tenant_id, page_id, slug)
    targets = [
        {"kind": "preview", "bucket": preview_bucket, "key": paths["preview"]},
        {"kind": "page", "bucket": pages_bucket, "key": paths["published"]},
    ]
    deleted = []
    for target in targets:
        if not target.get("bucket"):
            continue
        s3_client.delete_object(Bucket=target["bucket"], Key=target["key"])
        deleted.append(target)

    invalidation = invalidate_path(
        paths["published"],
        cloudfront_client=cloudfront_client,
        distribution_id=pages_distribution_id,
        caller_reference=f"{page_id}:delete:{int(time.time() * 1000)}",
    )
    return {
        "page_id": page_id,
        "tenant_id": tenant_id,
        "artifacts": deleted,
        "invalidation": invalidation,
    }


def invalidate_published_artifact(
    artifacts: list[dict[str, str]],
    *,
    cloudfront_client: Any | None,
    distribution_id: str,
    page_id: str,
) -> dict[str, Any] | None:
    if not cloudfront_client or not distribution_id:
        return None

    published = next((artifact for artifact in artifacts if artifact.get("kind") == "published"), None)
    if not published:
        return None

    return invalidate_path(
        published["key"],
        cloudfront_client=cloudfront_client,
        distribution_id=distribution_id,
        caller_reference=f"{page_id}:publish:{int(time.time() * 1000)}",
    )


def invalidate_path(
    key: str,
    *,
    cloudfront_client: Any | None,
    distribution_id: str,
    caller_reference: str,
) -> dict[str, Any] | None:
    if not cloudfront_client or not distribution_id:
        return None

    path = cloudfront_path(key)
    response = cloudfront_client.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {
                "Quantity": 1,
                "Items": [path],
            },
            "CallerReference": caller_reference,
        },
    )
    return {
        "distribution_id": distribution_id,
        "paths": [path],
        "id": ((response or {}).get("Invalidation") or {}).get("Id"),
    }


def manifest_json(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True)
