"""Lead-capture domain logic (pure — no I/O).

A lead is a visitor submitting the inline form CTA on a published landing page. This module holds the
pure pieces the handler composes: normalization, field validation against the product's declared
`lead_capture.fields[]`, spam/abuse checks, and document/notification shaping. See plans/LEAD_CAPTURE.md.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

SCHEMA_VERSION = "2026-05-29"

# The hidden honeypot field the form renders; real users never fill it, bots do.
HONEYPOT_FIELD = "company_website"

LEAD_STATUSES = {"new", "contacted", "qualified", "archived"}

# Guardrails on the public ingest payload.
MAX_FIELDS = 25
MAX_FIELD_NAME_LEN = 64
MAX_FIELD_VALUE_LEN = 2000


class LeadValidationError(ValueError):
    """Raised when a submission fails field validation (maps to HTTP 400)."""


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: Any) -> str:
    """Keep a leading + and digits only, so the same number normalizes consistently for lookup/erase."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    plus = "+" if raw.lstrip().startswith("+") else ""
    return plus + re.sub(r"\D", "", raw)


def is_spam(payload: dict[str, Any]) -> bool:
    """Honeypot gate: a real submit leaves HONEYPOT_FIELD empty. Cheap first line of defense."""
    return bool(str((payload or {}).get(HONEYPOT_FIELD) or "").strip())


def validate_and_extract_fields(submitted: dict[str, Any], declared_fields: list[dict[str, Any]]) -> dict[str, str]:
    """Validate the submitted `fields` against the product's declared lead_capture.fields[].

    Enforces: declared-only (unknown keys dropped), required-present, light type checks, size caps.
    Returns the cleaned field map. Raises LeadValidationError on the first hard failure.
    """
    if not isinstance(submitted, dict):
        raise LeadValidationError("Lead fields must be an object.")
    if len(submitted) > MAX_FIELDS:
        raise LeadValidationError("Too many fields submitted.")

    # Default schema when a product declares an action but no explicit fields: a single required email.
    declared = declared_fields or [{"name": "email", "type": "email", "required": True}]
    declared_by_name = {str(field.get("name") or "").strip(): field for field in declared if field.get("name")}

    cleaned: dict[str, str] = {}
    for name, field in declared_by_name.items():
        if len(name) > MAX_FIELD_NAME_LEN:
            continue
        raw = submitted.get(name)
        value = str(raw if raw is not None else "").strip()
        if len(value) > MAX_FIELD_VALUE_LEN:
            raise LeadValidationError(f"Field '{name}' is too long.")
        field_type = str(field.get("type") or "text").strip().lower()
        required = bool(field.get("required"))
        if not value:
            if required:
                raise LeadValidationError(f"Field '{name}' is required.")
            continue
        if field_type == "email" and "@" not in value:
            raise LeadValidationError(f"Field '{name}' must be a valid email address.")
        if field_type in {"phone", "tel"} and not re.search(r"\d", value):
            raise LeadValidationError(f"Field '{name}' must be a valid phone number.")
        cleaned[name] = value

    if not cleaned:
        raise LeadValidationError("At least one field is required.")
    return cleaned


def lead_id_for(tenant_id: str, offer_id: str, idempotency_key: str, *, now: int, token: str) -> str:
    """Deterministic id when the client sends an idempotency key (so retries resolve to the same lead);
    otherwise a fresh time-prefixed id. Sorting for listing is done on created_at, not the id."""
    key = str(idempotency_key or "").strip()
    if key:
        digest = hashlib.sha1(f"{tenant_id}|{offer_id}|{key}".encode("utf-8")).hexdigest()[:24]
        return f"lead_{digest}"
    return f"lead_{int(now)}_{token}"


def consent_record(entry: Any, *, ip: str, now: int, offer_id: str) -> dict[str, Any]:
    """Normalize one opt-in into a stored proof record. `entry` is the client's {granted, text} for a list."""
    entry = entry if isinstance(entry, dict) else {}
    return {
        "granted": bool(entry.get("granted")),
        "text": str(entry.get("text") or "").strip()[:MAX_FIELD_VALUE_LEN],
        "timestamp": int(now),
        "ip": str(ip or "")[:64],
        "method": "web_form",
        "source_offer_id": str(offer_id or ""),
    }


def build_consent(payload_consent: Any, *, ip: str, now: int, offer_id: str) -> dict[str, Any]:
    """Two independent, granular opt-ins (tenant list + Junior Bay platform list). Never bundled.
    The Junior Bay list additionally requires double-opt-in confirmation before it is honored."""
    payload_consent = payload_consent if isinstance(payload_consent, dict) else {}
    platform = consent_record(payload_consent.get("platform_marketing"), ip=ip, now=now, offer_id=offer_id)
    platform["double_opt_in_confirmed"] = False
    return {
        "tenant_marketing": consent_record(payload_consent.get("tenant_marketing"), ip=ip, now=now, offer_id=offer_id),
        "platform_marketing": platform,
    }


def build_lead_submission(
    *,
    tenant_id: str,
    lead_id: str,
    offer_id: str,
    page_id: str,
    fields: dict[str, str],
    consent: dict[str, Any],
    provenance: dict[str, Any],
    idempotency_key: str,
    now: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "lead_submission",
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "offer_id": str(offer_id or ""),
        "page_id": str(page_id or ""),
        "fields": fields,
        "email_normalized": normalize_email(fields.get("email")),
        "phone_normalized": normalize_phone(fields.get("phone")),
        "consent": consent,
        "status": "new",
        "provenance": provenance,
        "idempotency_key": str(idempotency_key or ""),
        "created_at": int(now),
        "updated_at": int(now),
    }


def lead_display_name(lead: dict[str, Any]) -> str:
    fields = lead.get("fields") or {}
    return str(fields.get("name") or fields.get("email") or fields.get("phone") or "A visitor").strip()


def lead_notification(lead: dict[str, Any], tenant_id: str, now: int) -> dict[str, Any]:
    """Bell notification emitted on capture. Same shape as other emitters (booking/invoice)."""
    who = lead_display_name(lead)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "notification",
        "tenant_id": tenant_id,
        "notification_id": f"notif_lead_{lead.get('lead_id', '')}",
        "type": "lead",
        "severity": "info",
        "title": "New lead",
        "message": f"{who} submitted the form on your landing page.",
        "status": "unread",
        "sort_priority": 90,
        "related": {"lead_id": lead.get("lead_id", ""), "offer_id": lead.get("offer_id", "")},
        "action": {"label": "View leads", "route": "leads"},
        "created_at": int(now),
        "read_at": None,
        "archived_at": None,
    }


def lead_capture_fields(offer: dict[str, Any], products_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve the declared form fields from the offer's primary lead-gen product."""
    for item in (offer or {}).get("items") or []:
        product = products_by_id.get(str((item or {}).get("product_id") or ""))
        capture = (product or {}).get("lead_capture")
        if isinstance(capture, dict):
            fields = capture.get("fields")
            return fields if isinstance(fields, list) else []
    return []
