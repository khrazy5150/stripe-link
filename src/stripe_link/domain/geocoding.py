"""An address turned into coordinates, for the Sites editor's "Calculate" button.

A tenant should not have to look up their own latitude. `plans/TODO.md` ("Sundown math ... Source:
Business Address (Profile) geocoded") and `plans/LOCAL_SEO_SIGNALS.md` both named geocoding as the way
`organization.geo` gets filled; until now the only writer was two number inputs, so every Site that had
never been hand-edited reported "No location" to Sabbath mode while holding a complete postal address.

**This is a BUTTON, never a step in saving.** Geocoding at save would mean a stored coordinate nobody
chose, silently refreshed on an unrelated edit, and -- the part that matters -- a *wrong* one would be
indistinguishable from a right one, because nothing downstream can tell a plausible coordinate from a
correct one. So the tenant presses it, sees the place name we matched, and keeps or discards the result.
`locate` returns that label for exactly that reason: the match is reviewable or it is not trustworthy.

**Nominatim, and nothing at runtime.** The 2020 version of Sabbath mode died when the external sunset API
it depended on went away, so `domain/sabbath` computes sundown from pure maths and reaches the network
never. That rule is untouched here: this module is called once, by a person, while editing a Site. If
OpenStreetMap is unreachable the tenant types two numbers as they do today, and no store's closing time
depends on a third party being up. Their usage policy asks for a descriptive User-Agent and no more than
one request a second -- a button pressed a handful of times per Site sits far inside both.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: Nominatim's policy requires an identifying agent with a way to reach us. The same shape as
#: `social_links.VERIFIER_USER_AGENT`, which is this repo's other outbound caller.
USER_AGENT = "JuniorBayGeocoder/1.0 (+https://juniorbay.com)"

FETCH_TIMEOUT_SECONDS = 10
MAX_FETCH_BYTES = 256 * 1024

#: Six decimal places is ~0.1 m. Far past what sundown can use -- sunset moves about one minute per 25 km
#: of longitude at mid-latitudes -- but it is what was returned, and rounding it further would only
#: invent a false precision story in the other direction.
COORDINATE_DECIMALS = 6


class GeocodeError(Exception):
    """The lookup could not be performed. NOT "the address is not a place" -- that is `None`."""


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def is_placeable(address: Any) -> bool:
    """Whether this address is specific enough to be worth asking about.

    **A country or a region alone is refused rather than sent.** Nominatim will happily place "US" at the
    centroid of the United States, and that answer is not merely imprecise -- it is about an hour of
    sunset away from either coast, and it arrives looking exactly like a real result. A town or a postal
    code is the floor at which the answer is about the tenant's shop.
    """
    if not isinstance(address, dict):
        return False
    return bool(_text(address.get("locality")) or _text(address.get("postal_code")))


def _structured_query(address: dict) -> list[tuple[str, str]]:
    """The address as Nominatim's structured fields rather than one free-text string.

    Structured beats free text here because we already know which part is the town and which is the
    region: "St. George, UT" as free text competes with St George in Queensland, Ontario and Bermuda,
    while `city=St. George&state=UT&country=US` does not.
    """
    fields = (
        ("street", _text(address.get("street"))),
        ("city", _text(address.get("locality"))),
        ("state", _text(address.get("region"))),
        ("postalcode", _text(address.get("postal_code"))),
        ("country", _text(address.get("country"))),
    )
    return [(name, value) for name, value in fields if value]


def _fetch(url: str) -> str:
    import urllib.request

    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - every failure here is "ask again later", with a cause logged
        raise GeocodeError(str(exc) or type(exc).__name__) from exc


def _best_match(query: list[tuple[str, str]], fetch) -> dict | None:
    """The single best result for `query`, or None when the service answered with no match."""
    # `limit=1`: we want the best match or nothing. Offering a tenant a list of five candidates is a
    # disambiguation UI, and the address they typed is already their disambiguation.
    url = f"{NOMINATIM_URL}?{urlencode(query + [('format', 'jsonv2'), ('limit', '1')])}"
    raw = fetch(url)
    try:
        results = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise GeocodeError("the geocoder returned something that was not JSON") from exc
    if not isinstance(results, list) or not results:
        return None
    return results[0] if isinstance(results[0], dict) else None


def locate(address: Any, *, fetch=None) -> dict[str, Any] | None:
    """`{"latitude", "longitude", "label"}` for `address`, or None when it could not be placed.

    `label` is the place Nominatim believes it found, and the caller is expected to SHOW it. A geocoder's
    characteristic failure is not an error, it is a confident coordinate in the wrong town; the only
    defence that works is letting the person who knows the address read the match back.

    Raises `GeocodeError` when the service could not be asked at all -- a different outcome from "this
    address is not a place", and the tenant can do something about only one of them.
    """
    if not is_placeable(address):
        return None
    fetch = fetch or _fetch
    query = _structured_query(address)
    best = _best_match(query, fetch)
    matched = "address" if any(name == "street" for name, _ in query) else "area"
    if best is None and matched == "address":
        # SECOND AND LAST ATTEMPT, with the street DROPPED -- not cleaned up. A real address can fail the
        # first pass for ordinary reasons ("176 W 300 S St Apt 19" returns nothing: the unit number and
        # the abbreviations defeat the parser), and a town is a perfectly good answer for both things
        # geo is used for -- a town centroid is a few km out, which is seconds of sunset.
        #
        # Stripping the unit number and retrying was the obvious alternative and is the trap: asked
        # about "176 W 300 S" in St. George, Nominatim confidently returns *Trailblazer Boulevard* in a
        # different postcode (probed 2026-11-05). A wrong street presented as a street match is worse
        # than a right town presented as a town, so we never half-parse what the tenant typed.
        best = _best_match([(n, v) for n, v in query if n != "street"], fetch)
        matched = "area"
    if best is None:
        return None
    if not isinstance(best, dict):
        return None
    try:
        latitude = round(float(best["lat"]), COORDINATE_DECIMALS)
        longitude = round(float(best["lon"]), COORDINATE_DECIMALS)
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "label": _text(best.get("display_name")) or _text(best.get("name")),
        # "area" means the street was not used, so this is the town rather than the shop door. Reported
        # so the screen can say which it got instead of letting the tenant assume the finer one.
        "matched": matched,
    }
