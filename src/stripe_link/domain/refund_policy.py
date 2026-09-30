"""Where a refund policy COMES FROM. `domain/returns.py` decides what one MEANS.

plans/REFUND_POLICY.md. The bug this exists to end: `dashboard/src/stores/products.js` returned a hardcoded
policy literal at product-creation time, stamped `source: "user_preference_default"` on it, and the renderer
published it. 29 of 32 dev products carry that literal today. Nobody typed the sentence on their storefront,
nothing read the preference it claims to come from, and no screen could change it.

**This module does NOT port stripe-cart's vocabulary.** That was the plan's original wording and discovery
overruled it: stripe-link's own enums are better and already hold live data.

    window      stripe-cart  30/60/90_day_returns, 72/96/120_hour_renewal
                stripe-link  non_refundable, 72_hours, 7_days, 14_days, 30_days, 60_days, custom
    condition   stripe-cart  any, unused, unopened, unboxed
                stripe-link  ... plus defective_only and not_downloaded  <- digital-aware
    return      stripe-cart  print_label, manual_return, no_return      <- a LABEL-PRINTING concern
                stripe-link  return_required, no_return_customer_keeps, digital_revoke_access

stripe-link also has `keep_it_below`, which stripe-cart has no concept of. Per the repo's decision priority
(existing stripe-link architecture outranks stripe-cart behaviour), the vocabulary stays and the ALGORITHMS
are what get ported: two-level resolution, coercion of loose stored input, and generated display copy.

Strict on write, lenient on read -- the split `domain/sites.py` already uses. `normalize` never raises, so a
malformed stored policy still renders something true; `build` raises, so a bad policy cannot be written.

The return-method constants come from `domain/returns.py` rather than being restated here. That module
already owns what they mean for a refund in flight, and two spellings of `return_required` would be exactly
the kind of second source of truth this whole plan is about.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from stripe_link.domain.returns import KEEPS, RETURN_REQUIRED, REVOKE

PHYSICAL, DIGITAL, SUBSCRIPTION = "physical", "digital", "subscription"
CLASSES = (PHYSICAL, DIGITAL, SUBSCRIPTION)

NON_REFUNDABLE = "non_refundable"
CUSTOM = "custom"

# Where the resolved policy came from. `platform_default` is new and is the honest answer the old code could
# not give: it means nobody chose, and this is the platform's fallback. The retired values are still READ,
# because 29 live products carry `user_preference_default` and a reader that rejects them would blank the
# refund section on pages that currently show one.
SOURCE_PRODUCT_OVERRIDE = "product_override"
SOURCE_TENANT_DEFAULT = "tenant_default"
SOURCE_PLATFORM_DEFAULT = "platform_default"
SOURCE_TIP_JAR = "tip_jar_default"
RETIRED_SOURCES = ("user_preference_default", "user_preferences.physical_products")

# A policy carrying one of these was a DELIBERATE decision about this specific product and outranks the
# tenant default. `tip_jar_default` earns its place: `handlers/tip_jar_provision.py` writes non-refundable
# because a tip is not a purchase, and a tenant's 30-day physical-goods default must never make tips
# refundable. The retired sources are deliberately NOT here -- they are the literal, and falling through to
# the tenant default is the entire point.
AUTHORITATIVE_SOURCES = frozenset({SOURCE_PRODUCT_OVERRIDE, SOURCE_TIP_JAR})

# `basis` is what the clock runs from, and it is the reason the legacy copy generator was wrong: it rendered
# a 72-hour subscription window as "within 3 days of delivery" -- wrong unit AND wrong event, on a page
# making a commercial promise. Nothing is delivered to a subscriber and nothing arrives on renewal.
WINDOW_OPTIONS: dict[str, dict[str, Any]] = {
    NON_REFUNDABLE: {"short_label": "Non-refundable", "days": None, "hours": None},
    "72_hours": {"short_label": "72-hour refunds", "days": None, "hours": 72},
    "7_days": {"short_label": "7-day money-back", "days": 7, "hours": None},
    "14_days": {"short_label": "14-day money-back", "days": 14, "hours": None},
    "30_days": {"short_label": "30-day money-back", "days": 30, "hours": None},
    "60_days": {"short_label": "60-day money-back", "days": 60, "hours": None},
    # `custom` means the structured fields do not describe this policy -- the tenant's own prose governs.
    # There is no numeric field to hold "45 days", so no deadline can be computed from it. See `Open`.
    CUSTOM: {"short_label": "Refund policy", "days": None, "hours": None},
}

# The clause appended to the generated sentence. Empty means the condition adds nothing a buyer needs told:
# "in any condition" is noise, and `custom` is covered by the tenant's prose.
CONDITION_OPTIONS: dict[str, str] = {
    "any": "",
    "unused": "in unused condition",
    "unopened": "in unopened condition",
    "defective_only": "for defective items only",
    "not_downloaded": "provided the file has not been downloaded",
    CUSTOM: "",
}

RETURN_METHOD_OPTIONS: dict[str, str] = {
    RETURN_REQUIRED: "Customer returns the item",
    KEEPS: "No return — customer keeps the item",
    REVOKE: "Access is revoked",
    CUSTOM: "Custom",
}

WINDOW_BASIS: dict[str, str] = {PHYSICAL: "of delivery", DIGITAL: "of purchase", SUBSCRIPTION: "of renewal"}

# The platform's fallback when a tenant has set nothing. These reproduce EXACTLY what the JavaScript literal
# has been writing, on purpose: the fault was provenance and editability, not the numbers, and changing the
# numbers here would silently rewrite the promise on every live page that already shows one. Once tenants can
# see and set their own defaults, whether 30 days is the right platform fallback becomes a question worth
# asking -- but it is a separate question from stopping the lie.
CLASS_DEFAULTS: dict[str, dict[str, str]] = {
    PHYSICAL: {"refund_window": "30_days", "condition": "unused", "return_method": KEEPS},
    DIGITAL: {"refund_window": NON_REFUNDABLE, "condition": "any", "return_method": REVOKE},
    SUBSCRIPTION: {"refund_window": "72_hours", "condition": "any", "return_method": KEEPS},
}


class RefundPolicyError(ValueError):
    """A policy that cannot be written. Read paths never raise; see the module docstring."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _whole(value: Any) -> int | None:
    """Cents read back from DynamoDB arrive as `Decimal`, for which `isinstance(x, int)` is False.

    That footgun has already 404'd published pages once (`feedback_decimal_from_dynamo`), and
    `keep_it_below` is a money field read straight off a stored document.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_recurring(price: Any) -> bool:
    """Mirrors `validate_recurring_price`: `pricing_model` alone is not trusted.

    A price saved as recurring with no `recurring` object has shipped before and was sold to buyers as a
    one-time charge, so the interval is the evidence and the label is the claim.
    """
    if not isinstance(price, dict):
        return False
    recurring = price.get("recurring")
    if isinstance(recurring, dict) and recurring.get("interval"):
        return True
    return _text(price.get("pricing_model")).lower() == "recurring"


def _class_from_type(product: dict[str, Any]) -> str:
    product_type = _text(product.get("product_type")).lower()
    if product_type == SUBSCRIPTION:
        return SUBSCRIPTION
    if product_type == PHYSICAL:
        return PHYSICAL
    # Everything else -- digital, service, tip-jar, courses, blank -- is non-returnable goods for refund
    # purposes. Deliberately NOT following `fees.py`, which gives services their own fee class: a fee class
    # is about what the platform charges, and a service and a download have the same refund SHAPE (nothing
    # ships, nothing comes back). One less class for the tenant to configure.
    return DIGITAL


def purchase_class(product: dict[str, Any] | None, price: dict[str, Any] | None) -> str:
    """The policy class for a purchase of a KNOWN price. Use this wherever the price is in hand.

    A recurring price is a subscription whatever the goods are: what the buyer committed to is a renewal
    schedule, and a refund window measured from delivery means nothing on the fourth month of a box.
    """
    if _is_recurring(price):
        return SUBSCRIPTION
    return _class_from_type(product or {})


def product_class(product: dict[str, Any] | None) -> str:
    """The class for a product considered as a whole, when no particular price is in hand.

    **A single recurring price is not enough to make the product a subscription.** Live dev data has a
    `physical` product carrying both a one-time and a daily recurring price, and the blunt rule (any
    recurring price wins, which is what stripe-cart did) narrowed its published promise from 30 days of
    delivery to 72 hours of renewal -- for one-time buyers too, who are not renewing anything. stripe-cart
    could hold that rule because mixed pricing did not arise there; here it is ordinary.

    So a product is a subscription only when subscription is the ONLY way to buy it. Mixed pricing keeps the
    goods' own class, and `purchase_class` gives the exact answer once the buyer has chosen a price.
    """
    product = product or {}
    prices = [p for p in product.get("prices") or [] if isinstance(p, dict)]
    if prices and all(_is_recurring(p) for p in prices):
        return SUBSCRIPTION
    return _class_from_type(product)


def window_days(window: str) -> int | None:
    """The window as whole days, or None when it does not express one.

    None for `non_refundable` (no window) and for `custom` (prose governs, no number to read). Callers must
    treat None as "cannot compute a deadline", never as zero.
    """
    option = WINDOW_OPTIONS.get(window) or {}
    if option.get("days"):
        return int(option["days"])
    hours = option.get("hours")
    if hours:
        # Deliberately rounds DOWN: 72 hours is 3 days, and a window quoted in hours should never be
        # stretched by day-rounding into a longer promise than the tenant made.
        return int(hours) // 24
    return None


def generate_copy(policy_class: str, window: str, condition: str) -> tuple[str, str]:
    """`(short_label, full_policy)` for a structured policy. Empty full text for `custom`.

    Generated only where the tenant has written nothing -- `normalize` preserves their wording, because a
    business with its own legally-reviewed sentence must keep it.

    **The return note is NOT part of this text.** The literal appended it to `full_policy`, and
    `runtime/html.py` ALSO renders `refund_policy_return_note(policy)` as its own paragraph -- so every
    published physical-product page currently prints that paragraph twice, once as "does not" and once as
    "doesn't". Verified on `jb-pages-dev/test/page_3VmYubKR3AM`. One source: the note belongs to the
    renderer, the policy sentence belongs here.
    """
    policy_class = policy_class if policy_class in CLASSES else PHYSICAL
    option = WINDOW_OPTIONS.get(window) or WINDOW_OPTIONS[CLASS_DEFAULTS[policy_class]["refund_window"]]
    short_label = str(option["short_label"])

    if window == NON_REFUNDABLE:
        # Verbatim from the JavaScript literal this module replaces. It is clunky, and it is already the
        # legal sentence on live pages -- rewording a published promise to read better is not this plan's
        # job, and a diff in the wording would be a change nobody asked for.
        return short_label, ("All sales are final and as such, no item can be returned, replaced, "
                             "or refunded in full or in part.")
    if window == CUSTOM:
        return short_label, ""

    amount = f"{option['hours']} hours" if option.get("hours") else f"{option['days']} days"
    clause = CONDITION_OPTIONS.get(condition, "")
    sentence = f"Refunds are available within {amount} {WINDOW_BASIS[policy_class]}"
    return short_label, f"{sentence} {clause}." if clause else f"{sentence}."


def build(policy_class: str, *, refund_window: str, condition: str, return_method: str,
          short_label: str = "", full_policy: str = "", return_note: str = "",
          keep_it_below: Any = None, source: str = SOURCE_TENANT_DEFAULT) -> dict[str, Any]:
    """A complete, valid policy object. RAISES on anything unwritable.

    The write path is strict on purpose: every value that reaches a stored policy has been through here, so
    the vocabulary cannot drift and a page cannot promise something with no meaning behind it.
    """
    if policy_class not in CLASSES:
        raise RefundPolicyError(f"Unknown refund policy class '{policy_class}'.")
    if refund_window not in WINDOW_OPTIONS:
        raise RefundPolicyError(f"Unknown refund window '{refund_window}'.")
    if condition not in CONDITION_OPTIONS:
        raise RefundPolicyError(f"Unknown refund condition '{condition}'.")
    if return_method not in RETURN_METHOD_OPTIONS:
        raise RefundPolicyError(f"Unknown return method '{return_method}'.")

    generated_label, generated_full = generate_copy(policy_class, refund_window, condition)
    resolved_full = _text(full_policy) or generated_full
    if refund_window == CUSTOM and not resolved_full:
        # A custom policy IS its prose. Without it the page shows a summary line opening onto nothing, which
        # is the failure this plan exists to stop wearing a different hat.
        raise RefundPolicyError("A custom refund window requires full_policy text.")

    policy: dict[str, Any] = {
        "source": source,
        "refund_window": refund_window,
        "condition": condition,
        "return_method": return_method,
        "short_label": _text(short_label) or generated_label,
        "full_policy": resolved_full,
    }
    if _text(return_note):
        policy["return_note"] = _text(return_note)
    threshold = _whole(keep_it_below)
    if threshold and threshold > 0:
        policy["keep_it_below"] = threshold
    return policy


def normalize(policy: Any, *, policy_class: str) -> dict[str, Any]:
    """Coerce a stored or submitted policy into a valid one. NEVER raises.

    Unrecognised values fall back to the class default rather than being dropped, and the tenant's own
    wording is preserved over generated copy -- structured fields classify the policy, prose displays it.
    """
    policy_class = policy_class if policy_class in CLASSES else PHYSICAL
    default = CLASS_DEFAULTS[policy_class]
    raw = policy if isinstance(policy, dict) else {}

    window = _text(raw.get("refund_window")).lower()
    if window not in WINDOW_OPTIONS:
        window = default["refund_window"]
    condition = _text(raw.get("condition")).lower()
    if condition not in CONDITION_OPTIONS:
        condition = default["condition"]
    return_method = _text(raw.get("return_method"))
    if return_method not in RETURN_METHOD_OPTIONS:
        return_method = default["return_method"]

    generated_label, generated_full = generate_copy(policy_class, window, condition)
    normalized: dict[str, Any] = {
        "source": _text(raw.get("source")) or SOURCE_PLATFORM_DEFAULT,
        "refund_window": window,
        "condition": condition,
        "return_method": return_method,
        "short_label": _text(raw.get("short_label")) or generated_label,
        "full_policy": _text(raw.get("full_policy")) or generated_full,
    }
    if _text(raw.get("return_note")):
        normalized["return_note"] = _text(raw.get("return_note"))
    threshold = _whole(raw.get("keep_it_below"))
    if threshold and threshold > 0:
        normalized["keep_it_below"] = threshold
    return normalized


def platform_default(policy_class: str) -> dict[str, Any]:
    """The fallback, labelled as what it is. Never `tenant_default` -- no tenant chose this."""
    policy_class = policy_class if policy_class in CLASSES else PHYSICAL
    rule = CLASS_DEFAULTS[policy_class]
    return build(policy_class, refund_window=rule["refund_window"], condition=rule["condition"],
                 return_method=rule["return_method"], source=SOURCE_PLATFORM_DEFAULT)


def tenant_policies(tenant_profile: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The tenant's three defaults, with the platform's fallback standing in where they set none.

    `set_classes` names which ones are genuinely theirs, so a caller can tell a real default from a
    stand-in without re-deriving it.
    """
    stored = (tenant_profile or {}).get("refund_policies")
    stored = stored if isinstance(stored, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for policy_class in CLASSES:
        raw = stored.get(policy_class)
        if isinstance(raw, dict) and raw:
            policy = normalize(raw, policy_class=policy_class)
            policy["source"] = SOURCE_TENANT_DEFAULT
            out[policy_class] = policy
        else:
            out[policy_class] = platform_default(policy_class)
    return out


def resolve(*, tenant_profile: dict[str, Any] | None = None,
            product: dict[str, Any] | None = None,
            price: dict[str, Any] | None = None) -> dict[str, Any]:
    """The policy this product actually promises. Two levels, and an honest `source`.

    product override  >  tenant default for the class  >  platform default

    Pass `price` wherever the buyer's choice is known -- the order path, a receipt, a refund request. A
    product sold both one-time and by subscription makes two different promises, and only the price says
    which one this buyer was given.

    A product-level policy counts as an override only when its `source` says it was a decision about this
    product. That distinction is what the whole bug turns on: 29 live products carry a policy stamped
    `user_preference_default` by a JavaScript literal, and treating those as overrides would freeze the
    literal in place forever -- every one of them would keep promising 30 days no matter what the tenant
    later set. They fall through to the tenant default instead.

    The resolved object carries `policy_class` and `mode` for the UI, and is otherwise shaped exactly like a
    stored `refund_policy`, so `runtime/html.py` and `domain/returns.py` read it with no change.
    """
    product = product or {}
    policy_class = purchase_class(product, price) if price is not None else product_class(product)
    stored = product.get("refund_policy")
    stored = stored if isinstance(stored, dict) else {}

    if _text(stored.get("source")) in AUTHORITATIVE_SOURCES:
        resolved = normalize(stored, policy_class=policy_class)
        mode = "override"
    else:
        resolved = tenant_policies(tenant_profile)[policy_class]
        mode = "default"
        # A per-product `keep_it_below` is a fact about THIS item's postage economics, not a policy choice,
        # so it survives falling through to the tenant default. `domain/returns.py` reads it off the
        # product to waive a return that costs more to collect than the goods are worth.
        threshold = _whole(stored.get("keep_it_below"))
        if threshold and threshold > 0:
            resolved = dict(resolved)
            resolved["keep_it_below"] = threshold

    return dict(resolved) | {"policy_class": policy_class, "mode": mode}
