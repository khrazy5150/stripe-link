"""Tip jars — what a customer_chooses price may offer.

The amount range and the preset cap are the PLATFORM's, not the tenant's: a supporter typing their own
number needs a floor Stripe will actually charge and a ceiling that keeps a mistyped amount from becoming a
dispute, and the buttons have to fit in one row. So the tenant does not get to change them, and the server
does not trust a client that says otherwise.

Both readers come from one file (tip_rules.json), the way the composer and the image cropper already work.
A form that caps at five while the server accepts eight is the same class of bug as a preview that renders a
section the published page does not. See plans/PAY_WHAT_YOU_WANT.md.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent.parent / "tip_rules.json"
_FALLBACK: dict[str, Any] = {
    "min_amount": 100,
    "max_amount": 50000,
    "max_presets": 5,
    "max_presets_with_custom": 4,
    "intervals": ["day", "week", "month", "year"],
}
try:
    with _RULES_PATH.open(encoding="utf-8") as _fh:
        RULES: dict[str, Any] = {**_FALLBACK, **json.load(_fh)}
except (OSError, ValueError):
    # Degrade to the same numbers rather than to "no limits": an unbundled rules file must not quietly turn
    # a $500 ceiling into none at all.
    RULES = dict(_FALLBACK)

MIN_AMOUNT: int = int(RULES["min_amount"])
MAX_AMOUNT: int = int(RULES["max_amount"])
INTERVALS: set[str] = set(RULES["intervals"])


def max_presets(allow_custom: bool) -> int:
    """How many preset buttons fit. 'Enter your own' occupies one of the five when it is offered."""
    key = "max_presets_with_custom" if allow_custom else "max_presets"
    return int(RULES[key])


def whole_amount(value: Any) -> int | None:
    """One stored amount as an int, or None when it is not a whole, non-negative number.

    DynamoDB hands every number back as a `Decimal`, so `isinstance(amount, int)` passes in tests -- which
    build documents from JSON fixtures -- and fails on every document that has actually been through the
    table. That is exactly how a saved tip jar came back with no presets at all: the publisher refused the
    document, no artifact was written, and the page 404'd. Every scalar validator in documents.py already
    accommodates Decimal for this reason; a list of amounts is no different.

    Shared with the validator so "what counts as an amount" has ONE answer.
    """
    if isinstance(value, bool):  # bool is an int subclass, and a flag is not an amount
        return None
    if isinstance(value, Decimal):
        if value < 0 or value != value.to_integral_value():
            return None
        return int(value)
    if isinstance(value, int) and value >= 0:
        return value
    return None


class TipAmountError(ValueError):
    """The amount a buyer chose is not one this tip jar offers."""


def is_tip_price(price: dict[str, Any] | None) -> bool:
    return str((price or {}).get("pricing_model") or "") == "customer_chooses"


def preset_amounts(price: dict[str, Any]) -> list[int]:
    """What the TENANT keyed for each button, smallest first — what they keep, not what the buyer pays.

    Same split as an ordinary price, which stores `tenant_keyed_amount` beside the `unit_amount` the buyer
    is charged: the fee mode decides the distance between them, so the tenant types one number and the page
    displays the other (author, 2026-09-13; legacy stored exactly this pair as `unit_amount` + `_gross_amount`
    per preset price).

    A legacy `suggested_amount` counts as the single preset it always meant, so a document saved before
    presets existed still renders a button instead of nothing.
    """
    presets = [whole_amount(amount) for amount in (price.get("presets") or [])]
    if not any(presets) and price.get("suggested_amount"):
        presets = [whole_amount(price["suggested_amount"])]
    return sorted({amount for amount in presets if amount})


def preset_charges(price: dict[str, Any]) -> list[int]:
    """What the BUYER pays for each button, in the same order as preset_amounts().

    Computed once at authoring time by the same server calculation that prices everything else, and stored
    beside the presets — the renderer has no billing config to gross up with, and recomputing it per request
    would be a second answer to a question already answered.

    Documents written before this split carry no `preset_charges`; their presets WERE the charged amounts
    (the rule this supersedes), so they read back as their own charges and keep rendering the same numbers.
    """
    keyed = preset_amounts(price)
    charges = [whole_amount(amount) for amount in (price.get("preset_charges") or [])]
    if len(charges) != len(keyed) or not all(charges):
        return keyed
    return [amount for amount in charges if amount]


def preset_pairs(price: dict[str, Any]) -> list[tuple[int, int]]:
    """(what the tenant keeps, what the buyer pays) per button."""
    return list(zip(preset_amounts(price), preset_charges(price)))


def allows_custom(price: dict[str, Any]) -> bool:
    return bool(price.get("allow_custom"))


def allows_one_time(price: dict[str, Any]) -> bool:
    """Whether a single, non-repeating tip is on offer. Default YES.

    Absent means yes, so every document written before the field existed keeps offering both -- which is
    what those pages already do. Setting it false is how a tenant says "this is a membership": monthly
    unlocks something, and a one-off payment for it would buy nothing (author, 2026-09-14).
    """
    return price.get("allow_one_time") is not False


def resolve_charge(
    price: dict[str, Any],
    amount: Any,
    *,
    source: str = "preset",
    gross_up: Any = None,
) -> int:
    """What to CHARGE for the tip a buyer chose — the server's own answer, not the page's.

    The two sources are deliberately different, and the difference is the one thing to keep straight:

    * A **preset** arrives as the CHARGE the card displayed, so it is charged as it stands — and it must be
      one of the charges this price actually offers, or a crafted request could name any number it liked.
      (The tenant's own keyed amount sits in `presets`; `preset_charges` is what the buyer was shown.)
    * A **typed** amount is what the supporter means to GIVE, so the fee mode applies to it: under
      `net_guaranteed` the buyer covers the fees on top, which is the whole point of that mode. `gross_up`
      is the platform's own calculation, passed in so this module stays free of billing config.

    The ceiling bounds what the buyer TYPES, not what the fees make of it: §5a settled that fees pushing the
    charge past the range are fine, because the range exists to catch a mistyped tip, not to cap a card.
    """
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise TipAmountError("A tip amount must be a whole number of cents.") from None
    if amount < 0:
        raise TipAmountError("A tip amount must be a whole number of cents.")
    if source == "preset":
        if amount not in preset_charges(price):
            raise TipAmountError("That is not one of the amounts this page offers.")
        return amount
    if not allows_custom(price):
        raise TipAmountError("This tip jar does not accept a typed amount.")
    if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
        raise TipAmountError(
            f"A tip must be between {MIN_AMOUNT // 100} and {MAX_AMOUNT // 100} in whole currency units.")
    return int(gross_up(amount)) if gross_up else amount


def stamp_tip_jar(offer: dict[str, Any], products_by_id: dict[str, Any]) -> dict[str, Any]:
    """The offer, with `pricing_model` filled in when every landing item is a tip.

    Called once per render context, before anything asks the composer what this page IS. The composer takes
    the OFFER and never its products, so without this a tip jar composes as an ordinary checkout page --
    trust badges, "Buy Now", and a thin-content warning telling the tenant to add a specifications table.

    Returns the offer unchanged when it already says, or when it is not a tip jar; a COPY otherwise, so a
    render never mutates the document its caller holds.
    """
    if not offer or offer.get("pricing_model"):
        return offer
    if not offer_is_tip_jar(offer, products_by_id):
        return offer
    return {**offer, "pricing_model": "customer_chooses"}


def offer_is_tip_jar(offer: dict[str, Any], products_by_id: dict[str, Any]) -> bool:
    """Whether every landing item on this offer is a tip.

    The composer takes the OFFER and not its products (it runs from a publish stream holding only the page),
    so the answer is stamped onto the offer before composing rather than looked up inside it -- the same
    shape as `lead_capture_action`, which is denormalised for exactly this reason.

    Derived rather than trusted: an offer saved before the field existed still composes as a tip jar.
    """
    from stripe_link.domain.opportunities import STAGE_LANDING, stage_opportunities

    items = [item for item in stage_opportunities(offer or {}, STAGE_LANDING) if not item.get("service_id")]
    if not items:
        return False
    for item in items:
        product = products_by_id.get(str(item.get("product_id") or "")) or {}
        price_id = str(item.get("price_id") or "")
        price = next(
            (p for p in (product.get("prices") or []) if str(p.get("price_id") or "") == price_id),
            None,
        )
        if not is_tip_price(price):
            return False
    return True


def keyed_amount(price: dict[str, Any], charge: Any, *, source: str = "preset") -> int:
    """What the TENANT keeps out of a charge — the other half of the pair presets store.

    Frozen onto the order at checkout because it cannot be recovered afterwards: a preset's keyed amount is
    recoverable from the pair, but a TYPED amount only ever existed in the request. Without it, "refund the
    tip and keep the fees" (plans/PAY_WHAT_YOU_WANT.md §5f) is uncomputable for exactly the tips most likely
    to be disputed.
    """
    charge = int(charge)
    if source == "custom":
        return charge  # the supporter typed what they meant to GIVE; the fees were added on top
    pairs = preset_pairs(price)
    return next((keyed for keyed, offered in pairs if offered == charge), charge)


# A manage link has to outlive a cart-recovery nudge by a long way: the SUBSCRIPTION is open-ended, and this
# link is the only self-serve way to stop it, so a token that expires while the charge continues strands the
# supporter at exactly the moment it exists for. 13 months covers an annual tip plus a grace month.
#
# Long-lived is safe here only because the link is NARROW: it opens Stripe's cancel flow for the one
# subscription it was minted for, not the account portal (handlers/tip_manage.py). A full portal would show
# invoice history and the card's last four and allow a payment-method change -- at which point a year-old
# link in an inbox would be a data exposure rather than an off switch, and a short TTL would be the right
# answer instead. The narrowing is what buys the lifetime.
MANAGE_TOKEN_TTL_SECONDS = 400 * 24 * 60 * 60


def manage_token_doc(
    tenant_id: str,
    token: str,
    *,
    email: str,
    stripe_customer_id: str,
    subscription_id: str = "",
    mode: str = "live",
    now: int,
    ttl_seconds: int = MANAGE_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    """An opaque link that opens ONE supporter's Stripe billing portal.

    The same shape as `cart_token_doc`: the token dereferences server-side, so no customer id and no email
    ride in the URL. This is the whole of "a supporter can cancel without an account" (§5g) -- the peers
    solve it with a login, which is a product we deliberately are not building.
    """
    return {
        "schema_version": "2026-09-14",
        "document_type": "tip_token",
        "tenant_id": tenant_id,
        "token": token,
        "email": str(email or "").strip().lower(),
        "stripe_customer_id": str(stripe_customer_id or ""),
        "subscription_id": str(subscription_id or ""),
        "stripe_mode": "live" if str(mode) == "live" else "test",
        "created_at": int(now),
        "expires_at": int(now) + int(ttl_seconds),
    }
