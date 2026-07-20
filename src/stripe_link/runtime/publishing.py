import json
import os
import time
from typing import Any

from stripe_link.domain.documents import validate_offer_document, validate_page_document, validate_product_document
from stripe_link.runtime.artifacts import artifact_paths, cloudfront_path
from stripe_link.runtime.html import render_page


class PublishError(RuntimeError):
    pass


def page_slug(page: dict[str, Any]) -> str:
    slug = ((page.get("route") or {}).get("slug") or page.get("page_id") or "").strip("/")
    if not slug:
        raise PublishError("Page route.slug or page_id is required for publishing.")
    return slug


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


def carousel_offer_ids(page: dict[str, Any]) -> list[str]:
    """Offer ids referenced by product_carousel sections (the listicle sells several offers per page)."""
    ids: list[str] = []
    for section in page.get("sections", []):
        if section.get("type") == "product_carousel":
            for offer_id in section.get("offer_ids") or []:
                if offer_id and str(offer_id) not in ids:
                    ids.append(str(offer_id))
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

    offer = _load_offer_bundle(
        tenant_id, str(page.get("offer_id") or ""),
        offers_repository=offers_repository, products_repository=products_repository,
        services_repository=services_repository, products_by_id=products_by_id, services_by_id=services_by_id,
    )
    offers_by_id[str(offer.get("offer_id") or "")] = offer

    for referenced_id in carousel_offer_ids(page):
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
    offer, products_by_id, services_by_id, offers_by_id = load_render_context(
        page,
        offers_repository=offers_repository,
        products_repository=products_repository,
        services_repository=services_repository,
    )
    # Self-referencing canonical (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01). Interim: the published artifact
    # URL where the page actually lives; clean root-domain paths arrive with the Site object.
    published_paths = artifact_paths(str(page.get("tenant_id") or ""), str(page.get("page_id") or ""), page_slug(page))
    canonical_url = public_url(pages_domain, published_paths["published"])
    html = render_page(
        page,
        offer,
        products_by_id,
        checkout_url=checkout_url or checkout_base_url_for_page(page, offer, environment),
        api_base_url=api_base_url,
        services_by_id=services_by_id,
        offers_by_id=offers_by_id,
        canonical_url=canonical_url,
    )
    targets = artifact_targets(
        page,
        environment=environment,
        pages_bucket=pages_bucket,
        preview_bucket=preview_bucket,
        pages_domain=pages_domain,
        preview_domain=preview_domain,
    )

    artifacts = []
    for target in targets:
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
    }


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
