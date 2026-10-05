"""What the thank-you page tells a buyer about their parcel.

plans/THANK_YOU_PAGE.md P2. The page used to say "Free Shipping — your order will arrive within 5–7
business days" to everyone, including an order that had just paid $39.59 to Vancouver. This builds the
sentence from what actually happened, and it is the ONLY place that does: the page element and the
`{{arrival}}` token in a card both read the same promise, so a date cannot be worded two ways.

**Computed once, at order time, and stored on the order.** Not recomputed per page view — the buyer was
told a date, and that date must not quietly change because the tenant edited their cutoff next week.

**When it says "free"** (author, 2026-10-04) — exactly three situations and no others:

1. the tenant never entered dimensions and weight, so nothing could be rated;
2. the tenant deliberately chose a free zone;
3. it is not a physical product — and *that* case shows **no promise at all** rather than a reassurance,
   so `promise_for` returns `{}` and the renderer omits the element entirely.
"""
from __future__ import annotations

from typing import Any

from stripe_link.domain.delivery_estimate import estimate

FREE = "free"
PAID = "paid"
UNKNOWN = "unknown"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _whole(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def transit_days_for(quote: Any, service_token: str) -> tuple[Any, Any]:
    """`(min, max)` transit days for the service the buyer actually chose, from the stored quote row.

    The quote keeps every option it offered, each with its own `transit_days_min/max` — the carrier's for a
    live zone, the tenant's configured figures for a flat or free one. Both are business days.

    `(None, None)` when the service is not among them, which is a real answer: an order placed before this
    shipped, or a quote that expired, has no days to promise and must not borrow another service's.
    """
    wanted = _text(service_token)
    for option in (quote or {}).get("options") or []:
        if not isinstance(option, dict):
            continue
        if _text(option.get("service_token")) == wanted:
            return option.get("transit_days_min"), option.get("transit_days_max")
    return None, None


def service_label_for(quote: Any, service_token: str) -> str:
    """What to call the service in front of a buyer -- the tenant's own words when they set them."""
    wanted = _text(service_token)
    for option in (quote or {}).get("options") or []:
        if isinstance(option, dict) and _text(option.get("service_token")) == wanted:
            carrier = _text(option.get("carrier")).upper()
            label = _text(option.get("label"))
            return f"{carrier} {label}".strip() if carrier and label else (label or carrier)
    return ""


def promise_for(order: Any, quote: Any = None, *, tz_name: str = "UTC", cutoff_hour: int = 15,
                requires_shipping: bool = True) -> dict[str, Any]:
    """The whole promise, or `{}` when there is nothing honest to say.

    `{}` means the element does not render. A digital product has no parcel, and a thank-you page that
    reassures someone about delivery they are not expecting is worse than one that says nothing.
    """
    if not requires_shipping or not isinstance(order, dict):
        return {}
    shipping_quote = order.get("shipping_quote") if isinstance(order.get("shipping_quote"), dict) else {}
    service_token = _text(shipping_quote.get("service_token"))
    paid = _whole(order.get("shipping_amount"))
    low, high = transit_days_for(quote, service_token)
    dates = estimate(order.get("created_at"), transit_days_min=low, transit_days_max=high,
                     tz_name=tz_name, cutoff_hour=cutoff_hour)
    return {
        # `paid` is what the buyer was charged, so "free" here is the buyer's truth rather than the
        # tenant's cost -- an unmeasured parcel really did cost them nothing.
        "cost": PAID if paid > 0 else FREE,
        "amount": paid,
        "service": service_label_for(quote, service_token),
        **(dates or {}),
        # No dates is not a failure to report; it is the honest state of an order nobody could rate.
        "has_date": bool(dates),
    }


def revised_promise(order: Any, quote: Any, shipment: Any, *, shipped_on: Any) -> dict[str, Any]:
    """What the buyer should be told now the parcel has actually gone. `{}` when nothing can be said.

    plans/THANK_YOU_PAGE.md P4. Carries `changed`, because the wording turns on it: a date that still
    matches is simply stated, while one that moved is a correction. An apology for nothing teaches buyers
    to expect one and devalues the next real apology — and an EARLIER date is worth saying too, since
    arriving sooner than promised is good news nobody otherwise hears.

    **Transit days come from the service that actually shipped, where we can know it.** The tenant picks a
    carrier and service when they mark an order shipped, and it need not be the one the buyer paid for —
    upgrading to get a late parcel there on time is exactly what a tenant does. Three sources, in order of
    how much they actually know:

    1. the shipment's own `transit_days`, which the label-buying path has from the rate it bought;
    2. the stored quote's option for the service named on the shipment, when that service was one we
       quoted;
    3. the service the buyer was originally quoted — still right about the SHIP DATE, which is the part
       that moved, and honest about the rest.

    The carrier registry is not a fourth source: it knows which services carry tracking, not how fast they
    are, and inventing a duration for "Priority Mail" would be the typed-in guess this work replaced.
    """
    from stripe_link.domain.delivery_estimate import from_ship_date

    original = (order or {}).get("delivery_estimate") if isinstance(order, dict) else None
    original = original if isinstance(original, dict) else {}
    low, high = _shipment_transit_days(order, quote, shipment)
    revised = from_ship_date(shipped_on, transit_days_min=low, transit_days_max=high)
    if not revised:
        return {}
    was = str(original.get("arrives_on") or "")
    now = str(revised.get("arrives_on") or "")
    return {
        **revised,
        "service": _text((shipment or {}).get("service")) or _text(original.get("service")),
        # `changed` is False when there was no original to move from: nothing was promised, so nothing
        # was broken, and the buyer just gets a date.
        "changed": bool(was and now and was != now),
        "was": was or None,
        "later": bool(was and now and now > was),
    }


def _shipment_transit_days(order: Any, quote: Any, shipment: Any) -> tuple[Any, Any]:
    """`(min, max)` for the service that actually shipped — see `revised_promise` for the order."""
    ship = shipment or {}
    if ship.get("transit_days_min") is not None:
        return ship.get("transit_days_min"), ship.get("transit_days_max")
    named = _text(ship.get("service"))
    for option in (quote or {}).get("options") or []:
        if not isinstance(option, dict):
            continue
        labels = {_text(option.get("label")).lower(), _text(option.get("service_token")).lower()}
        if named and named.lower() in labels:
            return option.get("transit_days_min"), option.get("transit_days_max")
    quoted = (order or {}).get("shipping_quote") if isinstance(order, dict) else None
    return transit_days_for(quote, _text((quoted or {}).get("service_token")))


def revised_sentence(revised: Any) -> str:
    """One line for the shipment email. States a date, or corrects one."""
    if not isinstance(revised, dict) or not revised:
        return ""
    first = _spell(revised.get("arrives_on"))
    through = _spell(revised.get("arrives_through"))
    when = f"between {first} and {through}" if through and through != first else f"on {first}"
    if not revised.get("changed"):
        return f"It should reach you {when}."
    if revised.get("later"):
        # Named as a change rather than slipped in: the buyer is holding a date, and finding out by
        # noticing the parcel is late is worse than being told.
        return (f"This is later than the {_spell(revised.get('was'))} we first estimated — "
                f"it should now reach you {when}.")
    return f"Good news: that is sooner than we first estimated. It should reach you {when}."


def promise_sentence(promise: Any) -> str:
    """One line, for the element and for `{{arrival}}` alike.

    Dates are spelled out — "Wednesday, October 8" — because a buyer reads a day of the week faster than
    they read a number, and the day is what tells them whether they will be home.
    """
    if not isinstance(promise, dict) or not promise:
        return ""
    if not promise.get("has_date"):
        # Free because nothing could be rated, or because the tenant said so. Either way there is no date
        # to give, and promising one anyway is the sentence this module exists to delete.
        return "We'll email tracking details as soon as it ships."
    first = _spell(promise.get("arrives_on"))
    through = _spell(promise.get("arrives_through"))
    if through and through != first:
        return f"Estimated arrival between {first} and {through}."
    return f"Estimated to arrive {first}."


def arrival_phrase(promise: Any) -> str:
    """Just the date part, for substituting into a tenant's own sentence via `{{arrival}}`.

    Reads inside "Wait for your package to arrive {{arrival}}." -- so it carries its own preposition and
    falls back to a phrase rather than a blank, which would leave a sentence hanging mid-clause.
    """
    if not isinstance(promise, dict) or not promise or not promise.get("has_date"):
        return "soon — we'll email tracking when it ships"
    first = _spell(promise.get("arrives_on"))
    through = _spell(promise.get("arrives_through"))
    return f"between {first} and {through}" if through and through != first else f"on {first}"


_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _spell(iso_date: Any) -> str:
    """`2026-10-08` -> `Wednesday, October 8`. Hand-rolled rather than `strftime`, which is locale- and
    platform-dependent for day and month names and pads the day with a zero on some systems."""
    raw = _text(iso_date)
    if not raw:
        return ""
    try:
        from datetime import date

        day = date.fromisoformat(raw)
    except ValueError:
        return ""
    return f"{_DAYS[day.weekday()]}, {_MONTHS[day.month - 1]} {day.day}"
