"""Scheduled re-check of every verified custom domain (plans/DOMAIN_HEALTH_SWEEP.md).

Runs on EventBridge, dispatched from `handlers.sites` on the `aws.events` shape — it shares that function
rather than owning one because the stack sits near CloudFormation's 1MB transform limit, and because this
IS the right home: it re-asks the question `check_domain` answers once.

Live-mode only, by construction: a test-mode Site cannot hold a custom domain (`_reject_non_live_site`),
so there is nothing to sweep in test.

The PRIMARY hostname only -- deliberately not the `www.` sibling an apex Site also provisions. That
redirect is best-effort (`_setup_www_redirect`): the store serves whether or not it issues, and a tenant
who never created its DNS rows is in the same observable state as one whose rows broke. Without
per-hostname history those are indistinguishable, so checking it would nag about a redirect some tenants
never wanted. The connect screen already shows those rows with a Verify button; this sweep is for
regressions, not for setup the tenant chose not to finish.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from stripe_link.domain.custom_domains import CustomDomainError, diagnose_dns_records, find_custom_hostname
from stripe_link.domain.domain_health import (
    UNHEALTHY,
    domain_health_notification,
    failing_records,
    health_record,
    hostname_health,
    should_notify,
)
from stripe_link.cloudflare_secrets import get_cloudflare_api_token

logger = logging.getLogger(__name__)


def _sites(sites_repo):
    from stripe_link.repositories.documents import sites_repository

    return sites_repo or sites_repository(mode="live")


def _notifications(notifications_repo):
    from stripe_link.repositories.documents import notifications_repository

    return notifications_repo or notifications_repository(mode="live")


def handler(event, context, *, sites_repo=None, notifications_repo=None, hostname_fetcher=None,
            diagnoser=None, now_fn=lambda: int(time.time())):
    fetch = hostname_fetcher
    if fetch is None:
        zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
        api_token = get_cloudflare_api_token()
        if not zone_id or not api_token:
            # Not configured is not a failure: an environment without Cloudflare has no custom domains to
            # check. Saying so once beats a scheduled error every day.
            logger.info("domain health sweep skipped: Cloudflare is not configured")
            return {"checked": 0, "unhealthy": 0, "notified": 0, "skipped": "not_configured"}

        def fetch(domain: str) -> dict[str, Any] | None:
            return find_custom_hostname(domain, zone_id=zone_id, api_token=api_token)
    diagnose = diagnoser or diagnose_dns_records
    repo = _sites(sites_repo)
    now = int(now_fn())
    checked = unhealthy = notified = 0

    for site in repo.scan_type():
        hosting = site.get("hosting") or {}
        domain = str(hosting.get("custom_domain") or "").strip()
        verified = bool((hosting.get("verification") or {}).get("verified"))
        # Only domains we told the tenant were working. A connect-in-progress has its own screen and its
        # own Verify button; nagging about one mid-setup would be a notice with no new action.
        if not domain or not verified:
            continue
        checked += 1
        provisioning = site.get("domain_provisioning") or {}
        previous = provisioning.get("health") or {}
        try:
            state, reason = hostname_health(fetch(domain))
        except CustomDomainError as exc:
            # Cloudflare unreachable or erroring is OUR problem, not the tenant's. Record nothing and say
            # nothing -- a notice here would blame them for our outage.
            logger.warning("domain health: cloudflare lookup failed for %s: %s", domain, exc)
            continue
        except Exception:  # noqa: BLE001 - one bad Site must never stop the sweep
            logger.exception("domain health: unexpected error checking %s", domain)
            continue

        failures: list[dict[str, Any]] = []
        if state == UNHEALTHY:
            unhealthy += 1
            try:
                failures = failing_records(diagnose(provisioning.get("dns_records") or []))
            except Exception:  # noqa: BLE001 - diagnosis only decorates the message
                logger.exception("domain health: diagnosis failed for %s", domain)

        notify = should_notify(previous, state)
        if notify:
            try:
                _notifications(notifications_repo).put(
                    domain_health_notification(site, reason, failures, now))
                notified += 1
            except Exception:  # noqa: BLE001
                logger.exception("domain health: could not write the notice for %s", domain)
                notify = False

        record = health_record(state, reason, now, previous, notify)
        if record != previous:
            try:
                # TARGETED, never put(site). A sweep over many Sites is the fan-out that loses sibling
                # writes, and a concurrent check_domain writes this same document
                # (feedback-shared-document-read-modify-write).
                repo.update_domain_health(
                    str(site.get("tenant_id") or ""), str(site.get("site_id") or ""), record)
            except Exception:  # noqa: BLE001
                logger.exception("domain health: could not record state for %s", domain)

    logger.info("domain health sweep: checked=%s unhealthy=%s notified=%s", checked, unhealthy, notified)
    return {"checked": checked, "unhealthy": unhealthy, "notified": notified}
