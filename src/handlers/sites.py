import os
import re
import secrets
import string
import time

from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_site
from stripe_link.repositories.documents import RepositoryError, sites_repository, subdomain_registry

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


def handler(event, context, repository=None, registry=None):
    repository = repository or sites_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    site_id = path_params(event).get("site_id")
    resource = (event or {}).get("resource") or ""
    if method == "GET" and resource.endswith("/subdomain"):
        return check_subdomain(event, registry or subdomain_registry())
    if method == "PATCH" and site_id and resource.endswith("/status"):
        return update_site_status(event, repository, site_id)
    if method == "POST":
        return create_site(event, repository, registry)
    if method == "GET":
        if site_id:
            return get_site(event, repository, site_id)
        return list_sites(event, repository)
    if method == "DELETE" and site_id:
        return delete_site(event, repository, site_id)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


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
    }
    rule = subdomain_rule_error(label)
    if rule:
        result["reason"] = rule
        result["suggestions"] = suggest_subdomains(raw, registry) if label else []
        return json_response(result)
    owner = registry.owner_of(label)
    if owner and owner != site_id:
        result["reason"] = "That name is already taken."
        result["suggestions"] = suggest_subdomains(label, registry)
        return json_response(result)
    result["available"] = True
    return json_response(result)


def create_site(event, repository, registry=None):
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
        validate_site(document)
        _assert_pages_unassigned(repository, document)
        _reserve_subdomain(registry, document)
        saved = repository.put(document)
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
    return json_response({"sites": repository.list_for_tenant(tenant_id)})


def update_site_status(event, repository, site_id):
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
    site["status"] = status
    site["updated_at"] = int(time.time())
    try:
        saved = repository.put(site)
        return json_response({"site": saved})
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_site_status")


def delete_site(event, repository, site_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    deleted = repository.delete(tenant_id, site_id)
    if not deleted:
        return error_response("Site not found.", status_code=404, code="not_found")
    return json_response({"site": deleted})


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
