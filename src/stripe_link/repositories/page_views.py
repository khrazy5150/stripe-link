"""Storage for page-view counts. Its own table, deliberately.

Not the Pages table: any MODIFY there fires the publish stream, so counting views on the page document
would re-render and re-upload the artifact on every visitor, and the per-visitor dedupe rows would be fed
to the publisher as if they were pages.
"""
import os
from typing import Any

import boto3


class PageViewRepository:
    def __init__(self, table: Any):
        self.table = table

    def claim_view(self, item: dict[str, Any]) -> bool:
        """Record this (page, day, visitor) if it is new. False means we have already counted them today."""
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
            return True
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "ConditionalCheckFailedException":
                return False
            raise

    def increment_total(self, key: dict[str, str], now: int) -> None:
        """Atomic ADD. A read-modify-write would lose counts under concurrent traffic, which is the only
        traffic shape that makes the number worth having."""
        self.table.update_item(
            Key=key,
            UpdateExpression="ADD #views :one SET last_view_at = :now",
            ExpressionAttributeNames={"#views": "views"},
            ExpressionAttributeValues={":one": 1, ":now": now},
        )

    def totals_for_pages(self, page_ids: list[str]) -> dict[str, int]:
        """Views per page id. Missing keys simply have no views yet."""
        from stripe_link.domain.page_views import counter_key

        totals: dict[str, int] = {}
        for page_id in page_ids:
            try:
                item = (self.table.get_item(Key=counter_key(page_id)) or {}).get("Item") or {}
            except Exception:  # noqa: BLE001 - one unreadable counter must not cost the listing its others
                continue
            if item:
                totals[page_id] = int(item.get("views") or 0)
        return totals


def page_views_repository(table: Any | None = None) -> PageViewRepository:
    if table is not None:
        return PageViewRepository(table)
    return PageViewRepository(boto3.resource("dynamodb").Table(os.environ["PAGE_VIEWS_TABLE"]))
