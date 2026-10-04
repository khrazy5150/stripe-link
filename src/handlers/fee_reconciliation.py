"""Scheduled sweep: replace estimated Stripe fees with what Stripe actually took.

plans/FEE_RECONCILIATION.md Phase 1. The authoritative reconciliation pass, and the one that needs no
Stripe configuration: it reads orders that marked themselves an estimate, asks Stripe for the charge's
balance transaction, and corrects the order AND its ledger entry together.

**Why a sweep and not a webhook.** An upsell is a PaymentIntent we create ourselves, so nothing fires
afterwards to correct it, and the balance transaction is not attached yet when the handler asks -- proven
rather than assumed: `stripe returned []` on the create expansion and again on an immediate retry, on a
real funnel. A `charge.updated` subscription would narrow the window and is Phase 2, but the sweep stays
underneath it as the safety net, because an event that never arrives leaves no trace and a sweep that
finds nothing costs one scan.

**Every failure is per-order.** One tenant's revoked key, one unsettled charge, one Stripe outage must
not stop the pass: the next one picks up whatever this one left, because `fees_source` still says
`estimate` and the order is still inside the retry window.
"""
import logging
import os
import time

from stripe_link.domain.fee_reconciliation import _whole, drift, due, fees_of, settled
from stripe_link.domain.ledger import sale_entry_from_order
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import ledger_repository, orders_repository, stripe_keys_repository
from stripe_link.stripe_platform_secrets import checkout_credentials

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODES = ("test", "live")


def handler(event, context, *, orders_repo=None, ledger_repo=None, stripe_repo=None,
            secret_cipher=None, fetch_fees=None, true_up=None, now_fn=None, modes=MODES):
    """Reconcile both Stripe modes. Returns a per-mode tally, which is also what the logs carry."""
    from handlers.stripe_webhook import fetch_actual_fees, true_up_fees

    fetch_fees = fetch_fees or fetch_actual_fees
    true_up = true_up or true_up_fees
    secret_cipher = secret_cipher or KmsSecretCipher()
    now = int((now_fn or time.time)())
    stripe_repo = stripe_repo or (stripe_keys_repository() if os.environ.get("STRIPE_KEYS_TABLE") else None)

    tally = {}
    for mode in modes:
        tally[mode] = _reconcile_mode(
            mode, now,
            orders_repo=orders_repo or orders_repository(mode=mode),
            ledger_repo=ledger_repo or (ledger_repository(mode=mode) if os.environ.get("LEDGER_TABLE") else None),
            stripe_repo=stripe_repo, secret_cipher=secret_cipher,
            fetch_fees=fetch_fees, true_up=true_up)
    logger.info("fee reconciliation: %s", tally)
    return tally


def _reconcile_mode(mode, now, *, orders_repo, ledger_repo, stripe_repo, secret_cipher, fetch_fees, true_up):
    out = {"examined": 0, "corrected": 0, "unsettled": 0, "failed": 0, "drift_cents": 0}
    # SETTLE AGES, so the 180s gate can one day be argued from production rather than from two test-mode
    # charges. Read the caveat on `_settle_evidence` before trusting these: the sweep cannot observe a
    # charge settling EARLIER than the gate that let it look.
    ages: list[int] = []
    try:
        orders = orders_repo.scan_type()
    except Exception as exc:  # noqa: BLE001 - one mode's table problem is not the other's
        logger.warning("fee reconciliation could not scan %s orders: %s: %s", mode, type(exc).__name__, exc)
        return dict(out, failed=1)

    # Credentials are per TENANT, and resolving them costs a Secrets Manager read and a KMS decrypt. A
    # sweep touching twenty of one tenant's orders must pay for that once.
    creds: dict[str, tuple[str, str]] = {}
    for order in orders:
        if not due(order, now):
            continue
        out["examined"] += 1
        tenant_id = str(order.get("tenant_id") or "")
        try:
            if tenant_id not in creds:
                keys = (stripe_repo.get(tenant_id) if stripe_repo else None) or {}
                creds[tenant_id] = checkout_credentials(tenant_id, mode, keys, secret_cipher)
            api_key, account = creds[tenant_id]
            if not api_key:
                out["failed"] += 1
                continue
            age = now - _whole(order.get("created_at"))
            moved = reconcile_order(order, api_key=api_key, stripe_account=account, now=now,
                                    orders_repo=orders_repo, ledger_repo=ledger_repo,
                                    fetch_fees=fetch_fees, true_up=true_up)
            if moved is None:
                # Still not attached. Not a failure -- `fees_source` still says `estimate`, so the next
                # pass will ask again until the order ages out of the window.
                #
                # Logged with its age because this is the ONLY direct evidence the sweep produces about
                # how long settlement really takes: a charge that was still unsettled at N seconds puts a
                # hard floor under the delay. A success only puts a ceiling on it.
                out["unsettled"] += 1
                logger.info("fee settle: order=%s age=%ds NOT YET readable",
                            order.get("order_id"), age)
                continue
            out["corrected"] += 1
            out["drift_cents"] += moved
            ages.append(age)
            logger.info("fee settle: order=%s age=%ds readable drift=%+dc",
                        order.get("order_id"), age, moved)
        except Exception as exc:  # noqa: BLE001 - one bad order never stops the pass
            out["failed"] += 1
            logger.warning("fee reconciliation failed for %s: %s: %s",
                           order.get("order_id"), type(exc).__name__, exc)
    if ages:
        out["settled_age_min"] = min(ages)
        out["settled_age_max"] = max(ages)
    return out


def reconcile_order(order, *, api_key, stripe_account, now, orders_repo, ledger_repo,
                    fetch_fees=None, true_up=None):
    """Replace ONE order's estimated Stripe fee with the real one. Returns the drift in cents, or None
    when the balance transaction still is not there.

    The single-order primitive, so the 15-minute sweep and the `payment_intent.succeeded` webhook do the
    same thing rather than two things that drift apart -- the rule this codebase keeps relearning, most
    recently when an upsell grew a second shipping-pricing path.

    The caller decides WHICH orders to offer: the sweep by age, the webhook because Stripe just said this
    charge succeeded. Neither decides what correcting means.
    """
    from handlers.stripe_webhook import fetch_actual_fees, true_up_fees

    fetch_fees = fetch_fees or fetch_actual_fees
    true_up = true_up or true_up_fees
    before = fees_of(order)
    after = true_up(before, fetch_fees(str(order.get("payment_intent_id") or ""),
                                       api_key=api_key, stripe_account=stripe_account))
    if not settled(after):
        return None
    moved = drift(before, after)
    order["fees"] = after
    order["updated_at"] = now
    orders_repo.put(order)
    _restate_ledger(ledger_repo, order, now)
    if moved:
        logger.info("fee reconciliation corrected %s by %+d cents (%s -> %s)",
                    order.get("order_id"), moved, before.get("stripe_fee"), after.get("stripe_fee"))
    return moved


def _settle_evidence() -> str:
    """What the `fee settle:` log lines can and cannot tell you. Documentation, deliberately a function so
    it sits in the module a reader lands in rather than in a plan nobody opens.

    They record, per correction, how old the order was when its balance transaction proved readable. Over
    weeks that is a real production distribution, which is what the author asked for before tightening the
    180s gate to 120 (2026-10-04).

    **But it is censored data, and the censoring is ours.** The sweep only looks at orders older than
    `MIN_AGE_SECONDS`, so a charge that settled at 95s is first observed at 180s and recorded as 180.
    These lines can therefore prove "settled by N" and never "settled at N" -- they can justify LOOSENING
    the gate and can never, on their own, justify tightening it.

    To tighten it honestly, lower the gate below the suspected delay for a while and read the
    `NOT YET readable` lines instead: an order unsettled at 90s is direct evidence of a floor, and each
    one costs a single Stripe call. That is the experiment, and it is the opposite of the instinct to
    only log successes.
    """
    return __doc__ or ""


def _restate_ledger(ledger_repo, order, now):
    """Rewrite the order's ledger entry around the corrected fee.

    The entry id is deterministic (`le_sale_<pi>`), so appending the rebuilt row overwrites the same one
    rather than double-counting the sale -- the same property the webhook relies on to be replay-safe.

    **The original `source` is preserved**, read back off the stored row. Rebuilding would otherwise
    default it to `webhook`, which is the one thing an upsell is not, and would undo the provenance fix
    that made these rows legible in the first place.
    """
    if ledger_repo is None:
        return
    tenant_id = str(order.get("tenant_id") or "")
    entry_id = f"le_sale_{str(order.get('payment_intent_id') or order.get('order_id') or '')}"
    existing = ledger_repo.get(tenant_id, entry_id) or {}
    entry = sale_entry_from_order(order, now_epoch=now,
                                  source=str(existing.get("source") or "webhook"))
    if not entry:
        return
    # Keep the row's own history: when it first happened is not when we corrected it.
    if existing.get("occurred_at") is not None:
        entry["occurred_at"] = int(existing["occurred_at"])
    if existing.get("created_at") is not None:
        entry["created_at"] = int(existing["created_at"])
    ledger_repo.append(entry)
