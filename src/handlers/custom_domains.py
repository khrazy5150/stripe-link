import os
import time
from urllib.request import urlopen

from stripe_link.cloudflare_secrets import get_cloudflare_api_token
from stripe_link.common import error_response, json_response, parse_json_body, path_params, tenant_id_from_event
from stripe_link.domain.custom_domains import (
    CustomDomainError,
    assert_valid_domain,
    build_domain,
    create_custom_hostname,
    delete_custom_hostname,
    derive_status,
    dns_record_matches,
    get_custom_hostname,
    normalize_domain,
    validation_record_from_hostname,
)
from stripe_link.domain.documents import DocumentValidationError, validate_tenant_config
from stripe_link.repositories.documents import RepositoryError, custom_domains_index_repository, platform_config_repository


def handler(
    event,
    context,
    *,
    config_repo=None,
    index_repo=None,
    zone_id=None,
    api_token=None,
    opener=None,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})

    config_repo = config_repo or platform_config_repository()
    index_repo = index_repo or custom_domains_index_repository()
    zone_id = zone_id if zone_id is not None else os.environ.get("CLOUDFLARE_ZONE_ID", "")
    api_token = api_token if api_token is not None else get_cloudflare_api_token()
    opener = opener or urlopen

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    domain = path_params(event).get("domain")
    request_path = str(event.get("path") or event.get("resource") or "")
    is_check_route = bool(domain) and request_path.rstrip("/").endswith("/check")

    if not zone_id or not api_token:
        return error_response("Cloudflare is not configured.", status_code=500, code="cloudflare_not_configured")

    try:
        if method == "GET" and not domain:
            return list_domains(tenant_id, config_repo)
        if method == "POST" and not domain:
            return create_domain(
                event, tenant_id, config_repo, index_repo,
                zone_id=zone_id, api_token=api_token, opener=opener, now_fn=now_fn,
            )
        if method == "POST" and domain and is_check_route:
            return check_domain(
                tenant_id, domain, config_repo, index_repo,
                zone_id=zone_id, api_token=api_token, opener=opener, now_fn=now_fn,
            )
        if method == "DELETE" and domain:
            return delete_domain(
                tenant_id, domain, config_repo, index_repo,
                zone_id=zone_id, api_token=api_token, opener=opener,
            )
    except CustomDomainError as exc:
        return error_response(exc.message, status_code=exc.status_code, code="custom_domain_error")
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    except DocumentValidationError as exc:
        return error_response(str(exc), code="invalid_config")

    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def load_config(tenant_id, config_repo):
    config = config_repo.get(tenant_id) or {
        "schema_version": "2026-05-29",
        "document_type": "tenant_config",
        "tenant_id": tenant_id,
    }
    custom_domains = config.get("custom_domains")
    if not isinstance(custom_domains, dict):
        custom_domains = {"enabled": True, "domains": []}
    if not isinstance(custom_domains.get("domains"), list):
        custom_domains["domains"] = []
    custom_domains.setdefault("dns_target", os.environ.get("CUSTOM_DOMAIN_TARGET_HOST", "domains.jbay.uk"))
    config["custom_domains"] = custom_domains
    return config


def find_domain_entry(config, domain):
    for entry in config["custom_domains"]["domains"]:
        if entry.get("domain") == domain:
            return entry
    return None


def list_domains(tenant_id, config_repo):
    config = load_config(tenant_id, config_repo)
    return json_response({
        "domains": config["custom_domains"]["domains"],
        "dns_target": config["custom_domains"]["dns_target"],
    })


def create_domain(event, tenant_id, config_repo, index_repo, *, zone_id, api_token, opener, now_fn):
    body = parse_json_body(event)
    domain = str(body.get("domain") or "").strip()
    if domain:
        domain = normalize_domain(domain)
    else:
        domain = build_domain(body.get("apex_domain"), body.get("subdomain_label"))
    assert_valid_domain(domain)

    target_page_id = str(body.get("target_page_id") or "").strip()
    if not target_page_id:
        return error_response("target_page_id is required.", code="missing_target_page")

    config = load_config(tenant_id, config_repo)
    if find_domain_entry(config, domain):
        return error_response(f"Domain '{domain}' is already configured.", status_code=409, code="already_exists")

    cloudflare_hostname = create_custom_hostname(domain, zone_id=zone_id, api_token=api_token, opener=opener)
    validation_record = validation_record_from_hostname(cloudflare_hostname)

    now = int(now_fn())
    entry = {
        "domain": domain,
        "apex_domain": str(body.get("apex_domain") or "").strip() or normalize_domain(domain.split(".", 1)[-1]),
        "target_page_id": target_page_id,
        "target_type": "landing_page",
        "cloudflare_hostname_id": str(cloudflare_hostname.get("id") or ""),
        "status": "pending_dns",
        "ssl_status": str((cloudflare_hostname.get("ssl") or {}).get("status") or ""),
        "validation_record": validation_record,
        "created_at": now,
        "updated_at": now,
    }
    config["custom_domains"]["domains"].append(entry)
    validate_tenant_config(config)
    saved = config_repo.put(config)

    index_repo.put({"tenant_id": tenant_id, "domain": domain, "target_page_id": target_page_id, "status": "pending_dns"})

    saved_entry = find_domain_entry(saved, domain) or entry
    return json_response({"domain": saved_entry}, status_code=201)


def check_domain(tenant_id, domain, config_repo, index_repo, *, zone_id, api_token, opener, now_fn):
    config = load_config(tenant_id, config_repo)
    entry = find_domain_entry(config, domain)
    if not entry:
        return error_response("Domain not found.", status_code=404, code="not_found")

    cloudflare_hostname = get_custom_hostname(
        entry.get("cloudflare_hostname_id", ""), zone_id=zone_id, api_token=api_token, opener=opener,
    )
    validation_record = validation_record_from_hostname(cloudflare_hostname) or entry.get("validation_record") or {}
    dns_verified = dns_record_matches(
        validation_record.get("name", ""), "TXT", validation_record.get("value", ""), opener=opener,
    )
    status, ssl_status = derive_status(dns_verified=dns_verified, cloudflare_hostname=cloudflare_hostname)

    entry["status"] = status
    entry["ssl_status"] = ssl_status
    entry["validation_record"] = validation_record
    entry["updated_at"] = int(now_fn())
    validate_tenant_config(config)
    saved = config_repo.put(config)

    index_repo.put({"tenant_id": tenant_id, "domain": domain, "target_page_id": entry["target_page_id"], "status": status})

    saved_entry = find_domain_entry(saved, domain) or entry
    return json_response({"domain": saved_entry, "dns_verified": dns_verified})


def delete_domain(tenant_id, domain, config_repo, index_repo, *, zone_id, api_token, opener):
    config = load_config(tenant_id, config_repo)
    entry = find_domain_entry(config, domain)
    if not entry:
        return error_response("Domain not found.", status_code=404, code="not_found")

    delete_custom_hostname(entry.get("cloudflare_hostname_id", ""), zone_id=zone_id, api_token=api_token, opener=opener)

    config["custom_domains"]["domains"] = [
        item for item in config["custom_domains"]["domains"] if item.get("domain") != domain
    ]
    validate_tenant_config(config)
    config_repo.put(config)
    index_repo.delete(tenant_id, domain)

    return json_response({"deleted": True, "domain": domain})
