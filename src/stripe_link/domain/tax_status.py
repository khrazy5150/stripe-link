"""Whether Stripe is calculating a tenant's sales tax, and what we are allowed to say about it.

`plans/TAX_STATUS_AND_THRESHOLDS.md`. The boundary that decides this module's whole shape is the
author's, 2026-09-30:

> **Stripe determines tax. We make sure the tenant knows it exists, knows whether theirs is on, and
> knows where to go. We never determine, declare, or imply anything about their liability.**

So every string here is deliberately about **what is happening** ("no sales tax is being collected") and
never about **what is owed**. Not "you must register in Ohio", not "you owe tax", not even "you have
nexus" — those are Stripe's job, the tenant's, or their accountant's, and the cost of being confidently
wrong is borne by the tenant.

## The one control, and why it is allowed to exist

The plan says *"A control labelled 'Enable Stripe Tax' would imply the platform can make that statement
… so the control does not exist."* That is right about **compliance** and it does not rule out a control
over **our own behaviour**: whether we ask Stripe to calculate at checkout. The distinction is
`may_enable` — the switch is only offered once Stripe **already** reports `status: "active"`, which means
the tenant has done the head-office and registration work in their own Dashboard. We are never the thing
that makes the tax claim; we are the thing that acts on a claim Stripe has already accepted.

## Verified against Stripe's docs, 2026-10-12

- `GET /v1/tax/settings` with `Stripe-Account: acct_…` **works for Standard accounts** — the open
  question this plan carried ("readable by the platform?") is answered yes.
- `status` is `"active"` or `"pending"`; `status_details.pending.missing_fields` names what is missing.
- `tax.settings.updated` is a **Connect** webhook event, so the cached status can be pushed rather than
  polled.
- **`automatic_tax[enabled]=true` fails on a `pending` account**, which is exactly the trap the plan
  predicted — hence `calculates()` and nothing else decides whether we send it.
- **With no registration in the buyer's jurisdiction the calculation returns ZERO tax, not an error.** So
  an active-but-unregistered tenant is safe: they get a $0 tax line, not a broken checkout.
- *"`defaults.tax_code` and `defaults.tax_behavior` are only required if not provided in the product or
  price on each API call."* **This codebase never sets either on a Price** — only shipping rates carry
  them (`domain/shipping_charges.py`). So for THIS integration the account default is not optional, and
  `may_enable` requires it. Without that check a tenant could switch tax on, have every session fall
  down the fail-open ladder, and collect nothing while the screen said "Calculating" — a silent failure
  dressed as success, which is the single worst outcome available here.
"""
from __future__ import annotations

from typing import Any

ACTIVE = "active"
PENDING = "pending"
# Not a Stripe value. Ours, for "we asked and could not find out" -- a revoked key, an outage, an account
# that is not connected. It must never be shown as "no tax due"; it is shown as "we cannot tell".
UNKNOWN = "unknown"

STATUSES = (ACTIVE, PENDING, UNKNOWN)

# Stripe's `missing_fields` keys are API names. A tenant reading the Payments screen should see the thing
# they have to go and do, in the words their Stripe Dashboard uses.
FIELD_LABELS = {
    "head_office": "head office address",
    "defaults.tax_code": "default tax category",
    "defaults.tax_behavior": "whether prices include tax",
}

# Stripe's own vocabulary. `inferred_by_currency` counts as set -- it is a real answer, not an absence.
TAX_BEHAVIOURS = ("inclusive", "exclusive", "inferred_by_currency")


def from_settings(settings: dict[str, Any] | None, now: int) -> dict[str, Any]:
    """A `tax.settings` payload as the fields we cache. `UNKNOWN` when the payload says nothing.

    An unreadable or absent payload is **not** treated as `pending`: "the tenant has not finished setting
    tax up" and "we could not ask" are different facts that deserve different words, and collapsing them
    would have us nudging a tenant about work they may already have done.
    """
    settings = settings if isinstance(settings, dict) else {}
    raw = str(settings.get("status") or "").strip().lower()
    status = raw if raw in (ACTIVE, PENDING) else UNKNOWN
    details = settings.get("status_details") if isinstance(settings.get("status_details"), dict) else {}
    pending = details.get(PENDING) if isinstance(details.get(PENDING), dict) else {}
    missing = [str(f) for f in (pending.get("missing_fields") or []) if f]
    defaults = settings.get("defaults") if isinstance(settings.get("defaults"), dict) else {}
    behaviour = str(defaults.get("tax_behavior") or "").strip().lower()
    return {
        "status": status,
        "missing_fields": missing,
        # Captured because OUR prices never carry a tax behaviour, so the account default is what decides
        # whether a session can be created at all. See the module docstring.
        "tax_behavior": behaviour if behaviour in TAX_BEHAVIOURS else "",
        "checked_at": int(now),
    }


def apply_settings(tax_config: dict[str, Any] | None, settings: dict[str, Any] | None,
                   now: int) -> tuple[dict[str, Any], bool]:
    """Refresh the cached status, **preserving the tenant's `enabled` intent**. Returns `(config, changed)`.

    Deliberately the same shape as `bnpl.apply_capability_statuses`, and for the same reason: the
    Payments-screen read and the webhook push both land here, so the two can never refresh differently.

    **A tenant who switched tax on and then fell out of `active` keeps their intent recorded** rather
    than having it silently cleared. `calculates()` stops sending `automatic_tax` on its own, so nothing
    unsafe happens meanwhile — and when they fix their Stripe settings their choice is still there,
    instead of appearing to have been turned off by us.
    """
    current = dict(tax_config or {})
    fresh = from_settings(settings, now)
    changed = (current.get("status") != fresh["status"]
               or list(current.get("missing_fields") or []) != fresh["missing_fields"]
               or current.get("tax_behavior") != fresh["tax_behavior"])
    current.update(fresh)
    current["enabled"] = bool(current.get("enabled"))
    return current, changed


def may_enable(tax_config: dict[str, Any] | None) -> bool:
    """Whether the switch is offered at all. Stripe says `active` AND a default tax behaviour is set.

    The first half is the liability boundary in one predicate: we never offer a control whose effect
    depends on a tax claim Stripe has not already accepted.

    The second half is this integration's own requirement, not Stripe's — our Prices carry no
    `tax_behavior`, so without the account default `automatic_tax` cannot price a line and the session
    fails. Checking it here is what stops a tenant switching tax on and silently collecting nothing.
    """
    config = tax_config or {}
    return str(config.get("status") or "") == ACTIVE and bool(config.get("tax_behavior"))


def calculates(tax_config: dict[str, Any] | None) -> bool:
    """Whether checkout should send `automatic_tax[enabled]=true`. BOTH conditions, every time.

    The tenant's intent alone is not enough: `automatic_tax` errors outright on a `pending` account, so
    acting on a stale `enabled` would turn a tenant's tax settings lapsing into **refused checkouts**.
    An uncollected tax is recoverable and the tenant can be told; a sale that never completed is gone.
    """
    config = tax_config or {}
    return bool(config.get("enabled")) and may_enable(config)


def missing_labels(tax_config: dict[str, Any] | None) -> list[str]:
    """What Stripe says is missing, in a tenant's words rather than API names."""
    out = []
    for field in (tax_config or {}).get("missing_fields") or []:
        key = str(field)
        out.append(FIELD_LABELS.get(key, key.replace("_", " ").replace(".", " ")))
    return out


def describe(tax_config: dict[str, Any] | None, *, connected: bool = True) -> dict[str, Any]:
    """`{state, label, headline, detail, may_enable, calculating}` — everything the screen renders.

    The copy lives HERE rather than in the component because it is the part of this feature that carries
    legal risk, and a sentence about a tenant's tax that only exists inside a Vue template is a sentence
    nobody can test. Three states, because the right thing to say genuinely differs:

    * **active** — say it is on, and stop nudging.
    * **pending** — the most useful nudge there is: they started and did not finish, and Stripe will
      name what is missing.
    * **unknown** — say only that no tax is being collected. Never a word about whether any is due.
    """
    config = tax_config or {}
    if not connected:
        return {
            "state": UNKNOWN, "label": "Not available",
            "headline": "Connect Stripe to see your sales tax status.",
            "detail": "", "may_enable": False, "calculating": False,
        }
    status = str(config.get("status") or UNKNOWN)
    calculating = calculates(config)
    # ACTIVE BY STRIPE, BLOCKED BY US. Reported as its own case rather than folded into `pending`,
    # because contradicting Stripe ("unfinished" when their Dashboard says active) would send a tenant
    # looking for the wrong thing. It names the one setting that is actually missing.
    if status == ACTIVE and not config.get("tax_behavior"):
        return {
            "state": ACTIVE, "label": "One setting left",
            "headline": "Stripe Tax is active, but we need to know whether your prices include tax.",
            "detail": ("Set a default tax behaviour in your Stripe Tax settings — inclusive or exclusive"
                       " — then turn this on."),
            "may_enable": False, "calculating": False,
        }
    if status == ACTIVE:
        return {
            "state": ACTIVE,
            "label": "Calculating" if calculating else "Ready",
            "headline": ("Stripe is calculating sales tax on your orders."
                         if calculating else "Stripe Tax is set up and ready to use."),
            # NOT a compliance statement. It explains a $0 tax line a tenant would otherwise read as a
            # bug -- Stripe returns zero tax where there is no registration for the buyer's location.
            "detail": ("Tax is added where you are registered. Orders from anywhere else show no tax."
                       if calculating
                       else "Turn this on to add sales tax at checkout."),
            "may_enable": True, "calculating": calculating,
        }
    if status == PENDING:
        missing = missing_labels(config)
        return {
            "state": PENDING, "label": "Unfinished",
            "headline": "Your Stripe Tax setup is not finished, so no sales tax is being collected.",
            "detail": ("Stripe still needs your " + _join(missing) + "."
                       if missing else "Stripe still needs some details before it can calculate tax."),
            "may_enable": False, "calculating": False,
        }
    return {
        "state": UNKNOWN, "label": "Not enabled",
        "headline": "No sales tax is being collected on your orders.",
        # The ONLY nudge this module makes, and it asks for the one action we can honestly ask for.
        # Monitoring is free, which is the fact that makes the suggestion worth making at all.
        "detail": "Stripe can monitor for free where you may need to register.",
        "may_enable": False, "calculating": False,
    }


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]
