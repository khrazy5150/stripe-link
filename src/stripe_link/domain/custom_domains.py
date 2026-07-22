import json
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


def route_table(site: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project a Site's slug→page map into the flat routing table denormalized onto the domain-index record
    (plans/SITE_OBJECT.md §2.6). The edge resolver reads this, never the live Site document. Every attached
    slug is included with its enabled flag so the resolver can 404 a disabled slug without a Site read."""
    table: dict[str, dict[str, Any]] = {}
    for slug, entry in (site.get("pages") or {}).items():
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("page_id") or "")
        if not page_id:
            continue
        table[slug] = {"page_id": page_id, "enabled": entry.get("enabled", True) is not False}
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
    }


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
    if not DOMAIN_PATTERN.match(domain):
        raise CustomDomainError(f"'{domain}' is not a valid domain name.", status_code=400)
    if is_apex_domain(domain):
        raise CustomDomainError(
            "Apex domains aren't supported yet — use a subdomain like 'shop.example.com' or 'www.example.com'. "
            "Apex support is coming.",
            status_code=400,
        )


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


def custom_hostname_dns_records(
    cloudflare_hostname: dict[str, Any], *, hostname: str, dns_target: str, dcv_delegation_uuid: str | None = None
) -> list[dict[str, str]]:
    """The DNS records the tenant must create. Preferred shape = two STABLE CNAMEs: the routing CNAME and the
    DCV-delegation CNAME (Cloudflare then manages the ACME token + renewals). Only when no delegation UUID is
    available do we fall back to Cloudflare's rotating ownership TXT + `_acme-challenge` DCV records."""
    records: list[dict[str, str]] = [{"type": "CNAME", "name": hostname, "value": dns_target}]
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
