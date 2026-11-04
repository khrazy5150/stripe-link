#!/usr/bin/env python3
"""Move `UserProfile.business.brands` onto the Site that owns them (plans/SITE_AS_BUSINESS_IDENTITY.md §P4).

Brands belong to the business that owns them, and a business is a Site (§P3b). The tenant-wide list is the
last piece of business IDENTITY still on the user profile, and it is read as a fallback by the page
builder's brand picker — so it cannot simply be deleted: a tenant whose brands lived only there would open
the picker and find it empty.

**Only migrates where the answer is unambiguous: a tenant with exactly ONE Site carrying an organization.**
That is the same rule `sender_identity.site_organization` uses, and for the same reason — with two
businesses the platform cannot know which one owns "Luxe Wellness", and guessing would put one business's
brand in the other's picker, which is the bug this whole plan exists to close. Ambiguous tenants are
REPORTED for the tenant to assign by hand.

Additive and idempotent. A Site keeps brands it already has; a name it already owns is skipped
case-insensitively; the profile's copy is left alone, because removing the fallback is a separate step
gated on this having run everywhere.

Usage:
    PYTHONPATH=src python3 deploy/migrate_profile_brands_to_site.py dev            # dry run, both modes
    PYTHONPATH=src python3 deploy/migrate_profile_brands_to_site.py dev --apply
    PYTHONPATH=src python3 deploy/migrate_profile_brands_to_site.py prod --mode live --apply
"""
import argparse
import os
import sys

import boto3

from stripe_link.repositories.documents import sites_repository

MODES = ("test", "live")


def _profiles(table_name: str) -> list[dict]:
    """Every user profile that carries at least one brand."""
    table = boto3.resource("dynamodb").Table(table_name)
    found, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            brands = [str(b).strip() for b in ((item.get("business") or {}).get("brands") or [])
                      if str(b).strip()]
            if brands:
                found.append({"tenant_id": str(item.get("tenant_id") or ""),
                              "user_id": str(item.get("user_id") or ""), "brands": brands})
        if not page.get("LastEvaluatedKey"):
            return found
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def sole_site(sites, tenant_id: str):
    """The tenant's one Site carrying a business identity, or None when there is no single answer.

    A Site with no `organization.name` is not a candidate: nobody has told us it is a business yet, so it
    cannot be the one that owns a brand.
    """
    named = [s for s in sites.list_for_tenant(tenant_id)
             if str(((s or {}).get("organization") or {}).get("name") or "").strip()]
    return named[0] if len(named) == 1 else None


def migrate(profile: dict, mode: str, *, apply: bool) -> str:
    """Returns one of 'migrated', 'already', 'ambiguous', 'no_site'."""
    tenant_id, brands = profile["tenant_id"], profile["brands"]
    sites = sites_repository(mode=mode)
    site = sole_site(sites, tenant_id)
    if site is None:
        named = [s for s in sites.list_for_tenant(tenant_id)
                 if str(((s or {}).get("organization") or {}).get("name") or "").strip()]
        if not named:
            print(f"    [{mode}] {tenant_id}: no Site with a business name — nothing to migrate INTO")
            return "no_site"
        print(f"    [{mode}] {tenant_id}: {len(named)} businesses "
              f"({', '.join(s['organization']['name'] for s in named)}) — CANNOT know which owns "
              f"{brands}; assign by hand in Sites -> Edit -> Business")
        return "ambiguous"

    org = dict(site.get("organization") or {})
    existing = [str(b) for b in (org.get("brands") or [])]
    lowered = {b.strip().lower() for b in existing}
    additions = [b for b in brands if b.lower() not in lowered]
    if not additions:
        return "already"
    print(f"    [{mode}] {tenant_id}: {org.get('name')!r} += {additions}")
    if apply:
        org["brands"] = existing + additions
        sites.put({**site, "organization": org})
    return "migrated"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", choices=["dev", "prod"])
    parser.add_argument("--mode", choices=list(MODES), help="one Stripe mode; both when omitted")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = parser.parse_args()

    prefix = f"jb-{{}}-{args.environment}"
    os.environ.setdefault("SITES_TABLE", prefix.format("sites"))
    profiles_table = prefix.format("user-profiles")

    profiles = _profiles(profiles_table)
    modes = [args.mode] if args.mode else list(MODES)
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(profiles)} profile(s) carry brands, "
          f"modes {modes}\n")
    if not profiles:
        print("Nothing to migrate: no profile carries a brand. The fallback read in the page builder can "
              "be removed for this environment.")
        return 0

    tally: dict[str, int] = {}
    for profile in profiles:
        print(f"  tenant {profile['tenant_id']}: {profile['brands']}")
        for mode in modes:
            # ONE call per (profile, mode). An earlier draft called `migrate` twice here -- once applying
            # and once not -- which on a real run would have written, then reported the dry-run answer.
            outcome = migrate(profile, mode, apply=args.apply)
            tally[outcome] = tally.get(outcome, 0) + 1
    print("\n" + (", ".join(f"{k}: {v}" for k, v in sorted(tally.items())) or "nothing to do"))
    if tally.get("ambiguous"):
        print(f"{tally['ambiguous']} tenant(s) run more than one business: their brands are NOT moved, "
              f"because the platform cannot know which business owns which brand.")
    if not args.apply:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
