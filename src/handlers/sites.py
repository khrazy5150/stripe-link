import os
import re
import secrets
import string
import time

from stripe_link.cloudflare_secrets import get_cloudflare_api_token
from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.connect_sync import compute_site_eligibility, connect_state_fields, site_domain_verified, site_seo_enabled
from stripe_link.domain.sitemap import generate_indexnow_key
from stripe_link.stripe_client import stripe_request
from stripe_link.stripe_platform_secrets import get_platform_secret_key
from stripe_link.domain.custom_domains import (
    CustomDomainError,
    assert_valid_domain,
    create_custom_hostname,
    custom_hostname_dns_records,
    delete_custom_hostname,
    derive_status,
    diagnose_dns_records,
    find_custom_hostname,
    get_custom_hostname,
    domain_index_record,
    platform_domain_index_record,
    get_dcv_delegation_uuid,
    is_apex_domain,
    normalize_domain,
    normalize_route_path,
    retrigger_ssl_validation,
)
from stripe_link.domain.documents import DocumentValidationError, validate_site
from stripe_link.domain.social_links import (
    preserve_verification,
    site_backlink_host,
    verify_entry,
)
from stripe_link.domain.funnels import is_reserved_slug
from stripe_link.entitlement_gate import require_capability
from stripe_link.repositories.documents import (
    RepositoryError,
    custom_domains_index_repository,
    pages_repository,
    sites_repository,
    stripe_keys_repository,
    subdomain_registry,
)

SITE_SCHEMA_VERSION = "2026-07-20"
_ID_ALPHABET = string.ascii_letters + string.digits
_SITE_ID_RE = re.compile(r"^site_[A-Za-z0-9]+$")
_HOSTNAME_RE = re.compile(r"^(?!https?://)([a-z0-9-]+\.)+[a-z]{2,}$")
# A DNS label: lowercase alphanumerics + interior hyphens, no leading/trailing hyphen.
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MIN_SUBDOMAIN_LENGTH = 3
MAX_SUBDOMAIN_LENGTH = 63
# The tenant free-hosting domain lives in config, never hardcoded (plans/SITE_OBJECT.md §6).
DEFAULT_HOSTING_DOMAIN = "jbay.uk"

# Labels nobody may claim: infrastructure names, platform brands, and impersonation-prone words.
RESERVED_SUBDOMAINS = frozenset({
    "www", "api", "app", "apps", "admin", "administrator", "dashboard", "portal", "console",
    "mail", "email", "smtp", "imap", "pop", "ns", "ns1", "ns2", "dns", "mx", "webmail",
    "ftp", "cdn", "static", "assets", "media", "img", "images", "files", "download", "downloads",
    "checkout", "pay", "payment", "payments", "billing", "invoice", "invoices", "order", "orders",
    "store", "shop", "go", "link", "links", "url", "m", "mobile", "wap",
    "help", "support", "docs", "doc", "blog", "news", "status", "about", "contact",
    "dev", "development", "staging", "stage", "test", "testing", "sandbox", "demo", "preview", "beta", "alpha",
    "root", "host", "hosting", "localhost", "internal", "system", "platform", "official",
    "auth", "login", "signin", "signup", "register", "account", "accounts", "profile", "user", "users",
    "security", "abuse", "postmaster", "hostmaster", "noc", "no-reply", "noreply",
    "juniorbay", "jbay", "automizepro", "stripe", "connect",
})


def generate_site_id() -> str:
    return "site_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def _slugify(value) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "site"


def hosting_domain() -> str:
    return str(os.environ.get("PLATFORM_HOSTING_DOMAIN") or DEFAULT_HOSTING_DOMAIN).strip() or DEFAULT_HOSTING_DOMAIN


def normalize_subdomain(value) -> str:
    """Coerce free text into a DNS label: lowercase, non-alphanumerics → hyphens, collapse runs,
    trim, cap length. Returns "" when nothing usable remains."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:MAX_SUBDOMAIN_LENGTH].strip("-")


def subdomain_rule_error(label: str) -> str | None:
    """Return a human-readable reason `label` is unusable (too short/long, bad chars, reserved), else None.
    Assumes `label` is already normalized."""
    if len(label) < MIN_SUBDOMAIN_LENGTH:
        return f"Store name must be at least {MIN_SUBDOMAIN_LENGTH} characters."
    if len(label) > MAX_SUBDOMAIN_LENGTH:
        return f"Store name must be at most {MAX_SUBDOMAIN_LENGTH} characters."
    if not _SUBDOMAIN_RE.match(label):
        return "Use lowercase letters, numbers, and hyphens only (no leading or trailing hyphen)."
    if label in RESERVED_SUBDOMAINS:
        return "That name is reserved. Please choose another."
    return None


def suggest_subdomains(seed, registry, *, limit: int = 4) -> list:
    """Offer a few available alternatives derived from `seed` (used when a name is taken/invalid)."""
    base = normalize_subdomain(seed) or "store"
    base = base[: MAX_SUBDOMAIN_LENGTH - 8].strip("-") or "store"
    out: list = []
    for suffix in ("-2", "-store", "-shop", "-co", "-3", "-online", "-hq", "-1", "-official"):
        candidate = normalize_subdomain(base + suffix)
        if not candidate or candidate in out or subdomain_rule_error(candidate):
            continue
        if registry.owner_of(candidate) is None:
            out.append(candidate)
        if len(out) >= limit:
            break
    return out


def _ensure_platform_hostname(document: dict) -> None:
    """Build the platform hostname from the configured hosting domain when the client didn't send a full one.
    Keeps the tenant-free-hosting domain server-side/config-driven. The client may pass hosting.platform_subdomain
    (a desired name); otherwise we slugify the Site name."""
    hosting = document.get("hosting")
    if not isinstance(hosting, dict):
        return
    hosting.setdefault("type", "platform")
    if _HOSTNAME_RE.match(str(hosting.get("platform_hostname") or "")):
        hosting.pop("platform_subdomain", None)
        return
    subdomain = normalize_subdomain(hosting.get("platform_subdomain") or document.get("name") or document.get("site_id")) or "site"
    hosting["platform_hostname"] = f"{subdomain}.{hosting_domain()}"
    hosting.pop("platform_subdomain", None)


def handler(event, context, repository=None, registry=None, tenant_repo=None):
    mode = resolve_stripe_mode(event)
    repository = repository or sites_repository(mode=mode)
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    site_id = path_params(event).get("site_id")
    resource = (event or {}).get("resource") or ""
    if method == "GET" and resource.endswith("/subdomain"):
        return check_subdomain(event, registry or subdomain_registry())
    if method == "PATCH" and site_id and resource.endswith("/status"):
        return update_site_status(event, repository, site_id, mode=mode)
    if method == "POST" and site_id and resource.endswith("/homepage"):
        return set_homepage(event, repository, site_id)
    if method == "POST" and site_id and resource.endswith("/social/check"):
        return check_social_links(event, repository, site_id)
    if method == "POST" and site_id and resource.endswith("/pages"):
        return attach_page(event, repository, site_id, mode=mode)
    if method == "DELETE" and site_id and resource.endswith("/pages"):
        return detach_page(event, repository, site_id)
    if site_id and resource.endswith(("/domain", "/domain/check")):
        # Custom-domain serving is handled by the single production edge Worker, so the flow is live-only.
        # A test/dev Site can't serve a real domain — refuse rather than let a tenant reach a dead end.
        if os.environ.get("ENVIRONMENT") != "prod":
            return error_response(LIVE_ONLY_MESSAGE, status_code=403, code="custom_domains_live_only")
        if method == "POST" and resource.endswith("/domain/check"):
            return check_domain(event, repository, site_id, mode=mode)
        if method == "POST" and resource.endswith("/domain"):
            return connect_domain(event, repository, site_id)
        if method == "DELETE" and resource.endswith("/domain"):
            return disconnect_domain(event, repository, site_id)
    if method == "POST":
        gate = require_capability(event, "sites", tenant_repo)
        if gate is not None:
            return gate
        return create_site(event, repository, registry, mode=mode)
    if method == "GET":
        if site_id:
            return get_site(event, repository, site_id)
        return list_sites(event, repository)
    if method == "DELETE" and site_id:
        return delete_site(event, repository, site_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _unique_slug(pages: dict, seed) -> str:
    """A Site route slug from `seed`, not already used in `pages`."""
    base = "/" + _slugify(seed)
    slug, n = base, 2
    while slug in pages:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _attach_page_to_site(pages: dict, *, page_id, slug, page_type, category=None, label=None) -> None:
    """Place `page_id` at `slug` in the route map with `page_type` (+ optional category label). A different
    page already at `slug` is displaced to its own slug so it stays reachable; the incoming page is detached
    from any other slug it held (its existing label is kept unless a new one is given). Mutates `pages`."""
    occupant = pages.get(slug)
    if isinstance(occupant, dict) and occupant.get("page_id") and occupant["page_id"] != page_id:
        pages.pop(slug)
        pages[_unique_slug(pages, occupant.get("label") or occupant["page_id"])] = dict(occupant)
    existing_label = None
    for existing_slug, entry in list(pages.items()):
        if isinstance(entry, dict) and entry.get("page_id") == page_id:
            existing_label = entry.get("label")
            if existing_slug != slug:
                pages.pop(existing_slug)
    new_entry = {"page_id": page_id, "page_type": page_type, "enabled": True}
    if label or existing_label:
        new_entry["label"] = label or existing_label
    if category:
        new_entry["category"] = category
    pages[slug] = new_entry


def _put_site_index_records(saved: dict) -> None:
    """Sync the denormalized edge-resolver records for a Site: the custom-domain record (only when one is
    connected) AND the free platform-hostname record (always) so the Site serves on `{label}.<hosting-domain>`
    too (navigable free/test stores, plans/PLATFORM_HOSTNAME_SERVING.md). Best-effort — never fail a save on it."""
    try:
        repo = custom_domains_index_repository()
        if ((saved.get("hosting") or {}).get("custom_domain") or "").strip():
            repo.put(domain_index_record(saved))
        platform = platform_domain_index_record(saved)
        if platform:
            repo.put(platform)
    except Exception:  # noqa: BLE001
        pass


def _save_site_pages(repository, site):
    """Validate + persist a Site whose route map changed, and refresh the domain-index route table when a
    custom domain serves it. Returns (saved_site, error_response|None)."""
    site["updated_at"] = int(time.time())
    try:
        _assert_pages_unassigned(repository, site)  # a page belongs to at most one Site — attach can't steal it
        validate_site(site)
        saved = repository.put(site)
    except (DocumentValidationError, RepositoryError) as exc:
        return None, error_response(str(exc), code="invalid_site")
    _put_site_index_records(saved)  # custom-domain (if any) + the free platform-hostname record
    return saved, None


def set_homepage(event, repository, site_id):
    """Make a page the Site's homepage: attach it at "/" with page_type=homepage (plans/SITE_OBJECT.md §2.5b).
    Any different page currently at "/" moves to its own slug so it stays served — and linkable from the new
    homepage's catalog grid."""
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page_id = str(body.get("page_id") or "").strip()
    if not page_id:
        return error_response("page_id is required.", code="missing_page")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    pages = dict(site.get("pages") or {})
    _attach_page_to_site(pages, page_id=page_id, slug="/",
                         page_type=str(body.get("page_type") or "homepage").strip() or "homepage")
    site["pages"] = pages
    saved, error = _save_site_pages(repository, site)
    return error or json_response({"site": saved})


def attach_page(event, repository, site_id, mode="test"):
    """Attach a page to the Site at a chosen slug with a page_type (+ optional category for a category page).
    The generalized route-map primitive (plans/SITE_OBJECT.md §2.5b Slice 2); the storefront/category builder
    uses it, and it seeds the full route-map editor later."""
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_request")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page_id = str(body.get("page_id") or "").strip()
    if not page_id:
        return error_response("page_id is required.", code="missing_page")
    slug = normalize_route_path(body.get("slug"))
    if slug == "/" or not slug:
        return error_response("Use the homepage action to place a page at the root.", code="invalid_slug")
    if is_reserved_slug(slug):
        return error_response(
            f"'{slug}' is reserved for the sales funnel and can't be assigned manually.",
            code="reserved_slug",
        )
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    pages = dict(site.get("pages") or {})
    _attach_page_to_site(
        pages, page_id=page_id, slug=slug,
        page_type=str(body.get("page_type") or "landing").strip() or "landing",
        category=str(body.get("category") or "").strip() or None,
        label=str(body.get("label") or "").strip() or None,
    )
    _record_offer_link_on_attach(pages, page_id, tenant_id, mode=mode)
    site["pages"] = pages
    saved, error = _save_site_pages(repository, site)
    return error or json_response({"site": saved})


def _record_offer_link_on_attach(pages: dict, page_id: str, tenant_id: str, mode: str = "test") -> None:
    """Record a just-attached PUBLISHED offer page's offer_id on its route-map entry immediately, so it's
    eligible for storefront grids without waiting for a re-publish. (Publishing denormalizes the same link via
    _denormalize_page_catalog; this makes attach-a-product-then-see-it-in-the-store work in one step. Only
    published pages qualify — a draft has no live artifact to link to.) Best-effort: never block the attach."""
    try:
        page = pages_repository(mode=mode).get(tenant_id, page_id)
    except Exception:  # noqa: BLE001 - a lookup failure just defers the link to the next publish
        return
    if not page or page.get("status") != "published":
        return
    offer_id = str(page.get("offer_id") or "")
    if not offer_id:
        return
    for entry in pages.values():
        if isinstance(entry, dict) and entry.get("page_id") == page_id:
            entry["offer_id"] = offer_id


def detach_page(event, repository, site_id):
    """Remove a page from the Site's route map, freeing it to be attached to another Site (a page belongs to
    at most one Site — plans/SITE_OBJECT.md §2.5b). `page_id` comes from the query string. Idempotent: a page
    not on this Site is a no-op success."""
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    page_id = str(query_params(event).get("page_id") or "").strip()
    if not page_id:
        return error_response("page_id is required.", code="missing_page")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    pages = {slug: entry for slug, entry in (site.get("pages") or {}).items()
             if not (isinstance(entry, dict) and entry.get("page_id") == page_id)}
    site["pages"] = pages
    saved, error = _save_site_pages(repository, site)
    return error or json_response({"site": saved})


def check_subdomain(event, registry):
    """Availability check for a desired platform subdomain. Public to the dashboard; returns the
    normalized label, whether it's free, why not, and a few suggestions. `site_id` (optional) lets a
    Site re-check its own current label without seeing it as 'taken'."""
    params = (event or {}).get("queryStringParameters") or {}
    raw = params.get("name") or params.get("subdomain") or ""
    site_id = params.get("site_id") or ""
    label = normalize_subdomain(raw)
    result = {
        "input": raw,
        "normalized": label,
        "hostname": f"{label}.{hosting_domain()}" if label else "",
        "available": False,
        "reason": "",
        "suggestions": [],
        "owned_by_you": False,
    }
    rule = subdomain_rule_error(label)
    if rule:
        result["reason"] = rule
        result["suggestions"] = suggest_subdomains(raw, registry) if label else []
        return json_response(result)
    reservation = registry.reservation_of(label)
    if reservation and reservation.get("site_id") != site_id:
        tenant_id = tenant_id_from_event(event)
        # If the reservation belongs to this tenant, the label isn't "taken" — it's their own Site's address
        # in the other mode. Point them at Copy to Live instead of a dead-end + alternative names.
        if tenant_id and reservation.get("tenant_id") == tenant_id:
            result["owned_by_you"] = True
            result["reason"] = "You already use this address on another Site of yours — use Copy to Live to bring it here."
        else:
            result["reason"] = "That name is already taken."
            result["suggestions"] = suggest_subdomains(label, registry)
        return json_response(result)
    result["available"] = True
    return json_response(result)


def create_site(event, repository, registry=None, mode="test"):
    registry = registry or subdomain_registry()
    try:
        document = parse_json_body(event)
        if not isinstance(document, dict):
            return error_response("Site body must be an object.", code="invalid_site")
        if not _SITE_ID_RE.match(str(document.get("site_id") or "")):
            document["site_id"] = generate_site_id()
        document["document_type"] = "site"
        document.setdefault("schema_version", SITE_SCHEMA_VERSION)
        document.setdefault("tenant_id", tenant_id_from_event(event, document))
        now = int(time.time())
        document.setdefault("created_at", now)
        document["updated_at"] = now
        _ensure_platform_hostname(document)
        # Read the stored Site BEFORE validating: same_as verification state is server-owned and has to be
        # restored from what we stored, not taken from the payload. A client that could send
        # verification.state="verified" could assert any brand's real profile as its own identity in our
        # JSON-LD -- which is the whole reason sameAs is gated. See domain/social_links.py.
        existing = repository.get(str(document.get("tenant_id") or ""), str(document.get("site_id") or ""))
        organization = document.get("organization")
        if isinstance(organization, dict) and organization.get("same_as") is not None:
            organization["same_as"] = preserve_verification(organization, (existing or {}).get("organization"))
        validate_site(document)
        _assert_pages_unassigned(repository, document)
        _reserve_subdomain(registry, document)
        # An edit that flips the Site's search visibility (seo_enabled) must re-render the pages, since robots +
        # the storefront chrome are baked into each artifact at publish time (mirrors archive re-render).
        saved = repository.put(document)
        if existing is not None and site_seo_enabled(existing) != site_seo_enabled(saved):
            _republish_site_pages(str(saved.get("tenant_id") or ""), saved, mode=mode)
        return json_response({"site": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_site")


def _reserve_subdomain(registry, document: dict) -> None:
    """Atomically claim the Site's platform subdomain in the global registry (first-claim-wins).
    Custom-domain hosting is validated/reserved elsewhere, so it's skipped here."""
    hosting = document.get("hosting") or {}
    if hosting.get("type") == "custom":
        return
    hostname = str(hosting.get("platform_hostname") or "")
    label = hostname.split(".")[0] if hostname else ""
    if not label:
        return
    rule = subdomain_rule_error(label)
    if rule:
        raise DocumentValidationError(rule)
    claimed = registry.reserve(
        label,
        site_id=str(document.get("site_id") or ""),
        tenant_id=str(document.get("tenant_id") or ""),
        now=int(time.time()),
    )
    if not claimed:
        suggestions = suggest_subdomains(label, registry)
        hint = f" Try: {', '.join(suggestions)}." if suggestions else ""
        raise DocumentValidationError(f"The address '{hostname}' is already taken.{hint}")


def get_site(event, repository, site_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    return json_response({"site": site})


def list_sites(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    sites = repository.list_for_tenant(tenant_id)
    _refresh_eligibility(repository, tenant_id, sites)
    # Tell the dashboard THIS environment's free-tier hosting domain (prod jbay.uk / test jbay.be) so the
    # "store address" suffix + copy reflect the env instead of a hardcoded value.
    return json_response({"sites": sites, "hosting_domain": hosting_domain()})


def _refresh_eligibility(repository, tenant_id, sites):
    """Recompute each Site's indexing eligibility from the live Connect + domain state and persist any change,
    so the badge self-heals when the Sites screen loads (e.g. after a domain verified or Connect was captured).
    Best-effort: never fail the listing on a recompute error."""
    now = int(time.time())
    for site in sites:
        try:
            changed = False
            connect_verified, connect_restricted = _connect_state(tenant_id, site.get("environment"))
            eligibility = compute_site_eligibility(
                site, connect_verified=connect_verified, connect_restricted=connect_restricted,
                domain_verified=site_domain_verified(site),
            )
            if eligibility != (site.get("indexing") or {}).get("eligibility"):
                site["indexing"] = {**(site.get("indexing") or {}), "eligibility": eligibility, "eligibility_updated_at": now}
                changed = True
            # Backfill an IndexNow key for a verified Site that predates key generation (needed for SEO-15).
            if site_domain_verified(site) and not ((site.get("seo") or {}).get("indexnow_key")):
                site["seo"] = {**(site.get("seo") or {}), "indexnow_key": generate_indexnow_key()}
                changed = True
            if changed:
                site["updated_at"] = now
                repository.put(site)
        except Exception:
            continue


def update_site_status(event, repository, site_id, mode="test"):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_site_status")
    status = str(body.get("status") or "").strip()
    if status not in {"draft", "active", "archived"}:
        return error_response("Site status must be one of: draft, active, archived.", code="invalid_site_status")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    status_changed = str(site.get("status") or "") != status
    site["status"] = status
    site["updated_at"] = int(time.time())
    try:
        saved = repository.put(site)
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_site_status")
    # Archiving/reactivating changes each page's robots directive (noindex when archived), so re-render the
    # Site's pages immediately — the dashboard tells the tenant it takes effect now.
    if status_changed:
        _republish_site_pages(tenant_id, saved, mode=mode)
    return json_response({"site": saved})


def delete_site(event, repository, site_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, site_id)
    if not deleted:
        return error_response("Site not found.", status_code=404, code="not_found")
    return json_response({"site": deleted})


# ---------------------------------------------------------------------------------------------------------
# Custom-domain bridge (plans/SITE_OBJECT.md §2.6 first slice): a Site connects its own domain, which serves
# the Site's homepage (the "/" page) via the existing Cloudflare-for-SaaS resolver. On verification the domain
# becomes canonical and the Site can be index-eligible. Path-aware multi-page serving is deferred.
# ---------------------------------------------------------------------------------------------------------

def _cloudflare_config():
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    api_token = get_cloudflare_api_token()
    target_host = os.environ.get("CUSTOM_DOMAIN_TARGET_HOST", "domains.jbay.uk")
    return zone_id, api_token, target_host


def _apex_proxy_ips():
    """The static A/AAAA IPs for apex proxying (plans/SITE_OBJECT.md §2.6b), read from config. Empty until
    Cloudflare apex proxying is procured — then apex domains switch from ALIAS/flattening guidance to plain
    A/AAAA records (works on every provider, incl. Route 53) with no code change."""
    def _ips(name):
        return tuple(ip.strip() for ip in str(os.environ.get(name) or "").split(",") if ip.strip())
    return _ips("CLOUDFLARE_APEX_IPV4"), _ips("CLOUDFLARE_APEX_IPV6")


def _connect_state(tenant_id, environment):
    """(connect_verified, connect_restricted) for the tenant. Prefers the Connect verification the
    account.updated webhook captured on the stripe_keys doc; if it was never captured (a pre-existing connected
    account that hasn't had an update) but the tenant has a connected account, pulls the live status from
    Stripe ONCE and persists it — so eligibility reflects reality instead of a missing webhook."""
    mode = "live" if environment == "live" else "test"
    try:
        keys_repo = stripe_keys_repository()
        keys = keys_repo.get(tenant_id, mode)
    except Exception:
        return False, False
    state = str((keys or {}).get("connect_verification") or "")
    if state:
        return state == "verified", state == "restricted"
    account_id = str((keys or {}).get("connect_account_id") or "").strip()
    if not account_id:
        return False, False
    try:
        api_key = get_platform_secret_key(mode)
        if not api_key:
            return False, False
        account = stripe_request("GET", f"/accounts/{account_id}", api_key=api_key)
    except Exception:
        return False, False
    fields = connect_state_fields(account, now=int(time.time()))
    try:
        keys_repo.put({**keys, **fields, "mode": mode})
    except Exception:
        pass
    new_state = fields.get("connect_verification")
    return new_state == "verified", new_state == "restricted"


def _ensure_homepage(document, homepage_page_id):
    """The custom domain serves the Site's homepage — the page at slug "/". Returns its page_id, designating
    the requested page as homepage (moving it to "/") when the Site doesn't have one yet."""
    pages = document.get("pages") or {}
    root = pages.get("/")
    if isinstance(root, dict) and root.get("page_id"):
        return root["page_id"]
    homepage_page_id = str(homepage_page_id or "").strip()
    if not homepage_page_id:
        return None
    for slug, entry in list(pages.items()):
        if isinstance(entry, dict) and entry.get("page_id") == homepage_page_id:
            pages.pop(slug)
            pages["/"] = dict(entry)
            document["pages"] = pages
            return homepage_page_id
    # The Site doesn't track this page yet (it was created after the Site, before the page↔Site editor exists)
    # — attach the chosen page as the homepage so the domain has something to serve.
    pages["/"] = {"page_id": homepage_page_id, "page_type": "landing", "enabled": True}
    document["pages"] = pages
    return homepage_page_id


def _tag_www_records(records, domain):
    """Annotate the paired www hostname's DNS rows so the dashboard explains they set up a redirect, not a
    second live site — the www host 301s to the apex once its cert issues."""
    note = f"Points www at us so it 301-redirects to {domain} (your canonical root domain)."
    for rec in records or []:
        rec["note"] = note
    return records or []


def _setup_www_redirect(domain, *, zone_id, api_token, target_host, dcv_uuid, site_id, tenant_id):
    """For an APEX custom domain, provision a `www.<apex>` custom hostname that 301-redirects to the apex (the
    canonical, SEO — plans/SITE_OBJECT.md §2.6b). Best-effort: the apex works regardless of www. The redirect
    is driven by a `redirect_to` field on the www domain-index record (the resolver/Worker read it). Returns
    (www_hostname_id, www_dns_records, www_status), all empty on failure."""
    www = f"www.{domain}"
    try:
        www_hostname = create_custom_hostname(www, zone_id=zone_id, api_token=api_token)
    except CustomDomainError:
        www_hostname = find_custom_hostname(www, zone_id=zone_id, api_token=api_token)
    if not www_hostname:
        return "", [], ""
    www_records = _tag_www_records(
        custom_hostname_dns_records(www_hostname, hostname=www, dns_target=target_host, dcv_delegation_uuid=dcv_uuid), domain
    )
    www_status, _ = derive_status(cloudflare_hostname=www_hostname)
    try:
        custom_domains_index_repository().put(
            {"tenant_id": tenant_id, "domain": www, "redirect_to": domain, "status": www_status, "site_id": site_id}
        )
    except Exception:
        pass
    return str(www_hostname.get("id") or ""), www_records, www_status


def _teardown_www_redirect(provisioning, domain, *, zone_id, api_token, tenant_id):
    """Best-effort teardown of the paired www→apex redirect (Cloudflare hostname + index record) on disconnect."""
    www_id = str((provisioning or {}).get("www_custom_hostname_id") or "")
    if www_id and zone_id and api_token:
        try:
            delete_custom_hostname(www_id, zone_id=zone_id, api_token=api_token)
        except CustomDomainError:
            pass
    if domain:
        try:
            custom_domains_index_repository().delete(tenant_id, f"www.{domain}")
        except RepositoryError:
            pass


def _refresh_www_status(provisioning, domain, *, zone_id, api_token, dcv_uuid, site_id, tenant_id):
    """Re-poll the paired www hostname's status and re-write its redirect index record, so the www→apex
    redirect goes live once www's certificate issues. Best-effort; returns the fresh www dns_records (or [])."""
    www_id = str((provisioning or {}).get("www_custom_hostname_id") or "")
    if not www_id or not zone_id or not api_token:
        return []
    www = f"www.{domain}"
    try:
        www_hostname = get_custom_hostname(www_id, zone_id=zone_id, api_token=api_token)
    except CustomDomainError:
        return list((provisioning or {}).get("www_dns_records") or [])
    www_status, _ = derive_status(cloudflare_hostname=www_hostname)
    www_records = _tag_www_records(
        custom_hostname_dns_records(www_hostname, hostname=www, dns_target=provisioning.get("dns_target") or "", dcv_delegation_uuid=dcv_uuid), domain
    )
    provisioning["www_status"] = www_status
    provisioning["www_dns_records"] = www_records
    try:
        custom_domains_index_repository().put(
            {"tenant_id": tenant_id, "domain": www, "redirect_to": domain, "status": www_status, "site_id": site_id}
        )
    except Exception:
        pass
    return www_records


def _recompute_eligibility(site, tenant_id, now):
    connect_verified, connect_restricted = _connect_state(tenant_id, site.get("environment"))
    eligibility = compute_site_eligibility(
        site, connect_verified=connect_verified, connect_restricted=connect_restricted,
        domain_verified=site_domain_verified(site),
    )
    site["indexing"] = {**(site.get("indexing") or {}), "eligibility": eligibility, "eligibility_updated_at": now}
    return eligibility


def check_social_links(event, repository, site_id):
    """Re-check every checkable social profile on this Site and record what we found.

    Deliberately checks ALL of them in one request rather than one per row. Each fetch is a second or
    two and the cap is 6, so the worst case sits well inside API Gateway's 29s -- and a per-row endpoint
    would invite a tenant to sit and click, turning a slow social host into a queue of retries.

    Verification is only ever written HERE. The write boundary in create_site discards whatever a client
    sends, so this is the single producer of a `verified` state.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    organization = site.get("organization") or {}
    entries = organization.get("same_as") or []
    if not entries:
        return json_response({"site": site, "checked": 0})
    backlink_host = site_backlink_host(site)
    if not backlink_host:
        return error_response(
            "This Site has no address yet, so there is nothing for a profile to link back to.",
            code="no_backlink_host")
    now = int(time.time())
    checked = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry["verification"] = verify_entry(entry, backlink_host, now)
        if entry["verification"].get("method"):
            checked += 1
    organization["same_as"] = entries
    site["organization"] = organization
    site["updated_at"] = now
    saved = repository.put(site)
    return json_response({"site": saved, "checked": checked, "backlink_host": backlink_host})


LIVE_ONLY_MESSAGE = "Custom domains are available on your live Site only. Switch to Live to connect a domain."


def _reject_non_live_site(site):
    """Custom domains are a LIVE-only feature, and the axis that matters is the SITE's environment.

    The reason is reputational, not technical: a test Site serving a real domain would present sandbox
    pages as a real business, and search engines have no way to tell the difference. That is a
    reputation the tenant cannot get back.

    The router already refuses this on non-prod DEPLOYMENTS, but that is a different axis. On the prod
    deployment a Site with environment="test" passed that check, and neither connect nor check looked
    again -- so the only thing standing between a test Site and a real domain was the dashboard choosing
    not to render the form. Client-side gates are not access control.
    """
    if str(site.get("environment") or "").lower() != "live":
        return error_response(LIVE_ONLY_MESSAGE, status_code=403, code="custom_domains_live_only")
    return None


def connect_domain(event, repository, site_id):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_domain")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    gate = _reject_non_live_site(site)
    if gate is not None:
        return gate
    zone_id, api_token, target_host = _cloudflare_config()
    if not zone_id or not api_token:
        return error_response("Custom domains are not configured.", status_code=500, code="cloudflare_not_configured")
    domain = normalize_domain(body.get("domain"))
    try:
        assert_valid_domain(domain)
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="invalid_domain")
    homepage_id = _ensure_homepage(site, body.get("homepage_page_id"))
    if not homepage_id:
        return error_response("Choose which page your domain should show as its homepage.", code="homepage_required")
    try:
        cloudflare_hostname = create_custom_hostname(domain, zone_id=zone_id, api_token=api_token)
    except CustomDomainError as exc:
        # A prior partial attempt (or a retry) may have already created the Cloudflare hostname — reuse it so
        # connect is idempotent instead of dead-ending on 'duplicate custom hostname'.
        cloudflare_hostname = find_custom_hostname(domain, zone_id=zone_id, api_token=api_token)
        if not cloudflare_hostname:
            return error_response(exc.message, status_code=exc.status_code, code="custom_domain_error")
    dcv_uuid = get_dcv_delegation_uuid(zone_id=zone_id, api_token=api_token)
    apex_ipv4, apex_ipv6 = _apex_proxy_ips()
    dns_records = custom_hostname_dns_records(cloudflare_hostname, hostname=domain, dns_target=target_host, dcv_delegation_uuid=dcv_uuid, apex_ipv4=apex_ipv4, apex_ipv6=apex_ipv6)
    status, ssl_status = derive_status(cloudflare_hostname=cloudflare_hostname)
    now = int(time.time())
    hosting = site.get("hosting") or {}
    hosting["custom_domain"] = domain
    hosting.setdefault("type", "platform")  # stays platform until verified — see check_domain
    hosting["verification"] = {"verified": False, "method": "cloudflare_saas"}
    site["hosting"] = hosting
    provisioning = {
        "custom_hostname_id": str(cloudflare_hostname.get("id") or ""),
        "dns_records": dns_records,
        "dns_target": target_host,
        "status": status,
        "ssl_status": ssl_status,
        "homepage_page_id": homepage_id,
        "updated_at": now,
    }
    # An apex domain also gets a www.<apex> hostname that 301s to the apex (the canonical). Best-effort; the
    # apex serves regardless. Its DNS record is shown alongside the apex's.
    if is_apex_domain(domain):
        www_id, www_records, www_status = _setup_www_redirect(
            domain, zone_id=zone_id, api_token=api_token, target_host=target_host, dcv_uuid=dcv_uuid,
            site_id=site_id, tenant_id=tenant_id,
        )
        if www_id:
            provisioning["www_custom_hostname_id"] = www_id
            provisioning["www_dns_records"] = www_records
            provisioning["www_status"] = www_status
            dns_records = dns_records + www_records
            provisioning["dns_records"] = dns_records
    site["domain_provisioning"] = provisioning
    site["updated_at"] = now
    try:
        validate_site(site)
        saved = repository.put(site)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_domain")
    _put_site_index_records(saved)
    return json_response(
        {"site": saved, "dns_target": target_host, "dns_records": dns_records, "status": status},
        status_code=201,
    )


def _republish_site_pages(tenant_id, site, pages_repo=None, mode="test"):
    """Re-publish every page attached to the Site by re-putting its page doc, firing the publish stream. Called
    when a custom domain FIRST verifies: the reserved /sale //flash-sale + post-purchase funnel slugs, and each
    page's canonical/robots/index-eligibility, are computed at publish time gated on the domain being verified
    (`on_custom_domain`), so without this a page published BEFORE verification never picks them up until the
    tenant manually re-saves (plans/SALES_FUNNELS.md P2b). Best-effort — a verify must never fail on this."""
    try:
        pages_repo = pages_repo or pages_repository(mode=mode)
        seen = set()
        now = int(time.time())
        for entry in (site.get("pages") or {}).values():
            page_id = str(entry.get("page_id") or "") if isinstance(entry, dict) else ""
            if not page_id or page_id in seen:
                continue
            seen.add(page_id)
            page = pages_repo.get(tenant_id, page_id)
            if page:
                page["updated_at"] = now
                pages_repo.put(page)  # a MODIFY fires page_publish, which re-runs publish_page_document
    except Exception:  # noqa: BLE001 - re-publish is a best-effort side effect of verification
        pass


def check_domain(event, repository, site_id, pages_repo=None, mode="test"):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    gate = _reject_non_live_site(site)
    if gate is not None:
        return gate
    was_verified = bool(((site.get("hosting") or {}).get("verification") or {}).get("verified"))
    provisioning = site.get("domain_provisioning") or {}
    hostname_id = str(provisioning.get("custom_hostname_id") or "")
    domain = str((site.get("hosting") or {}).get("custom_domain") or "")
    if not hostname_id or not domain:
        return error_response("No custom domain is connected to this Site.", code="no_domain")
    zone_id, api_token, target_host = _cloudflare_config()
    try:
        cloudflare_hostname = get_custom_hostname(hostname_id, zone_id=zone_id, api_token=api_token)
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="custom_domain_error")
    dcv_uuid = get_dcv_delegation_uuid(zone_id=zone_id, api_token=api_token)
    apex_ipv4, apex_ipv6 = _apex_proxy_ips()
    dns_records = custom_hostname_dns_records(cloudflare_hostname, hostname=domain, dns_target=provisioning.get("dns_target") or target_host, dcv_delegation_uuid=dcv_uuid, apex_ipv4=apex_ipv4, apex_ipv6=apex_ipv6)
    status, ssl_status = derive_status(cloudflare_hostname=cloudflare_hostname)
    # Routing is confirmed but the cert is still pending: actively re-run DCV so a "Verify" click issues the
    # certificate now instead of waiting for Cloudflare's next poll. Only safe with delegation (dcv_uuid set),
    # where Cloudflare owns the challenge record.
    if status == "pending_ssl" and dcv_uuid:
        try:
            refreshed = retrigger_ssl_validation(hostname_id, zone_id=zone_id, api_token=api_token)
            if refreshed:
                status, ssl_status = derive_status(cloudflare_hostname=refreshed)
        except CustomDomainError:
            pass
    now = int(time.time())
    verified = status == "active"
    # Refresh the paired www→apex redirect hostname (apex domains only) and show its DNS record alongside.
    if is_apex_domain(domain):
        www_records = _refresh_www_status(provisioning, domain, zone_id=zone_id, api_token=api_token, dcv_uuid=dcv_uuid, site_id=site_id, tenant_id=tenant_id)
        if www_records:
            dns_records = dns_records + www_records
    provisioning.update({"status": status, "ssl_status": ssl_status, "dns_records": dns_records, "updated_at": now})
    site["domain_provisioning"] = provisioning
    hosting = site.get("hosting") or {}
    hosting["type"] = "custom" if verified else "platform"
    hosting["verification"] = {"verified": verified, "method": "cloudflare_saas", **({"verified_at": now} if verified else {})}
    site["hosting"] = hosting
    if verified:
        # A verified Site needs an IndexNow key (hosted at /{key}.txt, submitted on publish). Generate once.
        seo = dict(site.get("seo") or {})
        if not seo.get("indexnow_key"):
            seo["indexnow_key"] = generate_indexnow_key()
            site["seo"] = seo
    _recompute_eligibility(site, tenant_id, now)
    site["updated_at"] = now
    try:
        validate_site(site)
        saved = repository.put(site)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_domain")
    _put_site_index_records(saved)
    # First verification: re-publish the Site's pages so publish-time, verified-domain-gated work (reserved
    # /sale //flash-sale + funnel slugs, per-page canonical/robots/index-eligibility) attaches for pages that
    # were published before the domain verified. The index above still reflects pre-verify pages.routes; the
    # re-publish updates pages.routes and re-syncs the index right after.
    if verified and not was_verified:
        _republish_site_pages(tenant_id, saved, pages_repo, mode=mode)
    # When not yet verified, tell the tenant exactly why: a record that isn't resolving (wrong name/value) vs.
    # records that look right but the certificate is still issuing.
    diagnostics, hint = [], ""
    if not verified:
        diagnostics = diagnose_dns_records(dns_records)
        missing = [d for d in diagnostics if not d.get("resolved")]
        if missing:
            parts = [f"{d['name']} ({d['note']})" if d.get("note") else d["name"] for d in missing]
            hint = "These records aren't resolving yet — check the name, type, and value exactly as shown: " + "; ".join(parts) + "."
        else:
            hint = "Your DNS records look correct. Cloudflare is issuing the certificate — this can take a few minutes. Re-check shortly."
    return json_response({"site": saved, "status": status, "dns_records": dns_records, "diagnostics": diagnostics, "hint": hint})


def disconnect_domain(event, repository, site_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    site = repository.get(tenant_id, site_id)
    if not site:
        return error_response("Site not found.", status_code=404, code="not_found")
    provisioning = site.get("domain_provisioning") or {}
    hostname_id = str(provisioning.get("custom_hostname_id") or "")
    domain = str((site.get("hosting") or {}).get("custom_domain") or "")
    zone_id, api_token, _ = _cloudflare_config()
    if hostname_id and zone_id and api_token:
        try:
            delete_custom_hostname(hostname_id, zone_id=zone_id, api_token=api_token)
        except CustomDomainError:
            pass  # best-effort teardown; the Cloudflare hostname may already be gone
    _teardown_www_redirect(provisioning, domain, zone_id=zone_id, api_token=api_token, tenant_id=tenant_id)
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
        saved = repository.put(site)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_domain")
    if domain:
        try:
            custom_domains_index_repository().delete(tenant_id, domain)
        except RepositoryError:
            pass
    return json_response({"site": saved, "disconnected": True})


def _assert_pages_unassigned(repository, document):
    """A page_id belongs to at most one Site (Site.schema.json). Reject a create/update that claims a page
    already routed by another of the tenant's Sites."""
    tenant_id = str(document.get("tenant_id") or "")
    site_id = str(document.get("site_id") or "")
    mine = {str(entry.get("page_id") or "") for entry in (document.get("pages") or {}).values() if entry.get("page_id")}
    if not mine or not tenant_id:
        return
    for other in repository.list_for_tenant(tenant_id):
        if other.get("site_id") == site_id:
            continue
        theirs = {str(entry.get("page_id") or "") for entry in (other.get("pages") or {}).values()}
        clash = mine & theirs
        if clash:
            raise DocumentValidationError(
                f"Page '{sorted(clash)[0]}' already belongs to Site '{other.get('site_id')}'. A page can belong to only one Site."
            )
