#!/usr/bin/env python3
"""Move business IDENTITY off the user profile and onto the Site that owns it (plans/SITE_AS_BUSINESS_IDENTITY.md §P4).

Carries `business.name`, `business.brands`, and a VERIFIED `business.email`. Not `phone`, `address`,
`timezone` or `shipping_cutoff_hour` — those are operational, read by shipping and the delivery estimate,
and the author has them moving under their own plan rather than riding along with identity (2026-11-03).

The author chose the clean end state: once every tenant has moved, the tenant-level fallback is DELETED
rather than kept as a safety net.

**This script is NOT the gate for that deletion, and saying so here because it was written as if it were.**
A tenant running two businesses gets `ambiguous` forever — which Site owns "Luxe Wellness" is genuinely
unknowable — so "has the migration run everywhere" is a condition that may never become true. The gate is
`deploy/audit_tenant_fallback.py`, which asks the answerable question instead: *if the fields vanished
right now, what would change?* This script is the thing that CLEARS blockers the audit reports; the audit
is what says when there are none left.

**Only migrates where the answer is unambiguous: a tenant with exactly ONE Site carrying an organization.**
That is the same rule `sender_identity.site_organization` uses, and for the same reason — with two
businesses the platform cannot know which one owns "Luxe Wellness", and guessing would put one business's
brand in the other's picker, which is the bug this whole plan exists to close. Ambiguous tenants are
REPORTED for the tenant to assign by hand.

Additive and idempotent. A Site keeps brands it already has; a name it already owns is skipped
case-insensitively; the profile's copy is left alone, because removing the fallback is a separate step
gated on this having run everywhere.

Usage:
    PYTHONPATH=src python3 deploy/migrate_business_identity_to_site.py dev          # dry run, both modes
    PYTHONPATH=src python3 deploy/migrate_business_identity_to_site.py dev --apply
    PYTHONPATH=src python3 deploy/migrate_business_identity_to_site.py prod --mode live --apply
"""
import argparse
import os
import sys

import boto3

from stripe_link.repositories.documents import sites_repository

MODES = ("test", "live")


def _profiles(table_name: str) -> list[dict]:
    """Every user profile carrying business identity worth moving: a name, brands, or a VERIFIED email."""
    table = boto3.resource("dynamodb").Table(table_name)
    found, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            business = item.get("business") or {}
            entry = {
                "tenant_id": str(item.get("tenant_id") or ""),
                "user_id": str(item.get("user_id") or ""),
                "name": str(business.get("name") or "").strip(),
                "brands": [str(b).strip() for b in (business.get("brands") or []) if str(b).strip()],
                # Pending is not verified, so an unconfirmed address is not identity to move.
                "email": (str(business.get("email") or "").strip().lower()
                          if business.get("email_verified") else ""),
                "email_verified_at": business.get("email_verified_at"),
            }
            if entry["name"] or entry["brands"] or entry["email"]:
                found.append(entry)
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


def fill(org: dict, profile: dict) -> tuple[dict, list[str]]:
    """Fill ONLY what the Site has not already said about itself. Returns (organization, what changed).

    Fill-empty-only is the never-clobber guarantee, the same rule `connect_sync.seed_business_identity`
    uses for the Stripe seed: a Site that has stated its own name must not have it overwritten by an older
    account-level value. Provenance is stamped in `organization.sources`, which §P3b added as a carrier and
    this gives its first writer.
    """
    org = dict(org)
    sources = dict(org.get("sources") or {})
    changed = []

    if profile.get("name") and not str(org.get("name") or "").strip():
        org["name"] = profile["name"]
        sources["name"] = "profile"
        changed.append(f"name={profile['name']!r}")

    brands = [str(b).strip() for b in (profile.get("brands") or []) if str(b).strip()]
    if brands:
        existing = [str(b) for b in (org.get("brands") or [])]
        lowered = {b.strip().lower() for b in existing}
        additions = [b for b in brands if b.lower() not in lowered]
        if additions:
            org["brands"] = existing + additions
            sources["brands"] = "profile"
            changed.append(f"brands+={additions}")

    # The VERIFIED address only, and never the pending record: a pending `code_hash` is salted with the
    # TENANT scope, so it could never verify under the Site scope -- carrying it would leave a code that
    # looks live and can never be confirmed.
    #
    # Carrying `email_verified` across is legitimate here and only here: the Site salt exists so one Site's
    # proof cannot cover ANOTHER Site, and this runs only for a tenant with exactly one. The tenant proved
    # they read mail at that address, and there is no second business for the proof to leak into.
    if profile.get("email") and not str(org.get("email") or "").strip():
        org["email"] = profile["email"]
        org["email_verified"] = True
        org["email_verified_at"] = int(profile.get("email_verified_at") or 0) or None
        sources["email"] = "profile"
        changed.append(f"email={profile['email']!r} (verified)")

    if changed:
        org["sources"] = sources
    return org, changed


def migrate(profile: dict, mode: str, *, apply: bool) -> str:
    """Returns one of 'migrated', 'already', 'ambiguous', 'no_site'."""
    tenant_id = profile["tenant_id"]
    sites = sites_repository(mode=mode)
    site = sole_site(sites, tenant_id)
    if site is None:
        named = [s for s in sites.list_for_tenant(tenant_id)
                 if str(((s or {}).get("organization") or {}).get("name") or "").strip()]
        if not named:
            print(f"    [{mode}] no Site with a business name — nothing to migrate INTO")
            return "no_site"
        print(f"    [{mode}] {len(named)} businesses "
              f"({', '.join(s['organization']['name'] for s in named)}) — CANNOT know which owns what; "
              f"assign by hand in Sites -> Edit -> Business")
        return "ambiguous"

    org, changed = fill(site.get("organization") or {}, profile)
    if not changed:
        return "already"
    print(f"    [{mode}] {str(site.get('organization', {}).get('name') or site.get('site_id'))!r}: "
          + ", ".join(changed))
    if apply:
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
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(profiles)} profile(s) carry business identity, "
          f"modes {modes}\n")
    if not profiles:
        print("Nothing to migrate: no profile carries a name, a brand or a verified email. The "
              "tenant-level fallback reads can be removed for this environment.")
        return 0

    tally: dict[str, int] = {}
    for profile in profiles:
        summary = ", ".join(filter(None, [
            f"name={profile['name']!r}" if profile["name"] else "",
            f"brands={profile['brands']}" if profile["brands"] else "",
            f"email={profile['email']!r}" if profile["email"] else "",
        ]))
        print(f"  tenant {profile['tenant_id']}: {summary}")
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
