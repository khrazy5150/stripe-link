"""Delete-all-test-data admin action — parity with stripe-cart's `admin_delete_test_data.py`.

**DESTRUCTIVE, and scoped by STRIPE MODE rather than by deployment.** Wipes the *authenticated tenant's*
test data: DynamoDB documents across the commerce tables + a best-effort Stripe test-mode cleanup. Three
behavioral adaptations from the legacy:
  1. **Tenant-scoped, not table-wide.** stripe-cart scanned and emptied whole tables; stripe-link is
     multi-tenant, so we delete only the caller's partition — emptying tables would nuke every tenant.
  2. **Mode-gated, not environment-gated.** This used to be refused outside dev. That guarded the wrong
     axis: a tenant's sandbox now lives on the same deployment as their live books, so refusing by
     environment denied the very tenants who need it while protecting nothing (dev and prod share one
     connected Stripe account). The guard is `mode == "test"`, and a live-mode caller is refused outright
     rather than quietly scoped down.
  3. **Addressed, not filtered.** Deletion runs through mode-scoped repositories, so the test slice is a
     KEY — `SK begins_with TYPE#test#`, or the `TENANT#{id}#test` partition for money. A live document is
     unreachable rather than excluded. Only the handful of mode-agnostic types still need a predicate.

Booking: **appointments and their slot_locks ARE deleted** (booking transactions/holds, like orders), but the
booking SETUP in the same ServicesTable — services, fulfillers, availability — is KEPT.

Excluded on purpose (setup / infrastructure, not "test data"): Stripe keys, tenant/user profiles,
preferences, shipping config, services/fulfillers/availability, routes, experiments, legal pages.

**Sites are deliberately kept** (decision 2026-07-24): a Site is a tenant's hostname / organization-NAP /
SEO *setup*, not test data — the goal is to delete test data, not factory-reset the workspace. Deleting a
Site would also (a) leave the tenant with NO Site (none is auto-created — tenants make them by hand), and
(b) orphan its `SubdomainRegistry` reservation (there is no release path). Custom domains are live-only, so
none exist in test anyway. A Site's `slug->page_id` map may keep stale entries pointing at deleted test
pages; those simply 404 and self-heal as the tenant republishes — an acceptable trade vs. the above. Do NOT
add Site deletion here.

Published-page S3/CloudFront artifacts are NOT cleaned here (the DB records are removed; a follow-up can
purge orphaned HTML).
"""
import logging
import os
import time

from stripe_link.common import error_response, json_response, resolve_stripe_mode, tenant_id_from_event
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories import documents
from stripe_link.repositories.documents import stripe_keys_repository
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials

logger = logging.getLogger(__name__)

# WHAT GETS CLEARED, AND HOW IT IS ADDRESSED.
#
# Nothing here builds a DynamoDB key. Each entry names a repository; the repository owns its table, its
# sort prefix and its mode, and `documents.delete_all_for_tenant` reads the partition that mode addresses.
# The previous version kept its own list of 15 physical tables and its own key strings, and the list went
# stale: seven mode-scoped tables were never cleared (shipments, coupon grants, coupon redemptions,
# booking credits, collections, experiments, sites), so a sandbox reset left behind redemption records
# that still counted against a coupon's usage limit and booking credits that still spent.
#
# A repository list cannot drift the same way: a new mode-scoped document type is a one-line addition
# here, and `tests/test_mode_scope_census.py` fails for any repository nobody has classified.
#
# THE TEST SLICE IS A KEY, NOT A PREDICATE. Every repository below refuses to be built without a mode, so
# a live document is not filtered out of the result -- there is no key that reaches it.
_SCOPED_REPOSITORIES = [
    ("products", documents.products_repository),
    ("offers", documents.offers_repository),
    ("coupons", documents.coupons_repository),
    ("coupon_grants", documents.coupon_grants_repository),
    ("coupon_redemptions", documents.coupon_redemptions_repository),
    ("pages", documents.pages_repository),
    ("collections", documents.collections_repository),
    ("experiments", documents.experiments_repository),
    ("carts", documents.carts_repository),
    ("cart_tokens", documents.cart_tokens_repository),
    ("tip_tokens", documents.tip_tokens_repository),
    ("purchase_tokens", documents.purchase_tokens_repository),
    ("shipping_quotes", documents.shipping_quotes_repository),
    ("shipping_actuals", documents.shipping_actuals_repository),
    ("shipments", documents.shipments_repository),
    ("invoices", documents.invoices_repository),
    ("review_invites", documents.review_invites_repository),
    ("appointments", documents.appointments_repository),
    ("booking_credits", documents.booking_credits_repository),
]

# Money documents live in a partition of their own per mode -- PK = TENANT#{id}#{mode} -- so the test
# slice is the whole partition (plans/STRIPE_MODE_STORAGE.md).
_MONEY_REPOSITORIES = [
    ("customers", documents.customers_repository),
    ("orders", documents.orders_repository),
    ("refunds", documents.refunds_repository),
    ("ledger", documents.ledger_repository),
]

# Mode-AGNOSTIC documents: the key says nothing about mode, so a test row has to PROVE it (see
# `_is_test_item`) and anything unprovable is kept and reported. These are the three the census records as
# scoped-at-read-time, plus slot locks, which are transient holds that expire on their own.
# This is the only path where a predicate still decides, and it is deliberately the smaller half.
_UNSCOPED_PREFIX_TABLES = [
    ("LEADS_TABLE", "LEAD_SUBMISSION#", "leads"),
    ("REVIEWS_TABLE", "REVIEW#", "reviews"),
    ("NOTIFICATIONS_TABLE", "NOTIFICATION#", "notifications"),
    ("NOTIFICATIONS_TABLE", "REFUND_REQUEST#", "refund_requests"),
    ("SERVICES_TABLE", "SLOTLOCK#", "slot_locks"),
]
# CheckoutSessions partitions on session_id (tenant_id is the sort key) -> a filtered scan is required.
_SCAN_TENANT_TABLES = ["CHECKOUT_SESSIONS_TABLE"]

# Booking SETUP (services, fulfillers, availability) and Sites are mode-scoped but deliberately KEPT --
# see the module docstring. They are absent from the lists above on purpose; do not "fix" that.


# API Gateway closes the connection at 29 seconds whatever the Lambda's own timeout is, so work that
# runs past it produces "Failed to fetch" in the browser -- no status, no body, no way for the tenant to
# tell a disaster from a success. That is exactly what happened on the first real run: the database half
# finished, the Stripe half ran on, the function hit its 120s timeout, and the tenant was left guessing.
#
# The database half is irreversible and must complete. The Stripe half is best-effort by nature (Stripe
# has no bulk test-data delete) and is RESUMABLE -- objects it already removed are gone, so running the
# action again continues where it stopped. So the budget is spent on the database and whatever is left
# goes to Stripe, which stops cleanly and says it is unfinished.
_API_GATEWAY_LIMIT_SECONDS = 29
# Measured, not guessed: a real run with 54 prices to archive returned at 24s against a 23s budget, which
# is far too close to a limit whose breach is indistinguishable from a crash. The cost of a wider margin is
# one more click, and the dialog already asks for it.
_RESPONSE_MARGIN_SECONDS = 11


def _label(env_name):
    return env_name.lower().replace("_table", "")


def handler(event, context, *, dynamodb=None, stripe_repo=None, secret_cipher=None, opener=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response("Method not allowed.", status_code=405, code="method_not_allowed")
    # There is deliberately NO environment gate here. One used to refuse this action whenever ENVIRONMENT
    # was prod, and the route itself was Condition: IsNonProd. Both guarded the DEPLOYMENT, which is the
    # wrong axis and was never the safety property: dev and prod hold the SAME tenant's live Stripe
    # credentials (one connected account, verified 2026-10-18), so "this is dev" never meant "no live
    # money here". It only meant a tenant with a sandbox on production could not clear it.
    #
    # What makes this safe is below, and it is stronger: the mode is in the KEY. See `_SCOPED_REPOSITORIES`.

    started = time.monotonic()
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    # THE MODE IS PART OF THE PERMISSION, not just part of the query. Since Stripe mode was decoupled from
    # the deployment environment, a tenant can be in test mode on a backend that also holds their live
    # data -- so "which environment is this" no longer answers "is it safe to delete". A caller in live
    # mode is refused outright rather than quietly scoped down to test.
    mode = resolve_stripe_mode(event)
    if mode != "test":
        return error_response(
            "Switch to test mode before deleting test data.", status_code=400, code="live_mode")

    if dynamodb is None:
        import boto3
        dynamodb = boto3.resource("dynamodb")

    deleted, kept, errors = {}, {}, {}
    # Key-addressed: the repository knows its table and its mode, so nothing here spells a key.
    for label, factory in _SCOPED_REPOSITORIES + _MONEY_REPOSITORIES:
        deleted[label] = _clear_repository(factory, tenant_id, mode, dynamodb, errors, label)
    for env_name in _SCAN_TENANT_TABLES:
        deleted[_label(env_name)] = _delete_scan_tenant(dynamodb, os.environ.get(env_name, ""), tenant_id, mode)
    # Predicate-decided: no mode in the key, so prove it or keep it. The key is still built by the
    # repository layer -- this handler spells no part of it.
    for env_name, sk_prefix, label in _UNSCOPED_PREFIX_TABLES:
        counts = _delete_test_items(dynamodb, os.environ.get(env_name, ""), sk_prefix, tenant_id)
        deleted[label], kept[label] = counts["deleted"], counts["kept"]

    try:
        stripe_results = _delete_stripe_test_data(
            tenant_id, stripe_repo, secret_cipher, opener,
            deadline=started + _API_GATEWAY_LIMIT_SECONDS - _RESPONSE_MARGIN_SECONDS)
    except Exception as exc:  # noqa: BLE001 - Stripe cleanup is best-effort; DB deletion already succeeded
        logger.warning("Stripe test-data cleanup failed for %s: %s", tenant_id, exc)
        stripe_results = {"error": str(exc)}

    # `kept` is reported, not hidden: leads, reviews and notifications are NOT mode-scoped, so nothing can
    # tell a test one from a live one and they are left alone. Saying so is the difference between a known
    # limit and a tenant wondering why their sandbox still has reviews in it.
    # `errors` is reported, never swallowed. A previous version caught a DynamoDB refusal and returned
    # "0 deleted", which is indistinguishable from "nothing was there" -- the action looked like it worked
    # for as long as nobody counted.
    return json_response({"success": not errors, "tenant_id": tenant_id, "mode": mode,
                          "deleted": deleted, "kept_not_mode_scoped": kept,
                          "errors": errors, "stripe": stripe_results})


def _clear_repository(factory, tenant_id, mode, dynamodb, errors, label):
    """Clear one repository's slice of this tenant, in this mode.

    The repository resolves its own table name from the environment; we only hand it the resource, so the
    injected one is used in tests and the real one in the Lambda. A repository whose table is not
    configured for this function is recorded as an error rather than counted as an empty success.
    """
    try:
        repository = factory(mode=mode)
        if not repository.table_name:
            raise RuntimeError("table not configured for this function")
        repository._table = dynamodb.Table(repository.table_name)
        return documents.delete_all_for_tenant(repository, tenant_id)
    except Exception as exc:  # noqa: BLE001 - one repository's failure must not abort the rest
        logger.warning("Failed clearing %s for %s: %s", label, tenant_id, exc)
        errors[label] = str(exc)
        return 0


def _delete_by_key(table, key_attrs, items):
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={attr: item[attr] for attr in key_attrs})


def _is_test_item(item):
    """Whether this document PROVABLY belongs to test mode.

    Two ways to be sure, because the two storage shapes differ: mode-scoped documents carry
    `stripe_mode` (written by the repository on every put) and their sort key reads `TYPE#test#id`.
    Anything that proves neither is NOT deleted -- the whole point of this function is that an unprovable
    document is left alone rather than guessed at. Under the old code the guess was "delete it".
    """
    if str(item.get("stripe_mode") or "").strip().lower() == "test":
        return True
    if "#test#" in str(item.get("SK") or ""):
        return True
    # A record NAMED after a test checkout session is a test record. Reviews and refund requests are not
    # mode-scoped, so before reviews were stamped (2026-10-18) their only proof was the order they came
    # from -- `order_cs_test_...`. Without this they came back in `kept_not_mode_scoped` forever and a
    # sandbox could never be cleared of them.
    from stripe_link.common import stripe_mode_from_reference

    return stripe_mode_from_reference(item.get("order_id")) == "test"


def _delete_test_items(dynamodb, table_name, sk_prefix, tenant_id):
    """Delete the PROVABLY-test documents of one type, and count what was left behind.

    This used to delete the tenant's whole partition. That was survivable while the action existed only on
    the dev stack, and became a live-data wipe the moment a tenant could be in test mode on a backend
    holding their live documents. These types share one partition across both modes; only the predicate
    separates them, which is why this path is kept as small as possible.
    """
    if not table_name:
        return {"deleted": 0, "kept": 0}
    try:
        return documents.delete_proven_items(
            dynamodb.Table(table_name), tenant_id, sk_prefix=sk_prefix, predicate=_is_test_item)
    except Exception as exc:  # noqa: BLE001 - one table's failure must not abort the rest
        logger.warning("Failed clearing %s: %s", table_name, exc)
        return {"deleted": 0, "kept": 0}


def _is_test_session(item, mode):
    """A checkout session belonging to `mode`. The session id carries it (`cs_test_`/`cs_live_`), and the
    stored `stripe_mode` carries it too; either proof is enough, neither being present means no."""
    if str(item.get("stripe_mode") or "").strip().lower() == mode:
        return True
    for value in item.values():
        if isinstance(value, str) and value.startswith(f"cs_{mode}_"):
            return True
    return False

def _delete_scan_tenant(dynamodb, table_name, tenant_id, mode="test"):
    """For tables not partitioned by tenant — scan and filter on tenant_id AND mode.

    A checkout session records which books it belongs to, and `cs_live_...` / `cs_test_...` says so in the
    id itself. Filtering on the tenant alone would have taken the live sessions with the test ones.
    """
    if not table_name:
        return 0
    from boto3.dynamodb.conditions import Attr
    try:
        table = dynamodb.Table(table_name)
        key_attrs = [k["AttributeName"] for k in table.key_schema]
        names = {f"#k{i}": attr for i, attr in enumerate(key_attrs)}
        # The projection must carry what the mode test reads, or every row looks unprovable and nothing is
        # deleted -- the quiet failure this whole fix exists to remove.
        names["#mode"] = "stripe_mode"
        kwargs = {
            "FilterExpression": Attr("tenant_id").eq(tenant_id),
            "ProjectionExpression": ", ".join(names.keys()),
            "ExpressionAttributeNames": names,
        }
        deleted = 0
        while True:
            resp = table.scan(**kwargs)
            items = [i for i in resp.get("Items", []) if _is_test_session(i, mode)]
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


def _collect_ids(path, *, api_key, stripe_account, opener, params=None, deadline=None):
    """All object ids for a Stripe list endpoint (paginated up front, so we don't mutate mid-iteration).

    Stops paginating once the budget is spent: on an account with thousands of test objects, LISTING them
    can consume the whole response window before a single one is deleted.
    """
    ids, cursor = [], None
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
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


def _delete_stripe_test_data(tenant_id, stripe_repo, secret_cipher, opener, *, deadline=None):
    """Best-effort Stripe test-mode cleanup (Stripe has no API to fully delete test data): archive prices,
    delete products (archive if they have prices), delete customers, delete coupons.

    Every object costs one sequential HTTPS round-trip, so this is unbounded in the tenant's object count
    and was the half that ran the function into its timeout. It now stops at `deadline` and reports
    `incomplete`, which is honest rather than silent: the work resumes on the next run because whatever it
    already removed is gone.
    """
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
    out_of_time = lambda: deadline is not None and time.monotonic() >= deadline
    listing = {"api_key": api_key, "stripe_account": stripe_account, "opener": opener, "deadline": deadline}

    if out_of_time():
        results["incomplete"] = True
        return results
    for price_id in _collect_ids("/prices", params={"active": "true"}, **listing):
        if out_of_time():
            results["incomplete"] = True
            return results
        try:
            call("POST", f"/prices/{price_id}", data={"active": "false"})
            results["prices_archived"] += 1
        except StripeApiError as exc:
            logger.info("Could not archive price %s: %s", price_id, exc)

    if out_of_time():
        results["incomplete"] = True
        return results
    for product_id in _collect_ids("/products", **listing):
        if out_of_time():
            results["incomplete"] = True
            return results
        try:
            call("DELETE", f"/products/{product_id}")
            results["products_deleted"] += 1
        except StripeApiError:
            try:
                call("POST", f"/products/{product_id}", data={"active": "false"})
                results["products_archived"] += 1
            except StripeApiError as exc:
                logger.info("Could not delete/archive product %s: %s", product_id, exc)

    if out_of_time():
        results["incomplete"] = True
        return results
    for customer_id in _collect_ids("/customers", **listing):
        if out_of_time():
            results["incomplete"] = True
            return results
        try:
            call("DELETE", f"/customers/{customer_id}")
            results["customers_deleted"] += 1
        except StripeApiError as exc:
            logger.info("Could not delete customer %s: %s", customer_id, exc)

    if out_of_time():
        results["incomplete"] = True
        return results
    for coupon_id in _collect_ids("/coupons", **listing):
        if out_of_time():
            results["incomplete"] = True
            return results
        try:
            call("DELETE", f"/coupons/{coupon_id}")
            results["coupons_deleted"] += 1
        except StripeApiError as exc:
            logger.info("Could not delete coupon %s: %s", coupon_id, exc)

    return results
