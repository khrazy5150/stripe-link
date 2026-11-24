"""Tenant video metadata and the ordered, cursor-based gallery projection."""

import re
import time
from concurrent.futures import ThreadPoolExecutor

VIDEO_JOB = "ai_video_job"
PREFIX = "video#"
MIGRATION = "video-gallery-migration"
PAGE_SIZE = 15
QUOTE_LIFETIME = 600
UNAVAILABLE_STATES = {"failed", "rejected", "nsfw", "canceled", "archive_failed"}
CURSOR_PATTERN = re.compile(r"video#[0-9]{16}#[0-9a-f-]{36}")


def _text(value, limit):
    return " ".join(value.split())[:limit].strip() if isinstance(value, str) else ""


def video_metadata(job, body=None):
    body = body or {}
    inputs = job.get("input") or {}
    prompt = _text(inputs.get("prompt") or body.get("prompt"), 2000)
    model = _text(job.get("model") or body.get("model"), 140)
    title = _text(body.get("title"), 90) or _text(prompt, 90) or "Generated video"
    supplied_tags = body.get("tags")
    if supplied_tags is not None and not isinstance(supplied_tags, list):
        raise ValueError("Video tags must be a list.")
    tags = []
    seen = set()
    for value in (*(supplied_tags or [])[:12], inputs.get("resolution"), inputs.get("aspect_ratio")):
        tag = _text(value, 40)
        if tag and tag.casefold() not in seen:
            tags.append(tag)
            seen.add(tag.casefold())
    expires = job.get("quote_expires_at")
    created = max(0, int((expires - QUOTE_LIFETIME) * 1000)) if isinstance(expires, (int, float)) else int(time.time() * 1000)
    return {"video_created_at": created, "title": title, "tags": tags, "model": model, "prompt": prompt}


def _project(tenant, job_id, metadata, availability):
    created = int(metadata["video_created_at"])
    return {
        **metadata,
        "tenant_id": tenant,
        "job_id": f"{PREFIX}{created:016d}#{job_id}",
        "video_id": job_id,
        "availability": availability,
    }


def register_for_gallery(jobs, tenant, job_id, metadata):
    jobs.put_if_current(_project(tenant, job_id, metadata, "pending"), field="availability", expected=None)


def _parallel_reads(read, identifiers):
    if not identifiers:
        return []
    with ThreadPoolExecutor(max_workers=PAGE_SIZE) as workers:
        return list(workers.map(read, identifiers))


def _availability(job):
    if not job or job.get("state") in UNAVAILABLE_STATES:
        return "unavailable"
    if job.get("state") == "completed" and job.get("video_available"):
        return "ready"
    return "pending"


def _index_legacy(jobs, tenant, marker, read):
    previous = marker.get("cursor") if marker else None
    rows, cursor = jobs.page_for_tenant(
        tenant, limit=PAGE_SIZE, cursor=previous or "", legacy_type=VIDEO_JOB,
    )
    remote_jobs = _parallel_reads(read, [row["job_id"] for row in rows])
    for row, job in zip(rows, remote_jobs):
        if job is None:
            continue
        availability = _availability(job)
        if availability == "unavailable":
            continue
        if job.get("state") == "quoted" and (job.get("quote_expires_at") or 0) <= time.time():
            continue
        projection = _project(tenant, row["job_id"], video_metadata(job), availability)
        jobs.put_if_current(projection, field="availability", expected="pending")
    jobs.put_if_current({"tenant_id": tenant, "job_id": MIGRATION, "cursor": cursor or "done"},
                        field="cursor", expected=previous)


def _matches(row, terms):
    search_text = " ".join([row["title"], row.get("prompt", ""), row.get("model", ""), *row["tags"]]).casefold()
    return all(term in search_text for term in terms)


def gallery_page(jobs, tenant, cursor, search, read):
    if cursor not in {"", "start"} and not CURSOR_PATTERN.fullmatch(cursor):
        raise ValueError("The gallery page cursor is invalid.")

    marker = jobs.get(tenant, MIGRATION, consistent=True)
    if not marker or marker.get("cursor") != "done":
        _index_legacy(jobs, tenant, marker, read)
        # Complete the index before showing any cards so older jobs sort together with new ones.
        return {"videos": [], "next_cursor": "start", "indexing": True}

    terms = _text(search, 160).casefold().split()
    rows, next_cursor = jobs.page_for_tenant(
        tenant, limit=PAGE_SIZE, cursor="" if cursor == "start" else cursor, prefix=PREFIX,
    )
    matching = [row for row in rows if row["availability"] != "unavailable" and _matches(row, terms)]
    pending = [row for row in matching if row["availability"] == "pending"]
    remote_jobs = _parallel_reads(read, [row["video_id"] for row in pending])
    for row, job in zip(pending, remote_jobs):
        availability = _availability(job)
        if job and job.get("state") == "quoted" and (job.get("quote_expires_at") or 0) <= time.time():
            availability = "unavailable"
        if availability != "pending":
            row["availability"] = availability
            jobs.put_if_current(row, field="availability", expected="pending")

    return {"videos": [
        {"id": row["video_id"], "title": row["title"], "tags": row["tags"],
         "created_at": int(row["video_created_at"]), "model": row["model"]}
        for row in matching if row["availability"] == "ready"
    ], "next_cursor": next_cursor}
