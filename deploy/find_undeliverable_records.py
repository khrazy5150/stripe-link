#!/usr/bin/env python3
"""Find stored records whose email address can never receive mail.

Written after 5,678 Delivery Status Notifications piled up in the platform's support mailbox
(2026-11-04). The addresses were reserved-domain placeholders — `jane@example.com`, `sam@example.com` —
sitting in production records, and SEVERAL unrelated flows mailed them: a webinar registration
confirmation and a subscription cancellation were the two seen. Every send cost SES 840 minutes of
retries and returned a DSN; one day's traffic was 201 sent / 153 bounced, a 76% bounce rate.

`mailer.send_email` now refuses these at the choke point, so they can no longer generate mail whatever
touches them. This finds the RECORDS, so they can be corrected or removed rather than left to be refused
forever.

READ-ONLY. It holds no writer: no put, no update, no delete, no --apply.

    PYTHONPATH=src python3 deploy/find_undeliverable_records.py prod
    PYTHONPATH=src python3 deploy/find_undeliverable_records.py dev
"""
import argparse
import collections
import json
import re
import sys

import boto3

# The tables that hold an address we might MAIL. Deliberately not every table: a reserved address in a
# log or an analytics row is noise, not a sender.
TABLES = ("orders", "customers", "carts", "lead-capture", "reviews", "invoices",
          "appointments", "notifications", "shipments")

ADDRESS = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
RESERVED = re.compile(r"@(?:[\w.-]+\.)?(?:example\.(?:com|net|org|edu)|test|invalid|localhost|local)$",
                      re.IGNORECASE)


def scan(table_name: str) -> list[dict]:
    table = boto3.resource("dynamodb").Table(table_name)
    rows, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", choices=["dev", "prod"])
    args = parser.parse_args()

    grand = collections.Counter()
    print(f"=== {args.environment}: records carrying an address that can never receive ===\n")
    for short in TABLES:
        name = f"jb-{short}-{args.environment}"
        try:
            rows = scan(name)
        except Exception as exc:  # noqa: BLE001 - a table that does not exist is not an error here
            print(f"  {name:28} (skipped: {type(exc).__name__})")
            continue

        hits: dict[str, list[str]] = collections.defaultdict(list)
        for row in rows:
            blob = json.dumps(row, default=str)
            for address in set(ADDRESS.findall(blob)):
                if RESERVED.search(address):
                    key = str(row.get("SK") or row.get("PK") or "?")
                    hits[address.lower()].append(key)
        total = sum(len(v) for v in hits.values())
        grand[name] = total
        print(f"  {name:28} {len(rows):>5} rows | {total:>4} reserved-address record(s)")
        for address, keys in sorted(hits.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"      {len(keys):>4}  {address:34} e.g. {keys[0][:46]}")

    found = sum(grand.values())
    print("\n" + "=" * 74)
    if found:
        print(f"  {found} record(s) carry an undeliverable address.")
        print("  They can no longer generate mail — `send_email` refuses them — but every flow that")
        print("  touches one now logs a refusal. Correct the address or delete the record to silence it.")
    else:
        print(f"  Nothing found in {args.environment}.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
