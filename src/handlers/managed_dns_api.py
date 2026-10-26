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
    scan_zone_records,
    worker_route_patterns,
)
from stripe_link.domain.custom_domains import (CustomDomainError, assert_valid_domain,
                                               normalize_domain, observe_mail_records,
                                               observe_name_servers, registrable_root)
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


def _zone_for_site(tenant_id: str, site_id: str, repo):
    """The in-progress zone for a Site, found WITHOUT being told the domain.

    This is what the panel asks on load, and it has to work without a domain because not knowing the
    domain is the whole situation: a tenant who started the flow and closed the tab has a zone on our
    account and their nameservers already moved, and nothing on the screen to show it. Tenant-scoped
    query, so it is one partition read rather than a scan.
    """
    try:
        zones = repo.list_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 - a panel that cannot look this up must still render
        logger.exception("managed dns: could not list zones for %s", tenant_id)
        return None
    for zone in zones or []:
        if str(zone.get("site_id") or "") == site_id:
            return zone
    return None


def start(event, sites_repository, site_id, *, mode="test", repo=None):
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

    # THE ZONE IS THE REGISTRABLE ROOT, always. A tenant who types www.example.com means "my website",
    # and managed DNS serves the apex AND www from one zone -- but Cloudflare would have been asked to
    # create a zone literally named `www.example.com`, which is not a thing it will do on this plan.
    # Found on the first UI run, where the apex warning (itself wrong in this flow) talked someone into
    # typing the www form.
    domain = registrable_root(normalize_domain(body.get("domain")))
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
        # Idempotent in the sense that matters -- no second zone, because that would orphan the first
        # while the tenant's nameservers may already point at it -- but NOT a no-op. It used to return
        # the bare zone with no review, so the blocked screen's "Check again" handed back `review: null`,
        # the state computed to DELEGATE, and the gate was silently dropped on the one path that exists
        # to re-run it.
        return _recheck(existing, tenant_id, domain, api_token, repo,
                        repair=bool(body.get("repair")))

    try:
        result = managed_dns.provision(
            tenant_id=tenant_id, domain=domain, now=int(time.time()),
            create_zone_fn=lambda d: create_zone(d, account_id=account_id, api_token=api_token),
            list_records_fn=lambda zid: list_zone_dns_records(zid, api_token=api_token),
            observe_fn=observe_mail_records,
            observe_ns_fn=observe_name_servers,
            scan_fn=lambda zid: scan_zone_records(zid, api_token=api_token),
            repository=repo, site_id=site_id,
        )
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="cloudflare_error")
    return json_response({"zone": result["zone"], "review": result["review"],
                          "name_servers": result["name_servers"], "site_id": site_id}, status_code=201)


def _recheck(record, tenant_id, domain, api_token, repo, *, repair=False):
    """Re-run the mail comparison on a zone that already exists, optionally repairing the import first.

    BLOCKED MUST BE RECOVERABLE. Cloudflare's scan runs once at zone creation, so a gap it left can
    never close on its own -- re-checking the same zone against the same live DNS gives the same answer
    forever, and the tenant's only way out would be to abandon the zone. `repair` copies the mail records
    their live DNS already serves into the zone we hold, which is the one action that can actually clear
    the block, and then re-compares.
    """
    zone_id = str(record.get("zone_id") or "")
    try:
        # Re-scan before re-comparing: "Check again" should mean Cloudflare looks again, not just that
        # we re-read what it found the first time.
        try:
            scan_zone_records(zone_id, api_token=api_token)
        except CustomDomainError:
            pass
        imported = list_zone_dns_records(zone_id, api_token=api_token)
        observed, complete = observe_mail_records(domain)
        if repair:
            for dns_record in managed_dns.importable_records(observed, imported):
                try:
                    create_dns_record(zone_id, dns_record, api_token=api_token)
                except CustomDomainError as exc:
                    if "already exists" not in (exc.message or "").lower():
                        logger.warning("managed dns: repair of %s on %s failed: %s",
                                       dns_record.get("name"), domain, exc.message)
            imported = list_zone_dns_records(zone_id, api_token=api_token)
        summary = managed_dns.review(imported, observed, observed_complete=bool(complete))
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="cloudflare_error")

    record["review"] = {"blocked": summary["blocked"], "missing": summary["missing"],
                        "checked_at": int(time.time())}
    repo.put(record)
    return json_response({
        "zone": record, "review": summary, "already_started": True,
        "name_servers": [] if summary["blocked"] else (record.get("name_servers") or []),
    })


def status(event, sites_repository, site_id, *, mode="test", repo=None):
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
    # Asked with a domain while polling, and WITHOUT one when the panel is reconstituting its state.
    record = _zone_for(tenant_id, domain, repo) if domain else _zone_for_site(tenant_id, site_id, repo)
    if not record:
        return error_response("No managed zone for this Site.", status_code=404, code="not_found")

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
        # Both halves, and the second is the one that makes the domain serve rather than 404.
        activated = _attach_to_site(record, sites_repository, site_id, mode) and activated
        record["activated_at"] = int(time.time())
    if record["status"] != previous or activated:
        repo.put(record)
    return json_response({
        "zone": record,
        "status": state,
        "activated": activated,
        # THE STORED VERDICT, carried on every poll. Without it a reload showed the nameservers for a
        # zone whose review had blocked: `status` returned no review, the state fell through to
        # DELEGATE, and the gate was bypassed by pressing F5. Third door onto the same bypass, after
        # "Check again" and the empty-review response from `start`.
        "review": record.get("review") or {},
        # Said on every poll while pending, because the honest answer to "why isn't it working yet" is
        # almost always someone else's cache. Resolvers pick up a new delegation at their own pace: on
        # the first real run Google and Quad9 had it within minutes while Cloudflare's own 1.1.1.1 still
        # served the old nameservers. Reporting that as a fault would be reporting DNS working normally.
        "propagating": state != "active",
    })


def _attach_to_site(record, sites_repository, site_id, mode: str) -> bool:
    """Make the Site actually SERVE this domain.

    THE HALF THAT WAS MISSING. Cloudflare records and Worker routes get a request to our edge; they do
    not tell the edge what to answer with. That is the `custom_domain` index record, and without it a
    tenant who did everything right -- zone active, certificate issued, nameservers changed -- gets a
    404 on their own domain. Found on the first run through the UI, 2026-10-26, after the scripted
    version passed because the test wrote that record by hand.

    Mirrors what `check_domain` does on first verification, through the same helpers rather than a
    second copy of the rules: hosting + verification, an IndexNow key, recomputed eligibility, the index
    records, and a re-publish so canonical/robots attach to pages published before the domain existed.
    """
    from handlers.sites import (_put_site_index_records, _recompute_eligibility, _republish_site_pages,
                                generate_indexnow_key)
    from stripe_link.domain.documents import validate_site
    from stripe_link.repositories.documents import pages_repository

    tenant_id, domain = record.get("tenant_id") or "", record.get("domain") or ""
    site = sites_repository.get(tenant_id, site_id)
    if not site:
        logger.warning("managed dns: no Site %s to attach %s to", site_id, domain)
        return False
    now = int(time.time())
    hosting = site.get("hosting") or {}
    hosting["custom_domain"] = domain
    hosting["type"] = "custom"
    # `managed_dns`, not `cloudflare_saas`: there is no custom hostname here and nothing to re-verify.
    # Cloudflare is authoritative for the zone, so the delegation going active IS the verification.
    hosting["verification"] = {"verified": True, "method": "managed_dns", "verified_at": now}
    site["hosting"] = hosting
    seo = dict(site.get("seo") or {})
    if not seo.get("indexnow_key"):
        seo["indexnow_key"] = generate_indexnow_key()
        site["seo"] = seo
    _recompute_eligibility(site, tenant_id, now)
    site["updated_at"] = now
    try:
        validate_site(site)
        saved = sites_repository.put(site)
    except Exception:  # noqa: BLE001 - a bad Site must not leave the zone half-wired and silent
        logger.exception("managed dns: could not attach %s to site %s", domain, site_id)
        return False
    _put_site_index_records(saved)
    try:
        _republish_site_pages(tenant_id, saved, pages_repository(mode=mode), mode=mode)
    except Exception:  # noqa: BLE001 - the domain serves either way; republish only refreshes metadata
        logger.exception("managed dns: re-publish after attaching %s failed", domain)
    return True


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


def _detach_from_site(domain: str, tenant_id: str, sites_repository, site_id, mode: str) -> None:
    """Undo what `_attach_to_site` did. The mirror image, and it was missing.

    Deleting the zone stops the domain serving; it does not stop the SITE claiming it. Without this the
    Site goes on saying "Connected & verified", stays index-eligible, keeps a resolver index record
    pointing at a zone that no longer exists, and -- because the panel renders the connected branch when
    `hosting.custom_domain` is set -- shows the custom-hostname screen instead of the managed-DNS flow.
    Found that way, 2026-10-26.

    The re-publish matters for the same reason it matters on an ordinary disconnect: `on_custom_domain`
    is baked into each published artifact -- canonical, robots, whether external link cards are real
    anchors -- so an artifact published while the domain was live keeps serving those claims from the
    platform host after the domain is gone.
    """
    from handlers.sites import _put_site_index_records, _recompute_eligibility, _republish_site_pages
    from stripe_link.domain.documents import validate_site
    from stripe_link.repositories.documents import custom_domains_index_repository, pages_repository

    site = sites_repository.get(tenant_id, site_id)
    if not site or str((site.get("hosting") or {}).get("custom_domain") or "") != domain:
        return                      # a Site that never claimed this domain has nothing to give back
    now = int(time.time())
    hosting = site.get("hosting") or {}
    hosting["custom_domain"] = None
    hosting["type"] = "platform"
    hosting.pop("verification", None)
    site["hosting"] = hosting
    site.pop("domain_provisioning", None)
    _recompute_eligibility(site, tenant_id, now)
    site["updated_at"] = now
    try:
        validate_site(site)
        saved = sites_repository.put(site)
    except Exception:  # noqa: BLE001 - the zone is already gone; leaving the Site attached is the worse half
        logger.exception("managed dns: could not detach %s from site %s", domain, site_id)
        return
    _put_site_index_records(saved)
    try:
        # `site_index_records` only EMITS a custom-domain record when one is connected, so the stale one
        # has to be removed by name -- otherwise the edge keeps an entry for a hostname we no longer hold.
        custom_domains_index_repository().delete(tenant_id, domain)
    except Exception:  # noqa: BLE001
        logger.exception("managed dns: could not drop the index record for %s", domain)
    try:
        _republish_site_pages(tenant_id, saved, pages_repository(mode=mode), mode=mode)
    except Exception:  # noqa: BLE001
        logger.exception("managed dns: re-publish after detaching %s failed", domain)


def stop(event, sites_repository, site_id, *, mode="test", repo=None):
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
    # Both halves, in this order: the zone is gone, so the Site must stop claiming the domain too.
    _detach_from_site(domain, tenant_id, sites_repository, site_id, mode)
    return json_response({
        "deleted": True,
        "zone_file": export,
        "restore_name_servers": record.get("original_name_servers") or [],
    })


def handle(event, sites_repository, site_id, method, mode="test"):
    """Route one managed-dns request. Called from `handlers.sites`, which owns the API resources.

    `mode` is the STRIPE mode, read from the request by the caller and threaded through rather than
    assumed. It is not the deployment: `dev` and `prod` are stacks, `test` and `live` are Stripe's
    books, and the two are independent axes. The Site repository and every re-publish below have to be
    told which books they are working in -- a hardcoded "live" here would read the right documents on a
    live Site by luck and the wrong ones the moment that stopped being the only case.
    """
    if method == "POST":
        return start(event, sites_repository, site_id, mode=mode)
    if method == "GET":
        return status(event, sites_repository, site_id, mode=mode)
    if method == "DELETE":
        return stop(event, sites_repository, site_id, mode=mode)
    return error_response("Unsupported method.", status_code=405, code="method_not_allowed")
