import logging
import os
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

from stripe_link.repositories.documents import (
    custom_domains_index_repository,
    collections_repository,
    reviews_repository,
    offers_repository,
    pages_repository,
    products_repository,
    routes_repository,
    services_repository,
    sites_repository,
    stripe_keys_repository,
)
from stripe_link.runtime.publishing import (
    delete_page_artifacts,
    deregister_page_route,
    detach_page_from_sites,
    publish_page_document,
    register_page_route,
)


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_deserializer = TypeDeserializer()


def deserialize_image(image: dict[str, Any]) -> dict[str, Any]:
    item = {
        key: _deserializer.deserialize(value)
        for key, value in image.items()
    }
    return normalize_dynamodb_value(item)


def normalize_dynamodb_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, list):
        return [normalize_dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: normalize_dynamodb_value(item)
            for key, item in value.items()
        }
    return value


def should_publish_record(record: dict[str, Any]) -> bool:
    if record.get("eventName") not in {"INSERT", "MODIFY", "REMOVE"}:
        return False
    image = (
        ((record.get("dynamodb") or {}).get("NewImage") or {})
        or ((record.get("dynamodb") or {}).get("OldImage") or {})
    )
    return bool(image)


def handler(event, context, *, offers_repo=None, products_repo=None, services_repo=None, sites_repo=None, pages_repo=None, domains_index_repo=None, reviews_repo=None, collections_repo=None, routes_repo=None, stripe_keys_repo=None, s3_client=None, cloudfront_client=None):
    # Mode-scoped repos (offers/products/services/sites/pages/collections) are built PER RECORD from each page's
    # own stripe_mode below — a single stream batch can mix modes (plans/STRIPE_MODE_DECOUPLING.md P4). Capture any
    # injected repos (tests) so the per-record build honours them. The rest are Stripe-mode-agnostic.
    _injected = {
        "offers": offers_repo, "products": products_repo, "services": services_repo,
        "sites": sites_repo, "pages": pages_repo, "collections": collections_repo,
    }
    stripe_keys_repo = stripe_keys_repo or (stripe_keys_repository() if os.environ.get("STRIPE_KEYS_TABLE") else None)
    domains_index_repo = domains_index_repo or (custom_domains_index_repository() if os.environ.get("CUSTOM_DOMAINS_TABLE") else None)
    reviews_repo = reviews_repo or (reviews_repository() if os.environ.get("REVIEWS_TABLE") else None)
    routes_repo = routes_repo or (routes_repository() if os.environ.get("ROUTES_TABLE") else None)
    if s3_client is None or cloudfront_client is None:
        import boto3

        if s3_client is None:
            s3_client = boto3.client("s3")
        if cloudfront_client is None:
            cloudfront_client = boto3.client("cloudfront")

    failures = []
    for record in (event or {}).get("Records", []):
        item_identifier = record.get("eventID") or record.get("eventId") or ""
        if not should_publish_record(record):
            continue

        try:
            dynamodb_record = record.get("dynamodb") or {}
            image = dynamodb_record.get("NewImage") or dynamodb_record.get("OldImage")
            page = deserialize_image(image)
            if page.get("document_type") != "page":
                continue

            # Bind this record's mode-scoped repos to the PAGE's own Stripe mode, so a test page publishes against
            # test offers/products/collections and a live page against live (plans/STRIPE_MODE_DECOUPLING.md P4).
            page_mode = "live" if str(page.get("stripe_mode") or "").strip().lower() == "live" else "test"
            offers_repo = _injected["offers"] or offers_repository(mode=page_mode)
            products_repo = _injected["products"] or products_repository(mode=page_mode)
            services_repo = _injected["services"] or (services_repository(mode=page_mode) if os.environ.get("SERVICES_TABLE") else None)
            sites_repo = _injected["sites"] or (sites_repository(mode=page_mode) if os.environ.get("SITES_TABLE") else None)
            pages_repo = _injected["pages"] or (pages_repository(mode=page_mode) if os.environ.get("PAGES_TABLE") else None)
            collections_repo = _injected["collections"] or (collections_repository(mode=page_mode) if os.environ.get("COLLECTIONS_TABLE") else None)
            if record.get("eventName") == "REMOVE" or page.get("status") == "archived":
                result = delete_page_artifacts(
                    page,
                    s3_client=s3_client,
                    pages_bucket=os.environ.get("PAGES_BUCKET", ""),
                    preview_bucket=os.environ.get("PAGES_PREVIEW_BUCKET", ""),
                    cloudfront_client=cloudfront_client,
                    pages_distribution_id=os.environ.get("PAGES_DISTRIBUTION_ID", ""),
                )
                # A deleted/archived page must also leave any Site's route map, or the Site is left pointing at
                # a gone page (a phantom slug / a homepage that 404s). Authoritative backstop for any delete path.
                detached = detach_page_from_sites(
                    sites_repo, domains_index_repo, str(page.get("tenant_id") or ""), str(page.get("page_id") or ""),
                )
                deregister_page_route(routes_repo, page)  # retire the shareable test link
                logger.info("Deleted page artifacts: %s (detached from %s site(s))", result, detached)
                continue

            old_image = dynamodb_record.get("OldImage") or {}
            old_page = deserialize_image(old_image) if old_image else {}
            if old_page.get("status") == "published" and page.get("status") != "published":
                result = delete_page_artifacts(
                    old_page,
                    s3_client=s3_client,
                    pages_bucket=os.environ.get("PAGES_BUCKET", ""),
                    preview_bucket=os.environ.get("PAGES_PREVIEW_BUCKET", ""),
                    cloudfront_client=cloudfront_client,
                    pages_distribution_id=os.environ.get("PAGES_DISTRIBUTION_ID", ""),
                )
                # Keep the code->page route on unpublish: the page is now a draft, so its
                # test.juniorbay.com/preview/{code} link stays live; /published/{code} 404s naturally once the
                # published artifact above is deleted. The route is retired only on archive/delete.
                logger.info("Deleted unpublished page artifacts: %s", result)

            result = publish_page_document(
                page,
                offers_repository=offers_repo,
                products_repository=products_repo,
                services_repository=services_repo,
                sites_repository=sites_repo,
                pages_repository=pages_repo,
                collections_repository=collections_repo,
                stripe_keys_repository=stripe_keys_repo,
                domains_index_repository=domains_index_repo,
                reviews_repository=reviews_repo,
                s3_client=s3_client,
                pages_bucket=os.environ.get("PAGES_BUCKET", ""),
                preview_bucket=os.environ.get("PAGES_PREVIEW_BUCKET", ""),
                environment=os.environ.get("ENVIRONMENT", "dev"),
                pages_domain=os.environ.get("PAGES_DISTRIBUTION_DOMAIN", ""),
                preview_domain=os.environ.get("PREVIEW_DISTRIBUTION_DOMAIN", ""),
                checkout_url=page.get("checkout_url"),
                api_base_url=os.environ.get("PUBLIC_API_BASE_URL", ""),
                cloudfront_client=cloudfront_client,
                pages_distribution_id=os.environ.get("PAGES_DISTRIBUTION_ID", ""),
            )
            # Register the code->page route for every saved (non-archived) page, draft or published, so both
            # test.juniorbay.com/preview/{code} and /published/{code} resolve. Idempotent; no-op without a code.
            register_page_route(routes_repo, page)
            logger.info("Published page artifacts: %s", result)
        except Exception as exc:
            logger.exception("Failed to publish page stream record: %s", exc)
            if item_identifier:
                failures.append({"itemIdentifier": item_identifier})

    return {"batchItemFailures": failures}
