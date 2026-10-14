"""Scheduled events — tenant-scoped CRUD (plans/WEBINAR.md P1).

Thin by design: everything here is `document_route`, the shared CRUD the services handler already used.
What makes an event an event lives in `domain/events.py` and `validate_event`, not in a request handler.
"""
from stripe_link.common import json_response
from stripe_link.document_route import document_route
from stripe_link.domain.documents import validate_event
from stripe_link.repositories.documents import events_repository


def handler(event, context, events_repo=None):
    events_repo = events_repo or events_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    return document_route(event, method, events_repo, "event", validate_event, "events", id_param="event_id")
