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
    NON_REFUNDABLE: {"short_label": "Non-refundable", "select_label": "No refunds",
                     "days": None, "hours": None},
    "72_hours": {"short_label": "72-hour refunds", "days": None, "hours": 72},
    "7_days": {"short_label": "7-day money-back", "days": 7, "hours": None},
    "14_days": {"short_label": "14-day money-back", "days": 14, "hours": None},
    "30_days": {"short_label": "30-day money-back", "days": 30, "hours": None},
    "60_days": {"short_label": "60-day money-back", "days": 60, "hours": None},
    "90_days": {"short_label": "90-day money-back", "days": 90, "hours": None},
    # `custom` means the structured fields do not describe this policy -- the tenant's own prose governs.
    # There is no numeric field to hold "45 days", so no deadline can be computed from it. See `Open`.
    CUSTOM: {"short_label": "Refund policy", "select_label": "Custom — write your own",
             "days": None, "hours": None},
}

# The clause appended to the generated sentence. Empty means the condition adds nothing a buyer needs told:
# "in any condition" is noise, and `custom` is covered by the tenant's prose.
CONDITION_OPTIONS: dict[str, str] = {
    "any": "",
    "unused": "in unused condition",
    "unopened": "in unopened condition",
    # The ordinary physical-goods rule, and the gap that started this plan: the clause making damage
    # caused by the customer ineligible. `unused` is stricter than most sellers mean and `any` gives away
    # the only protection they have, so a tenant selling anything mechanical had no honest option.
    "working_condition": "in working condition",
    "complete_in_packaging": "unused, in its original packaging, with all parts and accessories",
    # APPAREL's version of `complete_in_packaging`, and it is not a stricter form of it: a garment has no
    # packaging worth the name, and the two things a clothing seller actually needs intact are the price
    # tag and the hygiene seal. A tenant selling swimwear had to choose between `unused` (unprovable) and
    # `complete_in_packaging` (describing a box that never existed).
    "tags_intact": "with tags attached and any hygiene seals intact",
    # The honest middle ground. It changes the SENTENCE only -- no refund arithmetic is implied. Refunds
    # already support a partial amount and the merchant decides it; promising a deduction nothing computes
    # would be a new implicit promise, which is the thing this family of plans exists to stop.
    "any_value_adjusted": "in any condition — the refund is reduced to reflect any loss of value",
    "defective_only": "for defective items only",
    "not_downloaded": "provided the file has not been downloaded",
    CUSTOM: "",
}

# Human labels for the pickers. They live here, next to the values they name, so a screen never has to
# invent wording for a commercial term -- and `CLASS_LABELS` makes the service-to-digital mapping VISIBLE,
# which matters because a tenant selling services would otherwise hunt for a block that does not exist.
CONDITION_LABELS: dict[str, str] = {
    "any": "Any condition",
    "unused": "Unused",
    "unopened": "Unopened",
    "working_condition": "In working condition",
    "complete_in_packaging": "Unused, complete, in original packaging",
    "tags_intact": "Tags attached, hygiene seals intact",
    "any_value_adjusted": "Any condition — refund adjusted for loss of value",
    "defective_only": "Defective items only",
    "not_downloaded": "Not yet downloaded",
    CUSTOM: "Custom",
}

CLASS_LABELS: dict[str, str] = {
    PHYSICAL: "Physical goods",
    DIGITAL: "Digital goods & services",
    SUBSCRIPTION: "Subscriptions & recurring",
}

CLASS_HINTS: dict[str, str] = {
    PHYSICAL: "Anything that ships. The window runs from delivery.",
    DIGITAL: "Downloads, courses, services and bookings — nothing ships, so nothing comes back. "
             "The window runs from purchase.",
    SUBSCRIPTION: "Anything billed on a schedule. The window runs from each renewal, so a buyer who "
                  "forgets to cancel has this long to ask.",
}

# WHO PAYS THE POSTAGE -- the missing half of "Free returns", and the single most commercially
# significant fact a returns policy states. `domain/ledger.return_shipping_cost_entry` has recorded who
# BORE this cost since the shipping work; nothing has ever recorded who was PROMISED to.
SELLER_PAYS = "seller_pays"
# WHO PAYS and HOW IT TRAVELS are two facts, and this value is the one buyers look for. "Free returns"
# on its own leaves them wondering how; a prepaid label is the answer, and the platform really does buy
# one (`handlers/shipping.buy_return_label`, recorded on the refund request with an expiry), so the
# claim has something behind it rather than being a sentence we hope the tenant honours.
SELLER_PAYS_LABEL = "seller_pays_label"
BUYER_PAYS = "buyer_pays"
SHIPPING_NOT_APPLICABLE = "not_applicable"

RETURN_SHIPPING_OPTIONS: dict[str, str] = {
    SELLER_PAYS: "We pay return postage",
    SELLER_PAYS_LABEL: "We pay — prepaid label",
    BUYER_PAYS: "Customer pays return postage",
    SHIPPING_NOT_APPLICABLE: "Not applicable — nothing is sent back",
}

# The clause the renderer prints. Empty for `not_applicable`: nothing ships back, so the question does not
# arise and a sentence about it would be noise on a page about a download.
#
# "SEND", not "email". Nothing emails a return label automatically -- `buy_return_label` buys it and
# records it on the request, and the tenant passes it on. Naming the channel would promise a mechanism
# the platform does not perform, which is the exact fault this family of plans exists to stop.
RETURN_SHIPPING_CLAUSES: dict[str, str] = {
    SELLER_PAYS: "Return postage is on us.",
    SELLER_PAYS_LABEL: "Returns are free — we send you a prepaid label.",
    BUYER_PAYS: "Return postage is paid by the customer.",
    SHIPPING_NOT_APPLICABLE: "",
}

# WHAT COMES OFF THE REFUND, AND WHEN IT LANDS (plans/REFUND_POLICY_AND_GUARANTEES.md P8).
#
# Three facts every mainstream returns policy states and this vocabulary could not: a restocking fee, what
# happens to the outbound postage the buyer already paid, and how long the refund takes. Checked against
# TikTok Shop's clothing policy, which states all three; ours could express neither of the first two and
# said nothing at all about timing.
#
# They are FIELDS ON THE POLICY, not a third primitive. `buyer_guarantees` earned its own module because
# "we refund if tracking stops moving" is not a rule about sending an item back and no amount of
# window/condition/return-method vocabulary could express one. These three ARE rules about sending an item
# back -- they qualify the same refund the window governs -- so a second home for them would be the
# duplicate source of truth this family of plans keeps paying off.
#
# Each is ABSENT unless the tenant sets it, exactly like `keep_it_below`. Absence means the page says
# nothing, which is the one honest answer when nobody has chosen (P2).

# A restocking fee above half the price is not a restocking fee, it is a cancellation penalty, and several
# consumer regimes treat it as one. Clamped rather than refused, for `clamp_days`' reason: a form that
# rejects 80 teaches the tenant to fight it.
RESTOCKING_FEE_MAX_PERCENT = 50
# A month. "We issue your refund within 45 days" is not a promise anyone acts on, and a tenant who needs
# longer than 30 days is describing a dispute process rather than a refund.
REFUND_PROCESSING_MAX_DAYS = 30

# What happens to the postage the buyer ALREADY PAID to receive the goods. Distinct from `return_shipping`,
# which is the postage of sending them back -- two different charges, two different answers, and conflating
# them is how "free returns" came to mean four different things across the industry.
ORIGINAL_SHIPPING_UNSTATED = "unstated"
ORIGINAL_SHIPPING_REFUNDED = "refunded"
ORIGINAL_SHIPPING_NOT_REFUNDED = "not_refunded"

ORIGINAL_SHIPPING_OPTIONS: dict[str, str] = {
    ORIGINAL_SHIPPING_UNSTATED: "Don't say either way",
    ORIGINAL_SHIPPING_REFUNDED: "Refunded with the order",
    ORIGINAL_SHIPPING_NOT_REFUNDED: "Not refunded",
}

ORIGINAL_SHIPPING_CLAUSES: dict[str, str] = {
    ORIGINAL_SHIPPING_UNSTATED: "",
    ORIGINAL_SHIPPING_REFUNDED: "We refund your original shipping charge too.",
    ORIGINAL_SHIPPING_NOT_REFUNDED: "Your original shipping charge is not refunded.",
}

# WHAT THE BUYER GETS BACK -- money, or another one. A fourth field rather than a `return_method` value,
# because `return_method` is about what happens to the ITEM (it comes back, the buyer keeps it, access is
# revoked) and this is about what travels the other way. The two are independent: "keep the broken one, here
# is a new one" is an ordinary policy for low-value goods.
#
# `refund_only` is the default and prints NOTHING. Unlike `original_shipping`, where silence genuinely leaves
# a question open, there is no question here: a refund policy that says nothing about replacements refunds
# you, and a sentence saying so would be the noise `CONDITION_OPTIONS["any"]` deliberately omits.
RESOLUTION_REFUND_ONLY = "refund_only"
RESOLUTION_REPLACEMENT_OR_REFUND = "replacement_or_refund"
RESOLUTION_REPLACEMENT_FIRST = "replacement_first"

RESOLUTION_OPTIONS: dict[str, str] = {
    RESOLUTION_REFUND_ONLY: "Refund",
    RESOLUTION_REPLACEMENT_OR_REFUND: "Replacement or refund — buyer chooses",
    RESOLUTION_REPLACEMENT_FIRST: "Replacement, refund only if we cannot",
}

# "Your choice" is the construction `buyer_guarantees` already uses for the same promise ("we refund it or
# send it again -- your choice"), so a buyer meets one idea once.
RESOLUTION_CLAUSES: dict[str, str] = {
    RESOLUTION_REFUND_ONLY: "",
    RESOLUTION_REPLACEMENT_OR_REFUND: "We replace it or refund you — your choice.",
    RESOLUTION_REPLACEMENT_FIRST: "We replace the item. Where we cannot, we refund you instead.",
}

RETURN_METHOD_OPTIONS: dict[str, str] = {
    RETURN_REQUIRED: "Customer returns the item",
    KEEPS: "No return — customer keeps the item",
    REVOKE: "Access is revoked",
    CUSTOM: "Custom",
}

WINDOW_BASIS: dict[str, str] = {PHYSICAL: "of delivery", DIGITAL: "of purchase", SUBSCRIPTION: "of renewal"}

# A STARTING POINT FOR THE FORM, and never a published promise.
#
# These were the platform's fallback: a tenant who had set nothing still got a policy, stamped
# `platform_default`, and it reached live pages. Nobody chose it, and for physical goods it promised the
# buyer keeps the item AND may have their money back. `platform_default()` is gone and nothing manufactures
# a policy from this table any more (plans/REFUND_POLICY_AND_GUARANTEES.md P2).
#
# The values survive for two jobs that are not promises:
#
#   * seeding the settings form when a tenant first enables a class, so the three selects open on
#     something sensible rather than empty -- the tenant still has to enable and save before a page says
#     anything, which is the whole difference;
#   * coercing a single unrecognised field inside a policy that DOES exist (`normalize`), where the
#     alternative is dropping a field out of a document the tenant did save.
#
# Neither path can make a page promise anything the tenant did not enable. The name says `seeds` so that a
# future caller reaching for "the default policy" does not find one here.
CLASS_FORM_SEEDS: dict[str, dict[str, str]] = {
    PHYSICAL: {"refund_window": "30_days", "condition": "unused", "return_method": KEEPS},
    DIGITAL: {"refund_window": NON_REFUNDABLE, "condition": "any", "return_method": REVOKE},
    SUBSCRIPTION: {"refund_window": "72_hours", "condition": "any", "return_method": KEEPS},
}


def default_return_shipping(return_method: str) -> str:
    """What `return_shipping` means when the tenant has not chosen.

    `not_applicable` wherever nothing travels back -- a revoked download and a keep-it refund both leave
    no parcel to pay for, so asking the question there would invent a promise about postage that does not
    exist. Only a real return defaults to the buyer paying, which is the status quo on every page today:
    silence has always meant the customer arranges it.
    """
    return BUYER_PAYS if return_method == RETURN_REQUIRED else SHIPPING_NOT_APPLICABLE


# `{n}` is the ONE thing a browser may fill in. The settings screens preview these live as the tenant types
# a number, and asking the server per keystroke is not a thing a settings form does -- so the server owns
# every word and hands over a slot for a digit the tenant typed themselves. That is categorically different
# from the fault this module exists to end, where a JavaScript file owned the sentence.
RESTOCKING_FEE_CLAUSE = "We deduct a restocking fee of {n}% from your refund."
# "ISSUE", not "you get your money back". Pressing the button is the merchant's act and the only part of
# this they control; the card network then takes its own five to ten business days, and a policy that
# promised the landing date would be promising a clock nobody in this system holds. The second sentence
# says so, which costs the tenant nothing and saves them the support ticket.
PROCESSING_CLAUSE_AFTER_RETURN = ("We issue your refund within {n} days of receiving your return. "
                                  "Your bank may take a few days longer to show it.")
PROCESSING_CLAUSE_AFTER_APPROVAL = ("We issue your refund within {n} days of approving your request. "
                                    "Your bank may take a few days longer to show it.")


def restocking_fee_percent(value: Any) -> int:
    """The fee as a whole percent, or 0 for none. Clamped into what the term can honestly mean.

    0 rather than None so callers can treat it as a number throughout; `build` and `normalize` then omit the
    field entirely, because a stored `restocking_fee_percent: 0` would be a tenant's choice of "no fee"
    sitting in the document as if it were a fee of nothing.
    """
    percent = _whole(value)
    if percent is None or percent < 1:
        return 0
    return min(RESTOCKING_FEE_MAX_PERCENT, percent)


def refund_processing_days(value: Any) -> int:
    """How long the tenant takes to issue the refund, in whole days, or 0 for "nothing said"."""
    days = _whole(value)
    if days is None or days < 1:
        return 0
    return min(REFUND_PROCESSING_MAX_DAYS, days)


def refund_terms(policy: dict[str, Any] | None) -> list[str]:
    """The extra clauses this policy states, in the order a buyer wants them. [] when it states none.

    ORDER IS LOAD-BEARING, for `buyer_guarantees.GUARANTEES`' reason: may I send it back, how, less what,
    and when do I see the money. A buyer who has read one tenant's policy knows where to look on the next.
    The first two answers are the window and the return note; these are the last two.
    """
    policy = policy if isinstance(policy, dict) else {}
    window = _text(policy.get("refund_window")).lower()
    if window == NON_REFUNDABLE:
        # There is no refund, so there is nothing to deduct from and nothing to time. A page that said
        # "all sales are final" and then "we deduct 15%" would be describing two different policies.
        #
        # The replacement clause goes with them, and here the published copy settles it rather than
        # judgement: the non-refundable sentence reads "no item can be returned, REPLACED, or refunded in
        # full or in part". A tenant wanting "final sale, but we replace faulty goods" has `defective_only`
        # with a real window, which is that policy stated as what it is.
        return []
    policy_class = _text(policy.get("policy_class")).lower()
    return_method = _text(policy.get("return_method"))
    # Absent on a stored policy and present on a resolved one; an absent class reads as physical, because
    # the only way one of these clauses is reached is that a tenant chose it on the physical card.
    shipped = policy_class in ("", PHYSICAL)

    clauses: list[str] = []
    # FIRST, because it answers what the buyer gets before the clauses saying what comes off it and when it
    # lands. Physical only: a month of a subscription cannot be replaced, and re-granting a download is
    # `digital_revoke_access` running backwards rather than a replacement.
    resolution = _text(policy.get("resolution")).lower()
    if shipped and RESOLUTION_CLAUSES.get(resolution):
        clauses.append(RESOLUTION_CLAUSES[resolution])

    fee = restocking_fee_percent(policy.get("restocking_fee_percent"))
    # Nothing is restocked when nothing comes back. On a keep-it refund or a revoked download the fee
    # would be a deduction for a cost the tenant never incurs.
    if fee and return_method == RETURN_REQUIRED:
        clauses.append(RESTOCKING_FEE_CLAUSE.format(n=fee))

    original = _text(policy.get("original_shipping")).lower()
    # Only where something SHIPPED. Nothing was posted to a subscriber or a download buyer, so there is no
    # outbound charge to refund or withhold, and the sentence would be about a line that is not on the order.
    if shipped and ORIGINAL_SHIPPING_CLAUSES.get(original):
        clauses.append(ORIGINAL_SHIPPING_CLAUSES[original])

    days = refund_processing_days(policy.get("refund_processing_days"))
    if days:
        template = (PROCESSING_CLAUSE_AFTER_RETURN if return_method == RETURN_REQUIRED
                    else PROCESSING_CLAUSE_AFTER_APPROVAL)
        clauses.append(template.format(n=days))
    return clauses


def _attach_terms(policy: dict[str, Any], restocking_fee: Any, original_shipping: Any,
                  processing_days: Any, resolution: Any = None) -> None:
    """Put the three P8 terms on a policy, in place, omitting any the tenant did not set.

    Shared by `build` and `normalize` so the write path and the read path cannot disagree about when a term
    counts as chosen -- the exact kind of split that let `return_shipping` reach storage from one path and
    be discarded by another.
    """
    fee = restocking_fee_percent(restocking_fee)
    if fee:
        policy["restocking_fee_percent"] = fee
    original = _text(original_shipping).lower()
    if original in ORIGINAL_SHIPPING_OPTIONS and original != ORIGINAL_SHIPPING_UNSTATED:
        policy["original_shipping"] = original
    days = refund_processing_days(processing_days)
    if days:
        policy["refund_processing_days"] = days
    resolved = _text(resolution).lower()
    if resolved in RESOLUTION_OPTIONS and resolved != RESOLUTION_REFUND_ONLY:
        policy["resolution"] = resolved


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
    option = WINDOW_OPTIONS.get(window) or WINDOW_OPTIONS[CLASS_FORM_SEEDS[policy_class]["refund_window"]]
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
          keep_it_below: Any = None, source: str = SOURCE_TENANT_DEFAULT,
          return_shipping: str = "", restocking_fee: Any = None,
          original_shipping: str = "", processing_days: Any = None,
          resolution: str = "") -> dict[str, Any]:
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
    return_shipping = _text(return_shipping) or default_return_shipping(return_method)
    if return_shipping not in RETURN_SHIPPING_OPTIONS:
        raise RefundPolicyError(f"Unknown return shipping '{return_shipping}'.")
    original_shipping = _text(original_shipping) or ORIGINAL_SHIPPING_UNSTATED
    if original_shipping not in ORIGINAL_SHIPPING_OPTIONS:
        raise RefundPolicyError(f"Unknown original shipping '{original_shipping}'.")
    resolution = _text(resolution) or RESOLUTION_REFUND_ONLY
    if resolution not in RESOLUTION_OPTIONS:
        raise RefundPolicyError(f"Unknown resolution '{resolution}'.")

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
        "return_shipping": return_shipping,
    }
    if _text(return_note):
        policy["return_note"] = _text(return_note)
    threshold = _whole(keep_it_below)
    if threshold and threshold > 0:
        policy["keep_it_below"] = threshold
    # OMITTED WHEN UNSET, like `keep_it_below`. A stored `restocking_fee_percent: 0` or
    # `original_shipping: "unstated"` would be an absence dressed as a decision, and `tenant_policies`
    # hands these straight to a settings screen that would then show a fee of nothing as the tenant's own
    # choice.
    _attach_terms(policy, restocking_fee, original_shipping, processing_days, resolution)
    return policy


def normalize(policy: Any, *, policy_class: str) -> dict[str, Any]:
    """Coerce a stored or submitted policy into a valid one. NEVER raises.

    Unrecognised values fall back to the class default rather than being dropped, and the tenant's own
    wording is preserved over generated copy -- structured fields classify the policy, prose displays it.
    """
    policy_class = policy_class if policy_class in CLASSES else PHYSICAL
    default = CLASS_FORM_SEEDS[policy_class]
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
    # Absent on every policy stored before this field existed, which is nearly all of them -- so the
    # fallback has to be the status quo rather than a new promise. See `default_return_shipping`.
    return_shipping = _text(raw.get("return_shipping")).lower()
    if return_shipping not in RETURN_SHIPPING_OPTIONS:
        return_shipping = default_return_shipping(return_method)

    generated_label, generated_full = generate_copy(policy_class, window, condition)
    normalized: dict[str, Any] = {
        "source": _text(raw.get("source")) or SOURCE_PLATFORM_DEFAULT,
        "refund_window": window,
        "condition": condition,
        "return_method": return_method,
        "short_label": _text(raw.get("short_label")) or generated_label,
        "full_policy": _text(raw.get("full_policy")) or generated_full,
        "return_shipping": return_shipping,
    }
    if _text(raw.get("return_note")):
        normalized["return_note"] = _text(raw.get("return_note"))
    threshold = _whole(raw.get("keep_it_below"))
    if threshold and threshold > 0:
        normalized["keep_it_below"] = threshold
    # Unrecognised values here fall AWAY rather than to a class default, unlike the three enums above. A
    # window has to be something; a restocking fee does not, and coercing a nonsense value into a real
    # percentage would invent a deduction the tenant never chose.
    _attach_terms(normalized, raw.get("restocking_fee_percent"), raw.get("original_shipping"),
                  raw.get("refund_processing_days"), raw.get("resolution"))
    return normalized


def stored_policies(tenant_config: dict[str, Any] | None) -> dict[str, Any]:
    """Pull the tenant's per-class defaults out of their settings document.

    They live at `legal_defaults.refund_policies` on **TenantConfig**, not on TenantProfile as this plan
    first said. TenantProfile is written only by registration, auth and Stripe webhooks, and it holds
    `billing_status`, `tier_id`, `billing_exempt` and `stripe_subscription_id`; giving the dashboard a PUT
    over that document to reach a refund setting would hand tenants their own billing tier. TenantConfig is
    already the tenant-editable settings document, already served at `/config` with GET and PUT, and already
    holds `legal_defaults` -- the refund URL sits right beside the policy it links to.

    A bare top-level `refund_policies` map is also accepted, so a caller holding just the map still works.
    """
    config = tenant_config or {}
    legal = config.get("legal_defaults")
    if isinstance(legal, dict) and isinstance(legal.get("refund_policies"), dict):
        return legal["refund_policies"]
    stored = config.get("refund_policies")
    return stored if isinstance(stored, dict) else {}


def tenant_policies(tenant_config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """ONLY the classes the tenant actually set. A class they left alone is absent from the map.

    It used to stand the platform's fallback in for every gap, which is how a promise nobody chose came
    to be on every live page. Absence is the honest answer and a caller must handle it: where there is no
    answer the page says NOTHING -- silence is recoverable, a false promise is a dispute.
    """
    stored = stored_policies(tenant_config)
    out: dict[str, dict[str, Any]] = {}
    for policy_class in CLASSES:
        raw = stored.get(policy_class)
        if isinstance(raw, dict) and raw:
            policy = normalize(raw, policy_class=policy_class)
            policy["source"] = SOURCE_TENANT_DEFAULT
            out[policy_class] = policy
    return out


def resolve(*, tenant_config: dict[str, Any] | None = None,
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
        default = tenant_policies(tenant_config).get(policy_class)
        if default is None:
            # NOTHING TO RESOLVE. No override, and the tenant never set a default for this class -- so
            # there is no promise, and manufacturing one is the fault this phase removes. Callers must
            # read `mode` rather than assuming a policy: `render_refund_policy` renders nothing from an
            # empty dict, the money-back badge is suppressed, and `return_requirement` treats a physical
            # good with no resolved method as still requiring its return.
            return {"policy_class": policy_class, "mode": "unset"}
        resolved = default
        mode = "default"
        # A per-product `keep_it_below` is a fact about THIS item's postage economics, not a policy choice,
        # so it survives falling through to the tenant default. `domain/returns.py` reads it off the
        # product to waive a return that costs more to collect than the goods are worth.
        threshold = _whole(stored.get("keep_it_below"))
        if threshold and threshold > 0:
            resolved = dict(resolved)
            resolved["keep_it_below"] = threshold

    return dict(resolved) | {"policy_class": policy_class, "mode": mode}


def vocabulary() -> dict[str, Any]:
    """Everything a settings screen needs to offer these choices -- INCLUDING the generated sentences.

    The previews are precomputed here rather than left to the client, and that is the whole point. A
    JavaScript copy of this sentence template is how the bug in `stores/products.js` happened: the browser
    became the author of a commercial promise. 240 short strings is a cheap price for the server staying the
    only thing that can write one.
    """
    previews: dict[str, dict[str, str]] = {}
    for policy_class in CLASSES:
        for window in WINDOW_OPTIONS:
            for condition in CONDITION_OPTIONS:
                label, full = generate_copy(policy_class, window, condition)
                previews[f"{policy_class}|{window}|{condition}"] = {"short_label": label,
                                                                    "full_policy": full}
    return {
        "classes": list(CLASSES),
        "class_labels": dict(CLASS_LABELS),
        "class_hints": dict(CLASS_HINTS),
        "windows": [{"value": key, "label": option.get("select_label") or option["short_label"],
                     "badge": option["short_label"], "days": window_days(key)}
                    for key, option in WINDOW_OPTIONS.items()],
        "conditions": [{"value": key, "label": CONDITION_LABELS[key], "clause": clause}
                       for key, clause in CONDITION_OPTIONS.items()],
        "return_methods": [{"value": key, "label": label}
                           for key, label in RETURN_METHOD_OPTIONS.items()],
        # The screen shows this only for `return_required`; the clause travels with it so the preview is
        # the server's sentence rather than one the browser assembles.
        "return_shipping": [{"value": key, "label": label,
                             "clause": RETURN_SHIPPING_CLAUSES[key]}
                            for key, label in RETURN_SHIPPING_OPTIONS.items()],
        "return_shipping_defaults": {method: default_return_shipping(method)
                                     for method in RETURN_METHOD_OPTIONS},
        "original_shipping": [{"value": key, "label": label,
                               "clause": ORIGINAL_SHIPPING_CLAUSES[key]}
                              for key, label in ORIGINAL_SHIPPING_OPTIONS.items()],
        "resolutions": [{"value": key, "label": label, "clause": RESOLUTION_CLAUSES[key]}
                        for key, label in RESOLUTION_OPTIONS.items()],
        # The two numeric terms, as the server's own sentence with ONE slot for a digit. The screen fills
        # `{n}` with the number the tenant typed and owns nothing else about the wording -- see the
        # constants for why that is not the fault this module exists to end. Bounds travel with them so the
        # form can clamp before it previews, instead of showing a promise the server will quietly shrink.
        "terms": {
            "restocking_fee": {"template": RESTOCKING_FEE_CLAUSE, "max": RESTOCKING_FEE_MAX_PERCENT},
            "processing_days": {"template_after_return": PROCESSING_CLAUSE_AFTER_RETURN,
                                "template_after_approval": PROCESSING_CLAUSE_AFTER_APPROVAL,
                                "max": REFUND_PROCESSING_MAX_DAYS},
        },
        # The form's starting values, not a policy. The key name is the dashboard's and is kept.
        "class_defaults": {k: dict(v) for k, v in CLASS_FORM_SEEDS.items()},
        "previews": previews,
    }


def apply_to_product(document: dict[str, Any], tenant_config: dict[str, Any] | None) -> dict[str, Any]:
    """Stamp a product's refund policy for a WRITE, in place. Pure -- no I/O, so both write paths share it.

    plans/REFUND_POLICY.md step 5, and the correction that actually stops the bug. The dashboard used to
    decide what a product promised: a hardcoded literal in `stores/products.js` that reached live pages and
    claimed a provenance nothing ever read. Now the client sends an override INTENT or nothing, and the
    promise is composed here.

    Four cases:

    - **A deliberate override** — the three structured choices are honoured and the sentence generated from
      them. Invalid vocabulary is left untouched so `validate_product_document` reports it as the input error
      it is, rather than this quietly substituting something the tenant did not ask for.
    - **`tip_jar_default`** — left alone. `handlers/tip_jar_provision.py` writes non-refundable because a tip
      is not a purchase, and a tenant's physical-goods default must never make tips refundable.
    - **Anything else the client sent, including the old literal — DISCARDED.** This is the point: an old
      cached dashboard bundle still posting the literal gets the tenant's real default written instead. A
      browser is not a place you can enforce anything.
    - **No tenant default for the class** — the platform fallback, with `source` saying honestly that nobody
      chose it.

    Only touches a document being WRITTEN. Stored products keep their policy until the tenant next saves them
    -- the author's rule: nothing alters old data, everything is organic.
    """
    if not isinstance(document, dict):
        return document
    stored = document.get("refund_policy")
    stored = stored if isinstance(stored, dict) else {}
    policy_class = product_class(document)
    source = _text(stored.get("source"))

    if source == SOURCE_PRODUCT_OVERRIDE:
        try:
            document["refund_policy"] = build(
                policy_class,
                refund_window=_text(stored.get("refund_window")),
                condition=_text(stored.get("condition")),
                return_method=_text(stored.get("return_method")),
                # Carried through like every other structured choice. Left out, `build` supplied the
                # status-quo default instead and a tenant who overrode a product to promise free returns
                # silently got "paid by the customer" -- their choice discarded by the write path that
                # exists to honour it.
                return_shipping=_text(stored.get("return_shipping")),
                restocking_fee=stored.get("restocking_fee_percent"),
                original_shipping=_text(stored.get("original_shipping")),
                processing_days=stored.get("refund_processing_days"),
                resolution=_text(stored.get("resolution")),
                full_policy=_text(stored.get("full_policy")),
                return_note=_text(stored.get("return_note")),
                keep_it_below=stored.get("keep_it_below"),
                source=SOURCE_PRODUCT_OVERRIDE,
            )
        except RefundPolicyError:
            pass
        return document

    if source == SOURCE_TIP_JAR:
        return document

    # NOTHING IS STAMPED. The product used to receive a frozen copy of the tenant's default here, which
    # is why changing a default in Configuration changed nothing until every product happened to be
    # edited for some other reason -- a tenant could set their policy, press Save, and watch their pages
    # go on saying the old thing forever (plans/REFUND_POLICY_AND_GUARANTEES.md P3).
    #
    # `Product.refund_policy` is now the OVERRIDE CHANNEL ONLY: present when this product was
    # deliberately given its own terms, or when tip_jar_provision wrote one, and absent otherwise. The
    # promise is composed at publish from the live default instead, so the artifact still holds a
    # snapshot -- one refreshed every publish, which is the whole point.
    #
    # Removed rather than left as it was, because leaving the old stamp would mean a product edited
    # today keeps promising what the platform fallback said in October while its neighbours resolve
    # correctly, and the two would be indistinguishable on the page.
    document.pop("refund_policy", None)
    return document
