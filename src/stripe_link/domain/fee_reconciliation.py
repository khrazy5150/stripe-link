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


def due(order: dict[str, Any] | None, now: int, *,
        min_age_seconds: int = MIN_AGE_SECONDS,
        max_age_seconds: int = MAX_AGE_SECONDS) -> bool:
    """Whether this order should be re-asked. Four conditions, each of which has a reason to exist.

    - It must SAY it is an estimate. An order with no `fees_source` predates the marker, and correcting
      one would be rewriting history the tenant never asked anyone to touch.
    - It must name a charge. Without `payment_intent_id` there is nothing to look up -- which was true of
      every upsell ever written until 2026-10-04.
    - It must be old enough to have settled, and
    - young enough to be worth retrying.
    """
    fees = fees_of(order)
    if str(fees.get("fees_source") or "") != ESTIMATE:
        return False
    if not str((order or {}).get("payment_intent_id") or "").strip():
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
