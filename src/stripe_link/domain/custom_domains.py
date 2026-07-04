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


def build_domain(apex_domain: str, subdomain_label: str) -> str:
    apex = normalize_domain(apex_domain)
    label = str(subdomain_label or "").strip().lower()
    if not apex or not label:
        raise CustomDomainError("Both apex_domain and subdomain_label are required.", status_code=400)
    return f"{label}.{apex}"


def assert_valid_domain(domain: str) -> None:
    if not DOMAIN_PATTERN.match(domain):
        raise CustomDomainError(f"'{domain}' is not a valid domain name.", status_code=400)
    if domain.count(".") < 1:
        raise CustomDomainError("A subdomain is required (e.g. 'shop.example.com'), not a bare domain.", status_code=400)


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


def derive_status(*, dns_verified: bool, cloudflare_hostname: dict[str, Any]) -> tuple[str, str]:
    """Combine our own DNS check with Cloudflare's hostname/SSL state into the app-level status.

    Returns (status, ssl_status). `status` is one of the TenantConfig custom-domain enum
    values; `ssl_status` is Cloudflare's raw ssl.status string, stored for display/debugging.
    """
    ssl_status = str((cloudflare_hostname.get("ssl") or {}).get("status") or "")
    hostname_status = str(cloudflare_hostname.get("status") or "")

    if not dns_verified:
        return "pending_dns", ssl_status

    if hostname_status in {"moved", "deleted"} or any(marker in ssl_status for marker in _FAILED_SSL_STATUSES_MARKERS):
        return "failed", ssl_status

    if ssl_status in _ACTIVE_SSL_STATUSES and hostname_status in {"active", ""}:
        return "active", ssl_status

    return "pending_ssl", ssl_status
