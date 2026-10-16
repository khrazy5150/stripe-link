import logging
import os
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

from stripe_link.domain.platform_suspension import is_suspended
from stripe_link.repositories.documents import (
    RepositoryError,
    custom_domains_index_repository,
    collections_repository,
    experiments_repository,
    events_repository,
    reviews_repository,
    offers_repository,
    pages_repository,
    products_repository,
    routes_repository,
    services_repository,
    sites_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.runtime.publishing import (
    PublishConfigError,
    PublishError,
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


def _tenant_is_suspended(tenant_profiles_repo, page) -> bool:
    """Whether this page's tenant is suspended.

    FAILS CLOSED on a read error: an unreadable profile stops the publish. The opposite choice would mean a
    DynamoDB blip is all it takes to put a suspended tenant's page back on the air, and the page is the
    thing a suspension exists to remove.
    """
    if tenant_profiles_repo is None:
        return False
    tenant_id = str((page or {}).get("tenant_id") or "").strip()
    if not tenant_id:
        return False
    try:
        return is_suspended(tenant_profiles_repo.get(tenant_id, tenant_id))
    except Exception:  # noqa: BLE001
        logger.warning("Could not read tenant profile for %s; refusing to publish.", tenant_id)
        return True


def _tenant_pages(tenant_id, pages_repo=None):
    """Every page a tenant owns, in BOTH Stripe modes.

    A test-mode page is published to a real URL and is just as capable of carrying illegal content as a
    live one, so a takedown that only swept `live` would leave half the account up.
    """
    if pages_repo is not None:
        return pages_repo.list_for_tenant(tenant_id)
    found = []
    for mode in ("live", "test"):
        try:
            found.extend(pages_repository(mode=mode).list_for_tenant(tenant_id))
        except RepositoryError:
            continue
    return found


def _tenant_artifact_action(action, event, *, pages_repo=None, s3_client=None, cloudfront_client=None):
    """Take a tenant's published pages off the air, or put them back.

    **Artifacts only — page documents are not modified by a suspension.** Flipping each page to `archived`
    would also run `detach_page_from_sites` and `deregister_page_route`, which a restore would not undo:
    the tenant would come back to pages missing from their Site's route map. Deleting artifacts changes
    nothing a republish does not rebuild.
    """
    tenant_id = str((event or {}).get("tenant_id") or "").strip()
    if not tenant_id:
        return {"ok": False, "error": "tenant_id is required."}
    if action not in {"suspend_tenant", "restore_tenant"}:
        return {"ok": False, "error": f"Unknown action '{action}'."}

    pages = [p for p in _tenant_pages(tenant_id, pages_repo) if p.get("status") == "published"]
    touched, failed = [], []
    for page in pages:
        page_id = str(page.get("page_id") or "")
        try:
            if action == "suspend_tenant":
                delete_page_artifacts(
                    page,
                    s3_client=s3_client,
                    pages_bucket=os.environ.get("PAGES_BUCKET", ""),
                    preview_bucket=os.environ.get("PAGES_PREVIEW_BUCKET", ""),
                    cloudfront_client=cloudfront_client,
                    pages_distribution_id=os.environ.get("PAGES_DISTRIBUTION_ID", ""),
                )
            else:
                # Restore by RE-WRITING the document, which fires this same stream and republishes through
                # the ordinary path -- every repo, every rule, no second implementation of publishing that
                # could drift from the first. It works only once the suspension is lifted, because the
                # publish path above refuses a suspended tenant.
                mode = "live" if str(page.get("stripe_mode") or "").strip().lower() == "live" else "test"
                pages_repository(mode=mode).put(page)
            touched.append(page_id)
        except Exception as exc:  # noqa: BLE001 - one bad page must not abandon the rest of a takedown
            logger.exception("Tenant %s action %s failed for page %s", tenant_id, action, page_id)
            failed.append({"page_id": page_id, "error": str(exc)})

    logger.info("Tenant %s: %s touched %d page(s), %d failed", tenant_id, action, len(touched), len(failed))
    # `ok` is False when ANY page failed. A takedown that half worked must not report success -- the admin
    # has to know which pages are still up.
    return {"ok": not failed, "action": action, "tenant_id": tenant_id,
            "pages": touched, "page_count": len(touched), "failed": failed}

def should_publish_record(record: dict[str, Any]) -> bool:
    if record.get("eventName") not in {"INSERT", "MODIFY", "REMOVE"}:
        return False
    image = (
        ((record.get("dynamodb") or {}).get("NewImage") or {})
        or ((record.get("dynamodb") or {}).get("OldImage") or {})
    )
    return bool(image)


def handler(event, context, *, tenant_profiles_repo=None, offers_repo=None, products_repo=None, services_repo=None, sites_repo=None, pages_repo=None, domains_index_repo=None, reviews_repo=None, events_repo=None, collections_repo=None, routes_repo=None, stripe_keys_repo=None, experiments_repo=None, s3_client=None, cloudfront_client=None):
    # Mode-scoped repos (offers/products/services/sites/pages/collections) are built PER RECORD from each page's
    # own stripe_mode below — a single stream batch can mix modes (plans/STRIPE_MODE_DECOUPLING.md P4). Capture any
    # injected repos (tests) so the per-record build honours them. The rest are Stripe-mode-agnostic.
    _injected = {
        "offers": offers_repo, "products": products_repo, "services": services_repo,
        "sites": sites_repo, "pages": pages_repo, "collections": collections_repo,
        "experiments": experiments_repo,
    }
    stripe_keys_repo = stripe_keys_repo or (stripe_keys_repository() if os.environ.get("STRIPE_KEYS_TABLE") else None)
    domains_index_repo = domains_index_repo or (custom_domains_index_repository() if os.environ.get("CUSTOM_DOMAINS_TABLE") else None)
    reviews_repo = reviews_repo or (reviews_repository() if os.environ.get("REVIEWS_TABLE") else None)
    events_repo = events_repo or (events_repository() if os.environ.get("EVENTS_TABLE") else None)
    routes_repo = routes_repo or (routes_repository() if os.environ.get("ROUTES_TABLE") else None)
    # Store-level font preference (plans/FONT_SERVICE.md §9). Optional: without the table the preset stays
    # in charge, which is exactly what every page did before this was wired.
    tenant_profiles_repo = tenant_profiles_repo or (
        tenant_profiles_repository() if os.environ.get("TENANT_PROFILES_TABLE") else None
    )
    if s3_client is None or cloudfront_client is None:
        import boto3

        if s3_client is None:
            s3_client = boto3.client("s3")
        if cloudfront_client is None:
            cloudfront_client = boto3.client("cloudfront")

    # An INTERNAL invocation from the admin site, not a stream batch (plans/ADMIN_SITE.md §1c).
    #
    # Folded onto this function rather than given one of its own because this is where the pages bucket,
    # the distribution id, the IAM to use them, and `delete_page_artifacts` already live. A second home for
    # artifact-path knowledge is how two places start disagreeing about where a page is.
    #
    # It carries no identity of its own: Lambda-to-Lambda invoke is reachable only by a principal that was
    # granted it, and the only such principal is the admin API, which checks its own allow-list first.
    internal = str((event or {}).get("internal_admin") or "").strip()
    if internal:
        return _tenant_artifact_action(
            internal, event,
            pages_repo=_injected["pages"],
            s3_client=s3_client,
            cloudfront_client=cloudfront_client,
        )

    failures = []
    for record in (event or {}).get("Records", []):
        item_identifier = record.get("eventID") or record.get("eventId") or ""
        if not should_publish_record(record):
            continue

        page: dict = {}  # bound before the try so the permanent-failure log can name the page
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
            # A/B: a variant artifact must carry the TESTED page's canonical and robots, because the edge
            # serves it behind that page's URL (plans/AB_TESTING.md A2). Mode-scoped like the rest.
            experiments_repo = _injected["experiments"] or (experiments_repository(mode=page_mode) if os.environ.get("EXPERIMENTS_TABLE") else None)
            # A suspended tenant's page is never published, by ANY path that touches a page document --
            # including the tenant's own edit, a backfill, or a restore that ran before the suspension was
            # lifted. Deleting the artifact without this would be a takedown with a one-edit undo.
            if _tenant_is_suspended(tenant_profiles_repo, page):
                logger.info("Skipped publish for suspended tenant: %s", page.get("tenant_id"))
                continue

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
                # {stage}-test.juniorbay.com/preview/{code} link stays live; /published/{code} 404s naturally once the
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
                tenant_profiles_repository=tenant_profiles_repo,
                experiments_repository=experiments_repo,
                domains_index_repository=domains_index_repo,
                reviews_repository=reviews_repo,
                events_repository=events_repo,
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
            # {stage}-test.juniorbay.com/preview/{code} and /published/{code} resolve. Idempotent; no-op without a code.
            register_page_route(routes_repo, page)
            logger.info("Published page artifacts: %s", result)
        except PublishConfigError as exc:
            # The environment is wrong, not the data (an unset bucket name). A fix-forward deploy repairs it
            # and the retry then succeeds, so this one keeps the retry.
            logger.exception("Page publish is misconfigured, will retry: %s", exc)
            if item_identifier:
                failures.append({"itemIdentifier": item_identifier})
        except PublishError as exc:
            # PERMANENT. Every PublishError is a data condition -- an offer/product/service the page points at
            # is gone, a tenant_id mismatch, a missing bucket -- and no number of retries turns it into a
            # success. Reporting it as a batch item failure asks DynamoDB Streams to retry the record, and the
            # stream retries a failed record IN ORDER: the shard stops dead behind it, so every page saved
            # afterwards -- by any tenant -- silently stops rendering and never gets its route. One page whose
            # offer had been deleted blocked the shard for hours exactly this way. Drop it loudly instead.
            logger.error(
                "Dropping page stream record permanently (page=%s tenant=%s): %s",
                (page or {}).get("page_id"), (page or {}).get("tenant_id"), exc,
            )
        except Exception as exc:
            # Transient (throttling, S3/CloudFront 5xx, a bug). Worth a retry; the event source caps how many.
            logger.exception("Failed to publish page stream record: %s", exc)
            if item_identifier:
                failures.append({"itemIdentifier": item_identifier})

    return {"batchItemFailures": failures}
