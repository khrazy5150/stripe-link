#!/usr/bin/env python3
"""One-time (idempotent) backfill of platform-subdomain reservations for pre-existing Sites.

The SubdomainRegistry reserves each Site's `{label}.jbay.uk` label with a sentinel row so the label is
globally unique and permanent. Sites created before the registry existed have no such row, so an
availability check reports their label as free (it isn't). This sweep scans a Sites table and writes the
missing reservation rows. Safe to re-run: reserve() is a conditional put that no-ops when the label is
already owned by the same Site.

Usage:
    PYTHONPATH=src python3 deploy/backfill_subdomain_reservations.py dev   # or: prod
    PYTHONPATH=src python3 deploy/backfill_subdomain_reservations.py dev --dry-run
"""
import argparse
import sys
import time

import boto3
from boto3.dynamodb.conditions import Attr

from stripe_link.repositories.documents import SubdomainRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=["dev", "prod"], help="target environment")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args()

    table_name = f"jb-sites-{args.environment}"
    table = boto3.resource("dynamodb", region_name=args.region).Table(table_name)
    registry = SubdomainRegistry(table_name, table=table)
    now = int(time.time())

    sites, start_key = [], None
    while True:
        kwargs = {"FilterExpression": Attr("SK").begins_with("SITE#")}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        response = table.scan(**kwargs)
        sites.extend(response.get("Items", []))
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break

    print(f"[{table_name}] scanned {len(sites)} site(s)")
    reserved = skipped = conflicts = 0
    for site in sites:
        site_id = site.get("site_id")
        hosting = site.get("hosting") or {}
        hostname = str(hosting.get("platform_hostname") or "")
        label = hostname.split(".")[0] if hostname else ""
        if not label or not site_id:
            skipped += 1
            continue
        owner = registry.owner_of(label)
        if owner == site_id:
            skipped += 1
            continue
        if owner and owner != site_id:
            print(f"  ! CONFLICT '{label}' owned by {owner}, not {site_id} ({hostname}) — left untouched")
            conflicts += 1
            continue
        if args.dry_run:
            print(f"  would reserve '{label}' -> {site_id} ({hostname})")
        else:
            ok = registry.reserve(label, site_id=site_id, tenant_id=str(site.get("tenant_id") or ""), now=now)
            print(f"  reserved '{label}' -> {site_id} ({hostname})" if ok else f"  ! failed to reserve '{label}'")
            if not ok:
                conflicts += 1
                continue
        reserved += 1

    print(f"done: {reserved} reserved, {skipped} already-ok/skipped, {conflicts} conflict(s)")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
