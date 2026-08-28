"""Server-side reader for the platform's global app_config document (deploy-populated, DynamoDB).

The single place the backend reads centralized, config-driven platform values so a URL/identity change is a config
edit (no code change): the asset-delivery CDN base (public_asset_base_url) and the platform legal identity
(app_config.legal). Container-cached and FAILSAFE — with no APP_CONFIG_TABLE (tests, local) it reads nothing and
returns empties, so importing modules stay pure and tests stay fast. See plans/SERVE_HOST_SCHEME.md.
"""
import os
import time
from typing import Any

# Container cache with a TTL so a config edit (e.g. the legal address) reaches every warm Lambda within
# minutes — a warm container previously held the first read for its whole lifetime. Mirrors
# BILLING_CONFIG_CACHE_TTL_SECONDS in fees.py.
APP_CONFIG_CACHE_TTL_SECONDS = int(os.environ.get("APP_CONFIG_CACHE_TTL_SECONDS", "300"))
_CACHE: dict[str, Any] = {}


def _app_config_doc() -> dict[str, Any]:
    if "doc" in _CACHE and _CACHE.get("expires_at", 0) > time.time():
        return _CACHE["doc"]
    doc: dict[str, Any] = {}
    if os.environ.get("APP_CONFIG_TABLE"):
        try:  # never let a config read break a render / a public legal page
            from stripe_link.repositories.documents import app_config_repository

            doc = app_config_repository().get("app_config", "global") or {}
        except Exception:
            doc = {}
    _CACHE["doc"] = doc
    _CACHE["expires_at"] = time.time() + APP_CONFIG_CACHE_TTL_SECONDS
    return doc


def reset_cache() -> None:
    """Drop the container cache (tests)."""
    _CACHE.clear()


def asset_base_url() -> str:
    """The configured asset-CDN base for THIS stack's environment (public_asset_base_url); '' if unset."""
    env = os.environ.get("ENVIRONMENT", "")
    envs = _app_config_doc().get("environments") or {}
    return str((envs.get(env) or {}).get("public_asset_base_url") or "").rstrip("/")


def default_favicon_url() -> str:
    """The platform default favicon on the configured CDN; '' when unconfigured (so no literal is baked in)."""
    base = asset_base_url()
    return f"{base}/icon/favicon.png" if base else ""


def legal_overrides() -> dict[str, str]:
    """Platform legal-identity overrides (app_config.legal) to merge OVER the code defaults; {} if unset."""
    legal = _app_config_doc().get("legal")
    return {str(k): str(v) for k, v in legal.items()} if isinstance(legal, dict) else {}
