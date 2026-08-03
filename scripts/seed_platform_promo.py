#!/usr/bin/env python3
"""Seed a special-link promotion into PlatformPlansTable (SK=PROMO#{code}).

A promo grants a free-trial override and/or a Stripe discount when a tenant subscribes via a link that carries
?promo=<code>. Trials are promo-only (the base plan has no trial), so a trial-length promo is how you hand out a
free trial. See plans/SAAS_BILLING_PAYWALL.md.

Examples:
    # A 14-day free-trial link (no discount):
    python scripts/seed_platform_promo.py --mode test --table jb-platform-plans-dev \
        --promo-code TRIAL14 --trial-days 14

    # A "50% off for 3 months" link (creates the Stripe coupon + promotion code via API):
    python scripts/seed_platform_promo.py --mode test --table jb-platform-plans-dev \
        --secret-key sk_test_xxx --promo-code HALFOFF --percent-off 50 --duration repeating --duration-in-months 3

    # Reuse an existing Stripe promotion code:
    python scripts/seed_platform_promo.py --mode test --table jb-platform-plans-dev \
        --promo-code PARTNER --stripe-promotion-code promo_123 --trial-days 30
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.repositories.platform_plans import PlatformPlansRepository  # noqa: E402
from stripe_link.stripe_client import stripe_request  # noqa: E402


def _create_promotion_code(secret_key, code, percent_off, amount_off, duration, duration_in_months):
    coupon_data = {"duration": duration}
    if percent_off:
        coupon_data["percent_off"] = percent_off
    if amount_off:
        coupon_data["amount_off"] = amount_off
        coupon_data["currency"] = "usd"
    if duration == "repeating" and duration_in_months:
        coupon_data["duration_in_months"] = duration_in_months
    coupon = stripe_request("POST", "/coupons", api_key=secret_key, data=coupon_data)
    promotion_code = stripe_request("POST", "/promotion_codes", api_key=secret_key, data={
        "coupon": coupon["id"],
        "code": code,
    })
    return promotion_code["id"]


def main():
    parser = argparse.ArgumentParser(description="Seed a special-link promotion.")
    parser.add_argument("--mode", choices=["test", "live"], required=True)
    parser.add_argument("--table", required=True, help="PlatformPlansTable name (jb-platform-plans-{env}).")
    parser.add_argument("--promo-code", required=True, help="The link token, e.g. TRIAL14 (case-insensitive).")
    parser.add_argument("--plan-key", default="", help="Restrict the promo to a plan (default: any/default plan).")
    parser.add_argument("--trial-days", type=int, default=None, help="Free-trial length this promo grants.")
    parser.add_argument("--expires-at", type=int, default=0, help="Unix time the promo stops working (0 = never).")
    parser.add_argument("--max-redemptions", type=int, default=0, help="0 = unlimited (our own counter; deferred).")
    parser.add_argument("--inactive", action="store_true", help="Seed the promo disabled.")
    # Discount (optional). Either pass an existing --stripe-promotion-code, or create one with the flags below.
    parser.add_argument("--stripe-promotion-code", default="", help="Reuse an existing Stripe promotion code id.")
    parser.add_argument("--secret-key", default=os.environ.get("STRIPE_PLATFORM_SECRET_KEY", ""))
    parser.add_argument("--percent-off", type=float, default=0.0)
    parser.add_argument("--amount-off", type=int, default=0, help="In cents.")
    parser.add_argument("--duration", default="once", choices=["once", "repeating", "forever"])
    parser.add_argument("--duration-in-months", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stripe_promotion_code = args.stripe_promotion_code
    if not stripe_promotion_code and (args.percent_off or args.amount_off):
        if not args.secret_key:
            parser.error("Provide --secret-key to create the Stripe coupon/promotion code, or --stripe-promotion-code.")
        if args.dry_run:
            print(f"[dry-run] would create Stripe coupon ({args.percent_off or args.amount_off}) + promotion code {args.promo_code}")
            stripe_promotion_code = "promo_DRYRUN"
        else:
            stripe_promotion_code = _create_promotion_code(
                args.secret_key, args.promo_code, args.percent_off, args.amount_off,
                args.duration, args.duration_in_months)
            print(f"Created Stripe promotion code {stripe_promotion_code}.")

    promo = {
        "promo_code": args.promo_code.upper(),
        "active": not args.inactive,
    }
    if args.plan_key:
        promo["plan_key"] = args.plan_key
    if args.trial_days is not None:
        promo["trial_days"] = args.trial_days
    if args.expires_at:
        promo["expires_at"] = args.expires_at
    if args.max_redemptions:
        promo["max_redemptions"] = args.max_redemptions
    if stripe_promotion_code:
        promo["stripe_promotion_code"] = stripe_promotion_code

    if args.dry_run:
        print(f"[dry-run] would write promo -> {promo}")
        return

    PlatformPlansRepository(args.table).put_promo(args.mode, promo)
    link_hint = f"?promo={args.promo_code.upper()}"
    print(f"Seeded promo '{args.promo_code.upper()}' into {args.table} [{args.mode}]. Share a subscribe link with {link_hint}.")


if __name__ == "__main__":
    main()
