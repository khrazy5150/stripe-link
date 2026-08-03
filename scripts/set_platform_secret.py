#!/usr/bin/env python3
"""Merge a single key into the PLATFORM Stripe secret in AWS Secrets Manager.

stripe-link reads its platform Stripe secret (sk_*, whsec_*) from ONE Secrets Manager secret referenced by the
StripePlatformSecretArn deploy param (name: stripe-cart/{env}/platform/stripe — a legacy name; it IS stripe-link's
platform secret). This tool sets ONE key in that secret's JSON payload while preserving every other key — the safe
way to add e.g. the platform-billing webhook signing secret. The value is NEVER printed (fingerprint only). See
plans/SAAS_BILLING_PAYWALL.md.

Examples:
    # Add the platform-billing TEST webhook signing secret (prompts for the value, hidden input):
    python scripts/set_platform_secret.py --env dev --webhook platform_billing --mode test

    # Pipe the value in (e.g. from a password manager) instead of prompting:
    echo "whsec_xxx" | python scripts/set_platform_secret.py --env dev --webhook platform_billing --mode test --stdin

    # Explicit payload key, and preview without writing:
    python scripts/set_platform_secret.py --env prod --key whsec_platform_billing_live --dry-run
"""
import argparse
import getpass
import hashlib
import json
import sys


def _fingerprint(value):
    if not value:
        return "MISSING"
    return f"{value[:10]}…{value[-4:]} sha256:{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def main():
    p = argparse.ArgumentParser(description="Merge a key into the platform Stripe secret (Secrets Manager).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--env", choices=["dev", "prod"], help="Convenience: secret id stripe-cart/{env}/platform/stripe.")
    src.add_argument("--secret-id", help="Explicit Secrets Manager secret id or ARN (overrides --env).")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--key", help="JSON payload key to set, e.g. whsec_platform_billing_test or sk_test.")
    p.add_argument("--webhook", help="Webhook kind (e.g. platform_billing); with --mode, sets key whsec_{kind}_{mode}.")
    p.add_argument("--mode", choices=["test", "live"], help="Stripe mode, used with --webhook.")
    p.add_argument("--stdin", action="store_true", help="Read the value from stdin instead of a hidden prompt.")
    p.add_argument("--force", action="store_true", help="Overwrite an existing key without confirmation.")
    p.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    args = p.parse_args()

    secret_id = args.secret_id or (f"stripe-cart/{args.env}/platform/stripe" if args.env else None)
    if not secret_id:
        p.error("Provide --env dev|prod or --secret-id.")

    key = args.key
    if not key:
        if not (args.webhook and args.mode):
            p.error("Provide --key, or both --webhook <kind> and --mode <test|live>.")
        key = f"whsec_{args.webhook}_{args.mode}"

    value = (sys.stdin.readline() if args.stdin else getpass.getpass(f"Value for '{key}' (hidden): ")).strip()
    if not value:
        p.error("Empty value — nothing to set.")

    import boto3

    client = boto3.client("secretsmanager", region_name=args.region)
    payload = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])

    print(f"secret:       {secret_id}")
    print(f"keys before:  {sorted(payload.keys())}")
    existing = payload.get(key)
    if existing:
        print(f"'{key}' currently = {_fingerprint(existing)}")
        if not args.force and not args.dry_run:
            if input(f"Overwrite '{key}'? [y/N] ").strip().lower() != "y":
                print("Aborted — no change written.")
                return
    print(f"setting '{key}' = {_fingerprint(value)}")

    if args.dry_run:
        print("[dry-run] not written.")
        return

    payload[key] = value
    client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(payload))
    after = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    print(f"keys after:   {sorted(after.keys())}")
    print(f"'{key}' now = {_fingerprint(after.get(key))}")
    print("Done. stripe-link picks it up on the next secret cache refresh (no redeploy).")


if __name__ == "__main__":
    main()
