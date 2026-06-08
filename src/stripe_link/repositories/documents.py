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

    def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(
            self.table,
            KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant_id}") & Key("SK").begins_with(f"{self.sort_prefix}#")
        )
        return [self._strip_keys(item) for item in items]

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


def stripe_keys_repository(table: Any | None = None) -> SimpleKeyRepository:
    return SimpleKeyRepository(
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


def customers_repository(table: Any | None = None) -> TenantRangeRepository:
    return TenantRangeRepository(
        os.environ.get("CUSTOMERS_TABLE", ""),
        id_field="customer_id",
        table=table,
    )


def tenant_profiles_repository(table: Any | None = None) -> DynamoDocumentRepository:
    return DynamoDocumentRepository(
        os.environ.get("TENANT_PROFILES_TABLE", ""),
        document_type="tenant",
        id_field="tenant_id",
        table=table,
    )


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
