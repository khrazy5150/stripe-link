"""Delete-all-test-data admin action — parity with stripe-cart's `admin_delete_test_data.py`.

**DESTRUCTIVE and DEV/TEST-ONLY.** Wipes the *authenticated tenant's* test data: DynamoDB documents across
the commerce tables + a best-effort Stripe test-mode cleanup. Two behavioral adaptations from the legacy:
  1. **Tenant-scoped, not table-wide.** stripe-cart scanned and emptied whole tables; stripe-link is
     multi-tenant, so we delete only the caller's partition — emptying tables would nuke every tenant.
  2. **Hard dev-only gate.** Returns 403 unless `ENVIRONMENT` is a non-prod env; the API route is also
     `Condition: IsNonProd`, so it isn't even created in the prod stack (defense in depth).

Excluded on purpose (account config / infrastructure, not "test data"): Stripe keys, tenant/user profiles,
preferences, shipping config, Sites (custom domains), the services/booking family, routes, experiments,
legal pages. Published-page S3/CloudFront artifacts are NOT cleaned here (the DB records are removed; a
follow-up can purge orphaned HTML).
"""
import logging
import os

from stripe_link.common import error_response, json_response, tenant_id_from_event
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import stripe_keys_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

logger = logging.getLogger(__name__)

# Physical tables cleared. "PK" tables partition on TENANT#{id} (deleting the partition removes every
# document_type the tenant owns there — e.g. reviews+invites, carts+tokens, notifications+refund_requests).
_PK_TABLES = [
    "PRODUCTS_TABLE", "OFFERS_TABLE", "COUPONS_TABLE", "PAGES_TABLE", "LEADS_TABLE",
    "REVIEWS_TABLE", "CARTS_TABLE", "INVOICES_TABLE", "NOTIFICATIONS_TABLE",
]
# These partition on a raw `tenant_id` attribute.
_TENANT_ID_TABLES = ["CUSTOMERS_TABLE", "ORDERS_TABLE", "REFUNDS_TABLE", "LEDGER_TABLE"]
# CheckoutSessions partitions on session_id (tenant_id is the sort key) → a filtered scan is required.
_SCAN_TENANT_TABLES = ["CHECKOUT_SESSIONS_TABLE"]


def _label(env_name):
    return env_name.lower().replace("_table", "")


def handler(event, context, *, dynamodb=None, stripe_repo=None, secret_cipher=None, opener=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response("Method not allowed.", status_code=405, code="method_not_allowed")
    # Hard gate: never in prod. (The route is also Condition: IsNonProd — this is defense in depth.)
    if os.environ.get("ENVIRONMENT", "").lower() == "prod":
        return error_response("Delete test data is only available in the test environment.", status_code=403, code="forbidden")

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    if dynamodb is None:
        import boto3
        dynamodb = boto3.resource("dynamodb")

    deleted = {}
    for env_name in _PK_TABLES:
        deleted[_label(env_name)] = _delete_partition(dynamodb, os.environ.get(env_name, ""), "PK", f"TENANT#{tenant_id}")
    for env_name in _TENANT_ID_TABLES:
        deleted[_label(env_name)] = _delete_partition(dynamodb, os.environ.get(env_name, ""), "tenant_id", tenant_id)
    for env_name in _SCAN_TENANT_TABLES:
        deleted[_label(env_name)] = _delete_scan_tenant(dynamodb, os.environ.get(env_name, ""), tenant_id)

    try:
        stripe_results = _delete_stripe_test_data(tenant_id, stripe_repo, secret_cipher, opener)
    except Exception as exc:  # noqa: BLE001 - Stripe cleanup is best-effort; DB deletion already succeeded
        logger.warning("Stripe test-data cleanup failed for %s: %s", tenant_id, exc)
        stripe_results = {"error": str(exc)}

    return json_response({"success": True, "tenant_id": tenant_id, "deleted": deleted, "stripe": stripe_results})


def _delete_by_key(table, key_attrs, items):
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={attr: item[attr] for attr in key_attrs})


def _delete_partition(dynamodb, table_name, pk_name, pk_value):
    """Delete every item whose partition key matches — the tenant's whole slice of the table."""
    if not table_name:
        return 0
    from boto3.dynamodb.conditions import Key
    try:
        table = dynamodb.Table(table_name)
        key_attrs = [k["AttributeName"] for k in table.key_schema]
        names = {f"#k{i}": attr for i, attr in enumerate(key_attrs)}
        kwargs = {
            "KeyConditionExpression": Key(pk_name).eq(pk_value),
            "ProjectionExpression": ", ".join(names.keys()),
            "ExpressionAttributeNames": names,
        }
        deleted = 0
        while True:
            resp = table.query(**kwargs)
            items = resp.get("Items", [])
            if items:
                _delete_by_key(table, key_attrs, items)
                deleted += len(items)
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return deleted
    except Exception as exc:  # noqa: BLE001 - one table's failure must not abort the rest
        logger.warning("Failed clearing %s: %s", table_name, exc)
        return 0


def _delete_scan_tenant(dynamodb, table_name, tenant_id):
    """For tables not partitioned by tenant — scan and filter on tenant_id."""
    if not table_name:
        return 0
    from boto3.dynamodb.conditions import Attr
    try:
        table = dynamodb.Table(table_name)
        key_attrs = [k["AttributeName"] for k in table.key_schema]
        names = {f"#k{i}": attr for i, attr in enumerate(key_attrs)}
        kwargs = {
            "FilterExpression": Attr("tenant_id").eq(tenant_id),
            "ProjectionExpression": ", ".join(names.keys()),
            "ExpressionAttributeNames": names,
        }
        deleted = 0
        while True:
            resp = table.scan(**kwargs)
            items = resp.get("Items", [])
            if items:
                _delete_by_key(table, key_attrs, items)
                deleted += len(items)
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return deleted
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed scan-clearing %s: %s", table_name, exc)
        return 0


def _collect_ids(path, *, api_key, stripe_account, opener, params=None):
    """All object ids for a Stripe list endpoint (paginated up front, so we don't mutate mid-iteration)."""
    ids, cursor = [], None
    while True:
        page_params = dict(params or {})
        page_params["limit"] = 100
        if cursor:
            page_params["starting_after"] = cursor
        page = stripe_request("GET", path, api_key=api_key, stripe_account=stripe_account, params=page_params, opener=opener)
        data = page.get("data") or []
        ids.extend(obj["id"] for obj in data if obj.get("id"))
        if not page.get("has_more") or not data:
            break
        cursor = data[-1]["id"]
    return ids


def _delete_stripe_test_data(tenant_id, stripe_repo, secret_cipher, opener):
    """Best-effort Stripe test-mode cleanup (Stripe has no API to fully delete test data): archive prices,
    delete products (archive if they have prices), delete customers, delete coupons."""
    stripe_repo = stripe_repo or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    stripe_keys = stripe_repo.get(tenant_id, mode="test") or {}
    api_key, stripe_account = checkout_credentials(tenant_id, "test", stripe_keys, secret_cipher)
    if not api_key:
        return {"skipped": "no_test_key"}
    # SAFETY: only ever operate against a TEST secret key — never touch live objects.
    if not api_key.startswith("sk_test"):
        return {"skipped": "not_a_test_key"}

    results = {"prices_archived": 0, "products_deleted": 0, "products_archived": 0, "customers_deleted": 0, "coupons_deleted": 0}
    call = lambda method, path, **kw: stripe_request(method, path, api_key=api_key, stripe_account=stripe_account, opener=opener, **kw)

    for price_id in _collect_ids("/prices", api_key=api_key, stripe_account=stripe_account, opener=opener, params={"active": "true"}):
        try:
            call("POST", f"/prices/{price_id}", data={"active": "false"})
            results["prices_archived"] += 1
        except StripeApiError as exc:
            logger.info("Could not archive price %s: %s", price_id, exc)

    for product_id in _collect_ids("/products", api_key=api_key, stripe_account=stripe_account, opener=opener):
        try:
            call("DELETE", f"/products/{product_id}")
            results["products_deleted"] += 1
        except StripeApiError:
            try:
                call("POST", f"/products/{product_id}", data={"active": "false"})
                results["products_archived"] += 1
            except StripeApiError as exc:
                logger.info("Could not delete/archive product %s: %s", product_id, exc)

    for customer_id in _collect_ids("/customers", api_key=api_key, stripe_account=stripe_account, opener=opener):
        try:
            call("DELETE", f"/customers/{customer_id}")
            results["customers_deleted"] += 1
        except StripeApiError as exc:
            logger.info("Could not delete customer %s: %s", customer_id, exc)

    for coupon_id in _collect_ids("/coupons", api_key=api_key, stripe_account=stripe_account, opener=opener):
        try:
            call("DELETE", f"/coupons/{coupon_id}")
            results["coupons_deleted"] += 1
        except StripeApiError as exc:
            logger.info("Could not delete coupon %s: %s", coupon_id, exc)

    return results
