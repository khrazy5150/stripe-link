import json
import os
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CustomDomainError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
DNS_OVER_HTTPS_URL = "https://cloudflare-dns.com/dns-query"

DOMAIN_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")

_ACTIVE_SSL_STATUSES = {"active", "staging_active"}
_FAILED_SSL_STATUSES_MARKERS = ("timed_out", "expired", "inactive", "deleted")


def normalize_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0]
    text = text.rstrip(".")
    return text


# A Site route slug: "/" for the root, otherwise lowercase segments (letters/digits/hyphens) separated by
# single "/". Mirrors documents._SITE_SLUG_RE, redeclared here so the hot resolve path stays off the heavy
# document-validation import.
ROUTE_SLUG_PATTERN = re.compile(r"^/$|^/[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")


def normalize_route_path(path: str) -> str:
    """Fold a request path into a canonical Site slug: lowercased, no trailing slash (except root). Returns
    "/" for an empty path. The result is not guaranteed valid — the caller matches it against the route table."""
    text = str(path or "").strip().lower()
    if not text or text == "/":
        return "/"
    if not text.startswith("/"):
        text = "/" + text
    text = text.rstrip("/")
    return text or "/"


# Entry fields the edge resolver needs carried into the denormalized index alongside page_id/enabled. The
# resolver reads only this table (never the live Site), so anything it must act on has to be projected here.
# `price_context` drives the /sale //flash-sale sibling-artifact serving (plans/SALES_FUNNELS.md P1c);
# `funnel_role`/`strategy` let it compute the synthetic post-purchase funnel artifact for /upsell//downsell/
# /thank-you (P2b) from the base page_id + the request's funnel_step.
_RESOLVER_ENTRY_FIELDS = ("price_context", "funnel_role", "strategy")


def route_target(entry: Any) -> dict[str, Any] | None:
    """Normalize a route-map entry into a `RouteTarget` — the open abstraction the edge resolver hands off to
    (plans/SITE_COLLECTIONS.md P1c). Kinds: `page` (default, derived from page_id — byte-compatible with today's
    entries), `redirect`/`external` (a `location`), `collection` (a `collection_id`, routed rendering is a later
    slice). An entry may instead declare an explicit `target: {kind, …}`. None when the entry names no target."""
    if not isinstance(entry, dict):
        return None
    target = entry.get("target")
    if isinstance(target, dict) and target.get("kind"):
        return dict(target)
    page_id = str(entry.get("page_id") or "")
    if page_id:
        return {"kind": "page", "page_id": page_id}
    return None


def route_table(site: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project a Site's slug→target map into the flat routing table denormalized onto the domain-index record
    (plans/SITE_OBJECT.md §2.6). The edge resolver reads this, never the live Site document. Every entry carries
    its `RouteTarget` (`route_target`) + enabled flag so the resolver can 404 a disabled slug without a Site read,
    plus the resolver-visible fields (`_RESOLVER_ENTRY_FIELDS`) it must act on — e.g. `price_context`. `page_id`
    is kept alongside `target` for kind=page so an older resolver reading the field still works."""
    table: dict[str, dict[str, Any]] = {}
    for slug, entry in (site.get("pages") or {}).items():
        target = route_target(entry)
        if not target:
            continue
        row: dict[str, Any] = {"target": target, "enabled": entry.get("enabled", True) is not False}
        if target.get("kind") == "page":
            row["page_id"] = str(target.get("page_id") or "")  # back-compat with the legacy page_id read
        for field in _RESOLVER_ENTRY_FIELDS:
            if isinstance(entry, dict) and entry.get(field):
                row[field] = str(entry[field])
        table[slug] = row
    return table


def domain_index_record(site: dict[str, Any]) -> dict[str, Any]:
    """The denormalized record the edge resolver reads for a custom hostname, projected off the Site: the
    homepage page_id (back-compat), the full slug→page route table, and the provisioning status. One builder
    so the sites handler and the publisher write byte-identical records (plans/SITE_OBJECT.md §2.6)."""
    hosting = site.get("hosting") or {}
    root = (site.get("pages") or {}).get("/")
    homepage = str(root.get("page_id") or "") if isinstance(root, dict) else ""
    return {
        "tenant_id": str(site.get("tenant_id") or ""),
        "domain": str(hosting.get("custom_domain") or ""),
        "target_page_id": homepage,
        "routes": route_table(site),
        "status": str((site.get("domain_provisioning") or {}).get("status") or ""),
        "site_id": str(site.get("site_id") or ""),
        # The Site's Stripe mode, so the edge resolver reads the mode-partitioned artifact key
        # (plans/STRIPE_MODE_DECOUPLING.md P5). Custom domains are live-only, so this is "live" in practice.
        "stripe_mode": "live" if str(site.get("environment") or "").strip().lower() == "live" else "test",
    }


def platform_domain_index_record(site: dict[str, Any]) -> dict[str, Any] | None:
    """The domain-index record for the Site's free platform hostname (`{label}.<hosting-domain>`), so the edge
    resolver serves the Site there too — navigable free/test stores (plans/PLATFORM_HOSTNAME_SERVING.md). Always
    `active` (no verification — it's platform infra we own) and tagged `host_kind="platform"` so the edge marks
    every response `noindex` (the reputation-isolation floor). Same `route_table` as the custom-domain record, so
    the existing resolver serves it unchanged. None when the Site has no platform hostname."""
    hosting = site.get("hosting") or {}
    platform_hostname = str(hosting.get("platform_hostname") or "").strip()
    if not platform_hostname:
        return None
    root = (site.get("pages") or {}).get("/")
    homepage = str(root.get("page_id") or "") if isinstance(root, dict) else ""
    return {
        "tenant_id": str(site.get("tenant_id") or ""),
        "domain": platform_hostname,
        "target_page_id": homepage,
        "routes": route_table(site),
        "status": "active",
        "site_id": str(site.get("site_id") or ""),
        "host_kind": "platform",
        # Platform hostnames serve BOTH free/test and live Sites, so the resolver reads the mode-partitioned key
        # off this (plans/STRIPE_MODE_DECOUPLING.md P5).
        "stripe_mode": "live" if str(site.get("environment") or "").strip().lower() == "live" else "test",
    }


# Link-in-bio serving, path-on-apex: `jbay.page/{username}` (plans/SOCIAL_MEDIA_PAGES.md #4). Every creator
# shares ONE hostname, so the hostname alone cannot identify a tenant the way a custom domain or a platform
# subdomain does -- the index key has to carry the username too.
#
# Keyed per USERNAME (`jbay.page/maria`), never one `jbay.page` record holding a routes map of every creator.
# That alternative reads cheaper and is a single hot item, unbounded in size, where one tenant's publish
# rewrites every other tenant's routes and one bad write takes the whole domain down. Per-username records are
# the same shape the resolver already reads: one tenant, one page.
def creator_hosting_domain() -> str:
    """The apex link-in-bio pages serve under, per environment: `jbay.page` on prod, `test.jbay.page` on dev.

    Deliberately NOT the platform hosting domain -- it is the only surface carrying tenant-authored outbound
    links, and a reputation hit there must not reach commerce.

    NO built-in default, and that is the point. A hardcoded fallback would have made a dev stack with an unset
    variable write `jbay.page/{username}` records for TEST pages, on the apex prod serves live ones from. The
    per-environment split is the same one the platform host already makes (jbay.uk vs jbay.be); empty means
    the feature is off, which is what an unconfigured environment should get."""
    return str(os.environ.get("CREATOR_HOSTING_DOMAIN") or "").strip()


def creator_serving_enabled() -> bool:
    """Whether link hubs serve on {creator domain}/{username}. Default OFF, and it stays off until three
    things are true, not one: the zone exists, the Worker route is live, and plans/CREATOR_LINK_POLICY.md has
    shipped. That policy is the admission ticket for a shared apex carrying outbound links -- the pages carry
    no payment, so the link is the only lever an abuser has, and the allowlist/warning/takedown path is what
    keeps the domain alive."""
    return str(os.environ.get("CREATOR_SERVING_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def creator_host_key(creator_domain: str, username: str) -> str:
    """The domain-index key for a creator page: `{domain}/{username}`, both normalized."""
    domain = normalize_domain(creator_domain)
    label = str(username or "").strip().lower().strip("/")
    return f"{domain}/{label}" if domain and label else ""


def creator_username(site: dict[str, Any]) -> str:
    """The username a Site's link hub serves under: `hosting.creator_username`, else its subdomain label.

    Its OWN field, because a creator's handle and a store's address are different things that happen to be
    shaped alike -- `poliaxis-nutrition.jbay.uk` is a fine store address and a poor link-in-bio handle, and a
    tenant should not have to change where their shop lives to fix the second.

    But ONE NAMESPACE: it is reserved in the same registry as subdomain labels, so `maria.jbay.uk` and
    `jbay.page/maria` can only ever be the same tenant, and it inherits the syntax rule and
    RESERVED_SUBDOMAINS (`about`, `login`, `api`, `admin`, ... -- the path wordlist
    plans/SOCIAL_MEDIA_PAGES.md #4 says must exist before the first username is claimed).

    Falls back to the label so every Site that predates the field already has a working username, and so a
    tenant who never picks one still gets a URL rather than an error.
    """
    hosting = site.get("hosting") or {}
    chosen = str(hosting.get("creator_username") or "").strip().lower()
    if chosen:
        return chosen
    hostname = str(hosting.get("platform_hostname") or "").strip().lower()
    return hostname.split(".")[0] if hostname else ""


def creator_page_entry(site: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The Site's link hub: its route entry stamped `composition: "lead_social"` at publish time.

    Deterministic by slug when a Site somehow has more than one, so republishing cannot silently move which
    page a creator URL serves.
    """
    entries = [(slug, entry) for slug, entry in (site.get("pages") or {}).items()
               if isinstance(entry, dict) and entry.get("composition") == "lead_social"
               and str(entry.get("page_id") or "")]
    return sorted(entries)[0] if entries else None


def creator_page_url(site: dict[str, Any], page_id: str, creator_domain: str) -> str:
    """The public URL of this Site's link hub: `https://{creator_domain}/{username}`, or "" when it is not one.

    The hub's URL is the username -- NOT the origin plus the page's own slug, the way every other page on a
    Site is addressed. A link hub is the whole point of the apex it sits on, so `jbay.page/maria` IS the page;
    `jbay.page/maria/link-bio` would be a slug nobody typed and nobody would share.
    """
    found = creator_page_entry(site)
    if not found or not page_id or str(found[1].get("page_id") or "") != str(page_id):
        return ""
    host_key = creator_host_key(creator_domain, creator_username(site))
    return f"https://{host_key}" if host_key else ""


def creator_domain_index_record(site: dict[str, Any], creator_domain: str) -> dict[str, Any] | None:
    """The domain-index record serving this Site's link hub at `{creator_domain}/{username}`.

    Serves ONE page, with an EMPTY route table -- deliberately, and this is the reputation isolation the
    separate domain exists for. The Site's own table would expose its checkout, funnel and thank-you pages at
    `jbay.page/maria/...`, putting commerce on the one domain whose entire premise is that it carries no
    payment and can therefore be judged on its outbound links alone.

    None when this environment has no creator domain configured, or the Site has no username, or it has no
    published link hub -- in each case there is nothing to serve.
    """
    username = creator_username(site)
    found = creator_page_entry(site)
    host_key = creator_host_key(creator_domain, username)
    if not host_key or not found:
        return None
    _, entry = found
    return {
        "tenant_id": str(site.get("tenant_id") or ""),
        "domain": host_key,
        "target_page_id": str(entry.get("page_id") or ""),
        "routes": {},
        "status": "active",
        "site_id": str(site.get("site_id") or ""),
        "host_kind": "creator",
        "stripe_mode": "live" if str(site.get("environment") or "").strip().lower() == "live" else "test",
    }


# How many times a Site may change its link-in-bio handle, ever. Names are never released (see
# `retired_username_records`), so an unbounded rename is an unbounded private hoard of good short names -- the
# author's case: a novice renaming every couple of days quietly accumulates twenty of them. Three is enough
# for a genuine rebrand and few enough that hoarding is not a strategy.
MAX_USERNAME_CHANGES = 3


def usernames_left(site: dict[str, Any]) -> int:
    """Handle changes this Site has remaining. Surfaced BEFORE the change, never at the point of refusal."""
    retired = (site.get("hosting") or {}).get("retired_usernames") or []
    return max(0, MAX_USERNAME_CHANGES - len(retired))


def record_hosting_history(existing: dict[str, Any] | None, document: dict[str, Any]) -> None:
    """Remember the addresses this Site used to answer on, so the edge can stop answering on them CORRECTLY.

    Two kinds, treated differently on purpose:

    `retired_usernames` -- a handle is an IDENTITY. When a creator renames, the old handle must stop resolving
    rather than forward: forwarding ties the old name to the new person forever, which is wrong for the
    rebrand the rename usually is. The reservation is kept (nothing in this codebase releases one), so nobody
    can ever claim it -- the name is retired, not freed.

    `retired_hostnames` -- a store address is an ADDRESS. Nothing about identity is at stake, the UI promises
    "existing links keep working", and the links live in the tenant's own marketing. So these REDIRECT.

    Mutates `document` in place, and raises when the handle cap is spent.
    """
    hosting = document.setdefault("hosting", {})
    if existing is None:
        # First save: picking a name is not changing one, and a NEW Site has no history. Stripped rather than
        # trusted -- these fields decide what the edge does with an address (a moved-from hostname REDIRECTS
        # to this Site), so a client free to seed them could name someone else's hostname and point it here.
        # On the update path below every branch overwrites from the STORED document, so this is the only way in.
        hosting.pop("retired_usernames", None)
        hosting.pop("retired_hostnames", None)
        return
    old_hosting = existing.get("hosting") or {}

    old_handle, new_handle = creator_username(existing), creator_username(document)
    if old_handle and old_handle != new_handle:
        retired = [h for h in (old_hosting.get("retired_usernames") or []) if h != new_handle]
        if len(retired) >= MAX_USERNAME_CHANGES:
            raise CustomDomainError(
                f"This Site has used all {MAX_USERNAME_CHANGES} username changes.", status_code=400)
        hosting["retired_usernames"] = [*retired, old_handle]
    else:
        hosting["retired_usernames"] = old_hosting.get("retired_usernames") or []

    old_host, new_host = str(old_hosting.get("platform_hostname") or ""), str(hosting.get("platform_hostname") or "")
    if old_host and old_host != new_host:
        previous = [h for h in (old_hosting.get("retired_hostnames") or []) if h != new_host]
        hosting["retired_hostnames"] = [*previous, old_host]
    else:
        hosting["retired_hostnames"] = old_hosting.get("retired_hostnames") or []

    for key in ("retired_usernames", "retired_hostnames"):
        if not hosting.get(key):
            hosting.pop(key, None)


def _record_status(site: dict[str, Any]) -> str:
    """Whether the edge should SERVE this Site's records.

    An archived Site stops serving. It used to keep serving, which made `archived` a near-duplicate of the
    `seo_enabled` switch -- the only functional difference between them was one `noarchive` token -- while
    nothing did the thing a tenant winding a business down actually needs. Two states, two meanings:
    seo_enabled=false is "open, don't rank me"; archived is "closed".
    """
    return "archived" if str(site.get("status") or "") == "archived" else "active"


def retired_username_records(site: dict[str, Any], creator_domain: str) -> list[dict[str, Any]]:
    """Index rows for handles this Site has given up: present, so nobody else resolves there, and NOT serving."""
    rows = []
    for handle in (site.get("hosting") or {}).get("retired_usernames") or []:
        host_key = creator_host_key(creator_domain, handle)
        if host_key:
            rows.append({"tenant_id": str(site.get("tenant_id") or ""), "domain": host_key,
                         "site_id": str(site.get("site_id") or ""), "status": "retired",
                         "host_kind": "creator", "target_page_id": "", "routes": {}})
    return rows


def retired_hostname_records(site: dict[str, Any]) -> list[dict[str, Any]]:
    """Index rows for store addresses this Site has moved off: a 301 to the current one.

    Without these the OLD record simply stayed behind, still `active`, still pointing at the route table as it
    was on the day of the rename -- so the old address kept serving a snapshot that could never update again.
    The UI's promise that "existing links keep working" was being met by a page frozen in the past.
    """
    current = str((site.get("hosting") or {}).get("platform_hostname") or "")
    if not current:
        return []
    return [{"tenant_id": str(site.get("tenant_id") or ""), "domain": normalize_domain(host),
             "site_id": str(site.get("site_id") or ""), "status": _record_status(site),
             "host_kind": "platform", "redirect_to": current, "target_page_id": "", "routes": {}}
            for host in (site.get("hosting") or {}).get("retired_hostnames") or []]


def site_index_records(site: dict[str, Any], creator_domain: str = "") -> list[dict[str, Any]]:
    """EVERY edge record a Site should have: the addresses it answers on, plus the ones it must stop
    answering on. One builder, because two callers used to assemble this list separately (the sites handler
    and the publisher) and a rule added to one would simply not exist in the other.
    """
    records: list[dict[str, Any]] = []
    if ((site.get("hosting") or {}).get("custom_domain") or "").strip():
        records.append(domain_index_record(site))
    for builder in (platform_domain_index_record, lambda s: creator_domain_index_record(s, creator_domain)):
        record = builder(site)
        if record:
            records.append(record)
    # A Site's own status governs every address it answers on; a retired handle is off regardless.
    status = _record_status(site)
    for record in records:
        record["status"] = status
    _redirect_hub_off_the_platform_host(records, site, creator_domain)
    return records + retired_hostname_records(site) + retired_username_records(site, creator_domain)


def _redirect_hub_off_the_platform_host(records: list[dict[str, Any]], site: dict[str, Any],
                                        creator_domain: str) -> None:
    """A link hub answers on its creator URL, and 301s there from the free platform host.

    Serving it at both was the state after the creator record shipped, with only the canonical saying which
    address was preferred. That undercuts the reason the creator apex is a SEPARATE domain: if the hub also
    answers on the commerce host, that host is carrying exactly the tenant-authored outbound links the split
    exists to quarantine, and anyone judging a domain by its content finds them there anyway.

    The platform host ONLY. A tenant's verified custom domain is theirs -- their content, their reputation,
    their call -- and a hub is indexable there, which the creator apex never is. So that record is untouched
    and keeps serving the page.
    """
    found = creator_page_entry(site)
    if not found:
        return
    slug, entry = found
    url = creator_page_url(site, str(entry.get("page_id") or ""), creator_domain)
    if not url:
        return
    for record in records:
        if record.get("host_kind") != "platform":
            continue
        routes = record.get("routes") or {}
        if slug in routes:
            # No preserve_path on this one: the destination IS the page, not a host to re-walk the path under.
            routes[slug] = {"target": {"kind": "redirect", "location": url}, "enabled": True}


def build_domain(apex_domain: str, subdomain_label: str) -> str:
    apex = normalize_domain(apex_domain)
    label = str(subdomain_label or "").strip().lower()
    if not apex or not label:
        raise CustomDomainError("Both apex_domain and subdomain_label are required.", status_code=400)
    return f"{label}.{apex}"


# Common two-part public suffixes, so an apex like `example.co.uk` (3 labels) is treated as apex, not a
# subdomain. Not exhaustive — the real fix is Public Suffix List handling when apex support lands (2.6b).
_MULTIPART_TLDS = frozenset({
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "net.uk", "ltd.uk", "plc.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "co.nz", "net.nz", "org.nz",
    "co.za", "org.za", "co.jp", "or.jp", "ne.jp", "com.br", "com.mx", "co.in", "com.sg", "com.hk", "com.tr",
})


def is_apex_domain(domain: str) -> bool:
    """True if `domain` is a registrable apex (e.g. example.com, example.co.uk) rather than a subdomain. Apex
    can't hold the routing CNAME (DNS forbids CNAME-at-apex), so it isn't supported until 2.6b."""
    labels = domain.split(".")
    if ".".join(labels[-2:]) in _MULTIPART_TLDS:
        return len(labels) <= 3
    return len(labels) <= 2


def assert_valid_domain(domain: str) -> None:
    # Apex domains (example.com) are supported (plans/SITE_OBJECT.md §2.6b): they can't hold the routing
    # CNAME, so the tenant points the apex via CNAME-flattening / ALIAS / ANAME (or A-records when apex
    # proxying is configured) — custom_hostname_dns_records emits the right shape. See is_apex_domain.
    if not DOMAIN_PATTERN.match(domain):
        raise CustomDomainError(f"'{domain}' is not a valid domain name.", status_code=400)


def cloudflare_request(
    method: str,
    path: str,
    *,
    zone_id: str,
    api_token: str,
    data: dict[str, Any] | None = None,
    opener=None,
) -> dict[str, Any]:
    opener = opener or urlopen
    url = f"{CLOUDFLARE_API_BASE}/zones/{zone_id}{path}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        errors = payload.get("errors") or []
        message = errors[0].get("message") if errors else str(exc)
        raise CustomDomainError(message or "Cloudflare API request failed.", status_code=exc.code) from exc

    if not payload.get("success"):
        errors = payload.get("errors") or []
        message = errors[0].get("message") if errors else "Cloudflare API request was not successful."
        raise CustomDomainError(message)
    return payload.get("result") or {}


def create_custom_hostname(hostname: str, *, zone_id: str, api_token: str, opener=None) -> dict[str, Any]:
    return cloudflare_request(
        "POST",
        "/custom_hostnames",
        zone_id=zone_id,
        api_token=api_token,
        data={"hostname": hostname, "ssl": {"method": "txt", "type": "dv"}},
        opener=opener,
    )


def find_custom_hostname(hostname: str, *, zone_id: str, api_token: str, opener=None) -> dict[str, Any] | None:
    """Look up an existing Cloudflare custom hostname by name. Used to make connect idempotent: a prior
    partial attempt (or a retry) can reuse the hostname instead of hitting a 'duplicate' error."""
    from urllib.parse import quote

    result = cloudflare_request(
        "GET", f"/custom_hostnames?hostname={quote(hostname)}", zone_id=zone_id, api_token=api_token, opener=opener,
    )
    items = result if isinstance(result, list) else []
    for item in items:
        if item.get("hostname") == hostname:
            return item
    return items[0] if items else None


def retrigger_ssl_validation(hostname_id: str, *, zone_id: str, api_token: str, opener=None) -> dict[str, Any]:
    """Ask Cloudflare to re-run SSL DCV now instead of waiting for its next background poll. Returns the
    refreshed custom-hostname object (often already ssl.status=active when the DCV record is in place). Safe
    ONLY with DCV delegation, where Cloudflare owns the challenge record — a static TXT would be rotated out."""
    return cloudflare_request(
        "PATCH", f"/custom_hostnames/{hostname_id}", zone_id=zone_id, api_token=api_token,
        data={"ssl": {"method": "txt", "type": "dv"}}, opener=opener,
    )


def get_custom_hostname(hostname_id: str, *, zone_id: str, api_token: str, opener=None) -> dict[str, Any]:
    return cloudflare_request(
        "GET",
        f"/custom_hostnames/{hostname_id}",
        zone_id=zone_id,
        api_token=api_token,
        opener=opener,
    )


def delete_custom_hostname(hostname_id: str, *, zone_id: str, api_token: str, opener=None) -> dict[str, Any]:
    return cloudflare_request(
        "DELETE",
        f"/custom_hostnames/{hostname_id}",
        zone_id=zone_id,
        api_token=api_token,
        opener=opener,
    )


def validation_record_from_hostname(cloudflare_hostname: dict[str, Any]) -> dict[str, str]:
    ownership = cloudflare_hostname.get("ownership_verification") or {}
    return {
        "type": "TXT",
        "name": str(ownership.get("name") or ""),
        "value": str(ownership.get("value") or ""),
    }


def dns_record_matches(name: str, record_type: str, expected_value: str, *, opener=None) -> bool:
    if not name or not expected_value:
        return False
    opener = opener or urlopen
    url = f"{DNS_OVER_HTTPS_URL}?{urlencode({'name': name, 'type': record_type})}"
    request = Request(url, headers={"Accept": "application/dns-json"}, method="GET")
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False

    for answer in payload.get("Answer") or []:
        value = str(answer.get("data") or "").strip('"').rstrip(".")
        if value.lower() == str(expected_value).strip('"').rstrip(".").lower():
            return True
    return False


def _dns_has_records(name: str, record_type: str, *, opener=None) -> bool:
    """True if ANY record of `record_type` exists at `name` (value ignored) — used to detect a wrong-type
    entry (e.g. a TXT where a CNAME is required)."""
    if not name:
        return False
    opener = opener or urlopen
    url = f"{DNS_OVER_HTTPS_URL}?{urlencode({'name': name, 'type': record_type})}"
    request = Request(url, headers={"Accept": "application/dns-json"}, method="GET")
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(payload.get("Answer"))


def diagnose_dns_records(records: list[dict[str, str]], *, opener=None) -> list[dict[str, Any]]:
    """For each required DNS record, check whether it currently resolves to the expected value (via DNS-over-
    HTTPS). Purely diagnostic — Cloudflare's status is authoritative — but it lets the UI say exactly which
    record is missing or mistyped (the common "I made a TXT instead of a CNAME" mistake) instead of a generic
    'not verified yet'."""
    out: list[dict[str, Any]] = []
    for record in records or []:
        record_type = str(record.get("type") or "").upper()
        if record.get("apex"):
            # Apex routing (ALIAS/flattened-CNAME or A/AAAA) resolves to address records at the apex — there's
            # no CNAME to compare, so just confirm the apex answers with an A/AAAA.
            name = record.get("name", "")
            resolved = _dns_has_records(name, "A", opener=opener) or _dns_has_records(name, "AAAA", opener=opener)
            out.append({**record, "resolved": resolved, "note": ""})
            continue
        resolved = dns_record_matches(record.get("name", ""), record_type, record.get("value", ""), opener=opener) \
            if record_type in ("TXT", "CNAME") else False
        note = ""
        if not resolved and record_type in ("TXT", "CNAME"):
            other_type = "TXT" if record_type == "CNAME" else "CNAME"
            name = record.get("name", "")
            # Only flag a type mismatch when the CORRECT type is genuinely absent. A DCV-delegation CNAME
            # resolves to a TXT when followed, so a naive "is there a TXT here?" check would false-positive
            # even though the record is correctly a CNAME.
            if _dns_has_records(name, other_type, opener=opener) and not _dns_has_records(name, record_type, opener=opener):
                note = f"found a {other_type} record here — it must be a {record_type}"
        out.append({**record, "resolved": resolved, "note": note})
    return out


def derive_status(*, cloudflare_hostname: dict[str, Any], dns_verified: bool | None = None) -> tuple[str, str]:
    """The app-level status, derived from Cloudflare's authoritative hostname + SSL state (Cloudflare polls DNS
    itself, so its status is the source of truth — not our own probe). Returns (status, ssl_status):

    - hostname `status` reflects routing/ownership (active = the CNAME is seen and ownership is confirmed).
    - `ssl.status` reflects the certificate: active only once the SSL DCV record (see custom_hostname_dns_records)
      is in place and the cert issues.

    `dns_verified` is accepted for backward compatibility but no longer gates the result.
    """
    ssl_status = str((cloudflare_hostname.get("ssl") or {}).get("status") or "")
    hostname_status = str(cloudflare_hostname.get("status") or "")

    if hostname_status in {"moved", "deleted"} or any(marker in ssl_status for marker in _FAILED_SSL_STATUSES_MARKERS):
        return "failed", ssl_status
    if ssl_status in _ACTIVE_SSL_STATUSES and hostname_status in {"active", ""}:
        return "active", ssl_status
    if hostname_status != "active":
        return "pending_dns", ssl_status   # the routing CNAME isn't visible to Cloudflare yet
    return "pending_ssl", ssl_status         # hostname active; waiting on the SSL DCV record / cert issuance


_DCV_UUID_CACHE: dict[str, str] = {}


def get_dcv_delegation_uuid(*, zone_id: str, api_token: str, opener=None) -> str:
    """The zone's stable DCV-delegation UUID. It lets the tenant add ONE permanent CNAME
    (`_acme-challenge.<host>` -> `<host>.<uuid>.dcv.cloudflare.com`) so Cloudflare answers the ACME challenge
    itself — no rotating _acme-challenge TXT to chase, and certificate RENEWALS keep working automatically.
    Cached per zone (the UUID never changes)."""
    if zone_id in _DCV_UUID_CACHE:
        return _DCV_UUID_CACHE[zone_id]
    try:
        result = cloudflare_request("GET", "/dcv_delegation/uuid", zone_id=zone_id, api_token=api_token, opener=opener)
    except CustomDomainError:
        return ""
    uuid = str((result or {}).get("uuid") or "")
    if uuid:
        _DCV_UUID_CACHE[zone_id] = uuid
    return uuid


def _apex_routing_records(hostname: str, dns_target: str, apex_ipv4: tuple[str, ...], apex_ipv6: tuple[str, ...]) -> list[dict[str, str]]:
    """The routing record(s) for an apex domain (plans/SITE_OBJECT.md §2.6b). DNS forbids a CNAME at the apex,
    so either: (a) apex proxying is configured — the tenant adds plain A/AAAA records to our static IPs, which
    works on every provider incl. Route 53; or (b) the default — the tenant uses their provider's CNAME
    flattening / ALIAS / ANAME to point the apex at the SaaS target (works on Cloudflare, DNSimple, etc.)."""
    if apex_ipv4 or apex_ipv6:
        records = [{"type": "A", "name": hostname, "value": ip, "apex": "true"} for ip in apex_ipv4]
        records += [{"type": "AAAA", "name": hostname, "value": ip, "apex": "true"} for ip in apex_ipv6]
        return records
    return [{
        "type": "ALIAS", "name": hostname, "value": dns_target, "apex": "true",
        "note": "At your domain apex a plain CNAME is not allowed. Use your DNS provider's apex feature — "
                "an ALIAS or ANAME record, or Cloudflare's CNAME flattening — pointing to this target.",
    }]


def custom_hostname_dns_records(
    cloudflare_hostname: dict[str, Any], *, hostname: str, dns_target: str, dcv_delegation_uuid: str | None = None,
    apex_ipv4: tuple[str, ...] = (), apex_ipv6: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """The DNS records the tenant must create. A subdomain uses a routing CNAME; an apex uses A/AAAA (apex
    proxying) or an ALIAS/flattened CNAME. Plus the DCV-delegation CNAME (on `_acme-challenge`, a subdomain,
    so it works at the apex too) — Cloudflare then manages the ACME token + renewals. Only when no delegation
    UUID is available do we fall back to Cloudflare's rotating ownership TXT + `_acme-challenge` DCV records."""
    if is_apex_domain(hostname):
        records: list[dict[str, str]] = _apex_routing_records(hostname, dns_target, apex_ipv4, apex_ipv6)
    else:
        records = [{"type": "CNAME", "name": hostname, "value": dns_target}]
    if dcv_delegation_uuid:
        records.append({
            "type": "CNAME",
            "name": f"_acme-challenge.{hostname}",
            "value": f"{hostname}.{dcv_delegation_uuid}.dcv.cloudflare.com",
        })
        return records
    ownership = cloudflare_hostname.get("ownership_verification") or {}
    if ownership.get("name") and ownership.get("value"):
        records.append({"type": str(ownership.get("type") or "TXT").upper(), "name": str(ownership["name"]), "value": str(ownership["value"])})
    for record in (cloudflare_hostname.get("ssl") or {}).get("validation_records") or []:
        if record.get("txt_name") and record.get("txt_value"):
            records.append({"type": "TXT", "name": str(record["txt_name"]), "value": str(record["txt_value"])})
        elif record.get("cname") and record.get("cname_target"):
            records.append({"type": "CNAME", "name": str(record["cname"]), "value": str(record["cname_target"])})
    return records
