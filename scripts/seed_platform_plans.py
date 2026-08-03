#!/usr/bin/env python3
"""Seed the platform->tenant SaaS plan catalog (PlatformPlansTable).

Creates the Stripe Product + recurring Price on the PLATFORM account via the API (so you never touch the Stripe
dashboard), then writes the plan row + config (default plan + exempt bypass list) into the table for the given
billing mode. Idempotent-ish: pass --price-id to reuse an existing Price instead of creating a new one.

Usage (dry-run prints what it would do):
    python scripts/seed_platform_plans.py --mode test --table jb-platform-plans-dev \
        --secret-key sk_test_xxx --exempt-email you@example.com --dry-run

    # For real (creates the Stripe Product+Price and writes the table):
    python scripts/seed_platform_plans.py --mode test --table jb-platform-plans-dev \
        --secret-key sk_test_xxx --exempt-email you@example.com

Prices are IMMUTABLE: to raise the price later, run scripts/migrate_platform_price.py (creates a NEW Price and
optionally migrates existing subscribers at cycle end). See plans/SAAS_BILLING_PAYWALL.md.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.repositories.platform_plans import PlatformPlansRepository  # noqa: E402
from stripe_link.stripe_client import stripe_request  # noqa: E402


def _create_product_and_price(secret_key, amount_cents, interval, label):
    product = stripe_request("POST", "/products", api_key=secret_key, data={"name": label})
    product_id = product["id"]
    price = stripe_request("POST", "/prices", api_key=secret_key, data={
        "product": product_id,
        "unit_amount": amount_cents,
        "currency": "usd",
        "recurring": {"interval": interval},
    })
    return product_id, price["id"]


def main():
    parser = argparse.ArgumentParser(description="Seed the platform SaaS plan catalog.")
    parser.add_argument("--mode", choices=["test", "live"], required=True, help="Billing mode (which plan set).")
    parser.add_argument("--table", required=True, help="PlatformPlansTable name (jb-platform-plans-{env}).")
    parser.add_argument("--secret-key", default=os.environ.get("STRIPE_PLATFORM_SECRET_KEY", ""),
                        help="Platform Stripe secret key (needed only when creating the Product/Price).")
    parser.add_argument("--price-id", default="", help="Reuse an existing Stripe Price id instead of creating one.")
    parser.add_argument("--product-id", default="", help="Existing Product id (when reusing a price).")
    parser.add_argument("--plan-key", default="basic")
    parser.add_argument("--label", default="Bay Pass")
    parser.add_argument("--amount", type=int, default=958, help="Monthly amount in cents (default 958 = $9.58).")
    parser.add_argument("--interval", default="month", choices=["month", "year"])
    parser.add_argument("--trial-days", type=int, default=14)
    parser.add_argument("--fee-tier", default="basic")
    parser.add_argument("--exempt-email", action="append", default=[], help="Repeatable. Comped tenant emails.")
    parser.add_argument("--exempt-tenant-id", action="append", default=[], help="Repeatable. Comped tenant ids.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    price_id, product_id = args.price_id, args.product_id
    if not price_id:
        if not args.secret_key:
            parser.error("Provide --secret-key to create the Stripe Product/Price, or pass --price-id to reuse one.")
        if args.dry_run:
            print(f"[dry-run] would create Stripe Product '{args.label}' + {args.interval}ly "
                  f"Price {args.amount}c on the platform account.")
            price_id, product_id = "price_DRYRUN", "prod_DRYRUN"
        else:
            product_id, price_id = _create_product_and_price(args.secret_key, args.amount, args.interval, args.label)
            print(f"Created Stripe Product {product_id} + Price {price_id}.")

    plan = {
        "plan_key": args.plan_key,
        "label": args.label,
        "monthly_amount": args.amount,
        "price_id": price_id,
        "product_id": product_id,
        "trial_days": args.trial_days,
        "active": True,
        "highlight": True,
        "sort_order": 1,
        "fee_tier": args.fee_tier,
        "features": [],
    }
    config = {
        "default_plan_key": args.plan_key,
        "exempt_emails": args.exempt_email,
        "exempt_tenant_ids": args.exempt_tenant_id,
    }

    if args.dry_run:
        print(f"[dry-run] would write plan -> {plan}")
        print(f"[dry-run] would write config -> {config}")
        return

    repo = PlatformPlansRepository(args.table)
    repo.put_plan(args.mode, plan)
    repo.put_config(args.mode, config)
    print(f"Seeded plan '{args.plan_key}' (price {price_id}) + config into {args.table} [{args.mode}].")


if __name__ == "__main__":
    main()
