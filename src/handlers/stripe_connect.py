import base64
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import RepositoryError, stripe_keys_repository, tenant_profiles_repository
from stripe_link.security import redact_sensitive_fields
from stripe_link.stripe_platform_secrets import get_platform_secret_key


STRIPE_OAUTH_TOKEN_URL = "https://connect.stripe.com/oauth/token"
STRIPE_OAUTH_DEAUTHORIZE_URL = "https://connect.stripe.com/oauth/deauthorize"


def _normalize_mode(mode):
    return "live" if mode == "live" else "test"


def _redirect(location):
    return {
        "statusCode": 302,
        "headers": {
            "Location": location,
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": "",
    }


def _dashboard_redirect(params):
    base = (os.environ.get("DASHBOARD_URL") or "/").rstrip("/") or "/"
    query = urlencode(params)
    separator = "&" if "?" in base else "?"
    return _redirect(f"{base}{separator}{query}")


def _parse_state(state):
    parts = (state or "").split(":")
    return {
        "tenant_id": parts[0] if len(parts) > 0 else "",
        "mode": _normalize_mode(parts[1] if len(parts) > 1 else "test"),
        "chain": parts[2] if len(parts) > 2 else "",
        "path": parts[3] if len(parts) > 3 else "",
        "oauth_mode": _normalize_mode(parts[4] if len(parts) > 4 else parts[1] if len(parts) > 1 else "test"),
    }


def _tenant_owner_email(tenant_id, repository=None):
    if not tenant_id:
        return ""
    repository = repository or tenant_profiles_repository()
    tenant = repository.get(tenant_id, tenant_id) or {}
    owner = tenant.get("owner") if isinstance(tenant.get("owner"), dict) else {}
    return str(tenant.get("owner_email") or owner.get("email") or "").strip()


def _exchange_oauth_code(code, mode):
    secret_key = get_platform_secret_key(mode)
    if not secret_key:
        raise RuntimeError("Junior Bay platform Stripe secret is not configured.")

    payload = urlencode({
        "grant_type": "authorization_code",
        "code": code,
    }).encode("utf-8")
    auth = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    request = Request(
        STRIPE_OAUTH_TOKEN_URL,
        data=payload,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Stripe OAuth token exchange failed: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Stripe OAuth token exchange failed: {exc.reason}") from exc


def _stripe_oauth_request(url, payload, mode, error_prefix):
    secret_key = get_platform_secret_key(mode)
    if not secret_key:
        raise RuntimeError("Junior Bay platform Stripe secret is not configured.")

    auth = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    request = Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{error_prefix}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{error_prefix}: {exc.reason}") from exc


def _client_id_for_mode(mode):
    if mode == "test":
        return os.environ.get("STRIPE_CLIENT_ID_TEST", "").strip(), "test"
    return (
        os.environ.get("STRIPE_CLIENT_ID_LIVE", "").strip()
        or os.environ.get("STRIPE_CLIENT_ID", "").strip()
    ), "live"


def _deauthorize_connected_account(account_id, mode):
    client_id, oauth_mode = _client_id_for_mode(mode)
    if not client_id:
        raise RuntimeError("Stripe Connect is not configured for this environment.")
    return _stripe_oauth_request(
        STRIPE_OAUTH_DEAUTHORIZE_URL,
        {
            "client_id": client_id,
            "stripe_user_id": account_id,
        },
        oauth_mode,
        "Stripe OAuth deauthorization failed",
    )


def start_handler(event, context, tenant_repository=None):
    tenant_id = tenant_id_from_event(event)
    query = event.get("queryStringParameters") or {}
    mode = _normalize_mode(query.get("mode", "test"))
    chain = query.get("chain", "")
    path = query.get("path", "existing")
    should_redirect = query.get("redirect") == "1"
    client_id, oauth_mode = _client_id_for_mode(mode)
    redirect_uri = os.environ.get("STRIPE_CONNECT_REDIRECT_URI", "")
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not client_id or not redirect_uri:
        return error_response("Stripe Connect is not configured for this environment.", status_code=503, code="connect_not_configured")
    state = f"{tenant_id}:{mode}:{chain or 'single'}:{path or 'existing'}:{oauth_mode}"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    try:
        owner_email = _tenant_owner_email(tenant_id, tenant_repository)
        if owner_email:
            params["stripe_user[email]"] = owner_email
    except RepositoryError:
        pass
    params = urlencode(params)
    connect_url = f"https://connect.stripe.com/oauth/authorize?{params}"
    if should_redirect:
        return _redirect(connect_url)
    return json_response({
        "connect_url": connect_url,
        "state": state,
        "chain": chain or None,
        "oauth_mode": oauth_mode,
    })


def callback_handler(event, context, repository=None, secret_cipher=None):
    repository = repository or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    query = (event or {}).get("queryStringParameters") or {}
    state = _parse_state(query.get("state", ""))
    tenant_id = state["tenant_id"] or tenant_id_from_event(event)
    mode = state["mode"]
    chain = state["chain"]
    path = state["path"]
    oauth_mode = state["oauth_mode"]
    if query.get("error"):
        return _dashboard_redirect({
            "stripe_connect": "error",
            "mode": mode,
            "message": query.get("error_description") or query.get("error"),
        })
    code = query.get("code")
    if not tenant_id or not code:
        return _dashboard_redirect({
            "stripe_connect": "error",
            "mode": mode,
            "message": "Stripe did not return a usable authorization code.",
        })
    try:
        token_response = _exchange_oauth_code(code, oauth_mode)
        connected_mode = "live" if token_response.get("livemode") else oauth_mode
        now = int(time.time())
        existing = repository.get(tenant_id, connected_mode) or {}
        document = {
            **existing,
            "schema_version": "2026-05-29",
            "document_type": "stripe_keys",
            "tenant_id": tenant_id,
            "mode": connected_mode,
            "publishable_key": token_response.get("stripe_publishable_key") or existing.get("publishable_key", ""),
            "connect_account_id": token_response.get("stripe_user_id") or existing.get("connect_account_id", ""),
            "connect_status": "connected",
            "connect_scope": token_response.get("scope") or existing.get("connect_scope", ""),
            "connect_livemode": connected_mode == "live",
            "connect_requested_mode": mode,
            "connect_oauth_mode": oauth_mode,
            "connected_at": now,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        if token_response.get("access_token"):
            document["connect_access_token_ref"] = secret_cipher.encrypt(
                token_response["access_token"],
                tenant_id=tenant_id,
                mode=mode,
                field="connect_access_token",
            )
        if token_response.get("refresh_token"):
            document["connect_refresh_token_ref"] = secret_cipher.encrypt(
                token_response["refresh_token"],
                tenant_id=tenant_id,
                mode=mode,
                field="connect_refresh_token",
            )
        repository.put(document)

        return _dashboard_redirect({
            "stripe_connect": "connected",
            "mode": connected_mode,
            "tenant_id": tenant_id,
        })
    except (RuntimeError, RepositoryError, ValueError) as exc:
        return _dashboard_redirect({
            "stripe_connect": "error",
            "mode": mode,
            "message": str(exc),
        })


def status_handler(event, context, repository=None):
    repository = repository or stripe_keys_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        query = (event or {}).get("queryStringParameters") or {}
        mode = _normalize_mode(query.get("mode", "test"))
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        keys = repository.get(tenant_id, mode)
        return json_response({"stripe_connect": redact_sensitive_fields(keys) if keys else {"connect_status": "not_connected"}})
    if method in {"POST", "PUT"}:
        try:
            document = parse_json_body(event)
            if not document.get("tenant_id"):
                return error_response("tenant_id is required.", code="missing_tenant")
            saved = repository.put({
                "schema_version": "2026-05-29",
                "document_type": "stripe_keys",
                "mode": document.get("mode", "test"),
                "publishable_key": document.get("publishable_key", ""),
                **document,
            })
            return json_response({"stripe_connect": redact_sensitive_fields(saved)}, status_code=201)
        except (ValueError, RepositoryError) as exc:
            return error_response(str(exc), code="invalid_connect_status")
    if method == "DELETE":
        tenant_id = tenant_id_from_event(event)
        query = (event or {}).get("queryStringParameters") or {}
        mode = _normalize_mode(query.get("mode", "test"))
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        try:
            existing = repository.get(tenant_id, mode) or {}
            account_id = existing.get("connect_account_id")
            if account_id:
                _deauthorize_connected_account(account_id, mode)
            preserved = {
                key: value
                for key, value in existing.items()
                if not key.startswith("connect_") and key not in {"publishable_key"}
            }
            saved = repository.put({
                **preserved,
                "schema_version": "2026-05-29",
                "document_type": "stripe_keys",
                "tenant_id": tenant_id,
                "mode": mode,
                "connect_status": "not_connected",
                "updated_at": int(time.time()),
            })
            return json_response({"stripe_connect": redact_sensitive_fields(saved)})
        except (RuntimeError, RepositoryError, ValueError) as exc:
            return error_response(str(exc), code="disconnect_connect_error")
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")
