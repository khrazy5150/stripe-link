"""`POST /geocode` -- the Sites editor's "Calculate" button for latitude and longitude.

Server-side rather than a `fetch` from the dashboard, for three reasons that all point the same way:
OpenStreetMap's policy asks for an identifying User-Agent, which a browser will not let us set; the
outbound call stays on one controllable path if it ever needs a different provider, a cache or a limiter;
and the endpoint sits behind the Cognito authorizer, so this is not an open geocoding proxy for anyone
who finds the URL.

**It reads no table and writes nothing.** The coordinates go back to the form, the tenant looks at the
place name we matched, and the ordinary Site save stores them. Nothing here touches `organization.geo`
directly -- a button that wrote to the document would be a second writer of a document the Sites screen
saves whole (`feedback_shared_document_read_modify_write`), and it would also save a match the tenant had
not yet agreed with.
"""
import logging

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    tenant_id_from_event,
)
from stripe_link.domain.geocoding import GeocodeError, locate

logger = logging.getLogger(__name__)


def handler(event, context, locator=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"POST", "PUT"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405,
                              code="method_not_allowed")
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")
    # Required even though nothing is read or written per-tenant: without it this route is a free
    # geocoder for anyone who learns the path, and the bill and the rate limit would be ours.
    if not tenant_id_from_event(event, body):
        return error_response("tenant_id is required.", code="missing_tenant")
    address = body.get("address") if isinstance(body.get("address"), dict) else body
    try:
        found = (locator or locate)(address)
    except GeocodeError as exc:
        # The service, not the address. Logged with its cause, and reported as a retry rather than as
        # something the tenant mistyped -- they can always still type the two numbers
        # (`feedback_one_guess_hides_the_cause`).
        logger.exception("geocode: the lookup failed")
        return error_response(
            "The map service could not be reached just now. Try again, or type the coordinates in by hand.",
            status_code=502, code="geocoder_unavailable", extra={"detail": str(exc)})
    if found is None:
        # 404, deliberately: the request was fine and the service answered, there is just no such place.
        # Naming the two fields that would help is the difference between a dead end and a next step.
        return error_response(
            "That address could not be placed on the map. A city or a postal code is needed, and they "
            "must match the country.", status_code=404, code="address_not_found")
    return json_response(found)
