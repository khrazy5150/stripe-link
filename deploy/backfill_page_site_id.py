#!/usr/bin/env python3
"""One-time (idempotent) backfill of the page->Site reverse edge (plans/SITE_AS_BUSINESS_IDENTITY.md §3.1).

Every page created before `page.site_id` existed has none, so a consumer asking "whose business is this
page?" gets no answer and falls back — which is the bug this edge exists to fix. From here on the Site save
path keeps the edge current (`handlers/sites._reconcile_page_site_ids`); this walks the Sites that already
exist and stamps what they already route.

**`Site.pages` is the source of truth and is never written here.** This sweep only propagates it. If the two
ever disagree, the Site wins and re-running this fixes the page.

Runs PER MODE, because a Site lives at `SITE#<mode>#<site_id>` and a page at `PAGE#<mode>#<page_id>` — a
sweep that ignored the mode would stamp a live page with a test Site's id. Both modes are swept unless one
is named.

Usage:
    PYTHONPATH=src python3 deploy/backfill_page_site_id.py dev                     # dry-run, both modes
    PYTHONPATH=src python3 deploy/backfill_page_site_id.py dev --apply
    PYTHONPATH=src python3 deploy/backfill_page_site_id.py prod --mode live --apply
    PYTHONPATH=src python3 deploy/backfill_page_site_id.py dev --tenant t_abc --apply
"""
import argparse
import os
import sys

import boto3

from stripe_link.repositories.documents import pages_repository, sites_repository

MODES = ("test", "live")


def _tenant_ids(table_name: str) -> list[str]:
    """Every tenant with at least one Site, via a projection-only scan of the Sites table."""
    table = boto3.resource("dynamodb").Table(table_name)
    found, kwargs = set(), {"ProjectionExpression": "PK"}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            pk = str(item.get("PK") or "")
            if pk.startswith("TENANT#"):
                found.add(pk.split("#", 1)[1])
        if not page.get("LastEvaluatedKey"):
            return sorted(found)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def sweep(tenant_id: str, mode: str, *, apply: bool) -> tuple[int, int]:
    """Returns (stamped, already_correct). A page the Site no longer routes is NOT cleared here: this
    backfill adds the edge it can prove, and clearing on absence would need the full route map of every
    Site to be readable at once — a failure there would silently detach pages."""
    sites = sites_repository(mode=mode)
    pages = pages_repository(mode=mode)
    stamped = correct = 0
    for site in sites.list_for_tenant(tenant_id):
        site_id = str(site.get("site_id") or "")
        if not site_id:
            continue
        for entry in (site.get("pages") or {}).values():
            page_id = str(entry.get("page_id") or "")
            if not page_id:
                continue
            page = pages.get(tenant_id, page_id)
            if not page:
                print(f"    [{mode}] {page_id}: routed by {site_id} but the page is GONE — skipped")
                continue
            if str(page.get("site_id") or "") == site_id:
                correct += 1
                continue
            print(f"    [{mode}] {page_id}: {page.get('site_id') or '(none)'} -> {site_id}")
            if apply:
                pages.set_site_id(tenant_id, page_id, site_id)
            stamped += 1
    return stamped, correct


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", choices=["dev", "prod"])
    parser.add_argument("--mode", choices=list(MODES), help="one Stripe mode; both when omitted")
    parser.add_argument("--tenant", help="limit to one tenant")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = parser.parse_args()

    prefix = f"jb-{{}}-{args.environment}"
    os.environ.setdefault("SITES_TABLE", prefix.format("sites"))
    os.environ.setdefault("PAGES_TABLE", prefix.format("pages"))

    tenants = [args.tenant] if args.tenant else _tenant_ids(os.environ["SITES_TABLE"])
    modes = [args.mode] if args.mode else list(MODES)
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(tenants)} tenant(s), modes {modes}\n")

    total_stamped = total_correct = 0
    for tenant_id in tenants:
        print(f"  tenant {tenant_id}")
        for mode in modes:
            stamped, correct = sweep(tenant_id, mode, apply=args.apply)
            total_stamped += stamped
            total_correct += correct
    print(f"\n{'stamped' if args.apply else 'would stamp'}: {total_stamped}   already correct: {total_correct}")
    if not args.apply and total_stamped:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
