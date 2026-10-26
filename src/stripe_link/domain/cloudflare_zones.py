"""Creating and running a tenant's DNS zone on our Cloudflare account (plans/MANAGED_DNS.md P2).

`custom_domains.cloudflare_request` is zone-scoped by construction -- every URL it builds starts
`/zones/{zone_id}`. Zone CREATION is an account-scoped call, and so is nothing else here, which is why
this is a separate module rather than another parameter on that one: the two have different URL shapes,
different permissions, and very different blast radii. A token that can mint custom hostnames can embarrass
us; a token that can create and edit zones can take a tenant's business email offline.

Everything here takes `opener` so the whole path is testable without Cloudflare, which matters more than
usual: at the time of writing the live token cannot create zones at all, so fakes are the only way this
code runs.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from stripe_link.domain.custom_domains import CLOUDFLARE_API_BASE, CustomDomainError


def cloudflare_account_request(method: str, path: str, *, api_token: str,
                               data: dict[str, Any] | None = None, opener=None) -> Any:
    """An account-scoped Cloudflare call. Same error contract as the zone-scoped one, deliberately:
    callers already know how to handle `CustomDomainError`, and inventing a second exception for the
    same API would mean every call site grows a second except clause that does the same thing."""
    opener = opener or urlopen
    url = f"{CLOUDFLARE_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - a non-JSON error body is still an error
            payload = {}
        errors = payload.get("errors") or []
        message = errors[0].get("message") if errors else str(exc)
        raise CustomDomainError(message or "Cloudflare API request failed.", status_code=exc.code) from exc
    if not payload.get("success"):
        errors = payload.get("errors") or []
        message = errors[0].get("message") if errors else "Cloudflare API request was not successful."
        raise CustomDomainError(message)
    result = payload.get("result")
    return result if result is not None else {}


def create_zone(domain: str, *, account_id: str, api_token: str, opener=None) -> dict[str, Any]:
    """Create the tenant's zone on our account and return Cloudflare's record of it.

    `jump_start: True` runs Cloudflare's quick scan, which imports what it can find of the existing zone.
    That import is the ONLY thing standing between a nameserver change and a tenant's mail going dark, and
    Cloudflare's own docs say it "is not guaranteed to find all existing DNS records" -- so it is a
    starting point for the review, never the authority. `domain/managed_dns.review()` compares it against
    live DNS and refuses the switch on a discrepancy.

    `type: full` is the only setup Free and Pro plans offer, and it is the one we want: Cloudflare becomes
    authoritative, which is what lets the apex be a proxied record at all.
    """
    name = str(domain or "").strip().lower().rstrip(".")
    if not name or "." not in name:
        raise CustomDomainError("A domain is required to create a zone.", status_code=400)
    return cloudflare_account_request(
        "POST", "/zones", api_token=api_token, opener=opener,
        data={"name": name, "account": {"id": account_id}, "type": "full", "jump_start": True},
    )


def get_zone(zone_id: str, *, api_token: str, opener=None) -> dict[str, Any]:
    """The zone as Cloudflare currently sees it -- `status` is how we learn the nameserver change landed.
    Asked rather than inferred, for the same reason the health sweep asks: Cloudflare is watching the
    delegation continuously and we are not."""
    return cloudflare_account_request("GET", f"/zones/{zone_id}", api_token=api_token, opener=opener)


def list_zone_dns_records(zone_id: str, *, api_token: str, opener=None) -> list[dict[str, Any]]:
    """Every DNS record in the zone, paged to the end.

    PAGED ON PURPOSE. Cloudflare returns 100 per page by default, and a zone with a long mail setup --
    several MX, SPF, DMARC, a DKIM key per selector, plus whatever the old host left behind -- can pass
    that. Reading only the first page would hand the review a truncated list, and a truncated list is
    indistinguishable from a complete one at exactly the moment that distinction decides whether someone
    keeps receiving email.
    """
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        result = cloudflare_account_request(
            "GET", f"/zones/{zone_id}/dns_records?per_page=100&page={page}",
            api_token=api_token, opener=opener)
        batch = result if isinstance(result, list) else []
        records.extend(batch)
        if len(batch) < 100:
            return records
        page += 1
        if page > 50:               # 5,000 records: a zone that large is not a tenant's, it is a mistake
            return records


def create_dns_record(zone_id: str, record: dict[str, Any], *, api_token: str,
                      opener=None) -> dict[str, Any]:
    """Add one record to a zone we hold. Used for the serving records only -- the tenant's own records
    arrive through the import, and we do not author those."""
    return cloudflare_account_request("POST", f"/zones/{zone_id}/dns_records", api_token=api_token,
                                      opener=opener, data=record)


def create_worker_route(zone_id: str, pattern: str, script: str, *, api_token: str,
                        opener=None) -> dict[str, Any]:
    """Bind the custom-domain Worker to this zone, which is what makes the apex serve.

    Zone-scoped, but it goes through the account helper because a managed zone is not one of the zones
    the zone-scoped token is allowed to touch -- that token is scoped to our own three names, and a
    tenant zone does not exist when that scope is written.
    """
    return cloudflare_account_request(
        "POST", f"/zones/{zone_id}/workers/routes", api_token=api_token, opener=opener,
        data={"pattern": pattern, "script": script})


def delete_zone(zone_id: str, *, api_token: str, opener=None) -> dict[str, Any]:
    """Hand the domain back. Called only when a tenant asks to leave, never on disconnect.

    Disconnecting a custom domain removes a Site's claim on a hostname. This removes Cloudflare's
    authority over an entire domain -- mail included -- and the tenant's nameservers still point here
    until they change them back, so doing it unasked would break the domain rather than release it. The
    export comes first, always: see `managed_dns.zone_export`.
    """
    return cloudflare_account_request("DELETE", f"/zones/{zone_id}", api_token=api_token, opener=opener)


def worker_route_patterns(domain: str) -> list[str]:
    """The two patterns a tenant zone needs: the apex and everything under it.

    `*.example.com/*` does NOT match `example.com/*` -- the wildcard needs a label to stand for. Relying
    on one pattern is how the apex ends up falling through to the placeholder origin, which routes
    nowhere, producing a dead root domain and a working `www` on the same zone.
    """
    name = str(domain or "").strip().lower().rstrip(".")
    if not name or "." not in name:
        return []
    return [f"{name}/*", f"*.{name}/*"]
