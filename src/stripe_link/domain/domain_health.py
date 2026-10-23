"""Is a tenant's custom domain still working? (plans/DOMAIN_HEALTH_SWEEP.md)

Verification is one-shot: `check_domain` runs when the tenant clicks Verify and, before this, never again.
So a store could go dark while the dashboard kept saying *Connected & verified* — that is a stored boolean
from the day it passed. Silent causes: the tenant edits their own DNS, a registrar lapses, a provider
migration drops a CNAME, a removed `_acme-challenge` delegation stops the certificate renewing, or the
anycast IPs we publish for apex domains get reassigned.

Pure decisions only. The sweep handler does the I/O; everything here is a function of what it read, so the
rules are testable without Cloudflare, DNS or DynamoDB.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "2026-05-29"

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"

# Cloudflare's own words for a custom hostname that is serving. Anything else -- pending, blocked,
# moved, deleted, or a certificate that stopped renewing -- means the tenant's domain is not working,
# whatever our stored `verification.verified` boolean still says.
_SERVING_STATUS = "active"
_SERVING_SSL = "active"


def hostname_health(cloudflare_hostname: dict[str, Any] | None) -> tuple[str, str]:
    """(state, reason) for one custom hostname, from Cloudflare's record of it.

    CLOUDFLARE IS THE AUTHORITY, and asking it first is not an implementation detail — it is what keeps
    this sweep from crying wolf through an apex migration. Re-deriving the expected DNS records and
    comparing would flag every tenant still pointing at superseded-but-working apex IPs as broken, which
    is precisely the population mid-migration. What the tenant was TOLD is in `domain_provisioning`;
    whether it WORKS is here.
    """
    if not cloudflare_hostname:
        return UNHEALTHY, "no_hostname"
    status = str(cloudflare_hostname.get("status") or "").strip().lower()
    ssl_status = str(((cloudflare_hostname.get("ssl") or {}).get("status")) or "").strip().lower()
    if status != _SERVING_STATUS:
        return UNHEALTHY, f"status_{status or 'unknown'}"
    if ssl_status != _SERVING_SSL:
        return UNHEALTHY, f"ssl_{ssl_status or 'unknown'}"
    return HEALTHY, ""


def failing_records(diagnostics: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The records `diagnose_dns_records` could not resolve. Diagnostic only — it explains a failure
    Cloudflare already declared, and never declares one itself."""
    return [d for d in (diagnostics or []) if not d.get("resolved")]


def should_notify(previous: dict[str, Any] | None, state: str) -> bool:
    """Notify on a TRANSITION into unhealthy, never on every pass.

    A notice needs an action the tenant must take, and repeating it daily for a domain they have already
    been told about is noise that trains them to ignore the bell. Recovery is silent for the same reason:
    nothing is required of them.
    """
    if state != UNHEALTHY:
        return False
    return str((previous or {}).get("state") or "") != UNHEALTHY


def health_record(state: str, reason: str, now: int, previous: dict[str, Any] | None,
                  notified: bool) -> dict[str, Any]:
    """What to store on the Site so the next pass knows whether this is new."""
    record: dict[str, Any] = {"state": state, "checked_at": int(now)}
    if reason:
        record["reason"] = reason
    notified_at = int((previous or {}).get("notified_at") or 0)
    if notified:
        notified_at = int(now)
    # Cleared on recovery so a later failure notifies again rather than being mistaken for the old one.
    if state == HEALTHY:
        notified_at = 0
    if notified_at:
        record["notified_at"] = notified_at
    return record


def _record_phrase(record: dict[str, Any]) -> str:
    name = str(record.get("name") or "").strip()
    kind = str(record.get("type") or "").strip().upper()
    return f"the {kind} record for {name}" if kind and name else (name or "a DNS record")


def domain_health_notification(site: dict[str, Any], reason: str, failures: list[dict[str, Any]],
                               now: int) -> dict[str, Any]:
    """The one notice a tenant gets when their domain stops working.

    It names the record to fix where DNS explains it, because "your domain is down" is not an action.
    Deliberately does NOT claim the store is de-indexed or disconnected: nothing in this sweep changes
    the Site, and a notice that overstates the damage costs more trust than the outage.
    """
    domain = str((site.get("hosting") or {}).get("custom_domain") or "")
    site_id = str(site.get("site_id") or "")
    if failures:
        which = ", ".join(_record_phrase(f) for f in failures[:3])
        message = (f"{domain} has stopped resolving. Check {which} at your DNS provider — "
                   "the exact values are on the Site's custom domain panel.")
    elif reason.startswith("ssl_"):
        message = (f"The certificate for {domain} is not active. This usually means the "
                   f"_acme-challenge record was removed or changed; re-adding it lets Cloudflare renew.")
    elif reason == "no_hostname":
        message = (f"{domain} is no longer registered with our edge. Disconnect and reconnect it on the "
                   "Sites screen to re-provision.")
    else:
        message = (f"{domain} is not serving. Open the Site's custom domain panel and re-check the DNS "
                   "records shown there.")
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "notification",
        "tenant_id": str(site.get("tenant_id") or ""),
        # Keyed on the SITE, not the moment: a re-notification after recovery-then-failure should replace
        # the old row rather than stack a second copy of the same problem in the bell.
        "notification_id": f"notif_domain_{site_id}",
        "type": "domain_health",
        "severity": "warning",
        "title": "Your custom domain stopped working",
        "message": message,
        "status": "unread",
        "sort_priority": 10,
        "related": {"site_id": site_id, "domain": domain},
        "action": {"label": "Check domain", "route": "sites"},
        "created_at": int(now),
    }
