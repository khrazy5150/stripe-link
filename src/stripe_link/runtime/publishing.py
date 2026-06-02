import json
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

    targets.append({
        "kind": "test",
        "bucket": pages_bucket,
        "key": paths["test"],
        "cache_control": "no-cache, no-store, must-revalidate",
        "url": public_url(pages_domain, paths["test"]),
    })

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


def strip_document_keys(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if key not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"}
    }


def load_render_context(
    page: dict[str, Any],
    *,
    offers_repository: Any,
    products_repository: Any,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    tenant_id = str(page.get("tenant_id") or "")
    offer_id = str(page.get("offer_id") or "")
    offer = offers_repository.get(tenant_id, offer_id)
    if not offer:
        raise PublishError(f"Offer '{offer_id}' was not found for page '{page.get('page_id', '')}'.")

    validate_offer_document(offer)
    if offer.get("tenant_id") != tenant_id:
        raise PublishError("Page and offer tenant_id must match.")

    products_by_id: dict[str, dict[str, Any]] = {}
    for item in offer.get("items", []):
        product_id = item.get("product_id", "")
        product = products_repository.get(tenant_id, product_id)
        if not product:
            raise PublishError(f"Product '{product_id}' was not found for offer '{offer_id}'.")
        validate_product_document(product)
        if product.get("tenant_id") != tenant_id:
            raise PublishError("Page and product tenant_id must match.")
        products_by_id[product_id] = product

    return offer, products_by_id


def publish_page_document(
    page: dict[str, Any],
    *,
    offers_repository: Any,
    products_repository: Any,
    s3_client: Any,
    pages_bucket: str,
    preview_bucket: str,
    environment: str,
    pages_domain: str = "",
    preview_domain: str = "",
    checkout_url: str | None = None,
    cloudfront_client: Any | None = None,
    pages_distribution_id: str = "",
) -> dict[str, Any]:
    page = strip_document_keys(page)
    validate_page_document(page)
    offer, products_by_id = load_render_context(
        page,
        offers_repository=offers_repository,
        products_repository=products_repository,
    )
    html = render_page(page, offer, products_by_id, checkout_url=checkout_url or page.get("checkout_url"))
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

    path = cloudfront_path(published["key"])
    response = cloudfront_client.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {
                "Quantity": 1,
                "Items": [path],
            },
            "CallerReference": page_id,
        },
    )
    return {
        "distribution_id": distribution_id,
        "paths": [path],
        "id": ((response or {}).get("Invalidation") or {}).get("Id"),
    }


def manifest_json(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True)
