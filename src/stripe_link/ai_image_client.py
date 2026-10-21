"""Talking to `../sam/ai-image-generator`. The capability lives there; the policy stayed here.

A SERVER-TO-SERVER call with a shared secret, never a browser one. The key cannot travel to a browser,
which is also why the dashboard polls through this handler rather than the image service directly --
that, and the library being keyed on `tenant_id`, which is not guaranteed to equal the signed-in `sub`.

The service deliberately knows nothing about plans. Everything it is told here -- how many images, at
what quality, under whose id -- was decided by the gates in `ai_generate.py` before this module is
reached. It is the arm, not the judgement.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

DEFAULT_TIMEOUT = 15
_KEY_CACHE: dict[str, str] = {}


class ImageServiceError(RuntimeError):
    """The image service refused or could not be reached. `code` carries ITS code where there is one,
    and `blame` says whose problem it is, so a caller can word a message without guessing."""

    def __init__(self, message: str, *, status_code: int = 502, code: str = "image_service_failed",
                 blame: str = "transient"):
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = code
        self.blame = blame


def api_base() -> str:
    return os.environ.get("AI_IMAGE_API_BASE", "").rstrip("/")


def service_key() -> str:
    """The shared secret, env first and Secrets Manager second.

    The env var is resolved at deploy from the image stack's own generated secret, so the normal path
    costs no runtime call. The ARN fallback exists so the key can be rotated without redeploying this
    stack -- cached per container, like every other secret here, so a rotation is picked up as
    containers recycle.
    """
    direct = os.environ.get("AI_IMAGE_SERVICE_KEY", "").strip()
    if direct:
        return direct
    arn = os.environ.get("AI_IMAGE_SERVICE_KEY_SECRET_ARN", "").strip()
    if not arn:
        return ""
    if arn in _KEY_CACHE:
        return _KEY_CACHE[arn]
    try:
        import boto3

        value = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
        secret = str(value.get("SecretString") or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable key is "not configured", not a crash
        return ""
    _KEY_CACHE[arn] = secret
    return secret


def configured() -> bool:
    """Both halves present. Checked BEFORE a tenant's allowance is spent: refusing a misconfigured
    service after taking a credit would charge somebody for our mistake."""
    return bool(api_base() and service_key())


def call(path: str, *, method: str = "GET", body: dict[str, Any] | None = None, opener=None,
         timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    if not configured():
        raise ImageServiceError("Image generation is not configured.", status_code=503,
                                code="image_service_unconfigured", blame="service")
    opener = opener or request.urlopen
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"x-service-key": service_key()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{api_base()}{path}", data=data, headers=headers, method=method)
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        # READ THE BODY. The service classifies its own failures -- a refused prompt, a dead key, a
        # blip -- and the status line alone would throw that away and report all three as an outage.
        raw = ""
        try:
            raw = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            pass
        parsed = _parse(raw) if raw else {}
        raise ImageServiceError(str(parsed.get("message") or exc.reason or "Image generation failed."),
                                status_code=int(exc.code or 502),
                                code=str(parsed.get("error") or "image_service_failed"),
                                blame=str(parsed.get("blame") or _blame_for_status(int(exc.code or 502)))
                                ) from exc
    except error.URLError as exc:
        raise ImageServiceError(f"Could not reach image generation: {exc.reason}", status_code=502,
                                code="image_service_unreachable", blame="transient") from exc
    return _parse(raw)


def _blame_for_status(status: int) -> str:
    if status in (400, 422):
        return "tenant"
    if status in (401, 403, 503):
        return "service"
    return "transient"


def _parse(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ImageServiceError("Image generation returned invalid JSON.", status_code=502) from exc
    if not isinstance(parsed, dict):
        raise ImageServiceError("Image generation returned an invalid response.", status_code=502)
    return parsed


def start(*, owner_id: str, prompt: str, count: int, size: str, quality: str, tier: str = "",
          opener=None) -> dict[str, Any]:
    """Queue a generation. Returns the service's job, which is what the caller polls."""
    payload = {"owner_id": owner_id, "prompt": prompt, "count": int(count), "size": size,
               "quality": quality, "tier": tier}
    return call("/generate", method="POST", body=payload, opener=opener).get("job") or {}


def read(*, owner_id: str, job_id: str, opener=None) -> dict[str, Any]:
    """One job, scoped by owner. The service keys on both, so a job id alone cannot reach another
    tenant's row even if this handler got the owner wrong."""
    from urllib.parse import urlencode

    query = urlencode({"owner_id": owner_id, "job_id": job_id})
    return call(f"/jobs?{query}", method="GET", opener=opener).get("job") or {}
