"""Tenant-scoped access to the internal Junior Bay Media Engine."""

import base64
import hashlib
import json
import logging
import os
from urllib.parse import urlsplit
from uuid import UUID

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import BotoCoreError, ClientError
from botocore.httpsession import URLLib3Session

from stripe_link.api_auth import resolved_tenant
from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params
from stripe_link.domain.video_gallery import VIDEO_JOB as JOB_TYPE, gallery_page, register_for_gallery, video_metadata
from stripe_link.repositories.documents import RepositoryError, jobs_repository

logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
QUOTE_FIELDS = ("model", "prompt", "duration", "resolution", "aspect_ratio", "bitrate_mode", "image_url")
JOB_FIELDS = ("id", "state", "quoted_usd", "quote_expires_at", "retry_after_seconds", "video_available", "error")


class VideoServiceError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _call(base, method, path, *, data=None, headers=None):
    headers = dict(headers or {})
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if data is not None:
        headers["x-amz-content-sha256"] = hashlib.sha256(data).hexdigest()

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise VideoServiceError("Video generation is unavailable.")
    signed = AWSRequest(method=method, url=base + path, data=data, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", os.environ["AWS_REGION"]).add_auth(signed)
    response = URLLib3Session(timeout=25).send(signed.prepare())
    try:
        payload = json.loads(response.content)
    except ValueError:
        raise VideoServiceError("The video service returned an invalid response.") from None
    if not isinstance(payload, dict):
        raise VideoServiceError("The video service returned an invalid response.")
    if 200 <= response.status_code < 300:
        return payload, response.status_code

    detail = payload.get("detail")
    if isinstance(detail, list):
        detail = " ".join(str(item.get("msg", "")) for item in detail if isinstance(item, dict))
    if response.status_code in {400, 402, 403, 404, 409, 413, 415, 422, 429, 502, 503} and detail:
        raise VideoServiceError(str(detail), response.status_code)
    raise VideoServiceError("The video service is unavailable. Try again.")


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("A valid request or job ID is required.")
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("A valid request or job ID is required.") from None


def _reference_image(body):
    media_type = body.get("content_type")
    encoded = body.get("image_base64")
    if not isinstance(media_type, str) or media_type not in IMAGE_TYPES:
        raise VideoServiceError("Choose a JPEG, PNG, or WebP image.", 415)
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Choose a reference image.")
    if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise VideoServiceError("Choose an image up to 4 MiB.", 413)
    try:
        image = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError("The reference image could not be read.") from None
    if len(image) > MAX_IMAGE_BYTES:
        raise VideoServiceError("Choose an image up to 4 MiB.", 413)
    return media_type, image


def _job_response(job, status):
    return json_response({field: job.get(field) for field in JOB_FIELDS}, status)


def handler(event, context, *, repo=None, caller=None):
    method = event.get("httpMethod", "")
    if method == "OPTIONS":
        return json_response({})
    tenant, verified = resolved_tenant(event)
    if not verified:
        return error_response("Sign in to use video generation.", 401, code="unauthenticated")

    endpoint = str(path_params(event).get("proxy") or "").strip("/")
    parts = endpoint.split("/")
    base = os.environ.get("MEDIA_ENGINE_API_URL", "").rstrip("/")
    if not base:
        return error_response("Video generation is unavailable in this environment.", 503, code="video_unavailable")
    call = caller or _call

    try:
        if method == "GET" and endpoint == "gallery":
            query = query_params(event)
            jobs = repo or jobs_repository()

            def read_job(job_id):
                try:
                    job, _ = call(base, "GET", f"/jobs/{_uuid(job_id)}")
                    return job
                except VideoServiceError as exc:
                    if exc.status == 404:
                        return None
                    raise

            return json_response(gallery_page(jobs, tenant, query.get("cursor") or "", query.get("q"), read_job))
        if method == "GET" and endpoint == "models":
            models, status = call(base, "GET", "/console-models")
            return json_response(models, status)
        if method == "POST" and endpoint == "reference-image":
            media_type, image = _reference_image(parse_json_body(event))
            uploaded, status = call(base, "POST", "/jobs/reference-image", data=image,
                                    headers={"Content-Type": media_type})
            return json_response({"image_url": uploaded["image_url"]}, status)
        if method == "POST" and endpoint == "quote":
            body = parse_json_body(event)
            if body.get("tags") is not None and not isinstance(body["tags"], list):
                raise ValueError("Video tags must be a list.")
            request_id = _uuid(body.get("request_id"))
            key = hashlib.sha256(f"{tenant}:{request_id}".encode()).hexdigest()
            inputs = {field: body[field] for field in QUOTE_FIELDS if field in body}
            jobs = repo or jobs_repository()
            job, status = call(base, "POST", "/jobs/quote", data=inputs, headers={"Idempotency-Key": key})
            try:
                job_id = _uuid(job.get("id"))
            except ValueError:
                raise VideoServiceError("The video service returned an invalid job ID.") from None
            metadata = video_metadata(job, body)
            jobs.put({"tenant_id": tenant, "job_id": job_id, "document_type": JOB_TYPE,
                      "video_created_at": metadata["video_created_at"]})
            register_for_gallery(jobs, tenant, job_id, metadata)
            return _job_response(job, status)
        if parts[0] == "jobs" and len(parts) in {2, 3}:
            action = parts[2] if len(parts) == 3 else ""
            if (method, action) not in {("GET", ""), ("POST", "approve"), ("GET", "video-link")}:
                return error_response("Video operation not found.", 404)
            job_id = _uuid(parts[1])
            jobs = repo or jobs_repository()
            record = jobs.get(tenant, job_id, consistent=True)
            if not record or record.get("document_type") != JOB_TYPE:
                return error_response("Video job not found.", 404, code="video_job_not_found")
            path = f"/jobs/{job_id}"
            if action == "approve":
                body = parse_json_body(event)
                if "video_created_at" not in record:
                    legacy_job, _ = call(base, "GET", path)
                    register_for_gallery(jobs, tenant, job_id, video_metadata(legacy_job))
                job, status = call(base, "POST", path + "/approve", data={"approved_usd": body.get("approved_usd")})
            elif action == "video-link":
                suffix = "?download=true" if query_params(event).get("download") == "true" else ""
                link, status = call(base, "GET", path + "/video-link" + suffix)
                url = link.get("url")
                parsed = urlsplit(url) if isinstance(url, str) else None
                if not parsed or parsed.scheme != "https" or not parsed.hostname:
                    raise VideoServiceError("The video service returned an invalid playback link.")
                return json_response({"url": url}, status)
            else:
                job, status = call(base, "GET", path)
            return _job_response(job, status)
    except VideoServiceError as exc:
        return error_response(str(exc), exc.status, code="video_service_error")
    except ValueError as exc:
        return error_response(str(exc))
    except (BotoCoreError, ClientError, RepositoryError, KeyError) as exc:
        logger.warning("Video operation failed (%s): %s", method, type(exc).__name__)
        return error_response("The video service is unavailable. Try again.", 502, code="video_service_error")
    return error_response("Video operation not found.", 404)
