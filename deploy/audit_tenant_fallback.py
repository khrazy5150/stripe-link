#!/usr/bin/env python3
"""Is the tenant-level business-identity fallback still REACHED? (plans/SITE_AS_BUSINESS_IDENTITY.md §P4)

The author's decision: the fallback is **deleted** once every tenant has moved. The migration script was
written as the measure of "has moved", and that was the wrong gate — for a tenant running two businesses,
which Site owns a given brand is genuinely unknowable, so the migration reports `ambiguous` forever and the
gate never opens.

The answerable question is narrower: **if `UserProfile.business.{name,email,brands}` vanished right now,
what would change?** Nothing else about P4 needs deciding; this is the whole decision.

Read-only. Touches no document. Run it per environment and read the verdict:

    PYTHONPATH=src python3 deploy/audit_tenant_fallback.py dev
    PYTHONPATH=src python3 deploy/audit_tenant_fallback.py prod

Three independent findings, because the three fields are deleted for three different reasons:

1. **NAME** — reached by a page whose Site has no `organization.name`, and by a page attached to no Site at
   all (`resolve_business_name` → `preferences.business_name` → the owner's own name). Deleting it while
   either exists re-brands a live page after a person.
2. **EMAIL** — reached whenever a Site has no VERIFIED address. The fall-through is the signup email, which
   survives (it is on the profile, not in the `business` block), so this degrades a deliberate choice
   rather than breaking delivery — but it IS a change to where customer replies land.
3. **BRANDS** — reached by the page builder's picker for any brand not on the page's Site. Deleting it
   empties a dropdown; the data itself is untouched either way.
"""
import argparse
import os
import sys

import boto3


def _scan(table_name: str, projection: str | None = None) -> list[dict]:
    table = boto3.resource("dynamodb").Table(table_name)
    rows, kwargs = [], {"ProjectionExpression": projection} if projection else {}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def blockers_for(profile: dict, sites: list[dict], pages: list[dict]) -> dict[str, list[str]]:
    """What still READS each field of this tenant's `business` block. Pure, so it can be tested.

    `{field: [reasons]}`, empty list meaning nothing reaches it. The IO lives in `audit`; this is the
    judgement, and the deletion decision rests on it being right — a wrong answer here green-lights a
    regression on a live page.
    """
    business = profile.get("business") or {}
    name = str(business.get("name") or "").strip()
    brands = [str(b) for b in (business.get("brands") or []) if str(b).strip()]
    verified_email = str(business.get("email") or "").strip() if business.get("email_verified") else ""
    found: dict[str, list[str]] = {"name": [], "email": [], "brands": []}

    if name:
        for site in sites:
            if not str((site.get("organization") or {}).get("name") or "").strip():
                found["name"].append(f"Site {site.get('site_id') or site.get('SK')} has no business name")
        for page in pages:
            if not str(page.get("site_id") or "").strip():
                found["name"].append(f"page {page.get('page_id') or page.get('SK')} is attached to no Site")

    if verified_email:
        for site in sites:
            if not (site.get("organization") or {}).get("email_verified"):
                found["email"].append(
                    f"Site {site.get('site_id') or site.get('SK')} has no verified address")

    if brands:
        owned = {str(b).strip().lower()
                 for site in sites for b in ((site.get("organization") or {}).get("brands") or [])}
        missing = [b for b in brands if b.strip().lower() not in owned]
        if missing:
            found["brands"].append(f"{missing} on no Site")
    return found


def audit(environment: str) -> int:
    prefix = f"jb-{{}}-{environment}"
    profiles = _scan(prefix.format("user-profiles"))
    sites = _scan(prefix.format("sites"))
    pages = _scan(prefix.format("pages"))

    by_tenant: dict[str, list[dict]] = {}
    for row in sites:
        if not str(row.get("SK") or "").startswith("SITE#"):
            continue          # SUBDOMAIN#... reservation rows share this table
        by_tenant.setdefault(str(row.get("PK") or "").removeprefix("TENANT#"), []).append(row)

    pages_by_tenant: dict[str, list[dict]] = {}
    for row in pages:
        if not str(row.get("SK") or "").startswith("PAGE#"):
            continue
        pages_by_tenant.setdefault(str(row.get("PK") or "").removeprefix("TENANT#"), []).append(row)

    print(f"=== {environment}: {len(profiles)} profile(s), "
          f"{sum(len(v) for v in by_tenant.values())} Site row(s), "
          f"{sum(len(v) for v in pages_by_tenant.values())} page row(s)\n")

    total: dict[str, list[str]] = {"name": [], "email": [], "brands": []}
    for profile in profiles:
        tenant_id = str(profile.get("tenant_id") or "")
        business = profile.get("business") or {}
        states = [f"name={str(business.get('name') or '-')!r}",
                  f"brands={[str(b) for b in (business.get('brands') or [])] or '-'}",
                  f"verified_email={(str(business.get('email') or '') if business.get('email_verified') else '-')!r}"]
        if business.get("name") or business.get("brands") or business.get("email_verified"):
            print(f"  tenant {tenant_id}\n    profile says: {' '.join(states)}")
            found = blockers_for(profile, by_tenant.get(tenant_id, []),
                                 pages_by_tenant.get(tenant_id, []))
            for field, reasons in found.items():
                if reasons:
                    total[field].extend(f"{tenant_id}: {r}" for r in reasons)
                    print(f"    {field.upper():6} blocked: {reasons[0]}"
                          f"{f' (+{len(reasons) - 1} more)' if len(reasons) > 1 else ''}")
            print()

    print("=" * 78)
    for field, reasons in total.items():
        if reasons:
            print(f"  {field.upper():6} NOT SAFE to delete:")
            for line in reasons[:8]:
                print(f"           {line}")
            if len(reasons) > 8:
                print(f"           … and {len(reasons) - 8} more")
        else:
            print(f"  {field.upper():6} safe to delete in {environment}")
    print("=" * 78)
    print("\nThis is ONE environment. The fallback is shared code, so it may only be deleted once every\n"
          "environment says safe — dev AND prod.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", choices=["dev", "prod"])
    args = parser.parse_args()
    os.environ.setdefault("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-west-2"))
    return audit(args.environment)


if __name__ == "__main__":
    sys.exit(main())
