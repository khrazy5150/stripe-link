"""Which orders still owe the ledger a real Stripe fee.

Every sale records an ESTIMATED Stripe fee at the moment it is written -- the configured rate, computed
locally -- and most are corrected seconds later by the webhook, which reads the charge's balance
transaction. Upsells are not: they are PaymentIntents we create ourselves, so no webhook follows them, and
the balance transaction is not attached yet when the handler asks. Measured on a real funnel (2026-10-04):

    [fees] upsell ..._upsell_1 kept its estimate; stripe returned []
    [fees] upsell ..._upsell_2 kept its estimate; stripe returned []

Empty, not partial -- and empty again on an immediate retry. Nothing asked inside the buyer's request can
fix that, so the correction has to happen later, which is what this module decides.

**Why it matters, measured rather than argued.** The same funnel paid with a Canadian Visa, and Stripe
charges an extra 1.5% on a foreign-issued card:

    order       amount   recorded   actual   drift
    main         18564        847      847      +0   <- webhook trued it up
    upsell_1       900         57       70     +13
    upsell_2      1786         82      109     +27

Forty cents on twenty-seven dollars, one-directional, understating the tenant's cost. Every earlier run
matched exactly because the cards were US-issued and the estimate is right for those -- which is precisely
why this went unnoticed: an estimate is a plausible number, and plausible is indistinguishable from true
until something makes it say which it is.

`fees_source` is that something, and it is also the boundary this sweep works within. Orders written
before the field existed do not carry it and are never selected -- not a cutoff anyone has to maintain,
just the honest consequence of only correcting what announced itself as uncorrected.
"""
from __future__ import annotations

import os
from typing import Any

ESTIMATE = "estimate"
SETTLED = "balance_transaction"

# MEASURED, not guessed. Two real upsell charges were polled until their balance transaction became
# readable: 92s and 101s, both landing on the same ten-second tick, so the true delay is somewhere between
# ~82s and ~101s (2026-10-04). That one number closed every open timing question in this file -- including
# why no synchronous true-up could ever work, and why `payment_intent.succeeded`, which arrives about a
# second after the charge, is ninety seconds too early.
#
# 180 is that measurement plus room for a slower day. The author's call, deliberately above the evidence:
# tightening to 120 waits on production measurements rather than two test-mode charges. Asking early costs
# a wasted Stripe call and the next pass gets it anyway, so the conservative direction is the cheap one.
#
# OVERRIDABLE, because the honest way to tighten it is an experiment rather than an argument: drop the
# gate below the suspected delay for a while and read the `NOT YET readable` lines, which are the only
# direct evidence of a FLOOR the sweep can produce. A code constant would make that a commit-deploy-revert
# cycle with a test to loosen; an env var makes it a setting, and the DEFAULT is still the committed 180
# that every test asserts.
MIN_AGE_SECONDS = int(os.environ.get("FEE_SETTLE_MIN_AGE_SECONDS") or 180)
# ...and far enough back to cover a weekend of failed sweeps, but not so far that a permanently unsettled
# charge is re-asked forever. A charge still estimated after a week is a thing to look at, not to retry.
MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _whole(value: Any) -> int:
    """Cents, tolerating the `Decimal` a stored document hands back (`feedback_decimal_from_dynamo`)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fees_of(order: dict[str, Any] | None) -> dict[str, Any]:
    fees = (order or {}).get("fees")
    return fees if isinstance(fees, dict) else {}


def charge_reference(order: dict[str, Any] | None) -> tuple[str, str] | None:
    """How to reach this order's charge at Stripe: by its PaymentIntent, or by the invoice that paid it.

    PaymentIntent first, because it is the direct route and every checkout order has one.

    The invoice fallback is not a nicety. A subscription cycle invoice does not always carry a
    payment_intent, and `order_record_from_invoice` OMITS the field when it is absent -- it must, since
    that field is a GSI key and an empty string fails the entire write (setting it blindly took down
    every renewal on prod, 2026-09-22). Requiring it here meant such an order could never be trued up:
    its Stripe fee stayed our rounded-UP estimate forever, and once Stripe settled the charge the ledger
    audit reported the one-cent gap every five minutes, permanently, with no action that could resolve
    it. Found 2026-10-19 from a renewal that had been alarming since the 18th.

    Returns `(kind, id)` where kind is "payment_intent" or "invoice", or None when the order names
    neither and genuinely cannot be asked about.
    """
    order = order or {}
    payment_intent = str(order.get("payment_intent_id") or "").strip()
    if payment_intent:
        return ("payment_intent", payment_intent)
    invoice_id = str(order.get("invoice_id") or "").strip()
    if invoice_id:
        return ("invoice", invoice_id)
    return None


def due(order: dict[str, Any] | None, now: int, *,
        min_age_seconds: int = MIN_AGE_SECONDS,
        max_age_seconds: int = MAX_AGE_SECONDS) -> bool:
    """Whether this order should be re-asked. Four conditions, each of which has a reason to exist.

    - It must SAY it is an estimate. An order with no `fees_source` predates the marker, and correcting
      one would be rewriting history the tenant never asked anyone to touch.
    - It must name a charge, by PaymentIntent or by invoice (see `charge_reference`). Naming neither
      leaves nothing to look up -- which was true of every upsell ever written until 2026-10-04, and of
      every payment-intent-less subscription renewal until 2026-10-19.
    - It must be old enough to have settled, and
    - young enough to be worth retrying.
    """
    fees = fees_of(order)
    if str(fees.get("fees_source") or "") != ESTIMATE:
        return False
    if charge_reference(order) is None:
        return False
    age = now - _whole((order or {}).get("created_at"))
    return min_age_seconds <= age <= max_age_seconds


def settled(fees: dict[str, Any] | None) -> bool:
    """Whether a fee block now carries Stripe's own number rather than ours."""
    return str(fees_of({"fees": fees}).get("fees_source") or "") == SETTLED


def drift(before: dict[str, Any] | None, after: dict[str, Any] | None) -> int:
    """How far the estimate was out, in cents. Signed: positive means we had UNDER-stated Stripe's fee,
    which is the direction that flatters the tenant's books and the one worth reporting."""
    return _whole(fees_of({"fees": after}).get("stripe_fee")) - _whole(fees_of({"fees": before}).get("stripe_fee"))


# Stripe's own fee and the platform's cut, as `fee_details` names them. Kept as constants because three
# readers now agree on these strings and a typo in one of them would silently report a fee of zero.
STRIPE_FEE_TYPE = "stripe_fee"
APPLICATION_FEE_TYPE = "application_fee"


def fees_from_balance_transaction(txn: Any) -> dict[str, int]:
    """`{stripe_fee, platform_fee, net}` off a settled balance transaction, or `{}` when it has not settled.

    **Extracted so the charge-listing reader and the PaymentIntent reader cannot disagree.** The rule that
    matters is the one this used to state only inside `fees_from_payment_intent`: `txn.fee` is the TOTAL,
    Stripe's processing fee plus the platform's application fee, so reading `fee` as "the Stripe fee"
    double-counts the platform's cut against the tenant. Only `fee_details` can tell them apart
    (plans/MONEY_ACROSS_SILOS.md P4).

    An unsettled transaction returns `{}` rather than zeros — the same distinction the rest of this
    codebase keeps between *absent* and *nothing*, and the reason a usable estimate is never overwritten
    with a blank.
    """
    if not isinstance(txn, dict):
        return {}
    details = txn.get("fee_details") or []
    out: dict[str, int] = {}
    stripe_fee = sum(abs(_whole(d.get("amount"))) for d in details
                     if isinstance(d, dict) and str(d.get("type") or "") == STRIPE_FEE_TYPE)
    platform_fee = sum(abs(_whole(d.get("amount"))) for d in details
                       if isinstance(d, dict) and str(d.get("type") or "") == APPLICATION_FEE_TYPE)
    if stripe_fee:
        out["stripe_fee"] = stripe_fee
    if platform_fee:
        out["platform_fee"] = platform_fee
    if txn.get("net") is not None:
        out["net"] = _whole(txn.get("net"))
    return out
