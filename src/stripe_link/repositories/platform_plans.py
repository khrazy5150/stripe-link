import os
from typing import Any

from stripe_link.common import normalize_stripe_mode
from stripe_link.repositories.documents import (
    RepositoryError,
    _query_all_pages,
    assert_jb_resource_name,
)


class PlatformPlansRepository:
    """Global (NON-tenant) plan catalog for the platform->tenant SaaS subscription.

    Unlike the tenant-scoped DynamoDocumentRepository (PK = TENANT#{id}), these items are platform-wide and keyed by
    the platform's own BILLING mode (test|live) so test plans reference test Stripe prices:
      - PK = PLATFORM_BILLING#{billing_mode}
      - SK = PLAN#{plan_key}     -> one item per plan (the editable source of truth)
      - SK = CONFIG              -> singleton: default_plan_key + exempt bypass lists
    Hand-editable (an admin CRUD screen is a later phase). See plans/SAAS_BILLING_PAYWALL.md.
    """

    _CONFIG_SK = "CONFIG"

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
    def _pk(mode: str) -> str:
        return f"PLATFORM_BILLING#{normalize_stripe_mode(mode)}"

    @staticmethod
    def _plan_sk(plan_key: str) -> str:
        return f"PLAN#{plan_key}"

    @staticmethod
    def _promo_sk(promo_code: str) -> str:
        # Promo codes are case-insensitive: stored/looked up upper-cased so LAUNCH30 == launch30.
        return f"PROMO#{str(promo_code).strip().upper()}"

    def list_plans(self, mode: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = _query_all_pages(
            self.table,
            KeyConditionExpression=Key("PK").eq(self._pk(mode)) & Key("SK").begins_with("PLAN#"),
        )
        return [self._strip_keys(item) for item in items]

    def get_plan(self, mode: str, plan_key: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"PK": self._pk(mode), "SK": self._plan_sk(plan_key)})
        item = response.get("Item")
        return self._strip_keys(item) if item else None

    def put_plan(self, mode: str, plan: dict[str, Any]) -> dict[str, Any]:
        plan_key = str(plan.get("plan_key") or "").strip()
        if not plan_key:
            raise RepositoryError("Plan plan_key is required.")
        item = {
            **plan,
            "PK": self._pk(mode),
            "SK": self._plan_sk(plan_key),
            "billing_mode": normalize_stripe_mode(mode),
        }
        self.table.put_item(Item=item)
        return plan

    def get_promo(self, mode: str, promo_code: str) -> dict[str, Any] | None:
        if not str(promo_code or "").strip():
            return None
        response = self.table.get_item(Key={"PK": self._pk(mode), "SK": self._promo_sk(promo_code)})
        item = response.get("Item")
        return self._strip_keys(item) if item else None

    def put_promo(self, mode: str, promo: dict[str, Any]) -> dict[str, Any]:
        promo_code = str(promo.get("promo_code") or "").strip()
        if not promo_code:
            raise RepositoryError("Promo promo_code is required.")
        item = {
            **promo,
            "promo_code": promo_code.upper(),
            "PK": self._pk(mode),
            "SK": self._promo_sk(promo_code),
            "billing_mode": normalize_stripe_mode(mode),
        }
        self.table.put_item(Item=item)
        return promo

    def get_config(self, mode: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"PK": self._pk(mode), "SK": self._CONFIG_SK})
        item = response.get("Item")
        return self._strip_keys(item) if item else None

    def put_config(self, mode: str, config: dict[str, Any]) -> dict[str, Any]:
        item = {
            **config,
            "PK": self._pk(mode),
            "SK": self._CONFIG_SK,
            "billing_mode": normalize_stripe_mode(mode),
        }
        self.table.put_item(Item=item)
        return config

    @staticmethod
    def _strip_keys(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key not in {"PK", "SK"}}


def platform_plans_repository(table: Any | None = None) -> PlatformPlansRepository:
    return PlatformPlansRepository(os.environ.get("PLATFORM_PLANS_TABLE", ""), table=table)
