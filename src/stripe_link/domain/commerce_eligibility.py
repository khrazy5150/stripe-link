"""Being reachable is not being authorized to transact (plans/COMMERCE_ELIGIBILITY.md).

A published page's artifact is publicly readable at the pages distribution, and the checkout href it bakes is
absolute and self-contained — `clientID`, `offer`, `page_id`, `price_id`, `mode`, nothing depending on the
host it loaded from. Checkout's only page gate is `status == "published"`. So a tenant can detach a page from
their Site, removing it from every hostname the platform governs, and keep running a fully transacting
storefront on platform infrastructure. Every takedown lever today operates on hostnames; none of them reach
the artifact URL.

The rule is NOT "attached to a Site", because an A/B variant must transact while detached: the visitor is on
the control's URL but the CTA comes from the variant's artifact and carries the variant's own `page_id`, which
is what `order.attribution.page_id` reads for conversion attribution. The rule is that the page's public
IDENTITY — itself, or the control it is a variant of — is attached to a Site. A page attached to nothing,
standing for nothing, is the case with no legitimate claim to take money.

Two properties matter more than the rule itself:

1. **It fails open on infrastructure, closed only on a definite answer.** A Sites read that raises, a missing
   table, an experiments lookup that breaks — none of those refuse, in any mode. Refusing a legitimate
   checkout is worse than the hole. Only a successful lookup that finds no Site can refuse, and only under
   `enforce`.
2. **Phase 1 measures without acting.** `ELIGIBILITY_ENFORCEMENT` defaults to `observe`: the verdict is
   computed and the interesting cases logged, and `refuse` is always False. Nobody has measured what real
   traffic on these paths looks like, so the rule earns enforcement by being quiet first.
"""
import json
import os
from typing import Any

from stripe_link.domain.sites import site_for_page

OFF = "off"
OBSERVE = "observe"
ENFORCE = "enforce"

# Why a checkout was allowed or would be refused. Distinct strings because they are what the P1 logs are
# counted by, and "could not tell" must never be tallied as "not attached".
NO_PAGE = "no_page"                        # no page context at all — not this rule's business
ATTACHED = "attached"                      # the ordinary case: the page is on a Site
VARIANT_OF_ATTACHED = "variant_of_attached"  # detached A/B variant borrowing an attached control's identity
NOT_ATTACHED = "not_attached"              # the hole: published, transacting, standing for nothing
NO_SITES_TABLE = "no_sites_table"          # not configured — cannot evaluate
LOOKUP_FAILED = "lookup_failed"            # read raised (IAM, throttle, bad table) — cannot evaluate

UNDECIDED = (NO_SITES_TABLE, LOOKUP_FAILED)


def enforcement() -> str:
    """`off`, `observe` (default) or `enforce`. An unrecognised value means `observe`, never `enforce`:
    enforcement is the one behaviour that must require saying so exactly."""
    raw = str(os.environ.get("ELIGIBILITY_ENFORCEMENT") or "").strip().lower()
    return raw if raw in (OFF, OBSERVE, ENFORCE) else OBSERVE


def _identity_page_id(tenant_id: str, page_id: str, experiments_repo: Any) -> str:
    """The page whose public identity this artifact carries — itself, or the control it is a variant of.

    Deliberately not `runtime.publishing.identity_page_id`: that one swallows a failed experiments read and
    returns `page_id`, which is correct for publishing (an artifact must ship) and wrong here — it would make
    a detached variant of an attached control look like it stands for nothing. Exceptions propagate so the
    caller records LOOKUP_FAILED instead of NOT_ATTACHED.
    """
    if experiments_repo is None:
        return page_id
    from stripe_link.domain.experiments import variant_of_running_experiment

    experiment = variant_of_running_experiment(page_id, experiments_repo.list_for_tenant(tenant_id))
    if not experiment:
        return page_id
    return str(experiment.get("control_page_id") or "") or page_id


def evaluate(*, tenant_id: str, page_id: str, sites_repo: Any, experiments_repo: Any = None) -> dict[str, Any]:
    """Whether the page behind this transaction has a public identity attached to a Site.

    Ordering is a cost decision as much as a logic one: the common case (the page is on a Site) is answered by
    the Sites read alone, and the experiments table is only consulted for a page that turned out to be
    attached to nothing. The money path pays one extra read, not two.
    """
    if not page_id or not tenant_id:
        return _verdict(True, NO_PAGE, page_id, "")
    if sites_repo is None:
        return _verdict(True, NO_SITES_TABLE, page_id, "")
    try:
        site = site_for_page(sites_repo, tenant_id, page_id)
        if site:
            return _verdict(True, ATTACHED, page_id, str(site.get("site_id") or ""))
        identity = _identity_page_id(tenant_id, page_id, experiments_repo)
        if identity and identity != page_id:
            control_site = site_for_page(sites_repo, tenant_id, identity)
            if control_site:
                return _verdict(True, VARIANT_OF_ATTACHED, identity, str(control_site.get("site_id") or ""))
        return _verdict(False, NOT_ATTACHED, identity or page_id, "")
    except Exception as exc:  # noqa: BLE001 - see module docstring: infrastructure never refuses a checkout
        return _verdict(True, LOOKUP_FAILED, page_id, "", detail=f"{type(exc).__name__}: {exc}")


def _verdict(eligible: bool, reason: str, identity: str, site_id: str, *, detail: str = "") -> dict[str, Any]:
    return {
        "eligible": eligible,
        "reason": reason,
        "identity_page_id": identity,
        "site_id": site_id,
        "detail": detail,
        # Set by `guard`, which is the only thing that knows the enforcement mode. Kept here so a caller can
        # never read a verdict and forget to ask.
        "refuse": False,
    }


def guard(*, path: str, tenant_id: str, page_id: str, sites_repo: Any, experiments_repo: Any = None,
          stripe_mode: str = "") -> dict[str, Any]:
    """The shared entry point for every transacting handler: evaluate, record, and say whether to refuse.

    Returns the verdict with `refuse` set. Under `observe` (the default) `refuse` is always False and the
    interesting cases are logged — that is Phase 1. Under `enforce` a definite NOT_ATTACHED refuses; an
    undecided verdict still does not. Under `off` nothing is read at all, which is the kill switch for the
    extra Dynamo read on the money path.
    """
    mode = enforcement()
    if mode == OFF:
        return _verdict(True, NO_PAGE, page_id, "")
    verdict = evaluate(
        tenant_id=tenant_id, page_id=page_id, sites_repo=sites_repo, experiments_repo=experiments_repo)
    verdict["refuse"] = bool(mode == ENFORCE and not verdict["eligible"])
    _record(verdict, path=path, tenant_id=tenant_id, page_id=page_id, stripe_mode=stripe_mode, mode=mode)
    return verdict


def _record(verdict: dict[str, Any], *, path: str, tenant_id: str, page_id: str, stripe_mode: str,
            mode: str) -> None:
    """One structured line per interesting verdict.

    Deliberately the same shape as `common._log_auth_gap` — a JSON object under a namespace key, carrying a
    `verdict` and an `enforced` flag — because that is the repo's other Phase 1 measurement
    (plans/API_AUTHENTICATION.md) and two measurements running at once should be countable with one idiom.

    The ordinary attached case is NOT logged: it is every checkout the platform takes, and paying CloudWatch
    to record "normal" buys nothing. `undecided` is its own verdict rather than being folded into
    `not_attached`, because a broken grant counted as a detached page would make Phase 1 read as "the rule is
    safe to enforce" for precisely the wrong reason.
    """
    reason = verdict["reason"]
    if reason in (ATTACHED, VARIANT_OF_ATTACHED, NO_PAGE):
        return
    record = {
        "phase": "P1", "verdict": reason, "path": path, "tenant": tenant_id, "page_id": page_id,
        "identity_page_id": verdict["identity_page_id"], "stripe_mode": stripe_mode or "",
        "undecided": reason in UNDECIDED, "enforcement": mode, "enforced": bool(verdict["refuse"]),
    }
    if verdict["detail"]:
        record["detail"] = verdict["detail"]
    print(json.dumps({"commerce_eligibility": record}))
