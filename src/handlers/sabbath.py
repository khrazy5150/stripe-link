"""The tenant's Sabbath setting, and a preview of what it would actually do.

(plans/TODO.md "Sabbath mode" — the P2 Preferences UI.)

**Its own endpoint rather than a second writer of `PUT /config`.** The setting lives on `TenantConfig`,
a document the Configuration screen saves WHOLE: it reads the stored config, overlays the sections it
owns, and puts the lot back. A settings card doing the same from a different screen would restore its own
stale copy of refund policies, legal links and page defaults over whatever Configuration had just saved,
and the save would look like it worked because the response is built from the copy in memory
(`feedback_shared_document_read_modify_write`). This writes ONE attribute and touches nothing else.

**The GET is the reason this is a route at all.** Everything in `domain/sabbath` fails OPEN, so a tenant
who switches the Sabbath on while their Site carries no coordinates gets a store that never closes, no
error, and nothing anywhere to say why — the shape of `feedback_absence_reads_as_safety`. So the read
answers with the resolved window per Site, and says plainly when there is none. The maths runs here and
not in the dashboard because a JavaScript copy of the solar routine would be a second implementation of
the one number this feature is about, free to disagree with the gate that enforces it.
"""
import logging
import os
from typing import Any

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    resolve_stripe_mode,
    tenant_id_from_event,
)
from stripe_link.domain.documents import DocumentValidationError, validate_sabbath
from stripe_link.domain.sabbath import (DEFAULT_AFTER_MINUTES, DEFAULT_BEFORE_MINUTES,
                                        MAX_BUFFER_MINUTES, MAX_MANUAL_HOURS, MIN_BUFFER_MINUTES,
                                        MIN_MANUAL_HOURS, clamp_buffer, config as sabbath_config,
                                        status, timezone_for, validate_manual_window)
from stripe_link.repositories.documents import (RepositoryError, platform_config_repository,
                                                sites_repository, tenant_profiles_repository)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2026-05-29"

#: The bounds the screen draws its inputs from, so the maximum a tenant can type is the maximum the
#: server will keep. A hardcoded 60 in the dashboard is how the two come to disagree.
LIMITS = {
    "before_minutes": DEFAULT_BEFORE_MINUTES,
    "after_minutes": DEFAULT_AFTER_MINUTES,
    "min_minutes": MIN_BUFFER_MINUTES,
    "max_minutes": MAX_BUFFER_MINUTES,
    "min_manual_hours": MIN_MANUAL_HOURS,
    "max_manual_hours": MAX_MANUAL_HOURS,
}


def handler(event, context, repository=None, sites_repo=None, tenant_repo=None):
    repository = repository or platform_config_repository()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if method == "GET":
        return read(event, tenant_id, repository, sites_repo=sites_repo, tenant_repo=tenant_repo)
    if method in {"POST", "PUT"}:
        return save(event, tenant_id, repository, sites_repo=sites_repo, tenant_repo=tenant_repo)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _stores(tenant_id: str, mode: str, *, sites_repo=None, tenant_repo=None) -> list[dict[str, Any]]:
    """Every Site of this tenant, with the two things the window needs: coordinates and a timezone.

    Per SITE, because that is how the gate resolves it: the setting is the tenant's, the PLACE is the
    Site's (`organization.geo`), and a tenant can run businesses in two countries. One of them being
    closable and the other not is a real state, and a single combined answer would hide it.

    Returns `[]` on any failure. The setting itself still renders -- a tenant must be able to read and
    change their own choice while the Sites table is unavailable.
    """
    try:
        if sites_repo is None:
            if not os.environ.get("SITES_TABLE"):
                return []
            sites_repo = sites_repository(mode=mode)
        return list(sites_repo.list_for_tenant(tenant_id) or [])
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("sabbath: could not list Sites for %s", tenant_id)
        return []


def _profile(tenant_id: str, tenant_repo=None) -> dict[str, Any]:
    """The tenant profile, for the account business address the timezone falls back to."""
    try:
        tenant_repo = tenant_repo or tenant_profiles_repository()
        return tenant_repo.get(tenant_id, tenant_id) or {}
    except Exception:  # noqa: BLE001 - costs a timezone GUESS, not the answer
        logger.exception("sabbath: could not read the profile for %s", tenant_id)
        return {}


def _payload(tenant_id: str, stored: dict, mode: str, *, sites_repo=None, tenant_repo=None,
             now=None) -> dict[str, Any]:
    """The setting, the bounds, and what it resolves to at each of this tenant's Sites."""
    setting = sabbath_config(stored)
    # Read even when the setting is OFF, because the screen reports the timezone each Site's window
    # would be computed in, and that is the first thing a tenant checks BEFORE switching it on. Skipping
    # it while disabled would have shown them "UTC" and invited them to correct a zone that was right.
    profile = _profile(tenant_id, tenant_repo)
    sites = []
    for site in _stores(tenant_id, mode, sites_repo=sites_repo, tenant_repo=tenant_repo):
        organization = site.get("organization") if isinstance(site.get("organization"), dict) else {}
        resolved = status(stored, organization, timezone_name=timezone_for(organization, profile),
                          now=now)
        sites.append({
            "site_id": str(site.get("site_id") or ""),
            # The Site's own name before the business name: this list is for picking out WHICH of my
            # Sites, and that is what the tenant named it in the Sites screen.
            "name": (str(site.get("name") or "").strip()
                     or str(organization.get("name") or "").strip() or "Untitled Site"),
            **{key: resolved[key] for key in ("timezone", "has_coordinates", "sun_sets", "source",
                                              "closed_now", "starts_at", "ends_at")},
        })
    return {
        "sabbath": setting,
        "limits": LIMITS,
        "sites": sites,
        # WOULD THIS DO ANYTHING? The one question the toggle cannot answer on its own, and the whole
        # reason the screen asks the server. False with `enabled` true means a store that will never
        # close -- which is exactly the state that would otherwise go unreported.
        "effective": bool(setting["enabled"]) and any(s["source"] != "none" for s in sites),
        "closed_now": any(s["closed_now"] for s in sites),
    }


def read(event, tenant_id, repository, *, sites_repo=None, tenant_repo=None):
    try:
        stored = repository.get(tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    # NOT a 404 when the config document is absent, unlike `GET /config`. A tenant who has never saved
    # Configuration has no document, and they are the likeliest person to be switching this on for the
    # first time; the honest answer is the default setting, which is exactly what `config({})` returns.
    return json_response(_payload(tenant_id, stored, resolve_stripe_mode(event),
                                  sites_repo=sites_repo, tenant_repo=tenant_repo))


def save(event, tenant_id, repository, *, sites_repo=None, tenant_repo=None):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")
    block = body.get("sabbath") if isinstance(body.get("sabbath"), dict) else body
    manual = block.get("manual")
    stored = {
        "enabled": bool(block.get("enabled")),
        # Clamped, not refused: a tenant who types 90 means "as much as you allow", and the clamp is the
        # same one the gate applies, so what is stored is what will be enforced.
        "before_minutes": clamp_buffer(block.get("before_minutes"), DEFAULT_BEFORE_MINUTES),
        "after_minutes": clamp_buffer(block.get("after_minutes"), DEFAULT_AFTER_MINUTES),
    }
    if manual is not None:
        stored["manual"] = manual
    # VALIDATED BEFORE IT IS NORMALIZED, and that order is the whole point. `validate_manual_window`
    # CLAMPS the duration, so normalizing first turned a tenant's "3 hours" into 24 and stored it as
    # though they had asked for it -- while `PUT /config` refuses the same input outright. Two paths to
    # one document disagreeing, with the lenient one being the one a tenant hits, is exactly what
    # sharing `validate_sabbath` was meant to prevent (found by the test, 2026-11-05).
    #
    # The buffers are still clamped rather than refused: 90 minutes means "as much as you allow" and
    # there is a sane maximum to give them. A 3-hour "Sabbath" is not a dial at the wrong setting, it is
    # a different thing being configured, so it is sent back.
    try:
        validate_sabbath(stored)
    except DocumentValidationError as exc:
        return error_response(str(exc), code="invalid_sabbath")
    if manual is not None:
        # Through the SAME normalizer the gate reads it with, so a window that survives the save is a
        # window that will fire. `None` back means unusable -- a half-filled form that `validate_sabbath`
        # permits, because there every field is optional.
        normalized = validate_manual_window(manual)
        if normalized is None:
            return error_response(
                "A manual Sabbath window needs a weekday, an hour and a minute, and a duration of 24-25 hours.",
                code="invalid_sabbath")
        stored["manual"] = normalized
    try:
        # ONE attribute. See the module docstring: the Configuration screen owns this document whole, and
        # a read-modify-write from here would lose whatever it saved a moment ago.
        repository.set_attribute(tenant_id, "sabbath", stored,
                                 {"document_type": "tenant_config", "schema_version": SCHEMA_VERSION,
                                  "tenant_id": tenant_id})
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    except Exception:  # noqa: BLE001 - a write that failed must SAY so, and must leave a cause behind
        # LOGGED, then reported. A store setting that silently did not save is the worst of the three
        # outcomes: the tenant believes their shop closes on Friday and it does not
        # (`feedback_one_guess_hides_the_cause` -- the message is generic, the exception is not).
        logger.exception("sabbath: could not save the setting for %s", tenant_id)
        return error_response("That setting could not be saved. Please try again.",
                             status_code=502, code="save_failed")
    # Answered with the resolved preview, not just an echo: the tenant has just changed a buffer, and the
    # only useful confirmation is the window it produces.
    return json_response(_payload(tenant_id, {"sabbath": stored}, resolve_stripe_mode(event, body),
                                  sites_repo=sites_repo, tenant_repo=tenant_repo))
