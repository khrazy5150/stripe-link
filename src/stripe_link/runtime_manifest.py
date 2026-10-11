"""The deployed resource names, for the `/manifest` diagnostic endpoint.

**Its own module because it was costing 28 environment variables on 74 Lambdas.**

It lived in `stripe_link/common.py`, which every handler imports, and it names every table, bucket and
distribution the stack has. So a conservative reach analysis -- the kind Phase 2 of
`plans/TRANSFORM_BUDGET.md` has to trust before it deletes anything -- concluded that `jb-health` needed
35 environment variables, 28 of them because of this one function it never calls.

`handlers/manifest.py` is the ONLY caller, and always was. Moving the function moves the floor for every
other function in the stack, which is a larger win than trimming any individual handler.

Nothing about the endpoint changes.
"""
from typing import Any

import os

from stripe_link.common import project_prefix, runtime_environment


def runtime_manifest() -> dict[str, Any]:
    names = {
        "tables": {
            "app_config": os.environ.get("APP_CONFIG_TABLE", ""),
            "stripe_keys": os.environ.get("STRIPE_KEYS_TABLE", ""),
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
