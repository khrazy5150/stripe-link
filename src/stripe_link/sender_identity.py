"""WHO a tenant-authored email is from: the Site's business, resolved per message.

Separate from `mailer.py` ON PURPOSE. This module is the only thing in the codebase that reads the Sites
and Pages tables in order to name a sender, and `tests/test_env_var_grants.py` propagates what a module
reaches to every function that imports it. Left in the mailer it put fifteen functions short of
`SITES_TABLE` / `PAGES_TABLE` -- fifteen functions that merely SEND a message, each then declared both
names and granted read on both tables, for a lookup they never perform (measured, not guessed). Here, only the emitters that actually resolve a Site reach them
(plans/SITE_AS_BUSINESS_IDENTITY.md §4, plans/TRANSFORM_BUDGET.md Phase 2).

`mailer.send_email` keeps its own last-resort fallback to `tenant_email_identity`, which reads the user
profile and nothing else: a caller that states no sender at all still gets the tenant's name, and
platform-authored mail (a verification code) has no Site by definition.
"""

import os
from typing import Any

from stripe_link.mailer import tenant_email_identity


def site_organization(tenant_id: str, *, site_id: str = "", page_id: str = "", mode: str = "live",
                      sites_repo: Any | None = None, pages_repo: Any | None = None) -> dict[str, Any]:
    """The `organization` of the Site behind one message, or `{}` when no Site can be named.

    Two ways in, in order of directness:

    1. `site_id` -- the caller already knows which Site. One keyed read.
    2. `page_id` -- the caller knows WHERE the customer converted. The page carries a `site_id` reverse
       edge, so this is two keyed reads, falling back to a scan of the tenant's Sites when the edge is
       missing or stale (`domain.sites.find_site_for_page`; plans/SITE_AS_BUSINESS_IDENTITY.md §3.1).

    With neither, there is one more honest answer: if the tenant has exactly ONE Site carrying an
    organization, that is not a guess -- it is the only business they have. Two or more and this returns
    `{}` and the caller falls back to the tenant, because "the first Site with an organization" is a coin
    flip and picking it is how a Quill customer's invite came to be signed "Poliaxis Nutrition". That is
    the whole difference between this and the two sweep-local helpers it replaced.

    NEVER RAISES, for the same reason the rest of identity resolution does not: a failure here costs a
    business NAME, and the alternative is costing the message.

    `mode` is not optional in spirit. A Site lives at `SITE#<mode>#<site_id>` and a page at
    `PAGE#<mode>#<page_id>`, so resolving a test-mode order against the live partition answers with the
    wrong business or with nothing at all. It defaults to live because every sweep that mails a real
    customer is live-only; an emitter that can run in either mode MUST pass its own.
    """
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return {}
    try:
        if sites_repo is None:
            if not os.environ.get("SITES_TABLE"):
                return {}
            from stripe_link.repositories.documents import sites_repository

            sites_repo = sites_repository(mode=mode)
        site = None
        if str(site_id or "").strip():
            site = sites_repo.get(tenant_id, str(site_id).strip())
        elif str(page_id or "").strip():
            from stripe_link.domain.sites import find_site_for_page

            if pages_repo is None and os.environ.get("PAGES_TABLE"):
                from stripe_link.repositories.documents import pages_repository

                pages_repo = pages_repository(mode=mode)
            # The page read is only a SHORTCUT: it supplies the `site_id` edge so the lookup is keyed
            # instead of a scan. If it fails, `find_site_for_page` still finds the Site by looking for
            # this page_id in each Site's route map, so a throttled Pages table costs latency, not the
            # answer.
            try:
                page = (pages_repo.get(tenant_id, str(page_id).strip()) or {}) if pages_repo else {}
            except Exception:  # noqa: BLE001
                page = {}
            site = find_site_for_page(sites_repo, tenant_id, str(page_id).strip(), page=page)
        org = (site or {}).get("organization")
        if isinstance(org, dict) and str(org.get("name") or "").strip():
            return dict(org)
        return _the_only_organization(sites_repo, tenant_id)
    except Exception:  # noqa: BLE001 - branding is worth less than delivery
        return {}


def _the_only_organization(sites_repo: Any, tenant_id: str) -> dict[str, Any]:
    """The tenant's organization when there is exactly ONE to be had, else `{}`.

    Reached when nothing narrowed the message to a Site: mail with no page, or a page whose Site carries no
    organization. One candidate is unambiguous and strictly better than the tenant profile, which is empty
    on every tenant that has ever existed. Two candidates is a question this function cannot answer, and
    answering it anyway is the bug (plans/SITE_AS_BUSINESS_IDENTITY.md §1).
    """
    found = [org for org in ((site or {}).get("organization") for site in sites_repo.list_for_tenant(tenant_id))
             if isinstance(org, dict) and str(org.get("name") or "").strip()]
    return dict(found[0]) if len(found) == 1 else {}


def sending_identity(tenant_id: str, *, site_id: str = "", page_id: str = "", mode: str = "live",
                     profiles_repo: Any | None = None, sites_repo: Any | None = None,
                     pages_repo: Any | None = None) -> dict[str, Any]:
    """WHO this message is from: `{business_name, reply_to, organization, source}`.

    The one resolver every tenant-authored emitter calls (plans/SITE_AS_BUSINESS_IDENTITY.md §4). No
    emitter reads `Site.organization` or the user profile directly -- that rule is the whole point. Before
    it, two sweeps held their own copy of "the first Site that has an organization", which is a coin flip
    for a tenant running more than one business, and both then let the tenant profile's single business
    name override whatever the Site said.

    `source` records WHICH answer was used -- "site", "tenant" or "none" -- so a wrong name on a real
    message can be traced to a resolution rather than guessed at. It is not used for branching.

    Reply-To is the tenant's verified address in every case; see `email_identity`.
    """
    organization = site_organization(tenant_id, site_id=site_id, page_id=page_id, mode=mode,
                                     sites_repo=sites_repo, pages_repo=pages_repo)
    identity = tenant_email_identity(tenant_id, profiles_repo, organization=organization)
    return {**identity, "organization": organization,
            "source": ("site" if str(organization.get("name") or "").strip()
                       else ("tenant" if identity["business_name"] else "none"))}
