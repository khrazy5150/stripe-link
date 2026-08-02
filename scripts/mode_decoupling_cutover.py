#!/usr/bin/env python3
"""Stripe-mode decoupling cutover (plans/STRIPE_MODE_DECOUPLING.md P6).

BACK UP every jb- table to S3, then SELECTIVELY wipe only the per-tenant test-data tables so both
Stripe modes can be re-onboarded on the clean model. Platform reference tables (categories, app-config,
tier-policies, themes) are PRESERVED. DRY-RUN by default — pass --confirm to actually delete.

Three safety layers:
  1. jb- prefix ONLY — refuses any table not named `jb-<name>-<env>`, so it can never touch a stripe-cart
     (unprefixed) table that shares a name (e.g. platform-config vs jb-platform-config).
  2. Explicit allow-lists — only tables on the WIPE list are deleted; PRESERVE/REVIEW/unclassified are left
     alone and reported.
  3. Backup-first + dry-run-by-default — --confirm requires a --backup-bucket, and every jb- table (wipe AND
     preserve) is dumped to S3 as restorable DynamoDB-JSON before a single delete.

Dev-first: prod requires the explicit --allow-prod flag.

Examples:
  # See exactly what would happen (no writes):
  python scripts/mode_decoupling_cutover.py --env dev
  # Do it (dev), backing up first, and clear the published-page buckets:
  python scripts/mode_decoupling_cutover.py --env dev --confirm --backup-bucket jb-cutover-backups \
      --pages-bucket jb-pages-dev --preview-bucket jb-pages-preview-dev
"""
import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

# Platform reference / config — NEVER wiped (see plan). Global billing config is NOT a table (it lives in S3
# BILLING_CONFIG_BUCKET/global_billing_config.json), so it is unaffected regardless.
PRESERVE = {"product-categories", "app-config", "tier-policies", "themes"}

# Per-tenant but may hold hand-authored content — excluded from the wipe by default. Add --include-legal-pages
# to move it into the wipe set for this run.
REVIEW = {"legal-pages"}

# Per-tenant test content / accounts / transactions / funnel artifacts — re-created on re-onboard.
WIPE = {
    "calendar-connections", "carts", "checkout-sessions", "collections", "coupons", "custom-domains",
    "customers", "document-events", "experiments", "invoices", "lead-capture", "ledger", "media",
    "notifications", "offers", "orders", "pages", "platform-config", "products", "refunds", "reviews",
    "routes", "services", "shipping-config", "sites", "stripe-keys", "stripe-keys-v2", "tenant-profiles",
    "user-preferences", "user-profiles", "webhook-events",
}


def base_name(table: str, env: str) -> str | None:
    """The `<name>` of a `jb-<name>-<env>` table, or None if it isn't a jb- table for this env (SAFETY 1)."""
    prefix, suffix = "jb-", f"-{env}"
    if not table.startswith(prefix) or not table.endswith(suffix) or len(table) <= len(prefix) + len(suffix):
        return None
    return table[len(prefix):-len(suffix)]


def classify(base: str) -> str:
    if base in PRESERVE:
        return "PRESERVE"
    if base in REVIEW:
        return "REVIEW"
    if base in WIPE:
        return "WIPE"
    return "UNCLASSIFIED"


def discover_jb_tables(ddb, env: str) -> list[str]:
    tables = []
    for page in ddb.get_paginator("list_tables").paginate():
        for name in page.get("TableNames", []):
            if base_name(name, env) is not None:
                tables.append(name)
    return sorted(tables)


def scan_items(ddb, table: str, projection: list[str] | None = None):
    kwargs: dict = {"TableName": table}
    if projection:
        kwargs["ProjectionExpression"] = ", ".join(f"#k{i}" for i in range(len(projection)))
        kwargs["ExpressionAttributeNames"] = {f"#k{i}": a for i, a in enumerate(projection)}
    for page in ddb.get_paginator("scan").paginate(**kwargs):
        yield from page.get("Items", [])


def count_items(ddb, table: str) -> int:
    total = 0
    for page in ddb.get_paginator("scan").paginate(TableName=table, Select="COUNT"):
        total += page.get("Count", 0)
    return total


def key_attributes(ddb, table: str) -> list[str]:
    desc = ddb.describe_table(TableName=table)["Table"]
    return [k["AttributeName"] for k in desc["KeySchema"]]


def backup_table(ddb, s3, table: str, bucket: str, prefix: str) -> tuple[int, str]:
    """Dump every item as DynamoDB-JSON JSONL to S3 — directly restorable via put_item."""
    key = f"{prefix}/{table}.jsonl"
    lines, count = [], 0
    for item in scan_items(ddb, table):
        lines.append(json.dumps(item, sort_keys=True))
        count += 1
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body)
    return count, f"s3://{bucket}/{key}"


def delete_all_items(ddb, table: str, key_attrs: list[str]) -> int:
    deleted, batch = 0, []

    def flush():
        nonlocal deleted
        request = {table: batch}
        while request:
            resp = ddb.batch_write_item(RequestItems=request)
            request = resp.get("UnprocessedItems") or {}
        deleted += len(batch)

    for item in scan_items(ddb, table, projection=key_attrs):
        batch.append({"DeleteRequest": {"Key": {a: item[a] for a in key_attrs}}})
        if len(batch) == 25:
            flush()
            batch = []
    if batch:
        flush()
    return deleted


def clear_bucket(s3, bucket: str) -> int:
    deleted = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objs, "Quiet": True})
            deleted += len(objs)
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="Stripe-mode decoupling cutover (selective wipe).")
    ap.add_argument("--env", required=True, choices=["dev", "prod"], help="Which deployment to operate on.")
    ap.add_argument("--region", default=None, help="AWS region (defaults to the session/config region).")
    ap.add_argument("--confirm", action="store_true", help="Actually delete. Without this it is a dry run.")
    ap.add_argument("--allow-prod", action="store_true", help="Required to run against prod (dev-first safety).")
    ap.add_argument("--backup-bucket", default=None, help="S3 bucket for the pre-wipe backup (required with --confirm).")
    ap.add_argument("--backup-prefix", default="mode-decoupling-cutover", help="Key prefix for the backup dump.")
    ap.add_argument("--pages-bucket", default=None, help="Published-pages bucket to clear (optional).")
    ap.add_argument("--preview-bucket", default=None, help="Preview-pages bucket to clear (optional).")
    ap.add_argument("--include-legal-pages", action="store_true", help="Also wipe jb-legal-pages this run.")
    ap.add_argument("--stamp", default="run", help="Sub-folder for this run's backup (e.g. a date you pass in).")
    args = ap.parse_args()

    if args.env == "prod" and not args.allow_prod:
        print("Refusing to run against prod without --allow-prod (dev-first). Aborting.")
        return 2
    if args.confirm and not args.backup_bucket:
        print("--confirm requires --backup-bucket (back up before deleting). Aborting.")
        return 2

    wipe_set = set(WIPE) | ({"legal-pages"} if args.include_legal_pages else set())

    session = boto3.Session(region_name=args.region) if args.region else boto3.Session()
    ddb = session.client("dynamodb")
    s3 = session.client("s3")

    tables = discover_jb_tables(ddb, args.env)
    if not tables:
        print(f"No jb-*-{args.env} tables found. Nothing to do.")
        return 0

    plan: dict[str, list[str]] = {"WIPE": [], "PRESERVE": [], "REVIEW": [], "UNCLASSIFIED": []}
    for t in tables:
        base = base_name(t, args.env)
        action = "WIPE" if base in wipe_set else classify(base)
        plan[action].append(t)

    print(f"\n=== Stripe-mode decoupling cutover — env={args.env}  mode={'EXECUTE' if args.confirm else 'DRY-RUN'} ===")
    print(f"Discovered {len(tables)} jb-*-{args.env} tables.\n")
    for action in ("PRESERVE", "REVIEW", "UNCLASSIFIED", "WIPE"):
        for t in plan[action]:
            note = ""
            if action == "UNCLASSIFIED":
                note = "  <-- not on any list; LEFT UNTOUCHED, review its contents"
            if action == "REVIEW" and not args.include_legal_pages:
                note = "  <-- excluded from wipe (pass --include-legal-pages to wipe)"
            print(f"  [{action:12}] {t}{note}")
    print()

    # SAFETY 2: a PRESERVE table must never be in the delete set.
    guard = [t for t in plan["WIPE"] if base_name(t, args.env) in PRESERVE]
    if guard:
        print(f"SAFETY ABORT: preserve-listed tables in the wipe set: {guard}")
        return 3

    # Backup — every jb- table (wipe AND preserve), always, before any delete.
    if args.confirm:
        prefix = f"{args.backup_prefix}/{args.env}/{args.stamp}"
        print(f"Backing up all {len(tables)} tables to s3://{args.backup_bucket}/{prefix}/ ...")
        for t in tables:
            try:
                n, loc = backup_table(ddb, s3, t, args.backup_bucket, prefix)
                print(f"  backed up {n:>7} items  {t}  -> {loc}")
            except ClientError as exc:
                print(f"  BACKUP FAILED for {t}: {exc}. Aborting before any delete.")
                return 4
        print()

    # Wipe (or count, in dry-run).
    total = 0
    for t in plan["WIPE"]:
        if not args.confirm:
            n = count_items(ddb, t)
            print(f"  would delete ~{n:>7} items from {t}")
            total += n
            continue
        n = delete_all_items(ddb, t, key_attributes(ddb, t))
        print(f"  deleted {n:>7} items from {t}")
        total += n
    print(f"\n{'Would delete' if not args.confirm else 'Deleted'} {total} items across {len(plan['WIPE'])} tables.")

    # Published-page buckets (disposable). Media + config buckets are intentionally NOT cleared.
    for label, bucket in (("pages", args.pages_bucket), ("preview", args.preview_bucket)):
        if not bucket:
            continue
        if not args.confirm:
            print(f"  would clear {label} bucket: {bucket}")
        else:
            n = clear_bucket(s3, bucket)
            print(f"  cleared {n} objects from {label} bucket: {bucket}")

    if not args.confirm:
        print("\nDRY RUN — nothing was changed. Re-run with --confirm --backup-bucket <bucket> to execute.")
    else:
        print("\nDone. Next: re-onboard tenants, re-run Stripe Connect OAuth per mode, re-add custom domains,")
        print("and point both Stripe webhook endpoints at prod with both per-mode signing secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
