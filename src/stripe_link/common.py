import json
import os
from decimal import Decimal
from typing import Any


class JsonEncoder(json.JSONEncoder):
    def default(self, value: Any):
        if isinstance(value, Decimal):
            if value % 1 == 0:
                return int(value)
            return float(value)
        return super().default(value)


def runtime_environment() -> str:
    return os.environ.get("ENVIRONMENT", "dev")


def project_prefix() -> str:
    return os.environ.get("PROJECT_PREFIX", "jb")


def json_response(body: dict[str, Any], status_code: int = 200) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,PATCH,DELETE",
        },
        "body": json.dumps(body, cls=JsonEncoder),
    }


def parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = (event or {}).get("body") or "{}"
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object.")
    return parsed


def query_params(event: dict[str, Any]) -> dict[str, Any]:
    params = (event or {}).get("queryStringParameters") or {}
    return params if isinstance(params, dict) else {}


def path_params(event: dict[str, Any]) -> dict[str, Any]:
    params = (event or {}).get("pathParameters") or {}
    return params if isinstance(params, dict) else {}


def header_value(event: dict[str, Any], name: str) -> str:
    headers = (event or {}).get("headers") or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value or ""
    return ""


def tenant_id_from_event(event: dict[str, Any], body: dict[str, Any] | None = None) -> str:
    body = body or {}
    return (
        str(body.get("tenant_id") or "").strip()
        or str(query_params(event).get("tenant_id") or "").strip()
        or str(query_params(event).get("tenantID") or "").strip()
        or str(header_value(event, "X-Tenant-Id") or "").strip()
        or str(header_value(event, "X-Client-Id") or "").strip()
    )


def error_response(message: str, status_code: int = 400, *, code: str = "bad_request") -> dict[str, Any]:
    return json_response({
        "error": code,
        "message": message,
    }, status_code=status_code)


def runtime_manifest() -> dict[str, Any]:
    names = {
        "tables": {
            "app_config": os.environ.get("APP_CONFIG_TABLE", ""),
            "stripe_keys": os.environ.get("STRIPE_KEYS_TABLE", ""),
            "stripe_keys_dev": os.environ.get("STRIPE_KEYS_TABLE_DEV", ""),
            "stripe_keys_prod": os.environ.get("STRIPE_KEYS_TABLE_PROD", ""),
            "platform_config": os.environ.get("PLATFORM_CONFIG_TABLE", ""),
            "shipping_config": os.environ.get("SHIPPING_CONFIG_TABLE", ""),
            "tenant_profiles": os.environ.get("TENANT_PROFILES_TABLE", ""),
            "user_preferences": os.environ.get("USER_PREFERENCES_TABLE", ""),
            "user_profiles": os.environ.get("USER_PROFILES_TABLE", ""),
            "notifications": os.environ.get("NOTIFICATIONS_TABLE", ""),
            "services": os.environ.get("SERVICES_TABLE", ""),
            "leads": os.environ.get("LEADS_TABLE", ""),
            "invoices": os.environ.get("INVOICES_TABLE", ""),
            "products": os.environ.get("PRODUCTS_TABLE", ""),
            "offers": os.environ.get("OFFERS_TABLE", ""),
            "pages": os.environ.get("PAGES_TABLE", ""),
            "checkout_sessions": os.environ.get("CHECKOUT_SESSIONS_TABLE", ""),
            "orders": os.environ.get("ORDERS_TABLE", ""),
            "customers": os.environ.get("CUSTOMERS_TABLE", ""),
            "document_events": os.environ.get("DOCUMENT_EVENTS_TABLE", ""),
            "routes": os.environ.get("ROUTES_TABLE", ""),
            "tier_policies": os.environ.get("TIER_POLICIES_TABLE", ""),
            "media": os.environ.get("MEDIA_TABLE", ""),
            "themes": os.environ.get("THEMES_TABLE", ""),
            "legal_pages": os.environ.get("LEGAL_PAGES_TABLE", ""),
            "custom_domains": os.environ.get("CUSTOM_DOMAINS_TABLE", ""),
        },
        "buckets": {
            "pages": os.environ.get("PAGES_BUCKET", ""),
            "pages_preview": os.environ.get("PAGES_PREVIEW_BUCKET", ""),
            "media": os.environ.get("MEDIA_BUCKET", ""),
            "templates": os.environ.get("TEMPLATES_BUCKET", ""),
        },
        "distributions": {
            "pages_id": os.environ.get("PAGES_DISTRIBUTION_ID", ""),
            "pages_domain": os.environ.get("PAGES_DISTRIBUTION_DOMAIN", ""),
            "preview_id": os.environ.get("PREVIEW_DISTRIBUTION_ID", ""),
            "preview_domain": os.environ.get("PREVIEW_DISTRIBUTION_DOMAIN", ""),
        },
    }
    prefix = project_prefix()
    resource_values = [
        value
        for group in names.values()
        for value in group.values()
        if value and not value.startswith("E") and ".cloudfront.net" not in value
    ]
    return {
        "service": "stripe-link",
        "environment": runtime_environment(),
        "project_prefix": prefix,
        "resource_prefix_ok": all(value.startswith(f"{prefix}-") for value in resource_values),
        **names,
    }
