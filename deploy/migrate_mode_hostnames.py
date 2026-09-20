#!/usr/bin/env python3
"""Give every TEST-mode Site its own hostname (`{label}-test`), and clean up the row it used to share.

Why (found on prod 2026-09-20): a Site is stored twice -- `SITE#live#…` and `SITE#test#…` -- but the edge
index keeps ONE row per hostname. Both modes wrote that row, so the last publish won; once archiving stopped
serving, archiving either mode took the other off the air.

Run dry first. Nothing is written without --apply.

    python3 deploy/migrate_mode_hostnames.py --env dev
    python3 deploy/migrate_mode_hostnames.py --env dev --apply

TWO things this deliberately does NOT do:

  * It does not record the old hostname as `retired_hostnames`. That machinery writes a 301 from the old host
    to the new one -- and a test Site's old host IS its live twin's host, so the redirect would point the LIVE
    site at the sandbox. The old host is not being vacated; it belongs to the other mode.
  * It does not touch live-mode Sites. Their hostname is already correct and is the one customers have.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from handlers.sites import TEST_HOST_SUFFIX, platform_hostname_for, platform_label

DESER, SER = TypeDeserializer(), TypeSerializer()
HOSTING_DOMAIN = {"prod": "jbay.uk", "dev": "jbay.be"}


def rows(client, table):
    paginator = client.get_paginator("scan")
    for page in paginator.paginate(TableName=table):
        for item in page.get("Items", []):
            yield item, {k: DESER.deserialize(v) for k, v in item.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, choices=["dev", "prod"])
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    client = boto3.client("dynamodb", region_name=args.region)
    sites_table = f"jb-sites-{args.env}"
    domain = HOSTING_DOMAIN[args.env]

    planned = []
    for raw, site in rows(client, sites_table):
        if "#test#" not in str(site.get("SK") or ""):
            continue
        current = str((site.get("hosting") or {}).get("platform_hostname") or "")
        if not current:
            continue
        wanted = platform_hostname_for(platform_label(current), domain, "test")
        if wanted and wanted != current:
            planned.append((raw, site, current, wanted))

    if not planned:
        print("Nothing to migrate — every test-mode Site already has its own hostname.")
        return

    print(f"{sites_table}: {len(planned)} test-mode Site(s) to re-host\n")
    for _, site, current, wanted in planned:
        print(f"  {site.get('site_id')}  {current}  ->  {wanted}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return

    for raw, site, _current, wanted in planned:
        hosting = dict(site.get("hosting") or {})
        hosting["platform_hostname"] = wanted
        # Deliberately NOT adding the old host to retired_hostnames -- see the module docstring.
        client.update_item(
            TableName=sites_table,
            Key={"PK": raw["PK"], "SK": raw["SK"]},
            UpdateExpression="SET hosting = :h",
            ExpressionAttributeValues={":h": SER.serialize(hosting)},
        )
        print(f"  updated {site.get('site_id')} -> {wanted}")

    print("\nDone. Re-publish each affected Site's pages so the edge index picks up the new hostname;")
    print("the OLD row still carries whatever the other mode last wrote, which is now correct for it.")


if __name__ == "__main__":
    main()
