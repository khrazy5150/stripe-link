"""What the buyer was offered, what the carrier actually charged, and the gap between them.

plans/LIVE_SHIPPING_RATES.md. A quote is the record of an answer `resolve_options` already gave -- it is
NOT a second way of deciding a price. Nothing here rates anything; it remembers a rating so that the amount
reaching Stripe is the server's own number rather than one the browser handed back.

Three rules shape this module, all the author's, 2026-10-01:

1. **The quote is immutable.** Written once at quote time and never updated. A re-quote mints a NEW row.
   What happens later -- the label the tenant actually buys -- is a SEPARATE record pointing at it. That
   keeps three facts separately answerable: what the customer was charged, what the carrier charged, and
   the margin. `ledger.shipping_margin` returns None today for exactly the want of the second one.

2. **The browser never sends an amount.** It sends a `quote_id` and a `service_token`; the amount is read
   off the stored row. An amount in the DOM is an amount someone can edit -- the shipping element already
   follows this rule for the service, and the quote extends it to the price.

3. **A cheaper label is not an alert.** Variance flags in ONE direction. A tenant does not need to be told
   they made money.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

# How long a quoted price is honoured. Long enough to read a page and decide, short enough that a carrier's
# own pricing has not moved underneath it.
QUOTE_TTL_SECONDS = 30 * 60

# The row outlives the PRICE so a buyer who wandered off and came back, or a support question asked the
# next morning, still finds it. It is not the audit record: **the ORDER carries its own snapshot of the
# quoted service, amount and destination**, and that is what survives forever. Dividing it this way is what
# lets the quote row double as a cache (see `cache_id`) without a cache eviction ever destroying evidence.
QUOTE_RETENTION_SECONDS = 7 * 24 * 60 * 60

# threshold = max($2.00, 25% x quoted). Flat floor so trivial rates do not flag on pennies; a percentage so
# a $20 rate is not held to the same absolute tolerance as a $4 one (author's table, 2026-10-01).
VARIANCE_FLOOR = 200
VARIANCE_RATE = Decimal("0.25")

# What a caller should DO, rather than merely whether the quote was good. The branching at checkout is the
# whole point of validating, so it is named here and tested here instead of being re-derived per caller.
USE, REQUOTE, FALLBACK, USE_CHEAPEST = "use", "requote", "fallback", "use_cheapest"


def _whole(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except Exception:  # noqa: BLE001 - any unparseable amount is zero, never a crash in the buyer's path
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> str:
    """Dimensions and weights as a STABLE string, so a fingerprint does not change with float formatting."""
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except Exception:  # noqa: BLE001
        return "0.00"


def normalize_destination(destination: dict[str, Any] | None) -> dict[str, str]:
    """Country, postal code and region in the one shape everything downstream compares.

    Postal codes are upper-cased and stripped of spaces: a Canadian buyer typing "k1a 0b1" and "K1A0B1"
    is at one address, and a fingerprint that disagreed would spend a carrier call to learn that.
    """
    source = destination or {}
    return {
        "country": _text(source.get("country")).upper()[:2],
        "postal_code": _text(source.get("postal_code")).upper().replace(" ", ""),
        "region": _text(source.get("region")).upper()[:3],
    }


def fingerprint(*, offer_id: Any, items: list[dict[str, Any]] | None,
                parcels: list[dict[str, Any]] | None,
                destination: dict[str, Any] | None) -> str:
    """One value answering "is this the same cart, going to the same place, in the same boxes?".

    Covers the PARCELS and not just the line items, because the parcel is what a carrier priced. Two carts
    with identical lines pack identically, so including both is redundant -- but a packer change, a box
    added, or a product whose weight was corrected all SHOULD invalidate a quote, and only the parcel side
    notices those.
    """
    payload = {
        "offer": _text(offer_id),
        "items": sorted(
            [_text(i.get("product_id")), _text(i.get("price_id")), _whole(i.get("quantity") or 1)]
            for i in (items or [])
        ),
        "parcels": sorted(
            [_num(p.get("length")), _num(p.get("width")), _num(p.get("height")),
             _num(p.get("weight")), _text(p.get("template"))]
            for p in (parcels or [])
        ),
        "to": normalize_destination(destination),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cache_id(*, tenant_id: Any, mode: Any, cart_fingerprint: Any) -> str:
    """The quote id for this cart, to this place, for this tenant -- the same every time.

    Deriving the id instead of randomising it turns the quote row into its own cache: a buyer toggling
    between services, reloading, or coming back in ten minutes reads the row they already have with a
    single `get`, no carrier call and no index to maintain. A miss or an expired row mints the next one at
    the same id.

    Safe only because the ORDER keeps its own snapshot of what it transacted on (see
    QUOTE_RETENTION_SECONDS). If the row were the audit record, re-minting over it would be destroying
    evidence; because it is not, re-minting is just a cache refill.

    Two buyers with an identical cart going to an identical postcode legitimately share one quote -- the
    answer is the same answer. Their ORDERS stay separate, and so do their label-time records, which are
    keyed per order rather than per quote for exactly this reason.
    """
    seed = f"{_text(tenant_id)}|{_text(mode)}|{_text(cart_fingerprint)}"
    return "shq_" + hashlib.sha256(seed.encode()).hexdigest()[:32]


def build_quote(*, quote_id: str, tenant_id: str, mode: str, offer_id: str,
                destination: dict[str, Any] | None, parcels: list[dict[str, Any]] | None,
                items: list[dict[str, Any]] | None, options: list[dict[str, Any]] | None,
                source: str = "", currency: str = "usd", now: int = 0) -> dict[str, Any]:
    """The row, assembled. Pure -- the caller persists it.

    `mode` is written and matched later so a TEST quote can never price a LIVE checkout. The two run
    against different carrier keys and, in sandbox, against carriers that do not exist in production.
    """
    now = int(now or 0)
    clean = [opt for opt in (normalize_quote_option(o) for o in (options or [])) if opt]
    return {
        "quote_id": _text(quote_id),
        "tenant_id": _text(tenant_id),
        "mode": _text(mode),
        "offer_id": _text(offer_id),
        "destination": normalize_destination(destination),
        "fingerprint": fingerprint(offer_id=offer_id, items=items, parcels=parcels,
                                   destination=destination),
        "parcels": [
            {"length": _num(p.get("length")), "width": _num(p.get("width")),
             "height": _num(p.get("height")), "weight": _num(p.get("weight")),
             "box_name": _text(p.get("box_name") or p.get("name")), "template": _text(p.get("template"))}
            for p in (parcels or [])
        ],
        "options": clean,
        "source": _text(source),
        "currency": _text(currency).lower() or "usd",
        "created_at": now,
        "expires_at": now + QUOTE_TTL_SECONDS,
        "retention_expires_at": now + QUOTE_RETENTION_SECONDS,
    }


def normalize_quote_option(option: Any) -> dict[str, Any] | None:
    """One offerable service. Dropped entirely without a token: a service nobody can name cannot be chosen
    later, and an unnamed row in a quote is an amount with no way to validate the pick against it."""
    if not isinstance(option, dict):
        return None
    token = _text(option.get("service_token"))
    if not token:
        return None
    out = {
        "service_token": token,
        "carrier": _text(option.get("carrier")),
        "label": _text(option.get("label")) or token,
        "amount": _whole(option.get("amount")),
    }
    for key in ("estimated_days", "transit_days_min", "transit_days_max"):
        value = option.get(key)
        if value is not None:
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                pass
    return out


def option_for(quote: dict[str, Any] | None, service_token: Any) -> dict[str, Any] | None:
    token = _text(service_token)
    for option in (quote or {}).get("options") or []:
        if _text(option.get("service_token")) == token:
            return option
    return None


def cheapest_option(quote: dict[str, Any] | None) -> dict[str, Any] | None:
    options = [o for o in (quote or {}).get("options") or [] if isinstance(o, dict)]
    return min(options, key=lambda o: _whole(o.get("amount"))) if options else None


def is_expired(quote: dict[str, Any] | None, now: int) -> bool:
    return int((quote or {}).get("expires_at") or 0) <= int(now or 0)


def validate(quote: dict[str, Any] | None, *, tenant_id: str, mode: str, offer_id: str,
             cart_fingerprint: str, service_token: str, now: int) -> dict[str, Any]:
    """Whether this quote may price this checkout, and what to do when it may not.

    Returns `{action, reason, option}`. The ACTION is the point -- "invalid" is not a plan, and each kind
    of invalid wants a different answer:

    - `fallback`  the quote is not ours to use at all (missing, wrong tenant, wrong mode, wrong offer).
                  Ignore it and let `checkout_shipping`'s zone path answer, exactly as it does for a buyer
                  who never touched the element.
    - `requote`   the quote WAS ours but no longer describes this purchase (expired, or the cart changed
                  under the buyer). Ask the carrier again rather than charging a number that has rotted.
    - `use_cheapest` the chosen service is not in the quote -- a stale page, or a tampered token. The row's
                  own cheapest option is both safe and buyer-favourable; it is never a price we did not
                  compute.
    - `use`       everything matches.
    """
    if not quote:
        return {"action": FALLBACK, "reason": "missing", "option": None}
    if _text(quote.get("tenant_id")) != _text(tenant_id):
        return {"action": FALLBACK, "reason": "tenant_mismatch", "option": None}
    if _text(quote.get("mode")) != _text(mode):
        return {"action": FALLBACK, "reason": "mode_mismatch", "option": None}
    if _text(quote.get("offer_id")) != _text(offer_id):
        return {"action": FALLBACK, "reason": "offer_mismatch", "option": None}
    if _text(quote.get("fingerprint")) != _text(cart_fingerprint):
        return {"action": REQUOTE, "reason": "cart_changed", "option": None}
    if is_expired(quote, now):
        return {"action": REQUOTE, "reason": "expired", "option": None}
    chosen = option_for(quote, service_token)
    if not chosen:
        return {"action": USE_CHEAPEST, "reason": "service_unavailable", "option": cheapest_option(quote)}
    return {"action": USE, "reason": "", "option": chosen}


def agreed_shipping(metadata: dict[str, Any] | None,
                    shipping_address: dict[str, Any] | None) -> dict[str, Any]:
    """The buyer's half of the audit pair, read off a completed Checkout Session.

    Returns `{"shipping_quote": {...}}` so it spreads into an order document exactly like
    `buyer_paid_shipping`, or **`{}` when no quote priced this sale** -- a zone-priced or unpriced order
    gets no block at all rather than one full of empty strings claiming a quote that never existed.

    This is the record that outlives the quote row. It carries BOTH postcodes because a variance has to
    explain itself: "you were charged more than you quoted" is an assertion, "quoted 80202, shipped to
    80205" is a reason the tenant can check (author, 2026-10-01).

    The carrier's price is NOT here. It does not exist yet -- it is learned when the tenant buys the
    label, and lands in a separate record (`build_actual`).
    """
    meta = metadata or {}
    quote_id = _text(meta.get("shipping_quote_id"))
    if not quote_id:
        return {}
    quoted_postal = normalize_destination({"postal_code": meta.get("shipping_postal_code")})["postal_code"]
    actual_postal = normalize_destination(
        {"postal_code": (shipping_address or {}).get("postal_code")})["postal_code"]
    return {"shipping_quote": {
        "quote_id": quote_id,
        "service_token": _text(meta.get("shipping_service")),
        "quoted_amount": _whole(meta.get("shipping_quoted_amount")),
        "quoted_postal_code": quoted_postal,
        "actual_postal_code": actual_postal,
        # Hosted Checkout prefills a shipping address but gives us no way to LOCK it, so a buyer can type
        # a different one after we quoted. Recorded rather than blocked: refusing to ship over a postcode
        # change is worse than the problem it solves.
        "destination_matches": bool(quoted_postal) and quoted_postal == actual_postal,
    }}


def variance_threshold(quoted_amount: Any) -> int:
    """max($2.00, 25% of the quote). The author's table, 2026-10-01."""
    quoted = _whole(quoted_amount)
    return max(VARIANCE_FLOOR, int(Decimal(quoted) * VARIANCE_RATE))


def variance(*, quoted_amount: Any, actual_amount: Any) -> dict[str, Any]:
    """What the label cost against what the buyer paid, and whether it is worth the tenant's attention.

    `flagged` is ONE-DIRECTIONAL. A label cheaper than the quote is recorded as a saving and raises
    nothing: an alert that fires when a tenant makes money trains them to ignore alerts.
    """
    quoted, actual = _whole(quoted_amount), _whole(actual_amount)
    delta = actual - quoted
    threshold = variance_threshold(quoted)
    return {
        "quoted_amount": quoted,
        "actual_amount": actual,
        "delta": delta,
        "threshold": threshold,
        "flagged": delta > threshold,
        "direction": "over" if delta > 0 else ("under" if delta < 0 else "exact"),
    }


def order_variance(order: dict[str, Any] | None,
                   shipment: dict[str, Any] | None) -> dict[str, Any]:
    """The shipping-cost variance for ONE order, from data a caller already holds.

    plans/LIVE_SHIPPING_RATES.md phase 5. The durable audit row lives in `shipping_actual`, written when
    the label is bought -- but the Orders view already loads both halves (the order carries the quote, the
    shipment carries the label's cost), so it derives the same numbers rather than paying a read per row.
    One order list would otherwise be N extra lookups to display a badge most orders never show.

    Returns `{}` when there is nothing to compare, which is most orders: no quote priced it, or no label
    has been bought yet.
    """
    agreed = (order or {}).get("shipping_quote") or {}
    cost = (shipment or {}).get("cost") or {}
    if not agreed.get("quote_id") or cost.get("amount") is None:
        return {}
    out = variance(quoted_amount=agreed.get("quoted_amount"), actual_amount=cost.get("amount"))
    out["quoted_postal_code"] = _text(agreed.get("quoted_postal_code"))
    out["actual_postal_code"] = _text(agreed.get("actual_postal_code"))
    out["destination_matches"] = bool(agreed.get("destination_matches"))
    out["quoted_service_token"] = _text(agreed.get("service_token"))
    out["service_token"] = _text(shipment.get("service")) or out["quoted_service_token"]
    out["service_substituted"] = bool(
        out["quoted_service_token"] and out["service_token"] != out["quoted_service_token"])
    return out


def build_actual(*, quote_id: str, order_id: str, service_token: str, amount: Any,
                 quoted_amount: Any, destination: dict[str, Any] | None,
                 quoted_destination: dict[str, Any] | None, carrier: str = "",
                 currency: str = "usd", now: int = 0) -> dict[str, Any]:
    """What the carrier actually charged. A SEPARATE record -- the quote is never touched.

    Carries BOTH postal codes so a variance explains itself. "You were charged more than you quoted" is an
    assertion; "quoted 80202, shipped to 80205" is a reason the tenant can check.
    """
    return {
        "quote_id": _text(quote_id),
        "order_id": _text(order_id),
        "service_token": _text(service_token),
        "carrier": _text(carrier),
        "currency": _text(currency).lower() or "usd",
        "destination": normalize_destination(destination),
        "quoted_destination": normalize_destination(quoted_destination),
        "created_at": int(now or 0),
        "retention_expires_at": int(now or 0) + QUOTE_RETENTION_SECONDS,
        **variance(quoted_amount=quoted_amount, actual_amount=amount),
    }
