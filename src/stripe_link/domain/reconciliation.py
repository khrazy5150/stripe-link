"""Rebuild a tenant's six money components from Stripe alone, and check the ledger against it.

`plans/MONEY_ACROSS_SILOS.md` P4. The plan left this deliberately unshaped — *"whether that becomes a
screen, an operator tool, or just a reconciliation check is a decision better made once the data is
actually complete"* — and the answer the data gives is **a reconciliation check**. A screen would be a
second, slower copy of Reports; a check answers the thing the author actually asked for on 2026-10-07,
after a live sale went missing: *"the ledger in our software must match Stripe to the penny."*

## Which components Stripe can actually be asked about

| component | source | authority |
|---|---|---|
| `gross` | `charge.amount_captured` | **Stripe's** |
| `stripe_fee` | balance transaction `fee_details` | **Stripe's** |
| `platform_fee` | balance transaction `fee_details` | **Stripe's** |
| `tax` | the SESSION's `total_details`, not the charge | Stripe's, one call away |
| `cogs` | metadata we stamped at checkout (P2) | ours |
| `shipping_cost` | metadata we wrote at label purchase (P3) | ours |

**The plan said Stripe knows four of six. From a charge listing it knows three.** `tax` is on the
Checkout Session, and a charge does not carry its session — so reconstructing it costs a lookup per
charge, which this module accepts as an argument rather than pretending it is free. Zero tax is also the
true answer for every tenant today, Stripe Tax being off, so `known` says which it is instead of letting
a correct zero and an unasked question look identical.

**Only the first three are reconciled.** `cogs` and `shipping_cost` are values we wrote into Stripe
ourselves; comparing them with the ledger they came from would be reading back our own writes and calling
the agreement a check. They are reconstructed — that is the point of P3 — and never asserted against.

## What the check is for

Drift is **reported, never corrected.** Both times this went wrong the cause was a missing event and a
mis-keyed write; neither is fixed by nudging a total until it matches, and a self-correcting ledger would
have hidden both. The orphan pass next door answers "is there money here with no order?"; this answers
"and do the ones we do hold add up?".
"""
from __future__ import annotations

from typing import Any

from stripe_link.domain import cogs as cogs_metadata
from stripe_link.domain import shipping_cost_metadata
from stripe_link.domain.fee_reconciliation import fees_from_balance_transaction
from stripe_link.domain.orphan_charges import (invoice_id_of, is_ours, is_recordable,
                                               order_id_for_invoice)

# A reported disagreement must be a real one. A charge inside the sweep's window can still be mid-settle,
# and the sweep's own `MIN_AGE_SECONDS = 900` already excludes the young ones -- so anything left is
# either settled or unsettled-and-visible-as-such, and no slack is needed to absorb rounding. Stated as a
# constant anyway, because the first instinct on a false alarm is to widen it, and it should be widened
# HERE with a reason rather than in a caller.
TOLERANCE_CENTS = 0


def components_from_charge(charge: dict[str, Any], *, payment_intent: dict[str, Any] | None = None,
                           session: dict[str, Any] | None = None) -> dict[str, Any]:
    """One charge as the ledger's six components, in the ledger's sign convention, plus what is `known`.

    Costs are stored NEGATIVE, exactly as `ledger.sale_entry` stores them, so that summing a component
    across charges means the same thing here as it does there and "up" is always good.

    **`payment_intent` is where shipping cost lives, and the charge is not.** A charge's metadata is a
    copy frozen when the charge was created; P3 writes the label's cost onto the PaymentIntent *after*
    that, when the carrier is paid. So the charge's copy can never carry it, and passing only the charge
    yields `shipping_known: False` rather than a wrong zero. COGS is stamped before the charge exists and
    is read from either.
    """
    charge = charge if isinstance(charge, dict) else {}
    pi = payment_intent if isinstance(payment_intent, dict) else {}

    gross = abs(_whole(charge.get("amount_captured")))
    refunded = abs(_whole(charge.get("amount_refunded")))
    fees = fees_from_balance_transaction(charge.get("balance_transaction"))

    charge_meta = charge.get("metadata") if isinstance(charge.get("metadata"), dict) else {}
    pi_meta = pi.get("metadata") if isinstance(pi.get("metadata"), dict) else {}
    costs = cogs_metadata.from_metadata({**charge_meta, **pi_meta})
    postage = shipping_cost_metadata.from_metadata(pi_meta)

    tax_known = False
    tax = 0
    if isinstance(session, dict):
        totals = session.get("total_details")
        if isinstance(totals, dict) and totals.get("amount_tax") is not None:
            tax, tax_known = abs(_whole(totals.get("amount_tax"))), True

    return {
        "charge_id": str(charge.get("id") or ""),
        "amounts": {
            "gross": gross - refunded,
            "stripe_fee": -abs(_whole(fees.get("stripe_fee"))),
            "platform_fee": -abs(_whole(fees.get("platform_fee"))),
            "tax": tax,
            "cogs": -abs(_whole(costs.get("cogs"))),
            "shipping_cost": -abs(_whole(postage.get("shipping_cost"))),
        },
        "refunded": refunded,
        # WHICH FIGURES ARE ANSWERS AND WHICH ARE SILENCE. Every component above reads as a number, and
        # three of them are legitimately zero for most tenants today -- so without this map a
        # reconstruction cannot tell "no fee" from "not settled yet", and a profit built on it would be
        # the inflated-margin bug arriving from a new direction.
        "known": {
            "fees": bool(fees),
            "cogs": bool(costs.get("known")),
            "shipping": bool(postage.get("known")),
            "tax": tax_known,
        },
    }


def summarize_charges(charges, *, mode: str = "", this_silo: str = "",
                      payment_intents: dict[str, Any] | None = None,
                      sessions: dict[str, Any] | None = None) -> dict[str, Any]:
    """The same six totals `ledger.summarize` produces, derived from Stripe instead of from our table.

    Scoped by the SAME ownership rule the orphan pass uses, because both deployments hold credentials for
    the same connected account and each therefore lists the other's charges. Summing without that filter
    is how production reported the sandbox silo's money as its own (P4, defect 2) — a reconstruction
    without it would be a confident total of two silos' takings.

    `payment_intents` and `sessions` are id-keyed lookups the caller supplies when it has them. Absent,
    the result is honest about what it could not reach rather than quietly short.
    """
    payment_intents = payment_intents or {}
    sessions = sessions or {}
    totals = {"gross": 0, "stripe_fee": 0, "platform_fee": 0, "tax": 0, "cogs": 0, "shipping_cost": 0}
    counted = refunded = 0
    gaps = {"fees": 0, "cogs": 0, "shipping": 0, "tax": 0}

    for charge in charges or []:
        if not is_recordable(charge) or not is_ours(charge, this_silo=this_silo, mode=mode):
            continue
        pi_id = _id_of(charge.get("payment_intent"))
        row = components_from_charge(
            charge,
            payment_intent=payment_intents.get(pi_id),
            session=sessions.get(pi_id) or sessions.get(str(charge.get("id") or "")),
        )
        for key, value in row["amounts"].items():
            totals[key] += value
        refunded += int(row["refunded"])
        counted += 1
        for key in gaps:
            if not row["known"].get(key):
                gaps[key] += 1

    net = totals["gross"] + totals["stripe_fee"] + totals["platform_fee"]
    complete = counted > 0 and not gaps["cogs"] and not gaps["shipping"]
    return {
        "totals": totals,
        "net": net,
        # ONLY WHEN EVERY COST IS ACCOUNTED FOR, by the same rule `summarize` applies to the ledger: a
        # profit figure that silently excludes the charges it could not cost is worse than no figure.
        "profit": (net + totals["cogs"] + totals["shipping_cost"] - totals["tax"]) if complete else None,
        "profit_known": complete,
        "charges": counted,
        "refunded": refunded,
        "incomplete": gaps,
        "source": "stripe",
    }


def sale_entry_ids(charge: dict[str, Any]) -> list[str]:
    """The ledger ids under which THIS charge's sale could have been written, best candidate first.

    Deterministic ids are what make a bounded check possible at all: without them the only way to ask
    "does the ledger hold this charge?" is to read the tenant's entire financial history every five
    minutes, which grows forever and costs more the longer a tenant has been successful.

    **Two candidates, because two writers chose two keys.** `sale_entry_from_order` keys on
    `payment_intent or order_id`, and a subscription order has no PaymentIntent field at all (P4, defect
    1), so a renewal lands under `le_sale_order_<invoice>`. The manual invoicing path in
    `stripe_webhook.py` keys the same situation on the invoice's PaymentIntent instead. An invoice charge
    therefore has to be asked about both ways, invoice first, exactly as the orphan pass matches the
    invoice first and for the same reason.
    """
    invoice_id = invoice_id_of(charge)
    payment_intent = _id_of((charge or {}).get("payment_intent"))
    candidates = []
    if invoice_id:
        candidates.append(f"le_sale_{order_id_for_invoice(invoice_id)}")
    if payment_intent:
        candidates.append(f"le_sale_{payment_intent}")
    return candidates


def audit(charges, *, entry_for_id, mode: str = "", this_silo: str = "") -> dict[str, Any]:
    """Per charge: does the ledger hold the same money Stripe does? Bounded, and never raises.

    `entry_for_id` fetches one ledger entry by id — a point read, so the whole pass costs at most two
    lookups per charge and nothing at all per charge already in hand.

    **A charge with no entry is NOT reported here.** That is the orphan pass's finding, next door in the
    same loop, and reporting it twice would double every alarm for one missing sale. This pass is about
    the charges we DO hold being right; `unmatched` counts them so the two tallies can be read together.

    Fees are only compared once Stripe has settled them. Our stored fee starts as an estimate by design
    (`fee_reconciliation.ESTIMATE`) and the sweep's own job is to true it up — so comparing an unsettled
    charge would report the sweep's pending work as a discrepancy, every five minutes, for fifteen
    minutes, on every sale.
    """
    # `fee_checked` COUNTS THE CHARGES WHOSE FEES WERE ACTUALLY COMPARED, which is not a diagnostic
    # nicety: the fee half only runs when the caller expanded `balance_transaction`, and without this
    # counter a listing that forgot the expand looks exactly like a listing where everything agreed.
    # Three of the defects P4 fixed were code present and never reached, found only by someone reading a
    # dashboard by eye a day later.
    out = {"examined": 0, "matched": 0, "unmatched": 0, "failed": 0, "fee_checked": 0,
           "findings": [], "worst_cents": 0}
    for charge in charges or []:
        if not is_recordable(charge) or not is_ours(charge, this_silo=this_silo, mode=mode):
            continue
        out["examined"] += 1
        entry = None
        entry_id = ""
        try:
            for candidate in sale_entry_ids(charge):
                entry = entry_for_id(candidate)
                if entry:
                    entry_id = candidate
                    break
        except Exception:  # noqa: BLE001 - an unreadable table is not a disagreement about money
            out["failed"] += 1
            continue
        if not entry:
            out["unmatched"] += 1
            continue
        out["matched"] += 1
        if fees_from_balance_transaction(charge.get("balance_transaction")):
            out["fee_checked"] += 1
        finding = _compare_one(charge, entry, entry_id)
        if finding:
            out["findings"].append(finding)
            out["worst_cents"] = max(out["worst_cents"], int(finding["worst_cents"]))
    out["agrees"] = not out["findings"]
    return out


def _compare_one(charge: dict[str, Any], entry: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    """Stripe's view of one charge against the ledger entry for it, or None when they agree.

    `gross` is compared GROSS of refunds, because the sale entry records what was taken and a reversal is
    a separate entry of its own. Netting one side and not the other is the mistake that made the first
    draft of this module report a refunded sale as a disagreement.
    """
    amounts = entry.get("amounts") if isinstance(entry.get("amounts"), dict) else {}
    fees = fees_from_balance_transaction(charge.get("balance_transaction"))
    drift: dict[str, int] = {
        "gross": abs(_whole(charge.get("amount_captured"))) - abs(_whole(amounts.get("gross"))),
    }
    # Only once Stripe has a number of its own. See `audit`: ours is an estimate until the sweep trues it
    # up, and an estimate is a correct intermediate state rather than a discrepancy.
    if fees:
        drift["stripe_fee"] = abs(_whole(fees.get("stripe_fee"))) - abs(_whole(amounts.get("stripe_fee")))
        drift["platform_fee"] = (abs(_whole(fees.get("platform_fee")))
                                 - abs(_whole(amounts.get("platform_fee"))))
    worst = max((abs(value) for value in drift.values()), default=0)
    if worst <= TOLERANCE_CENTS:
        return None
    component = max(drift, key=lambda key: abs(int(drift.get(key) or 0)))
    return {
        "charge_id": str(charge.get("id") or ""),
        "entry_id": entry_id,
        "component": component,
        "drift": drift,
        "worst_cents": worst,
        "fees_settled": bool(fees),
    }


def describe(result: dict[str, Any]) -> str:
    """One line an operator can act on, naming the DIRECTION and the worst charge.

    Direction matters more than magnitude: "Stripe is ahead" is money taken and not recorded, "the ledger
    is ahead" is an entry with no charge behind it. They are different bugs and a bare delta makes the
    reader work that out. An earlier version of this named `net`, which hid the case it most needed to
    show — a sale we never recorded that was later refunded nets to zero on both sides.
    """
    findings = result.get("findings") or []
    examined, unmatched = result.get("examined", 0), result.get("unmatched", 0)
    if not findings:
        return (f"ledger agrees with Stripe on {result.get('matched', 0)} of {examined} charges"
                + (f" ({unmatched} not held here)" if unmatched else ""))
    worst = max(findings, key=lambda f: int(f.get("worst_cents") or 0))
    cents = int((worst.get("drift") or {}).get(worst.get("component")) or 0)
    ahead = "Stripe is ahead of the ledger" if cents > 0 else "the ledger is ahead of Stripe"
    return (f"{len(findings)} of {examined} charges disagree; worst {worst.get('charge_id')}: "
            f"{ahead} on {worst.get('component')} by {abs(cents)} cents "
            f"(entry {worst.get('entry_id')})")


def _id_of(value: Any) -> str:
    """Stripe hands a reference as an id or as the whole object once a caller expands it."""
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")


def _whole(value: Any) -> int:
    """int() rather than isinstance: a document read back from DynamoDB carries Decimal, and an
    isinstance check against int passes on a fixture and fails on stored data."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
