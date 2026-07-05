import os
from decimal import Decimal
from typing import Any


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
    ):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.document_type = document_type
        self.id_field = id_field
        self._table = table

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    @property
    def sort_prefix(self) -> str:
        return self.document_type.upper()

    def _key(self, tenant_id: str, document_id: str) -> dict[str, str]:
        return {
            "PK": f"TENANT#{tenant_id}",
            "SK": f"{self.sort_prefix}#{document_id}",
        }

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(document.get("tenant_id") or "").strip()
        document_id = str(document.get(self.id_field) or "").strip()
        if not tenant_id:
            raise RepositoryError("Document tenant_id is required.")
        if not document_id:
            raise RepositoryError(f"Document {self.id_field} is required.")

        item = {
            **document,
            **self._key(tenant_id, document_id),
            "GSI1PK": f"{self.sort_prefix}#{document_id}",
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
            KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant_id}") & Key("SK").begins_with(f"{self.sort_prefix}#")
        )
        return [self._strip_keys(item) for item in items]

    def find_by_id(self, document_id: str) -> dict[str, Any] | None:
        """Look up a document by id alone (cross-tenant) via GSI1. Assumes document_id is unique."""
        from boto3.dynamodb.conditions import Key

        response = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"{self.sort_prefix}#{document_id}"),
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


def products_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("PRODUCTS_TABLE", ""),
        document_type="product",
        id_field="product_id",
        table=table,
    )


def offers_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("OFFERS_TABLE", ""),
        document_type="offer",
        id_field="offer_id",
        table=table,
    )


def coupons_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("COUPONS_TABLE", ""),
        document_type="coupon",
        id_field="coupon_id",
        table=table,
    )


def pages_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("PAGES_TABLE", ""),
        document_type="page",
        id_field="page_id",
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
    def __init__(
        self,
        *,
        dev_table_name: str,
        prod_table_name: str,
        key_field: str = "tenant_id",
        dev_table: Any | None = None,
        prod_table: Any | None = None,
    ):
        if not dev_table_name:
            raise RepositoryError("Dev Stripe keys table name is required.")
        if not prod_table_name:
            raise RepositoryError("Prod Stripe keys table name is required.")
        assert_jb_resource_name(dev_table_name)
        assert_jb_resource_name(prod_table_name)
        self.dev_table_name = dev_table_name
        self.prod_table_name = prod_table_name
        self.key_field = key_field
        self._dev_table = dev_table
        self._prod_table = prod_table

    def table_for_mode(self, mode: str):
        if mode == "live":
            return self.prod_table
        return self.dev_table

    @property
    def dev_table(self):
        if self._dev_table is None:
            import boto3

            self._dev_table = boto3.resource("dynamodb").Table(self.dev_table_name)
        return self._dev_table

    @property
    def prod_table(self):
        if self._prod_table is None:
            import boto3

            self._prod_table = boto3.resource("dynamodb").Table(self.prod_table_name)
        return self._prod_table

    def put(self, document: dict[str, Any]) -> dict[str, Any]:
        key_value = str(document.get(self.key_field) or "").strip()
        mode = "live" if document.get("mode") == "live" else "test"
        if not key_value:
            raise RepositoryError(f"Document {self.key_field} is required.")
        self.table_for_mode(mode).put_item(Item=document)
        return document

    def get(self, key_value: str, mode: str = "test") -> dict[str, Any] | None:
        response = self.table_for_mode("live" if mode == "live" else "test").get_item(Key={self.key_field: key_value})
        return response.get("Item")

    def find_by_connect_account_id(self, account_id: str, mode: str = "test") -> dict[str, Any] | None:
        account_id = str(account_id or "").strip()
        if not account_id:
            return None

        from boto3.dynamodb.conditions import Attr

        table = self.table_for_mode("live" if mode == "live" else "test")
        request: dict[str, Any] = {
            "FilterExpression": Attr("connect_account_id").eq(account_id),
        }

        while True:
            response = table.scan(**request)
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
    ):
        if not table_name:
            raise RepositoryError("Table name is required.")
        assert_jb_resource_name(table_name)
        self.table_name = table_name
        self.id_field = id_field
        self._table = table

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
        self.table.put_item(Item=document)
        return document

    def get(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"tenant_id": tenant_id, self.id_field: document_id})
        return response.get("Item")

    def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        return _query_all_pages(self.table, KeyConditionExpression=Key("tenant_id").eq(tenant_id))


def stripe_keys_repository(table: Any | None = None) -> StripeKeysRepository:
    fallback_table = os.environ.get("STRIPE_KEYS_TABLE", "")
    return StripeKeysRepository(
        dev_table_name=os.environ.get("STRIPE_KEYS_TABLE_DEV") or fallback_table,
        prod_table_name=os.environ.get("STRIPE_KEYS_TABLE_PROD") or fallback_table,
        key_field="tenant_id",
        dev_table=table,
        prod_table=table,
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


def customers_repository(table: Any | None = None) -> TenantRangeRepository:
    return TenantRangeRepository(
        os.environ.get("CUSTOMERS_TABLE", ""),
        id_field="customer_id",
        table=table,
    )


def orders_repository(table: Any | None = None) -> TenantRangeRepository:
    return TenantRangeRepository(
        os.environ.get("ORDERS_TABLE", ""),
        id_field="order_id",
        table=table,
    )


def tenant_profiles_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("TENANT_PROFILES_TABLE", ""),
        document_type="tenant",
        id_field="tenant_id",
        table=table,
    )


def tenant_profiles_registration_repositories(table: Any | None = None) -> list[DynamoDocumentRepository]:
    table_names = [
        os.environ.get("TENANT_PROFILES_TABLE_DEV", ""),
        os.environ.get("TENANT_PROFILES_TABLE_PROD", ""),
    ]
    if not any(table_names):
        table_names = [os.environ.get("TENANT_PROFILES_TABLE", "")]

    repositories: list[DynamoDocumentRepository] = []
    seen: set[str] = set()
    for table_name in table_names:
        if not table_name or table_name in seen:
            continue
        seen.add(table_name)
        repositories.append(DynamoDocumentRepository(
            table_name,
            document_type="tenant",
            id_field="tenant_id",
            table=table,
        ))
    if not repositories:
        raise RepositoryError("Tenant profile registration table names are required.")
    return repositories


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


def services_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="service",
        id_field="service_id",
        table=table,
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


def appointments_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("SERVICES_TABLE", ""),
        document_type="appointment",
        id_field="appointment_id",
        table=table,
    )


def invoices_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("INVOICES_TABLE", ""),
        document_type="invoice",
        id_field="invoice_id",
        table=table,
    )


def routes_repository(table: Any | None = None) -> DynamoDocumentRepository:
    """Short-URL routes, keyed by tenant but resolvable by short_code via GSI1 (find_by_id)."""
    return DynamoDocumentRepository(
        os.environ.get("ROUTES_TABLE", ""),
        document_type="route",
        id_field="short_code",
        table=table,
    )


def experiments_repository(table: Any | None = None) -> DynamoDocumentRepository:
    """A/B experiments, keyed by tenant but resolvable by experiment_id via GSI1 (find_by_id)."""
    return DynamoDocumentRepository(
        os.environ.get("EXPERIMENTS_TABLE", ""),
        document_type="experiment",
        id_field="experiment_id",
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
