"""The managed-DNS endpoints (plans/MANAGED_DNS.md P3/P4).

Three calls, matching the three irreversible-ish moments:

    POST   /sites/{site_id}/managed-dns   create the zone, import, compare, return the review
    GET    /sites/{site_id}/managed-dns   poll; on `active`, wire the serving records and routes
    DELETE /sites/{site_id}/managed-dns   export, hand the domain back, delete the zone

Lives in its own module rather than in `handlers/sites.py` because that file is already long, and because
the import cost matters: `sites.py` is reached by the scheduled domain-health sweep too. `sites.handler`
imports this lazily, on the route.

A note on the shape of the flow. Creating a zone is NOT the irreversible step and is not gated as if it
were — it changes nothing on the internet, because the tenant's nameservers still point at their old
provider. **Handing over the nameservers is the irreversible step**, so that is what the mail review
withholds. The split is the whole reason this can be a safe flow at all: we get to look inside the zone
before asking anyone to commit to it.
"""

from __future__ import annotations

import logging
import os
import time

from stripe_link.cloudflare_secrets import get_cloudflare_dns_token
from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain import managed_dns
from stripe_link.domain.cloudflare_zones import (
    create_dns_record,
    create_worker_route,
    create_zone,
    delete_zone,
    get_zone,
    list_zone_dns_records,
    worker_route_patterns,
)
from stripe_link.domain.custom_domains import CustomDomainError, assert_valid_domain, normalize_domain, observe_mail_records
from stripe_link.repositories.documents import managed_zones_repository

logger = logging.getLogger(__name__)


def _config():
    """(account_id, api_token, worker_script). Read per request, never cached across invocations: the
    token is rotatable at runtime by design, and a cached one survives a rotation it should not."""
    return (os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            get_cloudflare_dns_token() or "",
            os.environ.get("CLOUDFLARE_WORKER_SCRIPT", ""))


def _zone_for(tenant_id: str, domain: str, repo):
    return repo.get(tenant_id, domain)


def start(event, sites_repository, site_id, *, repo=None):
    """Create the zone and return the review. The nameservers come back only if the review is clean."""
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = sites_repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")

    domain = normalize_domain(body.get("domain"))
    try:
        assert_valid_domain(domain)
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="invalid_domain")

    account_id, api_token, _ = _config()
    if not account_id or not api_token:
        return error_response("Managed DNS is not configured.", status_code=500,
                              code="managed_dns_not_configured")

    repo = repo or managed_zones_repository()
    existing = _zone_for(tenant_id, domain, repo)
    if existing:
        # Idempotent. A second POST is a tenant who refreshed, not a second zone -- and creating one
        # would leave the first orphaned on our account with their nameservers possibly pointing at it.
        return json_response({"zone": existing, "already_started": True})

    try:
        result = managed_dns.provision(
            tenant_id=tenant_id, domain=domain, now=int(time.time()),
            create_zone_fn=lambda d: create_zone(d, account_id=account_id, api_token=api_token),
            list_records_fn=lambda zid: list_zone_dns_records(zid, api_token=api_token),
            observe_fn=observe_mail_records,
            repository=repo,
        )
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="cloudflare_error")
    return json_response({"zone": result["zone"], "review": result["review"],
                          "name_servers": result["name_servers"], "site_id": site_id}, status_code=201)


def status(event, sites_repository, site_id, *, repo=None):
    """Where the delegation has got to, and — once Cloudflare says `active` — the wiring that makes the
    domain serve.

    Activation happens HERE rather than on a schedule because it is cheap, idempotent and needs to happen
    exactly once, the moment the zone goes active. A sweep would add a table scan and up to its own
    interval of delay to the one minute of the flow a tenant is actually watching.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    repo = repo or managed_zones_repository()
    domain = normalize_domain((event.get("queryStringParameters") or {}).get("domain"))
    record = _zone_for(tenant_id, domain, repo) if domain else None
    if not record:
        return error_response("No managed zone for this domain.", status_code=404, code="not_found")

    account_id, api_token, worker_script = _config()
    try:
        zone = get_zone(record["zone_id"], api_token=api_token)
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="cloudflare_error")

    state = managed_dns.zone_state(zone)
    previous = record.get("status")
    record["status"] = state
    activated = False
    if state == "active" and previous != "active":
        activated = _activate(record, api_token=api_token, worker_script=worker_script)
        record["activated_at"] = int(time.time())
    if record["status"] != previous or activated:
        repo.put(record)
    return json_response({
        "zone": record,
        "status": state,
        "activated": activated,
        # Said on every poll while pending, because the honest answer to "why isn't it working yet" is
        # almost always someone else's cache. Resolvers pick up a new delegation at their own pace: on
        # the first real run Google and Quad9 had it within minutes while Cloudflare's own 1.1.1.1 still
        # served the old nameservers. Reporting that as a fault would be reporting DNS working normally.
        "propagating": state != "active",
    })


def _activate(record, *, api_token, worker_script) -> bool:
    """Write the serving records and both Worker routes. Best-effort and idempotent: Cloudflare answers
    'already exists' for a repeat, which is success for our purposes, so a retried poll is harmless."""
    domain = record.get("domain") or ""
    zone_id = record.get("zone_id") or ""
    done = True
    for dns_record in managed_dns.serving_records(domain):
        try:
            create_dns_record(zone_id, dns_record, api_token=api_token)
        except CustomDomainError as exc:
            if "already exists" not in (exc.message or "").lower():
                logger.warning("managed dns: record %s on %s failed: %s",
                               dns_record.get("name"), domain, exc.message)
                done = False
    for pattern in worker_route_patterns(domain):
        try:
            create_worker_route(zone_id, pattern, worker_script, api_token=api_token)
        except CustomDomainError as exc:
            if "already exists" not in (exc.message or "").lower():
                # BOTH patterns matter: `*.example.com/*` does not match the apex, so losing the apex
                # route gives a dead root and a working www -- which reads as a DNS fault and is not.
                logger.warning("managed dns: route %s failed: %s", pattern, exc.message)
                done = False
    return done


def stop(event, sites_repository, site_id, *, repo=None):
    """Hand the domain back: export every record, then delete the zone.

    THE EXPORT COMES FIRST and its failure aborts the delete. A tenant leaving must leave with their DNS;
    deleting a zone we could not export turns 'you can go whenever you like' into a sentence that was
    only ever true on paper.

    The tenant's nameservers are NOT changed here -- they are not ours to change, and they still point at
    us until the tenant moves them. The response carries the originals we stored at provisioning so the
    dashboard can show exactly what to put back.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    repo = repo or managed_zones_repository()
    domain = normalize_domain((event.get("queryStringParameters") or {}).get("domain"))
    record = _zone_for(tenant_id, domain, repo) if domain else None
    if not record:
        return error_response("No managed zone for this domain.", status_code=404, code="not_found")

    _, api_token, _ = _config()
    try:
        records = list_zone_dns_records(record["zone_id"], api_token=api_token)
        export = managed_dns.zone_export(records, domain)
    except CustomDomainError as exc:
        return error_response(f"Could not export this zone, so it was not deleted: {exc.message}",
                              status_code=exc.status_code, code="export_failed")
    try:
        delete_zone(record["zone_id"], api_token=api_token)
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="cloudflare_error")
    repo.delete(tenant_id, domain)
    return json_response({
        "deleted": True,
        "zone_file": export,
        "restore_name_servers": record.get("original_name_servers") or [],
    })


def handle(event, sites_repository, site_id, method):
    """Route one managed-dns request. Called from `handlers.sites`, which owns the API resources."""
    if method == "POST":
        return start(event, sites_repository, site_id)
    if method == "GET":
        return status(event, sites_repository, site_id)
    if method == "DELETE":
        return stop(event, sites_repository, site_id)
    return error_response("Unsupported method.", status_code=405, code="method_not_allowed")
