import json
import os
import time
from typing import Any

from stripe_link.domain.documents import (
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_site,
)
from stripe_link.runtime.artifacts import artifact_paths, cloudfront_path
from stripe_link.domain.connect_sync import site_domain_verified
from stripe_link.domain.custom_domains import domain_index_record
from stripe_link.domain.funnels import funnel_slug_entries
from stripe_link.runtime.html import (
    INDEXABLE_ROBOTS,
    NOINDEX_FOLLOW_ROBOTS,
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


def resolve_category_grids(page: dict[str, Any], site: dict[str, Any] | None) -> None:
    """Populate a category-driven catalog_grid's items from the Site route map (plans/SITE_OBJECT.md §2.5b
    Slice 2): every landing page whose denormalized `category` matches becomes a card {offer_id, slug}. Runs
    before offers load so the referenced offers get bundled. A grid with an explicit `category` is always
    (re)resolved — the route map is the source of truth; curated grids (no `category`) are left untouched."""
    if not site:
        return
    entries = (site or {}).get("pages") or {}
    for section in page.get("sections") or []:
        if section.get("type") != "catalog_grid":
            continue
        category = str(section.get("category") or "").strip()
        if not category:
            continue
        items = [
            {"offer_id": str(entry.get("offer_id")), "slug": slug}
            for slug, entry in entries.items()
            if isinstance(entry, dict) and entry.get("offer_id") and str(entry.get("category") or "") == category
        ]
        section["items"] = items


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
    """Rewrite the denormalized domain-index record so the edge resolver sees the Site's new routes right away.
    Uses the injected repository in tests; falls back to the real one in the Lambda. Best-effort."""
    repo = domains_index_repository
    if repo is None:
        from stripe_link.repositories.documents import custom_domains_index_repository

        repo = custom_domains_index_repository()
    repo.put(domain_index_record(site))


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
            "cache_control": "public, max-age=300",
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
    for item in offer.get("items", []):
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


def publish_page_document(
    page: dict[str, Any],
    *,
    offers_repository: Any,
    products_repository: Any,
    services_repository: Any | None = None,
    sites_repository: Any | None = None,
    domains_index_repository: Any | None = None,
    reviews_repository: Any | None = None,
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
    # A category page's catalog_grid resolves its cards from the Site route map BEFORE offers load, so the
    # referenced offers get bundled by load_render_context (plans/SITE_OBJECT.md §2.5b Slice 2).
    resolve_category_grids(page, site)
    offer, products_by_id, services_by_id, offers_by_id = load_render_context(
        page,
        offers_repository=offers_repository,
        products_repository=products_repository,
        services_repository=services_repository,
    )
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
    # Serve the whole inline funnel on the Site's verified custom domain: attach the funnel's pages at slugs so
    # the edge resolver can route them, and refresh the denormalized route table. Best-effort — a failure here
    # must never block publishing the artifact itself (plans/SITE_OBJECT.md §2.6).
    if site and sites_repository is not None and site_domain_verified(site) and page.get("post_checkout"):
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
    canonical_path = "" if page_site_slug in ("", "/") else page_site_slug.lstrip("/")
    page_canonical = f"https://{custom_domain}/{canonical_path}" if on_custom_domain and custom_domain else canonical_url
    eligibility = ((site or {}).get("indexing") or {}).get("eligibility") or "blocked"
    site_archived = (site or {}).get("status") == "archived"

    page_reviews = load_page_reviews(reviews_repository, tenant_id, products_by_id, str((site or {}).get("site_id") or ""))

    def _render(robots: str) -> str:
        return render_page(
            page, offer, products_by_id, checkout_url=checkout, api_base_url=api_base_url,
            services_by_id=services_by_id, offers_by_id=offers_by_id, canonical_url=page_canonical,
            robots=robots, site=site, page_type=page_type, reviews=page_reviews,
        )

    artifacts = []
    indexable_words = None
    for target in targets:
        robots = page_robots_directive(
            kind=target["kind"], environment=environment, eligibility=eligibility,
            page_type=page_type, on_custom_domain=on_custom_domain, site_archived=site_archived,
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


def _homepage_image_urls(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[str]:
    from stripe_link.runtime.html import first_offer_product, seo_image_url

    product = first_offer_product(offer, products_by_id) or {}
    return [seo_image_url(image) for image in (product.get("images") or []) if image][:5]


def publish_site_crawl_files(*, site, homepage_page_id, custom_domain, page, image_urls, s3_client, pages_bucket, indexnow_opener=None):
    """Generate + write the Site's crawl files under the homepage artifact key, and submit the homepage URL to
    IndexNow. Best-effort on the IndexNow ping — never fail a publish on it."""
    from stripe_link.domain.sitemap import robots_txt, sitemap_xml

    # An archived Site drops its whole domain from crawling: empty sitemap + disallow-all robots (paired with
    # the noindex,nofollow,noarchive meta re-rendered onto each page). No IndexNow ping either.
    archived = (site or {}).get("status") == "archived"
    root = f"https://{custom_domain}/"
    sitemap = sitemap_xml([] if archived else [{"loc": root, "lastmod": page.get("updated_at") or page.get("published_at"), "images": image_urls}])
    robots = robots_txt(f"https://{custom_domain}/sitemap.xml", allow=not archived)
    prefix = f"{homepage_page_id}/"
    cache = "public, max-age=300"
    s3_client.put_object(Bucket=pages_bucket, Key=prefix + "sitemap.xml", Body=sitemap.encode("utf-8"),
                         ContentType="application/xml; charset=utf-8", CacheControl=cache)
    s3_client.put_object(Bucket=pages_bucket, Key=prefix + "robots.txt", Body=robots.encode("utf-8"),
                         ContentType="text/plain; charset=utf-8", CacheControl=cache)
    key = str(((site or {}).get("seo") or {}).get("indexnow_key") or "").strip()
    if key and not archived:
        s3_client.put_object(Bucket=pages_bucket, Key=prefix + f"{key}.txt", Body=key.encode("utf-8"),
                             ContentType="text/plain; charset=utf-8", CacheControl=cache)
        submit_indexnow(custom_domain, key, [root], opener=indexnow_opener)
    return {"root": root, "sitemap": root + "sitemap.xml", "indexnow_submitted": bool(key)}


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
