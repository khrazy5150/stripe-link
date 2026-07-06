"""Digital-download helpers (pure -- no I/O).

Digital products carry a `digital_asset` (file stored privately in the media bucket).
Buyers get a purchase-verified link `{api_base}/download?session_id&product_id&tenant_id`;
the serve endpoint checks the session's order is paid before issuing a short-lived
presigned URL.
"""

import re
from typing import Any
from urllib.parse import urlencode

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    name = _SAFE_FILENAME.sub("_", str(filename or "").strip()).strip("._") or "download"
    return name[:200]


def asset_bucket_key(tenant_id: str, product_id: str, asset_id: str, filename: str) -> str:
    return f"downloads/{tenant_id}/{product_id}/{asset_id}/{sanitize_filename(filename)}"


def build_download_url(api_base: str, *, tenant_id: str, session_id: str, product_id: str) -> str:
    base = str(api_base or "").rstrip("/")
    if not base or not session_id or not product_id or not tenant_id:
        return ""
    query = urlencode({"session_id": session_id, "product_id": product_id, "tenant_id": tenant_id})
    return f"{base}/download?{query}"


def digital_download_links(order: dict[str, Any], product: dict[str, Any], api_base: str) -> list[dict[str, str]]:
    """One link per digital product on the order (currently the order carries a single product)."""
    asset = (product or {}).get("digital_asset")
    if not isinstance(asset, dict) or not asset.get("bucket_key"):
        return []
    url = build_download_url(
        api_base,
        tenant_id=str(order.get("tenant_id") or ""),
        session_id=str(order.get("session_id") or ""),
        product_id=str((product or {}).get("product_id") or ""),
    )
    if not url:
        return []
    return [{"label": str(asset.get("filename") or "Download"), "url": url}]
