"""Finding ONE purchase from what a customer can actually tell us, and deciding what they may do with it.

plans/PURCHASE_SELF_SERVICE.md. A static page cannot ask for card details, so the form takes an email or a
phone number plus an optional approximate date. The server picks ONE transaction — the latest, or the one
nearest that date — and never enumerates: a list behind an emailed link is both a privacy target and the
screen that ends three subscriptions instead of the one the customer came for.

Pure functions. No I/O, no Stripe, no repositories.
"""

from __future__ import annotations

import re
from typing import Any

from stripe_link.domain.refund_ledger import refundable_ceiling

# What the contact index stores. NOT hashed, deliberately: it sits on the orders table beside
# `customer.email` in plain text, so hashing it would protect nothing from anyone who can read the row
# while costing every future debugging session. Hashing earns its place in the CROSS-TENANT lookup table
# (plan §5a), which is a separate object holding only contacts and ids.
_NON_DIGITS = re.compile(r"\D+")


def contact_key(value: str) -> str:
    """The index key for an email or phone number, or "" when it is neither.

    Prefixed so one field can carry both without the two ever colliding, and normalised so the key a
    customer types in a form matches the key written at checkout.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "@" in raw:
        local, _, domain = raw.partition("@")
        return f"e:{local.strip().lower()}@{domain.strip().lower()}" if local and domain else ""
    digits = _NON_DIGITS.sub("", raw)
    # Last 10 digits: a customer types "(206) 555-0100" where checkout stored "+12065550100". Comparing the
    # national part matches both without a phone-number library and without guessing a country code.
    return f"p:{digits[-10:]}" if len(digits) >= 10 else ""


def order_contact_keys(order: dict[str, Any]) -> list[str]:
    """Every key an order can be found by. Both, when checkout collected both.

    Prefers the stored `contact_keys` written at checkout, and COMPUTES them otherwise — which is what lets
    v1 ship with no backfill: an order written before the field existed still matches, because its email is
    right there on the row.
    """
    stored = order.get("contact_keys")
    if isinstance(stored, list) and stored:
        return [str(key) for key in stored if key]
    customer = order.get("customer") or {}
    keys = [contact_key(customer.get("email") or ""), contact_key(customer.get("phone") or "")]
    return [key for key in keys if key]


def order_epoch(order: dict[str, Any]) -> int:
    """`created_at` is written as a STRING on orders (the webhook stringifies it), so every comparison here
    has to go through this rather than trusting the type."""
    try:
        return int(str(order.get("created_at") or 0))
    except (TypeError, ValueError):
        return 0


def select_order(
    orders: list[dict[str, Any]],
    key: str,
    *,
    approximate_date: int | None = None,
) -> dict[str, Any] | None:
    """The ONE order this request is about.

    Latest by default -- people ask about the charge they just saw on their statement. An approximate date
    narrows instead of listing: the nearest match wins, which is what "not this one, it was around March"
    has to do on a second attempt.
    """
    if not key:
        return None
    matches = [order for order in orders if key in order_contact_keys(order)]
    if not matches:
        return None
    if approximate_date:
        return min(matches, key=lambda order: abs(order_epoch(order) - int(approximate_date)))
    return max(matches, key=order_epoch)


# How many purchases one lookup will list. A cap rather than everything: the email has to stay
# readable, and a contact with fifty orders is asking a question this flow cannot answer anyway.
MAX_LISTED = 10


def select_orders(
    orders: list[dict[str, Any]],
    key: str,
    *,
    approximate_date: int | None = None,
    limit: int = MAX_LISTED,
) -> list[dict[str, Any]]:
    """EVERY order this contact could mean, newest first.

    `select_order` answers "which one did they mean" and is right when there is one. It is wrong the
    moment a buyer has two: it silently returned the newest, so a customer with four subscriptions
    could cancel exactly one and had no route to the rest -- which sends them to their bank instead,
    the dispute this whole flow exists to avoid (measured 2026-09-28).

    An approximate date still NARROWS rather than picking: the orders nearest that date come first,
    so "it was around March" reorders the list instead of collapsing it to a guess.
    """
    if not key:
        return []
    matches = [order for order in orders if key in order_contact_keys(order)]
    if approximate_date:
        matches.sort(key=lambda order: abs(order_epoch(order) - int(approximate_date)))
    else:
        matches.sort(key=order_epoch, reverse=True)
    return _one_per_subscription(matches)[:max(1, int(limit))]


def _one_per_subscription(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per subscription; every one-off stands alone.

    A renewal writes an ORDER each cycle, so four daily subscriptions produced eight rows and the same
    subscription appeared twice -- once per charge. A buyer cancelling the first would then see the
    second still listed and conclude it had not worked, which is the doubt this whole flow exists to
    remove. Order is preserved, so whichever charge the caller ranked first is the one shown.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for order in orders:
        sub = subscription_id(order)
        if sub:
            if sub in seen:
                continue
            seen.add(sub)
        out.append(order)
    return out


def order_label(order: dict[str, Any]) -> str:
    """What this purchase is, as a buyer would recognise it.

    They are choosing between their own purchases, so the product name is the only thing that tells
    them apart -- an order id means nothing to the person who paid.
    """
    product = (order.get("product") or {}).get("name")
    if str(product or "").strip():
        return str(product).strip()
    lines = order.get("line_items") or []
    if lines:
        name = str((lines[0] or {}).get("name") or "").strip()
        # Stripe writes a renewal line as "1 x Creatine Gummies (at $32.91 / month)". The quantity and
        # price are shown beside it, so the leading count and trailing price are noise here.
        name = re.sub(r"^\s*\d+\s*[x\u00d7]\s*", "", name)
        name = re.sub(r"\s*\(at .*\)\s*$", "", name).strip()
        # A line reading "1 x $197.92 (at $197.92 / day)" strips to a bare price, and "$197.92 —
        # USD 197.92 subscription" tells a buyer nothing about WHICH purchase it is. Better to say
        # "Subscription" than to name it after its own amount.
        if name and not re.fullmatch(r"[^A-Za-z]*", name):
            return name
    return "Subscription" if subscription_id(order) else "Your purchase"


def is_recurring(order: dict[str, Any]) -> bool:
    """Whether stopping this one stops anything. A one-off has nothing to cancel."""
    return bool(subscription_id(order))


def is_refundable(order: dict[str, Any]) -> bool:
    """Whether there is money left on this order to ask about. Paid, and not already fully refunded."""
    if str(order.get("payment_status") or "") not in {"paid", ""}:
        return False
    total = int(order.get("amount_total") or 0)
    refunded = int(order.get("amount_refunded") or 0)
    return total > 0 and refunded < total


def subscription_id(order: dict[str, Any]) -> str:
    return str(order.get("subscription_id") or "")


def available_actions(order: dict[str, Any]) -> list[str]:
    """What this transaction allows, in the order they should be offered.

    The rule the whole flow runs on (plan §2): actions that cost the tenant nothing are self-serve; actions
    that move money are a REQUEST. So `cancel` happens on the spot and `refund` creates a request the tenant
    answers -- and the copy has to keep those apart, because "cancelled" is a fact and "requested" is a
    decision someone else makes.
    """
    actions = []
    if subscription_id(order):
        actions.append("cancel")
    if is_refundable(order):
        actions.append("refund")
    return actions


def purchase_summary(order: dict[str, Any]) -> dict[str, Any]:
    """The one line shown before anything happens: what we think this is.

    Confirmation, not enumeration -- one candidate, stated so a wrong match is visible BEFORE the customer
    acts on it. Without it a mismatch is silent; without the "not this one" path beside it, a mismatch is a
    dead end, and a dead end is how someone ends up at their bank instead.
    """
    product = order.get("product") or {}
    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    return {
        "order_id": str(order.get("order_id") or ""),
        "name": str(product.get("name") or "Your purchase"),
        "amount": int(order.get("amount_total") or 0),
        "currency": str(order.get("currency") or "usd"),
        "created_at": order_epoch(order),
        "interval": str(metadata.get("tip_recurring") or ""),
        "actions": available_actions(order),
    }


PURCHASE_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


def purchase_token_doc(
    tenant_id: str,
    token: str,
    *,
    order_id: str,
    email: str,
    mode: str = "live",
    now: int,
    ttl_seconds: int = PURCHASE_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    """A link to ONE transaction, for a few days.

    Short on purpose, and the opposite of the tip CANCEL link's 400 days: that one is the only self-serve
    way to stop an open-ended subscription, while this one is a session -- someone asked a question just
    now, and the refund window is bounded by the policy anyway. Scoped to one order, so a leaked link can
    never sweep a history (plan §3, §4).
    """
    return {
        "schema_version": "2026-09-14",
        "document_type": "purchase_token",
        "tenant_id": tenant_id,
        "token": token,
        "order_id": str(order_id or ""),
        "email": str(email or "").strip().lower(),
        "stripe_mode": "live" if str(mode) == "live" else "test",
        "created_at": int(now),
        "expires_at": int(now) + int(ttl_seconds),
    }


def refund_request_doc(
    order: dict[str, Any],
    *,
    reason: str = "",
    now: int,
    request_id: str,
) -> dict[str, Any]:
    """The customer's ask, as the document the tenant's Refunds screen already knows how to answer.

    A REQUEST, never a refund: the money is the tenant's to return. `status: new` is where their existing
    approve / reject / execute flow starts, and the notification it emits is what tells them it arrived.
    """
    customer = order.get("customer") or {}
    return {
        "schema_version": "2026-05-29",
        "document_type": "refund_request",
        "tenant_id": str(order.get("tenant_id") or ""),
        "refund_request_id": request_id,
        "status": "new",
        "risk_level": "unknown",
        "customer": {
            "name": str(customer.get("name") or ""),
            "email": str(customer.get("email") or ""),
        },
        "order_id": str(order.get("order_id") or ""),
        "amount": {
            "currency": str(order.get("currency") or "usd"),
            "paid_amount": int(order.get("amount_total") or 0),
            # What a refund can actually return, which is not always what was paid: a net_guaranteed tip
            # charged the supporter the fees on top, and only the gift ever reached the creator. Frozen here,
            # from the order in hand, so the tenant's confirm dialog can state the real figure without a
            # second read -- and so it cannot drift if the order is edited later.
            "refundable_amount": refundable_ceiling(order),
        },
        "reason": str(reason or "").strip()[:2000],
        "created_at": int(now),
        "updated_at": int(now),
    }
