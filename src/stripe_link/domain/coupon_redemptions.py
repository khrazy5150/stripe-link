"""The coupon redemption ledger (plans/COUPONS_COMPLETION.md — Option B, slice 1).

A coupon's `max_redemptions` used to be read from a counter nothing wrote, so the cap never fired and a
used-up coupon reached the buyer as a raw Stripe 500 instead of the branded "this offer has ended" page.
The fix is not to start writing that counter and leave it at that: under Option B, where WE evaluate the
rule, Stripe's `times_redeemed` cannot enforce a tenant's cap at all, because the Stripe Coupon is
disposable and lives for one checkout. The authoritative number has to be ours.

So a redemption becomes a durable business event rather than a number:

- It records what the discount actually was, against which cart, for whom.
- It is keyed on the checkout session, so a replayed webhook cannot count twice.
- It is written when the ORDER SUCCEEDS, not when a checkout is attempted — a distinction Stripe's own
  counter cannot express, and the reason a tenant's "500 redemptions" should mean 500 sales.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "2026-09-23"


def redemption_id_for(checkout_session_id: str) -> str:
    """The redemption's id, derived from the session that earned it.

    Derived rather than random on purpose: the id IS the idempotency key. Stripe retries a webhook until it
    gets a 2xx and can deliver the same event twice unprompted, so the second copy has to collide with the
    first at the database instead of being trusted not to arrive.
    """
    session_id = str(checkout_session_id or "").strip()
    return f"redemption_{session_id}" if session_id else ""


def redemption_document(
    *, tenant_id: str, coupon_id: str, code: str, checkout_session_id: str, stripe_mode: str, now: int,
    discount_amount: int = 0, qualifying_amount: int = 0, currency: str = "usd",
    payment_intent_id: str = "", customer_email: str = "", grant_id: str = "", order_id: str = "",
) -> dict[str, Any]:
    """One redemption. `qualifying_amount` is the part of the cart the coupon applied to.

    Today that equals the whole subtotal, because product scoping is not built and every coupon discounts
    everything it is allowed to touch. It is recorded separately anyway: under Option B it becomes the
    output of the rule evaluation, and a ledger that only ever stored the total would have to be
    backfilled the day that lands.
    """
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "coupon_redemption",
        "tenant_id": tenant_id,
        "redemption_id": redemption_id_for(checkout_session_id),
        "coupon_id": coupon_id,
        "code": code,
        "checkout_session_id": str(checkout_session_id or ""),
        "stripe_mode": stripe_mode,
        "discount_amount": int(discount_amount or 0),
        "qualifying_amount": int(qualifying_amount or 0),
        "currency": str(currency or "usd").lower(),
        "redeemed_at": int(now),
        "created_at": int(now),
        "updated_at": int(now),
    }
    # Optional identifiers, omitted rather than blanked: several are GSI keys elsewhere in this codebase and
    # DynamoDB refuses an empty string on one of those.
    for field, value in (
        ("payment_intent_id", payment_intent_id),
        ("customer_email", customer_email),
        ("grant_id", grant_id),
        ("order_id", order_id),
    ):
        if str(value or "").strip():
            document[field] = str(value).strip()
    return document


def amounts_from_session(session: dict[str, Any]) -> tuple[int, int, str]:
    """`(discount_amount, qualifying_amount, currency)` as Stripe reported them on the paid session.

    Read from the session rather than recomputed: what the buyer was actually charged is the only number
    worth recording, and re-deriving it here would invent a second opinion about a settled fact.
    """
    total_details = session.get("total_details") or {}
    discount = int(total_details.get("amount_discount") or 0)
    subtotal = int(session.get("amount_subtotal") or 0)
    currency = str(session.get("currency") or "usd").lower()
    return discount, subtotal, currency
