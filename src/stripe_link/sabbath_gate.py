"""Shared handler helper: refuse a sale while the tenant's store is closed for the Sabbath.

The cross-cutting twin of `entitlement_gate`, and here for the same reason: four handlers now take money
(`checkout`, `cart_checkout`, `upsell`, `booking`) and a closure enforced at three of them is worse than
one enforced nowhere — the tenant believes their shop is shut while an upsell link quietly keeps selling.

**One module so the REFUSAL is identical too.** The status code, the error code and the body shape are
decided here rather than at four call sites, because a buyer who meets this at checkout and again on an
upsell should not be told two different things, and a dashboard reading `store_closed_sabbath` should not
have to know which door the shopper came through.

Everything fails OPEN. See `domain/sabbath.assert_open`: refusing a sale the tenant did not ask to refuse
is worse than taking one during a window we could not compute.
"""
from typing import Any

from stripe_link.common import error_response
from stripe_link.domain.sabbath import SabbathClosedError, assert_open

__all__ = ["SabbathClosedError", "assert_store_open", "closed_response"]


def site_organization_for(tenant_id: str, page_id: str, mode: str) -> dict[str, Any]:
    """The organization of the Site this sale belongs to — for its COORDINATES.

    Reuses `sender_identity.site_organization`, the one place that already answers *which of this
    tenant's businesses is this?*, rather than walking the page->Site edge a fourth time.

    Fails to `{}`, which leaves the store OPEN: a closure that fired because a Site lookup hiccuped would
    refuse a sale the tenant never asked to refuse.
    """
    try:
        from stripe_link.sender_identity import site_organization

        return site_organization(tenant_id, page_id=page_id, mode=mode) or {}
    except Exception:  # noqa: BLE001 - see the docstring
        import logging

        logging.getLogger(__name__).exception("sabbath: could not resolve the Site for %s/%s",
                                              tenant_id, page_id)
        return {}


def timezone_for(organization: dict, profile: dict) -> str:
    """The zone the window is computed in, Site before account.

    `working_day` already resolves exactly this pair for the shipping cutoff, so the Sabbath uses the
    same answer: a tenant who told us their shop keeps Denver hours should not have to say it twice, and
    two resolutions of "which timezone is this business in" would eventually disagree.
    """
    try:
        from stripe_link.domain.store_timezone import working_day

        zone, _cutoff = working_day(organization, (profile or {}).get("business"))
        return zone or "UTC"
    except Exception:  # noqa: BLE001 - UTC is visibly a placeholder, not a plausible wrong answer
        import logging

        logging.getLogger(__name__).exception("sabbath: could not resolve a timezone; using UTC")
        return "UTC"


def assert_store_open(profile: Any, *, tenant_id: str, page_id: str = "", mode: str = "live",
                      now: Any = None) -> None:
    """Raise `SabbathClosedError` if this tenant has closed their store right now.

    Call it AFTER the platform's own refusals (billing hold, suspension). Those are the platform refusing
    on its own behalf; this is the merchant's choice about their own shop, and a suspended store reported
    as merely observing the Sabbath would tell a shopper to come back on Sunday to a shop we closed.
    """
    organization = site_organization_for(tenant_id, page_id, mode)
    assert_open(profile, organization, timezone_name=timezone_for(organization, profile), now=now)


def closed_response(exc: SabbathClosedError) -> dict[str, Any]:
    """The one refusal every transaction point returns.

    **503, not 403.** This is temporary and the shopper SHOULD come back; 403 invites a buyer to give up
    and tells a crawler the URL is forbidden. The resume moment travels in the body so a closure page can
    say WHEN, in the store's own zone — "closed" without "until when" is the difference between a pause
    and a dead link.
    """
    return error_response(
        "This store is closed for the Sabbath.", status_code=503, code="store_closed_sabbath",
        extra={"resume_at": exc.resume_at.isoformat(), "timezone": exc.timezone_name},
    )
