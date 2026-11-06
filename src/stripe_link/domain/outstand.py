"""The Outstand publisher, behind the normalized adapter contract (plans/ATTENTION_PRIMITIVE.md §6.1).

**The contract is the insurance.** A post is stored in OUR schema and mapped to the vendor's request shape
here, at the edge, so a second publisher — or a direct per-platform adapter — slots in behind the same
`publish()` without touching anything that calls it. Nothing above this module may learn the word
`containers`.

**One publish FANS OUT.** `POST /v1/posts/` takes an `accounts` array and answers per account, so a single
call can half-succeed: published to Instagram, failed on LinkedIn. `publish()` therefore returns a
`PublishResult` carrying one `AccountResult` per destination, never a single id. The original contract had
room for one result, and that error would have surfaced as data loss in the retry path rather than as
anything a test would catch (§6.1, corrected 2026-11-06).

**Status is a state, not a verdict.** A publish is `pending` until the vendor has actually posted. No
caller may branch on "did it work?" inline; the 15-minute sweep reconciles (§7a Decision 1).

Nothing here reaches the network at import, and every call takes its transport, so the tests state exactly
what the vendor said and assert what we made of it.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

API_BASE = "https://api.outstand.so"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

#: Per-destination states the vendor reports. `pending` is the one that matters: it is the state a fresh
#: publish is in, and the reason the sweep exists.
PENDING, PUBLISHED, FAILED, DELETED = "pending", "published", "failed", "deleted"
TERMINAL_STATES = frozenset({PUBLISHED, FAILED, DELETED})

#: Scheduling is the vendor's, capped at 30 days (§6.2g #4). Past that the sweep still owns the post, so
#: this is a ceiling on what we hand over, not on what a tenant may schedule.
MAX_SCHEDULE_DAYS = 30


class OutstandError(Exception):
    """The call could not be completed. NOT "the post failed" — that is a per-destination `status`."""

    def __init__(self, message: str, *, status_code: int = 0, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    @property
    def is_auth_failure(self) -> bool:
        """401/403 — the key, not the post. Worth distinguishing: a tenant can do nothing about it and it
        must not be retried into a rate limit."""
        return self.status_code in (401, 403)

    @property
    def is_retryable(self) -> bool:
        """A transport fault or the vendor's own 5xx. 4xx is ours to fix and retrying it only burns quota.
        429 is retryable but wants backoff, which the sweep already applies."""
        return self.status_code == 0 or self.status_code == 429 or 500 <= self.status_code < 600


def api_key(*, refresh: bool = False) -> str | None:
    """The platform's Outstand key, from Secrets Manager by ARN then a plain variable.

    Same shape as `cloudflare_secrets._token_from` and for the same reason: the value is read by name at
    runtime and never travels through a template, a commit or a log line.
    """
    from stripe_link.cloudflare_secrets import _token_from

    return _token_from("OUTSTAND_API_KEY_SECRET_ARN", "OUTSTAND_API_KEY", "outstand", refresh)


def _request(method: str, path: str, *, body: Any = None, token: str = "", transport=None) -> dict:
    """One JSON call. `transport(method, url, headers, body) -> (status, text)` in tests."""
    url = f"{API_BASE}{path}"
    key = token or api_key() or ""
    if not key:
        # Said as a configuration fault, because that is what it is. An empty Authorization header would
        # come back as a 401 and read as the vendor rejecting us.
        raise OutstandError("No Outstand API key is configured (OUTSTAND_API_KEY_SECRET_ARN).")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    status, text = (transport or _send)(method, url, headers, payload)
    if status >= 400:
        raise OutstandError(f"Outstand returned HTTP {status}", status_code=status, body=text[:2000])
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise OutstandError("Outstand returned something that was not JSON", status_code=status,
                            body=text[:2000]) from exc
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _send(method: str, url: str, headers: dict, payload: bytes | None):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 4xx carries the vendor's own explanation, which is the sentence someone needs in order to fix
        # it. Dropping the body here is how an actionable error becomes "HTTP 400".
        return exc.code, exc.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - transport faults are status 0 and retryable
        raise OutstandError(str(exc) or type(exc).__name__) from exc


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def account_result(entry: Any) -> dict[str, Any]:
    """One destination's outcome, in OUR words.

    `status` defaults to `pending` rather than to failure: the vendor omits it until the post has been
    processed, and reading "absent" as "failed" would retry a post that is merely on its way
    (`feedback_absence_reads_as_safety`, the same shape).
    """
    entry = entry if isinstance(entry, dict) else {}
    status = _text(entry.get("status")).lower() or PENDING
    return {
        "account_id": _text(entry.get("id")),
        "network": _text(entry.get("network")).lower(),
        "username": _text(entry.get("username")),
        "status": status if status in (PENDING, PUBLISHED, FAILED, DELETED) else PENDING,
        "external_post_id": _text(entry.get("platformPostId")),
        "error": _text(entry.get("error")),
        "published_at": _text(entry.get("publishedAt")),
    }


def publish_result(payload: Any) -> dict[str, Any]:
    """The vendor's create/read response as a `PublishResult` (§6.1)."""
    body = payload if isinstance(payload, dict) else {}
    post = body.get("post") if isinstance(body.get("post"), dict) else body
    accounts = post.get("socialAccounts")
    return {
        "post_id": _text(post.get("id")),
        "scheduled_at": _text(post.get("scheduledAt")),
        "published_at": _text(post.get("publishedAt")),
        "is_draft": bool(post.get("isDraft")),
        "results": [account_result(a) for a in (accounts if isinstance(accounts, list) else [])],
    }


def is_settled(result: Any) -> bool:
    """True when every destination has reached a terminal state — what the sweep asks before it stops
    looking. A post with no destinations is NOT settled: that is a malformed response, not a finished job.
    """
    results = (result or {}).get("results") if isinstance(result, dict) else None
    return bool(results) and all(r.get("status") in TERMINAL_STATES for r in results)


def list_accounts(*, token: str = "", transport=None) -> list[dict[str, Any]]:
    """Every connected account, as `{account_id, network, username, nickname}`.

    **The id is the key, never the username.** The vendor accepts either in `accounts`, which makes a
    handle look usable — but a social handle can be renamed at any time, and the stored string would then
    resolve to nothing and read as a vendor fault rather than a rename (§11a).
    """
    body = _request("GET", "/v1/social-accounts", token=token, transport=transport)
    raw = body.get("socialAccounts") or body.get("data") or body.get("accounts") or []
    return [{
        "account_id": _text(a.get("id")),
        "network": _text(a.get("network")).lower(),
        "username": _text(a.get("username")),
        "nickname": _text(a.get("nickname")),
    } for a in (raw if isinstance(raw, list) else []) if isinstance(a, dict) and _text(a.get("id"))]


def publish(post: Any, *, token: str = "", transport=None) -> dict[str, Any]:
    """Publish or schedule OUR post document. Returns a `PublishResult`.

    `post` is our schema: `{accounts: [id], content: str, media: [url], scheduled_at: iso|None}`. The
    mapping to `containers` happens here and nowhere else.
    """
    post = post if isinstance(post, dict) else {}
    accounts = [a for a in (post.get("accounts") or []) if _text(a)]
    if not accounts:
        raise OutstandError("A post needs at least one destination account.")
    container: dict[str, Any] = {"content": _text(post.get("content"))}
    media = [_text(m) for m in (post.get("media") or []) if _text(m)]
    if media:
        container["media"] = media
    body: dict[str, Any] = {"accounts": accounts, "containers": [container]}
    scheduled_at = _text(post.get("scheduled_at"))
    if scheduled_at:
        # Handed over only inside the vendor's 30-day ceiling. Beyond it the sweep keeps the post and
        # submits it later -- sending a date the vendor refuses would turn a scheduled post into an error
        # the tenant cannot act on (§6.2g #4).
        body["scheduledAt"] = scheduled_at
    return publish_result(_request("POST", "/v1/posts/", body=body, token=token, transport=transport))


def fetch_post(post_id: str, *, token: str = "", transport=None) -> dict[str, Any]:
    """Re-read one post — what the sweep reconciles `pending` destinations against."""
    if not _text(post_id):
        raise OutstandError("A post id is required.")
    return publish_result(
        _request("GET", f"/v1/posts/{quote(_text(post_id), safe='')}", token=token, transport=transport))


def upload_media(filename: str, content_type: str, data: bytes, *, token: str = "", transport=None,
                 put=None) -> dict[str, Any]:
    """The vendor's three-step presigned upload, as one call: presign -> PUT the bytes -> confirm.

    Returns `{media_id, url}`. **Confirmed uploads are retained 60 days** — the only limit the vendor
    documents, and not a size or codec ceiling, which §11a #7 still has to discover by pushing real files.
    """
    presign = _request("POST", "/v1/media/upload",
                       body={"filename": _text(filename), "content_type": _text(content_type)},
                       token=token, transport=transport)
    media_id, upload_url = _text(presign.get("id")), _text(presign.get("upload_url"))
    if not media_id or not upload_url:
        raise OutstandError("Outstand did not return an upload URL.", body=json.dumps(presign)[:2000])
    (put or _put_bytes)(upload_url, content_type, data)
    confirmed = _request("POST", f"/v1/media/{media_id}/confirm", body={"size": len(data)}, token=token,
                         transport=transport)
    return {"media_id": media_id, "url": _text(confirmed.get("url")) or _text(presign.get("url"))}


def _put_bytes(url: str, content_type: str, data: bytes) -> None:
    """The raw bytes to the presigned URL. **No Authorization header** — the signature IS the credential,
    and sending our bearer token to a storage origin would leak it outside the API."""
    import urllib.request

    request = urllib.request.Request(url, data=data, method="PUT",
                                     headers={"Content-Type": content_type or "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise OutstandError(f"Media upload returned HTTP {response.status}",
                                    status_code=response.status)
    except OutstandError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OutstandError(str(exc) or type(exc).__name__) from exc


def configured() -> bool:
    """Whether publishing is switched on at all. Empty key disables the feature cleanly, the same way an
    empty `AiImageApiBase` disables image generation."""
    return bool(os.environ.get("OUTSTAND_API_KEY_SECRET_ARN") or os.environ.get("OUTSTAND_API_KEY"))
