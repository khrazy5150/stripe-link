"""Is this Site shut for the Sabbath right now? -- the question the LIVE PAGE path asks.

Separate from `sabbath_gate` for one concrete reason: that module reaches `sender_identity`, which reads
the Pages table, so importing it from the live resolver would declare PAGES_TABLE on a function that never
looks at a page document (`tests/test_env_var_grants.py` catches exactly this, and caught it here). The
same propagation is why `timezone_for` was moved into `domain/sabbath`.

Everything here fails OPEN and serving. A store that went dark because a lookup hiccuped is a worse
outcome than one that stayed open through its own Sabbath.
"""
from typing import Any

from stripe_link.domain.sabbath import SabbathClosedError, assert_open, timezone_for


def tenant_settings(tenant_id: str) -> dict[str, Any]:
    """The tenant's OWN settings document (`TenantConfig`), where the Sabbath choice is stored.

    **Not the tenant PROFILE, deliberately, and it costs a read to say so.** The profile would have been
    free -- every caller here already holds it for the billing and suspension checks -- but it is written
    by the billing webhook as `tenant_repo.put({**tenant, **updates})`, a load-mutate-put. A tenant
    saving this setting in the ~100ms between that read and that write would have it silently reverted,
    which is the shared-document trap this codebase has already been bitten by. TenantConfig has exactly
    one writer: the tenant.

    The read is one keyed lookup against a Stripe round trip, so the trade is a few milliseconds for a
    class of bug that is invisible when it happens.

    Fails to `{}`, which leaves the store OPEN.
    """
    try:
        from stripe_link.repositories.documents import platform_config_repository

        return platform_config_repository().get(tenant_id) or {}
    except Exception:  # noqa: BLE001 - see the docstring
        import logging

        logging.getLogger(__name__).exception("sabbath: could not read settings for %s", tenant_id)
        return {}

def site_organization_by_id(tenant_id: str, site_id: str, mode: str) -> dict[str, Any]:
    """The organization of a Site named DIRECTLY, for its coordinates.

    The sibling of `site_organization_for`, which starts from a page_id and must walk page -> Site. The
    live page resolver already holds the `site_id`, so making it go the long way would cost a Pages read
    on every store request and would declare PAGES_TABLE on a function that never otherwise touches it
    (`sender_identity`'s docstring, on why that propagation matters).

    Fails to `{}`, which leaves the store OPEN.
    """
    try:
        import os

        if not site_id or not os.environ.get("SITES_TABLE"):
            return {}
        from stripe_link.repositories.documents import sites_repository

        site = sites_repository(mode=mode).get(tenant_id, str(site_id).strip()) or {}
        organization = site.get("organization")
        return organization if isinstance(organization, dict) else {}
    except Exception:  # noqa: BLE001 - see the docstring
        import logging

        logging.getLogger(__name__).exception("sabbath: could not resolve Site %s for %s", site_id,
                                              tenant_id)
        return {}


def closure_for_site(tenant_id: str, site_id: str, mode: str = "live", *, now: Any = None,
                     settings: Any = None, profile: Any = None):
    """`SabbathClosedError` if this Site is shut right now, else None. For the page resolver.

    The gate the PAYING handlers use raises, because there the closure must abort a sale. Here the caller
    is choosing which page to serve, so the closure is a value: serving a page is not an error.

    **The settings read short-circuits everything else.** This runs on the live store path, and the
    Sabbath is off for all but a handful of tenants -- so a tenant who has not switched it on pays one
    keyed lookup and no Site read, no profile read and no solar maths. (The Worker caches each resolve for
    60s, so even that one lookup happens about once a minute per path rather than once per visitor.)

    Returns None on ANY failure, which leaves the store OPEN and serving. A store that went dark because a
    lookup hiccuped would be the worst outcome this feature could produce.
    """
    try:
        if settings is None:
            settings = tenant_settings(tenant_id)
        from stripe_link.domain.sabbath import config as sabbath_config

        if not sabbath_config(settings)["enabled"]:
            return None
        organization = site_organization_by_id(tenant_id, site_id, mode)
        if profile is None:
            from stripe_link.repositories.documents import tenant_profiles_repository

            profile = tenant_profiles_repository().get(tenant_id, tenant_id) or {}
        assert_open(settings, organization, timezone_name=timezone_for(organization, profile), now=now)
    except SabbathClosedError as exc:
        return exc
    except Exception:  # noqa: BLE001 - see the docstring
        import logging

        logging.getLogger(__name__).exception("sabbath: could not decide closure for %s/%s", tenant_id,
                                              site_id)
        return None
    return None
