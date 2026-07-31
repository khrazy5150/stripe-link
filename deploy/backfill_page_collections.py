#!/usr/bin/env python3
"""One-time (idempotent) migration of inline catalog_grids to Collections (plans/SITE_COLLECTIONS.md P1d).

Storefront/category pages built before the Collection entity existed carry their grid config inline on the
catalog_grid section (scope="all" / category / curated items[]). This sweep converts each such grid into a
first-class Collection doc and rewrites the section to a `collection_id` embed, so the collection-native builder
(P1e) and the publisher resolve them uniformly. The Collection is written FIRST, then the changed page, so the
embed always resolves. Safe to re-run: a grid that already has a collection_id is skipped.

Discovers every tenant with an un-migrated grid via a cross-tenant scan of the Pages table, then runs the
per-tenant backfill. Pass a tenant_id to limit the sweep to one tenant.

Usage:
    PYTHONPATH=src python3 deploy/backfill_page_collections.py dev            # dry-run every tenant
    PYTHONPATH=src python3 deploy/backfill_page_collections.py dev --apply     # write
    PYTHONPATH=src python3 deploy/backfill_page_collections.py dev --tenant t_abc --apply
"""
import argparse
import os
import secrets
import sys

import boto3

from stripe_link.repositories.documents import (
    collections_repository,
    pages_repository,
    sites_repository,
)
from stripe_link.runtime.publishing import backfill_page_collections

_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _new_collection_id() -> str:  # mirrors src/handlers/collections.py so IDs are indistinguishable
    return "coll_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=["dev", "prod"], help="target environment")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--tenant", default="", help="limit to one tenant_id (default: every tenant with a grid)")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()

    env = args.environment
    # The repo constructors read table names from env vars — set them so this runs outside Lambda.
    os.environ["PAGES_TABLE"] = f"jb-pages-{env}"
    os.environ["SITES_TABLE"] = f"jb-sites-{env}"
    os.environ["COLLECTIONS_TABLE"] = f"jb-collections-{env}"
    resource = boto3.resource("dynamodb", region_name=args.region)

    pages = pages_repository(table=resource.Table(f"jb-pages-{env}"))
    sites = sites_repository(table=resource.Table(f"jb-sites-{env}"))
    collections = collections_repository(table=resource.Table(f"jb-collections-{env}"))

    if args.tenant:
        tenants = [args.tenant]
    else:
        tenants = sorted({
            str(page.get("tenant_id"))
            for page in pages.scan_type()
            if page.get("tenant_id")
            and any(isinstance(s, dict) and s.get("type") == "catalog_grid" and not s.get("collection_id")
                    for s in (page.get("sections") or []))
        })

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] jb-pages-{env}: {len(tenants)} tenant(s) with un-migrated grid(s)")
    total_pages = total_collections = 0
    for tenant_id in tenants:
        summary = backfill_page_collections(
            pages, sites, collections, tenant_id,
            id_factory=_new_collection_id, dry_run=not args.apply,
        )
        total_pages += summary["pages_migrated"]
        total_collections += summary["collections_created"]
        for coll in summary["collections"]:
            print(f"  {tenant_id}  {coll['page_id']} -> {coll['collection_id']} "
                  f"(rule={coll['rule']}, members={coll['members']})")

    verb = "migrated" if args.apply else "would migrate"
    print(f"done: {verb} {total_pages} page(s), {total_collections} collection(s)"
          + ("" if args.apply else "  — re-run with --apply to write"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
