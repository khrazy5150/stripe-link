import os
from decimal import Decimal
from typing import Any

from stripe_link.common import normalize_stripe_mode


class RepositoryError(RuntimeError):
    pass


class ResourceIsolationError(RepositoryError):
    pass


def assert_jb_resource_name(name: str) -> None:
    if not name.startswith("jb-"):
        raise ResourceIsolationError(f"Refusing to use non-jb resource '{name}'.")


def _query_all_pages(table: Any, **query: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    request = dict(query)

    while True:
        response = table.query(**request)
        items.extend(response.get("Items", []))

        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            return items

        request["ExclusiveStartKey"] = last_evaluated_key


class DynamoDocumentRepository:
    def __init__(
        self,
        table_name: str,
        *,
        document_type: str,
        id_field: str,
        table: Any | None = None,
        mode: str | None = None,
    ):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.document_type = document_type
        self.id_field = id_field
        self._table = table
        # When set, this repo is Stripe-mode-scoped: mode is baked into the SK + GSI1PK so a tenant's test and
        # live documents (which may share an id after a test->live promote) are DISTINCT items that coexist in
        # the one per-deployment table (plans/STRIPE_MODE_DECOUPLING.md). None = mode-agnostic (legacy layout).
        self.mode = normalize_stripe_mode(mode) if mode is not None else None

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    @property
    def sort_prefix(self) -> str:
        return self.document_type.upper()

    def _sk(self, document_id: str) -> str:
        if self.mode is not None:
            return f"{self.sort_prefix}#{self.mode}#{document_id}"
        return f"{self.sort_prefix}#{document_id}"

    def _list_prefix(self) -> str:
        if self.mode is not None:
            return f"{self.sort_prefix}#{self.mode}#"
        return f"{self.sort_prefix}#"

    def _gsi1pk(self, document_id: str) -> str:
        if self.mode is not None:
            return f"{self.sort_prefix}#{self.mode}#{document_id}"
        return f"{self.sort_prefix}#{document_id}"

    def _key(self, tenant_id: str, document_id: str) -> dict[str, str]:
        return {
            "PK": f"TENANT#{tenant_id}",
            "SK": self._sk(document_id),
        }

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(document.get("tenant_id") or "").strip()
        document_id = str(document.get(self.id_field) or "").strip()
        if not tenant_id:
            raise RepositoryError("Document tenant_id is required.")
        if not document_id:
            raise RepositoryError(f"Document {self.id_field} is required.")

        if self.mode is not None:
            document = {**document, "stripe_mode": self.mode}

        item = {
            **document,
            **self._key(tenant_id, document_id),
            "GSI1PK": self._gsi1pk(document_id),
            "GSI1SK": f"TENANT#{tenant_id}",
        }
        self.table.put_item(Item=item)
        return document

    def get(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key=self._key(tenant_id, document_id))
        item = response.get("Item")
        if not item:
            return None
        return self._strip_keys(item)

    def delete(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        response = self.table.delete_item(
            Key=self._key(tenant_id, document_id),
            ReturnValues="ALL_OLD",
        )
        item = response.get("Attributes")
        if not item:
            return None
        return self._strip_keys(item)

    def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(
            self.table,
            KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant_id}") & Key("SK").begins_with(self._list_prefix())
        )
        return [self._strip_keys(item) for item in items]

    def scan_type(self) -> list[dict[str, Any]]:
        """Cross-tenant scan of every document of this repo's type. Intended for periodic
        sweeps (e.g. due-reminder delivery), not the request path — it reads the whole table.
        Mode-scoped when the repo is bound to a mode; otherwise returns every mode."""
        from boto3.dynamodb.conditions import Attr

        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {"FilterExpression": Attr("SK").begins_with(self._list_prefix())}
        while True:
            response = self.table.scan(**request)
            items.extend(response.get("Items", []))
            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
            request["ExclusiveStartKey"] = last_evaluated_key
        return [self._strip_keys(item) for item in items]

    def find_by_id(self, document_id: str) -> dict[str, Any] | None:
        """Look up a document by id alone (cross-tenant) via GSI1. Assumes document_id is unique
        within the repo's mode (the GSI1PK carries the mode when the repo is mode-scoped)."""
        from boto3.dynamodb.conditions import Key

        response = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(self._gsi1pk(document_id)),
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return self._strip_keys(items[0])

    def increment_view(self, tenant_id: str, document_id: str, page_id: str, amount: int = 1) -> None:
        """Atomically bump stats.views_by_page[page_id] by amount.

        Used by the experiment resolver on every running resolve, where a full read-modify-write
        put() would race under concurrent traffic. Assumes stats.views_by_page exists (the map is
        seeded when the document is created); ADD creates the per-page counter on first hit.
        """
        self.table.update_item(
            Key=self._key(tenant_id, document_id),
            UpdateExpression="ADD #stats.#views.#page :amount",
            ExpressionAttributeNames={"#stats": "stats", "#views": "views_by_page", "#page": page_id},
            ExpressionAttributeValues={":amount": amount},
        )

    def _strip_keys(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in {"PK", "SK", "GSI1PK", "GSI1SK"}
        }


def products_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("PRODUCTS_TABLE", ""),
        document_type="product",
        id_field="product_id",
        table=table,
        mode=mode,
    )


def offers_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("OFFERS_TABLE", ""),
        document_type="offer",
        id_field="offer_id",
        table=table,
        mode=mode,
    )


def coupons_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("COUPONS_TABLE", ""),
        document_type="coupon",
        id_field="coupon_id",
        table=table,
        mode=mode,
    )


def pages_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("PAGES_TABLE", ""),
        document_type="page",
        id_field="page_id",
        table=table,
        mode=mode,
    )


def sites_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SITES_TABLE", ""),
        document_type="site",
        id_field="site_id",
        table=table,
        mode=mode,
    )


class SubdomainRegistry:
    """Global (cross-tenant) reservation of platform subdomains.

    A Site's platform hostname (`{label}.jbay.uk`) is a real routable address, so its label must be
    unique across ALL tenants, not just within one. This is enforced with sentinel items in the Sites
    table (PK=SUBDOMAIN#{label}, SK=RESERVATION) claimed via a conditional put: the first writer wins
    under concurrency. A reservation is never recycled — once a label points at a Site it keeps
    pointing there even after a rename, so previously-shared hosted URLs never resolve to someone else.
    """

    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    @staticmethod
    def _key(label: str) -> dict[str, str]:
        return {"PK": f"SUBDOMAIN#{label}", "SK": "RESERVATION"}

    def owner_of(self, label: str) -> str | None:
        """Return the site_id that currently owns `label`, or None if the label is unreserved."""
        label = str(label or "").strip().lower()
        if not label:
            return None
        item = self.table.get_item(Key=self._key(label)).get("Item")
        return item.get("site_id") if item else None

    def reserve(self, label: str, *, site_id: str, tenant_id: str, now: int) -> bool:
        """Claim `label` for `site_id`. Return True on success, False if another Site already owns it.
        Idempotent: re-reserving a label this same Site already owns succeeds."""
        from botocore.exceptions import ClientError

        label = str(label or "").strip().lower()
        if not label:
            raise RepositoryError("Subdomain label is required.")
        if not site_id:
            raise RepositoryError("site_id is required to reserve a subdomain.")
        item = {
            **self._key(label),
            "document_type": "subdomain_reservation",
            "subdomain": label,
            "site_id": site_id,
            "tenant_id": tenant_id,
            "reserved_at": int(now),
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) OR #sid = :sid",
                ExpressionAttributeNames={"#sid": "site_id"},
                ExpressionAttributeValues={":sid": site_id},
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise RepositoryError(str(exc)) from exc


def subdomain_registry(table: Any | None = None) -> SubdomainRegistry:
    return SubdomainRegistry(os.environ.get("SITES_TABLE", ""), table=table)


def calendar_connections_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("CALENDAR_CONNECTIONS_TABLE", ""),
        document_type="calendar_connection",
        id_field="connection_id",
        table=table,
    )


def oauth_states_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("CALENDAR_CONNECTIONS_TABLE", ""),
        document_type="oauth_state",
        id_field="state_id",
        table=table,
    )


class SimpleKeyRepository:
    def __init__(
        self,
        table_name: str,
        *,
        key_field: str,
        table: Any | None = None,
    ):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.key_field = key_field
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        key_value = str(document.get(self.key_field) or "").strip()
        if not key_value:
            raise RepositoryError(f"Document {self.key_field} is required.")
        self.table.put_item(Item=document)
        return document

    def get(self, key_value: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={self.key_field: key_value})
        return response.get("Item")


class StripeKeysRepository:
    """A tenant's Stripe keys for BOTH modes, isolated in ONE per-deployment table (Stripe-mode decoupling,
    plans/STRIPE_MODE_DECOUPLING.md). Mode is part of the composite key (PK=`tenant_id`, SK=`mode`) — NOT a
    second physical table — so a deployment holds a tenant's test AND live keys side by side. `mode` is stamped
    onto every write and required on every read; anything not explicitly "live" is treated as "test" (fail-safe)."""

    def __init__(
        self,
        table_name: str,
        *,
        key_field: str = "tenant_id",
        mode_field: str = "mode",
        table: Any | None = None,
    ):
        if not table_name:
            raise RepositoryError("Stripe keys table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.key_field = key_field
        self.mode_field = mode_field
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    @staticmethod
    def _mode(value: Any) -> str:
        return "live" if str(value or "").strip().lower() == "live" else "test"

    def _key(self, key_value: str, mode: str) -> dict[str, str]:
        return {self.key_field: key_value, self.mode_field: self._mode(mode)}

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        key_value = str(document.get(self.key_field) or "").strip()
        if not key_value:
            raise RepositoryError(f"Document {self.key_field} is required.")
        document = {**document, self.mode_field: self._mode(document.get(self.mode_field))}
        self.table.put_item(Item=document)
        return document

    def get(self, key_value: str, mode: str = "test") -> dict[str, Any] | None:
        response = self.table.get_item(Key=self._key(key_value, mode))
        return response.get("Item")

    def find_by_connect_account_id(self, account_id: str, mode: str = "test") -> dict[str, Any] | None:
        account_id = str(account_id or "").strip()
        if not account_id:
            return None

        from boto3.dynamodb.conditions import Attr

        request: dict[str, Any] = {
            "FilterExpression": Attr("connect_account_id").eq(account_id) & Attr(self.mode_field).eq(self._mode(mode)),
        }

        while True:
            response = self.table.scan(**request)
            items = response.get("Items", [])
            if items:
                return items[0]

            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                return None

            request["ExclusiveStartKey"] = last_evaluated_key


class AppConfigRepository:
    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        config_key = str(document.get("config_key") or "").strip()
        environment = str(document.get("environment") or "").strip()
        if not config_key:
            raise RepositoryError("Document config_key is required.")
        if not environment:
            raise RepositoryError("Document environment is required.")
        self.table.put_item(Item=dynamodb_safe_document(document))
        return document

    def get(self, config_key: str, environment: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"config_key": config_key, "environment": environment})
        return response.get("Item")


def app_config_repository(table: Any | None = None) -> AppConfigRepository:
    return AppConfigRepository(
        os.environ.get("APP_CONFIG_TABLE", ""),
        table=table,
    )


def dynamodb_safe_document(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [dynamodb_safe_document(item) for item in value]
    if isinstance(value, dict):
        return {key: dynamodb_safe_document(item) for key, item in value.items()}
    return value


class TenantRangeRepository:
    def __init__(
        self,
        table_name: str,
        *,
        id_field: str,
        table: Any | None = None,
        mode: str | None = None,
    ):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.id_field = id_field
        self._table = table
        # Orders/customers carry globally-unique ids (no cross-mode id reuse), so mode is a filtered ATTRIBUTE
        # here rather than part of the key: stamp on write, filter list/get by mode (plans/STRIPE_MODE_DECOUPLING.md).
        self.mode = normalize_stripe_mode(mode) if mode is not None else None

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(document.get("tenant_id") or "").strip()
        document_id = str(document.get(self.id_field) or "").strip()
        if not tenant_id:
            raise RepositoryError("Document tenant_id is required.")
        if not document_id:
            raise RepositoryError(f"Document {self.id_field} is required.")
        if self.mode is not None:
            document = {**document, "stripe_mode": self.mode}
        self.table.put_item(Item=document)
        return document

    def get(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"tenant_id": tenant_id, self.id_field: document_id})
        item = response.get("Item")
        if not item:
            return None
        if self.mode is not None and normalize_stripe_mode(item.get("stripe_mode")) != self.mode:
            return None
        return item

    def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Attr, Key

        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("tenant_id").eq(tenant_id)}
        if self.mode is not None:
            kwargs["FilterExpression"] = Attr("stripe_mode").eq(self.mode)
        return _query_all_pages(self.table, **kwargs)

    def find_by_payment_intent(self, payment_intent_id: str) -> dict[str, Any] | None:
        """Resolve an order from a Stripe PaymentIntent via the PaymentIntentIndex GSI."""
        from boto3.dynamodb.conditions import Key

        if not payment_intent_id:
            return None
        response = self.table.query(
            IndexName="PaymentIntentIndex",
            KeyConditionExpression=Key("payment_intent_id").eq(payment_intent_id),
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None


class RefundsRepository:
    """Immutable refunds ledger keyed (tenant_id, refund_id), with GSIs to dedupe by
    stripe_refund_id and list by order_id."""

    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        if not str(document.get("tenant_id") or "").strip():
            raise RepositoryError("Refund tenant_id is required.")
        if not str(document.get("refund_id") or "").strip():
            raise RepositoryError("Refund refund_id is required.")
        self.table.put_item(Item=dynamodb_safe_document(document))
        return document

    def get(self, tenant_id: str, refund_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"tenant_id": tenant_id, "refund_id": refund_id})
        return response.get("Item")

    def list_for_order(self, order_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(self.table, IndexName="OrderIndex", KeyConditionExpression=Key("order_id").eq(order_id))
        items.sort(key=lambda item: int(item.get("created_at") or 0))
        return items

    def find_by_stripe_refund(self, stripe_refund_id: str) -> dict[str, Any] | None:
        from boto3.dynamodb.conditions import Key

        if not stripe_refund_id:
            return None
        response = self.table.query(
            IndexName="StripeRefundIndex",
            KeyConditionExpression=Key("stripe_refund_id").eq(stripe_refund_id),
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None


def refunds_repository(table: Any | None = None) -> RefundsRepository:
    return RefundsRepository(os.environ.get("REFUNDS_TABLE", ""), table=table)


class LedgerRepository:
    """Append-only transaction ledger keyed (tenant_id, entry_id), with an OrderIndex GSI to
    list every financial movement for an order. Entry ids are deterministic per financial
    effect (e.g. le_sale_<payment_intent>), so a duplicate append overwrites the same row —
    idempotent by primary key."""

    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def append(self, document: dict[str, Any]) -> dict[str, Any]:
        if not str(document.get("tenant_id") or "").strip():
            raise RepositoryError("Ledger entry tenant_id is required.")
        if not str(document.get("entry_id") or "").strip():
            raise RepositoryError("Ledger entry entry_id is required.")
        self.table.put_item(Item=dynamodb_safe_document(document))
        return document

    def get(self, tenant_id: str, entry_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"tenant_id": tenant_id, "entry_id": entry_id})
        return response.get("Item")

    def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(self.table, KeyConditionExpression=Key("tenant_id").eq(tenant_id))
        items.sort(key=lambda item: int(item.get("occurred_at") or item.get("created_at") or 0))
        return items

    def list_for_order(self, order_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(self.table, IndexName="OrderIndex", KeyConditionExpression=Key("order_id").eq(order_id))
        items.sort(key=lambda item: int(item.get("occurred_at") or item.get("created_at") or 0))
        return items


def ledger_repository(table: Any | None = None) -> LedgerRepository:
    return LedgerRepository(os.environ.get("LEDGER_TABLE", ""), table=table)


class SlotLockRepository:
    """Atomic slot holds (in the services table) that prevent double-booking. A claim is a
    conditional put keyed by (tenant, fulfiller, slot_start); it succeeds only if no live lock
    exists — an expired lock (hold_expires_at < now) may be reclaimed. DynamoDB TTL on
    hold_expires_at eventually sweeps abandoned holds."""

    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def _key(self, tenant_id: str, fulfiller_id: str | None, slot_start: str) -> dict[str, str]:
        return {"PK": f"TENANT#{tenant_id}", "SK": f"SLOTLOCK#{fulfiller_id or 'any'}#{slot_start}"}

    def claim(self, tenant_id: str, fulfiller_id: str | None, slot_start: str, *, appointment_id: str, hold_expires_at: int, now: int) -> bool:
        """Return True if the slot was claimed, False if it is already held by a live lock."""
        from botocore.exceptions import ClientError

        item = {
            **self._key(tenant_id, fulfiller_id, slot_start),
            "tenant_id": tenant_id,
            "document_type": "slot_lock",
            "fulfiller_id": fulfiller_id or "",
            "slot_start": slot_start,
            "appointment_id": appointment_id,
            "hold_expires_at": int(hold_expires_at),
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(SK) OR #hold < :now",
                ExpressionAttributeNames={"#hold": "hold_expires_at"},
                ExpressionAttributeValues={":now": int(now)},
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise RepositoryError(str(exc)) from exc

    def release(self, tenant_id: str, fulfiller_id: str | None, slot_start: str) -> None:
        self.table.delete_item(Key=self._key(tenant_id, fulfiller_id, slot_start))


def slot_locks_repository(table: Any | None = None) -> SlotLockRepository:
    return SlotLockRepository(os.environ.get("SERVICES_TABLE", ""), table=table)


def webhook_events_repository(table: Any | None = None) -> SimpleKeyRepository:
    return SimpleKeyRepository(os.environ.get("WEBHOOK_EVENTS_TABLE", ""), key_field="event_id", table=table)


def stripe_keys_repository(table: Any | None = None) -> StripeKeysRepository:
    return StripeKeysRepository(
        os.environ.get("STRIPE_KEYS_TABLE", ""),
        key_field="tenant_id",
        table=table,
    )


def platform_config_repository(table: Any | None = None) -> SimpleKeyRepository:
    return SimpleKeyRepository(
        os.environ.get("PLATFORM_CONFIG_TABLE", ""),
        key_field="tenant_id",
        table=table,
    )


def shipping_config_repository(table: Any | None = None) -> SimpleKeyRepository:
    return SimpleKeyRepository(
        os.environ.get("SHIPPING_CONFIG_TABLE", ""),
        key_field="tenant_id",
        table=table,
    )


def customers_repository(table: Any | None = None, *, mode: str | None = None) -> TenantRangeRepository:
    return TenantRangeRepository(
        os.environ.get("CUSTOMERS_TABLE", ""),
        id_field="customer_id",
        table=table,
        mode=mode,
    )


def orders_repository(table: Any | None = None, *, mode: str | None = None) -> TenantRangeRepository:
    return TenantRangeRepository(
        os.environ.get("ORDERS_TABLE", ""),
        id_field="order_id",
        table=table,
        mode=mode,
    )


def tenant_profiles_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("TENANT_PROFILES_TABLE", ""),
        document_type="tenant",
        id_field="tenant_id",
        table=table,
    )


def tenant_profiles_registration_repositories(table: Any | None = None) -> list[DynamoDocumentRepository]:
    """Registration writes ONLY the local per-deployment tenant-profiles table. The legacy cross-env dual-write
    (both `-DEV` and `-PROD`) is retired under data isolation (plans/STRIPE_MODE_DECOUPLING.md) — dev runs
    unreleased code and must never write real prod profiles. Returns a single-element list so callers that iterate
    the registration targets stay unchanged."""
    return [tenant_profiles_repository(table)]


def user_preferences_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("USER_PREFERENCES_TABLE", ""),
        document_type="preferences",
        id_field="user_id",
        table=table,
    )


def user_profiles_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("USER_PROFILES_TABLE", ""),
        document_type="user_profile",
        id_field="user_id",
        table=table,
    )


def notifications_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("NOTIFICATIONS_TABLE", ""),
        document_type="notification",
        id_field="notification_id",
        table=table,
    )


def refund_requests_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("NOTIFICATIONS_TABLE", ""),
        document_type="refund_request",
        id_field="refund_request_id",
        table=table,
    )


def leads_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("LEADS_TABLE", ""),
        document_type="lead_submission",
        id_field="lead_id",
        table=table,
    )


def reviews_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("REVIEWS_TABLE", ""),
        document_type="review",
        id_field="review_id",
        table=table,
    )


def collections_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    """Collections — ordered, curated groups of a Site's pages (plans/SITE_COLLECTIONS.md). Tenant-scoped like
    every other document; a Collection carries its own site_id."""
    return DynamoDocumentRepository(
        os.environ.get("COLLECTIONS_TABLE", ""),
        document_type="collection",
        id_field="collection_id",
        table=table,
        mode=mode,
    )


def carts_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("CARTS_TABLE", ""),
        document_type="cart",
        id_field="cart_id",
        table=table,
        mode=mode,
    )


def cart_tokens_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    # Shares CARTS_TABLE via a distinct document_type (the reviews + review_invites precedent).
    return DynamoDocumentRepository(
        os.environ.get("CARTS_TABLE", ""),
        document_type="cart_token",
        id_field="token",
        table=table,
        mode=mode,
    )


def review_invites_repository(table: Any | None = None) -> DynamoDocumentRepository:
    # Post-purchase invite records — same table as reviews, distinct document_type (own SK prefix + scan_type).
    return DynamoDocumentRepository(
        os.environ.get("REVIEWS_TABLE", ""),
        document_type="review_invite",
        id_field="invite_id",
        table=table,
    )


def services_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="service",
        id_field="service_id",
        table=table,
        mode=mode,
    )


def fulfillers_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="fulfiller",
        id_field="fulfiller_id",
        table=table,
    )


def tenant_availability_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="tenant_availability",
        id_field="availability_id",
        table=table,
    )


def availability_exceptions_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="availability_exception",
        id_field="exception_id",
        table=table,
    )


def appointments_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="appointment",
        id_field="appointment_id",
        table=table,
        mode=mode,
    )


def invoices_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("INVOICES_TABLE", ""),
        document_type="invoice",
        id_field="invoice_id",
        table=table,
        mode=mode,
    )


def routes_repository(table: Any | None = None) -> DynamoDocumentRepository:
    """Short-URL routes, keyed by tenant but resolvable by short_code via GSI1 (find_by_id)."""
    return DynamoDocumentRepository(
        os.environ.get("ROUTES_TABLE", ""),
        document_type="route",
        id_field="short_code",
        table=table,
    )


def experiments_repository(table: Any | None = None, *, mode: str | None = None) -> DynamoDocumentRepository:
    """A/B experiments, keyed by tenant but resolvable by experiment_id via GSI1 (find_by_id)."""
    return DynamoDocumentRepository(
        os.environ.get("EXPERIMENTS_TABLE", ""),
        document_type="experiment",
        id_field="experiment_id",
        table=table,
        mode=mode,
    )


# Platform legal pages are global (not per-tenant); they live under one reserved partition
# and are resolvable by page_id via GSI1. Built-in defaults cover the empty-table case.
PLATFORM_TENANT_ID = "platform"


def legal_pages_repository(table: Any | None = None) -> DynamoDocumentRepository:
    """Platform-global legal pages (terms/privacy/refund), resolvable by page_id via GSI1."""
    return DynamoDocumentRepository(
        os.environ.get("LEGAL_PAGES_TABLE", ""),
        document_type="legal_page",
        id_field="page_id",
        table=table,
    )


def custom_domains_index_repository(table: Any | None = None) -> DynamoDocumentRepository:
    """Denormalized domain -> tenant/page lookup index, kept in sync with TenantConfig.custom_domains.

    TenantConfig remains the source of truth for a domain's full record; this index exists
    only so the public resolve endpoint can look up a domain in O(1) via GSI1 instead of
    scanning every tenant's config.
    """
    return DynamoDocumentRepository(
        os.environ.get("CUSTOM_DOMAINS_TABLE", ""),
        document_type="custom_domain",
        id_field="domain",
        table=table,
    )


class ProductCategoriesRepository:
    """Shared, non-tenant-scoped taxonomy of TENANT-CONTRIBUTED categories (curated ones live in code).

    Distinct-tenant usage is counted with a DynamoDB string set: recording a usage ADDs the tenant_id, which
    is atomic and idempotent, so a tenant re-saving the same category never double-counts. Promotion (>= N
    distinct tenants) is derived at read time from the set size — see domain/categories.py.
    """

    def __init__(self, table_name: str, *, table: Any | None = None):
        if not table_name:
            raise RepositoryError("Product categories table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def get(self, category_key: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"category_key": str(category_key)})
        return response.get("Item")

    def list_all(self) -> list[dict[str, Any]]:
        """Every contributed category. The table is small and slow-changing (only the long tail lives here;
        curated categories are code), so a scan is fine and lets the endpoint filter/dedup in one place."""
        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {}
        while True:
            response = self.table.scan(**request)
            items.extend(response.get("Items") or [])
            key = response.get("LastEvaluatedKey")
            if not key:
                return items
            request["ExclusiveStartKey"] = key

    def record_usage(self, category_key: str, label: str, product_type: str, tenant_id: str, now: int) -> None:
        """Register that `tenant_id` used this category for a `product_type` product. ADD is atomic and
        idempotent on both sets; label/created_at are only written on first sight (if_not_exists)."""
        category_key = str(category_key or "").strip()
        tenant_id = str(tenant_id or "").strip()
        if not category_key or not tenant_id:
            return
        expression_values: dict[str, Any] = {
            ":t": {tenant_id},
            ":label": str(label or category_key),
            ":now": int(now),
        }
        add_parts = ["tenant_ids :t"]
        if str(product_type or "").strip():
            expression_values[":pt"] = {str(product_type).strip()}
            add_parts.append("types :pt")
        self.table.update_item(
            Key={"category_key": category_key},
            UpdateExpression=(
                "ADD " + ", ".join(add_parts)
                + " SET label = if_not_exists(label, :label), created_at = if_not_exists(created_at, :now), updated_at = :now"
            ),
            ExpressionAttributeValues=expression_values,
        )


def product_categories_repository(table: Any | None = None) -> ProductCategoriesRepository:
    return ProductCategoriesRepository(os.environ.get("PRODUCT_CATEGORIES_TABLE", ""), table=table)
