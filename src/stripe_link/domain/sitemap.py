"""Per-Site crawl artifacts (plans/SITE_OBJECT.md Phase 2.4, ON_PAGE_SEO SEO-14/15): sitemap.xml, robots.txt,
and the IndexNow key. Pure generation — the publisher writes these to S3 next to the homepage artifact and
submits to IndexNow."""
import secrets
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


def generate_indexnow_key() -> str:
    """A per-Site IndexNow key: 32 hex chars (within IndexNow's 8–128 range, no ambiguous characters)."""
    return secrets.token_hex(16)


def _iso_date(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def sitemap_xml(entries: list[dict[str, Any]]) -> str:
    """A urlset over `entries` = [{loc, lastmod?(epoch seconds), images?[urls]}]. Carries the image-sitemap
    namespace so cross-origin product images (images.juniorbay.com) are still discoverable."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for entry in entries:
        loc = str(entry.get("loc") or "").strip()
        if not loc:
            continue
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(loc)}</loc>")
        lastmod = _iso_date(entry.get("lastmod"))
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        for image in entry.get("images") or []:
            image = str(image or "").strip()
            if image:
                lines.append(f"    <image:image><image:loc>{escape(image)}</image:loc></image:image>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def robots_txt(sitemap_url: str, *, allow: bool = True) -> str:
    """robots.txt for a custom domain. Allow-variant (the default) points crawlers at the sitemap. An archived
    Site serves the disallow-all variant so its whole domain is dropped from crawling (pairs with the
    noindex,nofollow,noarchive meta on each page). Platform hosts never serve robots.txt."""
    if not allow:
        return "User-agent: *\nDisallow: /\n"
    return f"User-agent: *\nAllow: /\n\nSitemap: {sitemap_url.strip()}\n"


def indexnow_body(host: str, key: str, url_list: list[str]) -> dict[str, Any]:
    """The IndexNow submission payload (POST to INDEXNOW_ENDPOINT)."""
    return {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": [url for url in url_list if url],
    }
