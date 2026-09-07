"""Recognising a YouTube or Vimeo link, and what to render for it.

A tenant who already has their video on YouTube should not have to re-upload it. Pasting the link is the
obvious thing to do -- which is why the old "Video URL" field, which wanted a bare `.mp4`, silently
rendered a YouTube link as a BROKEN IMAGE on the published page.

Parsing lives here, pure, because it is the security boundary: the id is interpolated into an iframe URL,
so it is matched against a strict character class rather than trusted. A URL that is not recognisably one
of these providers is not an embed, and the caller falls back to its file handling.
"""

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

# Deliberately strict. Anything reaching an iframe src or a thumbnail URL must be [A-Za-z0-9_-] only, so a
# crafted link cannot add query parameters or escape the URL it is placed in.
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_VIMEO_ID = re.compile(r"^[0-9]{6,12}$")

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
                  "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}


def _youtube_id(parsed) -> str:
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host in ("youtu.be", "www.youtu.be"):
        return path.split("/")[0]
    if path.startswith(("embed/", "shorts/", "live/", "v/")):
        return path.split("/", 1)[1].split("/")[0]
    return (parse_qs(parsed.query).get("v") or [""])[0]


def _vimeo_id(parsed) -> str:
    # vimeo.com/123, player.vimeo.com/video/123, vimeo.com/channels/staffpicks/123 -- the id is the last
    # purely numeric segment, which is what every one of those shapes has in common.
    for part in reversed([p for p in parsed.path.split("/") if p]):
        if part.isdigit():
            return part
    return ""


def parse_video_embed(url: Any) -> dict[str, str] | None:
    """{provider, video_id, embed_url, thumbnail_url} for a recognised link, else None."""
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text if "//" in text else f"https://{text}")
    host = parsed.netloc.lower()

    if host in _YOUTUBE_HOSTS:
        video_id = _youtube_id(parsed)
        if _YOUTUBE_ID.match(video_id):
            return {
                "provider": "youtube",
                "video_id": video_id,
                # nocookie: YouTube sets no tracking cookie until the visitor actually plays.
                "embed_url": f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&rel=0",
                # Deterministic, so the poster costs no API call at publish time. hqdefault always exists;
                # maxresdefault does not, and a missing one renders as a grey 404 placeholder.
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            }
        return None

    if host in _VIMEO_HOSTS:
        video_id = _vimeo_id(parsed)
        if _VIMEO_ID.match(video_id):
            return {
                "provider": "vimeo",
                "video_id": video_id,
                "embed_url": f"https://player.vimeo.com/video/{video_id}?autoplay=1",
                # Vimeo thumbnails need an oEmbed lookup, so there is no deterministic URL. Rather than add
                # a network call to publish, the facade falls back to a neutral poster.
                "thumbnail_url": "",
            }
        return None

    return None


def is_video_embed(url: Any) -> bool:
    return parse_video_embed(url) is not None
