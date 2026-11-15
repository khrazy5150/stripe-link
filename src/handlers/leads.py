"""Lead capture API.

- POST /leads is PUBLIC (anonymous visitor on a published landing page). Tenant/offer are resolved
  server-side from the payload IDs, never from a client-supplied key. Protected by a honeypot + payload
  caps (rate limiting is a documented follow-up, plans/LEAD_CAPTURE.md §8).
- GET/PATCH paths are tenant-scoped like every other authenticated dashboard handler.

See plans/LEAD_CAPTURE.md.
"""
import logging
import secrets
import time
from typing import Callable

from stripe_link.common import (
    error_response,
    header_value,
    json_response,
    parse_json_body,
    path_params,
    query_params,
    resolve_stripe_mode,
    tenant_id_from_event,
)
from stripe_link.domain.documents import DocumentValidationError, validate_lead_submission
from stripe_link.domain.events import (CANCELLED, FULL, PASSED, accepts_registration,
                                        record_registration, release_registration)
from stripe_link.domain.opportunities import STAGE_LANDING, stage_opportunities
from stripe_link.entitlement_gate import require_capability
from stripe_link.domain.page_views import identifier_slug
from stripe_link.domain.leads import (
    attendance_token,
    record_attendance,
    LeadValidationError,
    build_consent,
    build_lead_submission,
    is_spam,
    lead_capture_fields,
    lead_id_for,
    lead_notification,
    validate_and_extract_fields,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    events_repository,
    leads_repository,
    notifications_repository,
    offers_repository,
    products_repository,
)


logger = logging.getLogger(__name__)


# What a visitor is told, per refusal state. The domain returns a STATE; the sentence belongs here.
_REGISTRATION_REFUSALS = {
    PASSED: "That session has already started.",
    FULL: "That session is full.",
    CANCELLED: "That session was cancelled.",
    "unknown": "That session is no longer available.",
}


def handler(
    event,
    context,
    *,
    leads_repo=None,
    offers_repo=None,
    products_repo=None,
    notifications_repo=None,
    events_repo=None,
    now_fn: Callable[[], int] = lambda: int(time.time()),
    tenant_repo=None,
):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    # Leads are mode-agnostic CRM records; the offer/product context they capture is read in the request's mode.
    mode = resolve_stripe_mode(event)
    leads_repo = leads_repo or leads_repository()
    if method == "POST":
        # ONE PUBLIC ENDPOINT, TWO SHAPES. A webinar attendance beacon is a POST from a published page by
        # somebody who is not signed in -- the same trust properties the ingest below already has, and the
        # same table. A route of its own would be a second copy of those decisions plus CloudFormation
        # transform budget, which this stack has spent real time recovering before (plans/WEBINAR.md §13).
        #
        # Routed on the payload rather than the path for that reason. It differs from ingest in the way
        # that matters: ingest is anonymous and this names a registrant, which is what the token is for.
        if _is_attendance_beacon(event):
            return registrant_action(
                event, leads_repo=leads_repo,
                events_repo=events_repo or events_repository(), now=now_fn())
        return ingest_lead(
            event,
            leads_repo=leads_repo,
            offers_repo=offers_repo or offers_repository(mode=mode),
            products_repo=products_repo or products_repository(mode=mode),
            notifications_repo=notifications_repo,
            events_repo=events_repo,
            now=now_fn(),
            mode=mode,
        )
    # Tenant-side lead access requires the `lead_capture` plan capability. The public POST ingest above stays open
    # (buyers never see a plan gate); an unentitled tenant simply can't view/manage leads.
    if method in {"GET", "PATCH"}:
        gate = require_capability(event, "lead_capture", tenant_repo)
        if gate is not None:
            return gate
    if method == "GET":
        lead_id = path_params(event).get("lead_id")
        if lead_id:
            return get_lead(event, leads_repo, lead_id)
        return list_leads(event, leads_repo)
    if method == "PATCH":
        lead_id = path_params(event).get("lead_id")
        if not lead_id:
            return error_response("lead_id is required.", code="missing_lead")
        return update_lead_status(event, leads_repo, lead_id, now_fn())
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _is_attendance_beacon(event) -> bool:
    """True when this POST is a watch beacon rather than a registration. Parsed defensively: a malformed
    body is not an attendance beacon, and `ingest_lead` below will produce the proper error for it."""
    try:
        payload = parse_json_body(event)
    except ValueError:
        return False
    return isinstance(payload, dict) and bool(payload.get("attend_token"))


def registrant_action(event, *, leads_repo, events_repo=None, now):
    """What an IDENTIFIED registrant may do without an account: send a watch beacon, or give the seat back
    (plans/AUTO_WEBINAR.md P4, plans/WEBINAR.md §12).

    Both prove the same `attend_token` on the same public POST, so the verification lives in one place
    rather than being written twice and drifting. `action: "unregister"` is the only thing that is not a
    beacon; everything else is one.

    **Always 202, whatever happens.** An unknown registration, a wrong token and a successful write are
    indistinguishable to the caller, so this cannot be used to discover which registrations exist, to
    confirm a guessed token, or to probe whether a cancellation took. It is also the cheapest answer for
    something fired every thirty seconds.

    The token is compared with `secrets.compare_digest`. Timing on a string compare is a thin channel, but
    what it guards is a stranger's registration record and constant-time costs nothing.
    """
    accepted = json_response({"status": "accepted"}, status_code=202)
    try:
        payload = parse_json_body(event)
    except ValueError:
        return accepted
    tenant_id = identifier_slug(payload.get("tenant_id"))
    lead_id = identifier_slug(payload.get("lead_id"))
    token = str(payload.get("attend_token") or "")
    if not tenant_id or not lead_id or not token:
        return accepted
    try:
        position = max(0, int(payload.get("position") or 0))
    except (TypeError, ValueError):
        position = 0
    try:
        lead = leads_repo.get(tenant_id, lead_id)
        if not lead:
            return accepted
        expected = attendance_token(lead)
        if not expected or not secrets.compare_digest(expected, token):
            return accepted
        if str(payload.get("action") or "") == "unregister":
            return _unregister(lead, leads_repo=leads_repo, events_repo=events_repo, now=int(now))
        leads_repo.put(record_attendance(lead, position=position, now=int(now)))
    except Exception as exc:  # noqa: BLE001 - a viewer must never see a failure here
        print(f"registrant action not recorded for {lead_id}: {type(exc).__name__}: {exc}")
    return accepted


def _unregister(lead, *, leads_repo, events_repo, now):
    """Give the seat back. The registrant's row is MARKED, not deleted.

    Deleting would take the consent record and the provenance with it -- the evidence that this person
    asked to be contacted, and when. That is exactly what a complaint has to be answered with, so the one
    moment it is most tempting to erase a row is the moment it is least safe to. `archived` is a status
    the leads screen already understands, so the tenant side needs nothing new.

    Idempotent: a double tap or a retried beacon must not decrement the seat count twice and hand the
    session a seat it does not have.
    """
    accepted = json_response({"status": "accepted"}, status_code=202)
    if str(lead.get("status") or "") == "archived":
        return accepted
    leads_repo.put({**lead, "status": "archived", "unregistered_at": int(now), "updated_at": int(now)})
    # Best-effort and AFTER the lead is marked, mirroring registration. A seat count that failed to
    # decrement is a door closed slightly early; a lead still marked registered would keep sending
    # reminders for a session the person has left, which is the worse of the two.
    event_id = str(lead.get("event_id") or "")
    occurrence_id = str(lead.get("occurrence_id") or "")
    if events_repo and event_id and occurrence_id:
        try:
            scheduled = events_repo.get(str(lead.get("tenant_id") or ""), event_id)
            if scheduled:
                events_repo.put(release_registration(scheduled, occurrence_id))
        except Exception as exc:  # noqa: BLE001 - the cancellation stands either way
            logger.warning("seat not released for event %s: %s", event_id, exc)
    return accepted


def _request_context(event) -> dict:
    ctx = (event or {}).get("requestContext") or {}
    identity = ctx.get("identity") or {}
    return {
        "ip": str(identity.get("sourceIp") or "")[:64],
        "user_agent": str(header_value(event, "User-Agent") or "")[:512],
        "referer": str(header_value(event, "Referer") or header_value(event, "Referrer") or "")[:512],
    }


def ingest_lead(event, *, leads_repo, offers_repo, products_repo, notifications_repo, events_repo=None, now, mode="test"):
    try:
        payload = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_lead")

    # Honeypot: silently accept-and-drop so bots get no signal that they were caught.
    if is_spam(payload):
        return json_response({"status": "accepted"}, status_code=202)

    tenant_id = str(payload.get("tenant_id") or "").strip()
    offer_id = str(payload.get("offer_id") or "").strip()
    page_id = str(payload.get("page_id") or "").strip()
    if not tenant_id or not offer_id:
        return error_response("tenant_id and offer_id are required.", code="invalid_lead")

    offer = offers_repo.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="not_found")

    products_by_id = {}
    for item in stage_opportunities(offer, STAGE_LANDING):
        product_id = str((item or {}).get("product_id") or "").strip()
        if product_id and product_id not in products_by_id:
            product = products_repo.get(tenant_id, product_id)
            if product:
                products_by_id[product_id] = product

    declared = lead_capture_fields(offer, products_by_id)
    try:
        fields = validate_and_extract_fields(payload.get("fields") or {}, declared)
    except LeadValidationError as exc:
        return error_response(str(exc), code="invalid_lead")

    # A webinar registration names the session it is for. The SERVER decides whether that session can
    # still be registered for -- the page asks the same function at publish, but a page is a cached
    # artifact and the visitor's copy may be hours old, so the client is never the authority here.
    event_id = str(payload.get("event_id") or "").strip()
    occurrence_id = str(payload.get("occurrence_id") or "").strip()
    scheduled_event = None
    # "Tell me about the next one" names an EVENT and no sitting, because the whole point is that none of
    # them suits. It therefore skips the checks below -- every one of which asks a question about a
    # specific occurrence, and the honest answer to all of them here is "that is not what was asked".
    wants_next = bool(payload.get("wants_next")) and not occurrence_id
    if wants_next:
        event_id = str(payload.get("event_id") or "").strip()
    elif event_id or occurrence_id:
        if not (event_id and occurrence_id):
            return error_response("event_id and occurrence_id are required together.", code="invalid_registration")
        # Resolved HERE, not at the top: an ordinary lead capture never touches the events table, and
        # building the repository for every submission would make the common path depend on a table it
        # has no business knowing about.
        events_repo = events_repo or events_repository()
        scheduled_event = events_repo.get(tenant_id, event_id)
        if not scheduled_event:
            return error_response("Event not found.", status_code=404, code="not_found")
        accepted, reason = accepts_registration(scheduled_event, occurrence_id, now=int(now))
        if not accepted:
            # The REASON travels, so the page can say "that session has already run" rather than "no".
            return error_response(_REGISTRATION_REFUSALS.get(reason, "This session is not accepting registrations."),
                                  status_code=409, code=f"registration_{reason}")

    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    lead_id = lead_id_for(tenant_id, offer_id, idempotency_key, now=now, token=secrets.token_hex(8))

    # Request-level idempotency: a retried submit resolves to the same lead, returned without a rewrite.
    if idempotency_key:
        existing = leads_repo.get(tenant_id, lead_id)
        if existing:
            return json_response({"lead_id": lead_id, "status": "duplicate"}, status_code=200)

    context = _request_context(event)
    consent = build_consent(payload.get("consent"), ip=context["ip"], now=now, offer_id=offer_id)
    provenance = {**context, "submitted_at": int(now)}
    lead = build_lead_submission(
        tenant_id=tenant_id,
        lead_id=lead_id,
        offer_id=offer_id,
        page_id=page_id,
        fields=fields,
        consent=consent,
        provenance=provenance,
        idempotency_key=idempotency_key,
        now=now,
        event_id=event_id,
        occurrence_id=occurrence_id,
        wants_next=wants_next,
    )
    # WHICH BOOKS THIS CAME FROM. Leads are a CRM record rather than a transaction, so the repository is
    # not mode-scoped -- but a tenant testing their own form still gets a fake person in the list beside
    # their real ones, and `delete test data` cannot tell them apart. Unlike a refund request, a lead
    # carries no id that reveals the mode: page_id and offer_id are deliberately IDENTICAL across modes
    # (the cross-mode copy preserves ids), so there is nothing to derive it from later. It has to be
    # recorded at capture or it is lost.
    lead["stripe_mode"] = mode
    try:
        validate_lead_submission(lead)
        leads_repo.put(lead)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_lead")

    if scheduled_event is not None:
        _send_registration_confirmation(scheduled_event, occurrence_id, fields, tenant_id,
                                        page_id=str(lead.get("page_id") or ""), mode=mode,
                                        lead_id=lead_id, attend_token=attendance_token(lead),
                                        page_url=str(provenance.get("referer") or ""))
        # Best-effort, and AFTER the lead is safely stored: a failed count must not lose a registration.
        # Read-compare-write, so a burst can overbook by one (plans/WEBINAR.md §4) -- the registration is
        # the record that matters, and the count exists to close the door roughly, not exactly.
        try:
            events_repo.put(record_registration(scheduled_event, occurrence_id))
        except RepositoryError:
            logger.warning("registration stored but seat count not updated for event %s", event_id)

    _emit_lead_notification(notifications_repo, lead, tenant_id, now, mode)
    return json_response({"lead_id": lead_id, "status": "captured"}, status_code=201)


def _send_registration_confirmation(scheduled_event, occurrence_id, fields, tenant_id, *,
                                    page_id="", mode="live", lead_id="", attend_token="", page_url=""):
    """Confirm the seat, with the calendar file. Best-effort by design.

    A send that fails must never cost the registration: the lead is already stored, and a visitor who sees
    an error after giving their address will simply submit again, producing a second lead for a seat they
    already hold. So every failure here is logged and swallowed -- the person IS registered, which is the
    fact that matters, and the reminder sweep will reach them again before the session.
    """
    recipient = str((fields or {}).get("email") or "").strip()
    if not recipient:
        return
    try:
        from stripe_link.domain.events import occurrence_by_id
        from stripe_link.domain.ics import invite_for_occurrence
        from stripe_link.domain.registration_email import registration_confirmation
        from stripe_link.mailer import send_email
        from stripe_link.sender_identity import sending_identity

        occurrence = occurrence_by_id(scheduled_event, occurrence_id)
        if occurrence is None:
            return
        message = registration_confirmation(
            scheduled_event, occurrence, name=str((fields or {}).get("name") or ""),
            watch_url=_watch_url(scheduled_event, page_url, lead_id, attend_token))
        if not message["subject"]:
            return
        # WHO the confirmation is from. Stated rather than left to the mailer's tenant-level fallback,
        # because the registration happened ON A PAGE and that page names the Site whose business is
        # running the session (plans/SITE_AS_BUSINESS_IDENTITY.md §4).
        identity = sending_identity(tenant_id, page_id=page_id, mode=mode)
        send_email(
            to=recipient, subject=message["subject"], html=message["html"], text=message["text"],
            tenant_id=tenant_id, from_name=identity["business_name"],
            reply_to=identity["reply_to"],
            calendar_invite=invite_for_occurrence(scheduled_event, occurrence),
            calendar_filename="session.ics",
        )
    except Exception as exc:  # noqa: BLE001 — a failed confirmation must not fail the registration
        logger.warning("registration stored but confirmation not sent for %s: %s", recipient, exc)


def _emit_lead_notification(notifications_repo, lead, tenant_id, now, mode="test"):
    import os

    repo = notifications_repo or (notifications_repository(mode=mode) if os.environ.get("NOTIFICATIONS_TABLE") else None)
    if not repo:
        return
    try:
        repo.put(lead_notification(lead, tenant_id, now))
    except Exception:  # noqa: BLE001 - a notification failure must never fail the capture
        pass


def lead_mode(lead):
    """Which books a lead came from, or "" when it belongs to both.

    No derivation is possible for an older record: a lead's page_id and offer_id are the same in both
    modes by design, so one captured before the mode was recorded simply cannot be placed. Those are
    shown in both modes rather than hidden -- a lead is a person who asked to be contacted, and losing
    one is worse than showing it twice.

    **An EVENT REGISTRATION belongs to both modes, whatever mode it was captured in**, and that is not a
    concession -- it is what keeps the screen honest. An event is deliberately mode-agnostic (a free
    session is not money, see repositories/documents.events_repository), so the session a test-mode
    registrant signed up for is a real one that will really happen. The reminder sweep emails them
    accordingly, with no mode filter. Hiding them from the live Leads screen would therefore show a
    tenant FEWER registrants than are about to be contacted -- a count they would plan a webinar around.
    What is displayed has to match what the software will do.
    """
    if str((lead or {}).get("event_id") or "").strip():
        return ""
    stored = str((lead or {}).get("stripe_mode") or "").strip().lower()
    return stored if stored in ("live", "test") else ""


def list_leads(event, leads_repo):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    leads = leads_repo.list_for_tenant(tenant_id)
    # Mode-scoped at read time, matching the bell: `_emit_lead_notification` already scopes the
    # NOTIFICATION about a lead, while the lead itself appeared in both lists. One of those was wrong.
    mode = resolve_stripe_mode(event)
    leads = [lead for lead in leads if lead_mode(lead) in (mode, "")]
    params = query_params(event)
    offer_id = str(params.get("offer_id") or "").strip()
    status = str(params.get("status") or "").strip()
    if offer_id:
        leads = [lead for lead in leads if lead.get("offer_id") == offer_id]
    if status:
        leads = [lead for lead in leads if lead.get("status") == status]
    leads.sort(key=lambda lead: lead.get("created_at", 0), reverse=True)
    return json_response({"leads": leads, "count": len(leads)})


def get_lead(event, leads_repo, lead_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    lead = leads_repo.get(tenant_id, lead_id)
    if not lead:
        return error_response("Lead not found.", status_code=404, code="not_found")
    return json_response({"lead": lead})


def update_lead_status(event, leads_repo, lead_id, now):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_lead")
    status = str(body.get("status") or "").strip()
    if status not in {"new", "contacted", "qualified", "archived"}:
        return error_response("Lead status must be one of: new, contacted, qualified, archived.", code="invalid_lead")
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    lead = leads_repo.get(tenant_id, lead_id)
    if not lead:
        return error_response("Lead not found.", status_code=404, code="not_found")
    lead["status"] = status
    lead["updated_at"] = int(now)
    try:
        saved = leads_repo.put(lead)
        return json_response({"lead": saved})
    except RepositoryError as exc:
        return error_response(str(exc), code="invalid_lead")


def _watch_url(scheduled_event, page_url, lead_id, attend_token):
    """Where an AUTO-webinar is watched: the page they registered on, carrying who they are.

    "" for a live event, which has a join link of its own, and "" when anything is missing -- a half-built
    link is worse than none, because the confirmation then promises something that does not work.

    The page URL comes from the REFERER the registration arrived with. That is the page the visitor was
    actually standing on, which beats reconstructing one from a slug and a custom domain and being wrong
    for exactly the tenants who set a domain up. It is attacker-controlled, so it is accepted only when it
    is an https URL and is rebuilt from its parts rather than concatenated.
    """
    from urllib.parse import urlencode, urlsplit, urlunsplit

    from stripe_link.domain.events import DELIVERY_AUTO, delivery

    if delivery(scheduled_event) != DELIVERY_AUTO:
        return ""
    if not lead_id or not attend_token or not page_url:
        return ""
    parts = urlsplit(str(page_url).strip())
    if parts.scheme != "https" or not parts.netloc:
        return ""
    query = urlencode({"r": lead_id, "k": attend_token})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
