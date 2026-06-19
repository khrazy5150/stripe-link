import logging
import os
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

from stripe_link.repositories.documents import offers_repository, products_repository
from stripe_link.runtime.publishing import delete_page_artifacts, publish_page_document


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


def handler(event, context, *, offers_repo=None, products_repo=None, s3_client=None, cloudfront_client=None):
    offers_repo = offers_repo or offers_repository()
    products_repo = products_repo or products_repository()
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
            image = (record.get("dynamodb") or {}).get("NewImage") or (record.get("dynamodb") or {}).get("OldImage")
            page = deserialize_image(image)
            if page.get("document_type") != "page":
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
                logger.info("Deleted page artifacts: %s", result)
                continue

            result = publish_page_document(
                page,
                offers_repository=offers_repo,
                products_repository=products_repo,
                s3_client=s3_client,
                pages_bucket=os.environ.get("PAGES_BUCKET", ""),
                preview_bucket=os.environ.get("PAGES_PREVIEW_BUCKET", ""),
                environment=os.environ.get("ENVIRONMENT", "dev"),
                pages_domain=os.environ.get("PAGES_DISTRIBUTION_DOMAIN", ""),
                preview_domain=os.environ.get("PREVIEW_DISTRIBUTION_DOMAIN", ""),
                checkout_url=page.get("checkout_url"),
                cloudfront_client=cloudfront_client,
                pages_distribution_id=os.environ.get("PAGES_DISTRIBUTION_ID", ""),
            )
            logger.info("Published page artifacts: %s", result)
        except Exception as exc:
            logger.exception("Failed to publish page stream record: %s", exc)
            if item_identifier:
                failures.append({"itemIdentifier": item_identifier})

    return {"batchItemFailures": failures}
