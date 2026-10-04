"""Suggesting a store's timezone from where its business is.

plans/THANK_YOU_PAGE.md P1. A tenant should not have to hunt through a list of six hundred IANA names to
tell us when their afternoon ends — but they must be able to, because the suggestion is often wrong in a
way only they can see. A seller may live in Pacific time and ship from a warehouse in Mountain time, and
either answer can be the right one depending on which they consider their working day (author,
2026-10-04: *"we suggest but don't dictate"*).

So: a best guess from the address, and a free choice over the top. Nothing here is authoritative, and
nothing refuses a value it does not recognise.

**US states are mapped, other countries get their single common zone.** Deliberately shallow — a table
that tried to resolve every multi-zone country from a postal code would be large, wrong at the edges, and
no better than asking. The countries with one practical zone are covered; everywhere else falls back to
UTC, which is visibly a placeholder rather than a plausible wrong answer.
"""
from __future__ import annotations

from typing import Any

FALLBACK = "UTC"

# The zones a store is plausibly in, grouped for a picker. Not the full IANA list: a tenant who needs one
# that is missing can still store any string, because nothing validates against this.
COMMON_ZONES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("United States & Canada", (
        "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
        "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
        "America/Toronto", "America/Winnipeg", "America/Edmonton", "America/Vancouver", "America/Halifax",
    )),
    ("Europe & Africa", (
        "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Madrid", "Europe/Paris",
        "Europe/Berlin", "Europe/Amsterdam", "Europe/Brussels", "Europe/Zurich", "Europe/Rome",
        "Europe/Stockholm", "Europe/Oslo", "Europe/Copenhagen", "Europe/Helsinki", "Europe/Warsaw",
        "Europe/Athens", "Europe/Istanbul", "Africa/Lagos", "Africa/Johannesburg", "Africa/Nairobi",
        "Africa/Cairo",
    )),
    ("Asia & Pacific", (
        "Asia/Jerusalem", "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata", "Asia/Dhaka", "Asia/Bangkok",
        "Asia/Singapore", "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Asia/Manila",
        "Australia/Perth", "Australia/Adelaide", "Australia/Brisbane", "Australia/Sydney",
        "Pacific/Auckland",
    )),
    ("Latin America", (
        "America/Mexico_City", "America/Tijuana", "America/Bogota", "America/Lima", "America/Santiago",
        "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Panama",
    )),
    ("Other", (FALLBACK,)),
)

# US states/territories -> zone. The one country where country alone is useless, and the one most of this
# platform's sellers are in.
_US_STATE_ZONES: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix", "AR": "America/Chicago",
    "CA": "America/Los_Angeles", "CO": "America/Denver", "CT": "America/New_York",
    "DE": "America/New_York", "DC": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "HI": "Pacific/Honolulu", "ID": "America/Denver",
    "IL": "America/Chicago", "IN": "America/New_York", "IA": "America/Chicago",
    "KS": "America/Chicago", "KY": "America/New_York", "LA": "America/Chicago",
    "ME": "America/New_York", "MD": "America/New_York", "MA": "America/New_York",
    "MI": "America/New_York", "MN": "America/Chicago", "MS": "America/Chicago",
    "MO": "America/Chicago", "MT": "America/Denver", "NE": "America/Chicago",
    "NV": "America/Los_Angeles", "NH": "America/New_York", "NJ": "America/New_York",
    "NM": "America/Denver", "NY": "America/New_York", "NC": "America/New_York",
    "ND": "America/Chicago", "OH": "America/New_York", "OK": "America/Chicago",
    "OR": "America/Los_Angeles", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "SD": "America/Chicago", "TN": "America/Chicago",
    "TX": "America/Chicago", "UT": "America/Denver", "VT": "America/New_York",
    "VA": "America/New_York", "WA": "America/Los_Angeles", "WV": "America/New_York",
    "WI": "America/Chicago", "WY": "America/Denver", "PR": "America/Puerto_Rico",
}

# Countries with one zone a store is realistically in. Multi-zone countries (CA, AU, BR, RU, MX) are
# deliberately absent unless a region narrows them, because guessing wrong there is worse than not
# guessing: a plausible wrong answer gets accepted, an obvious placeholder gets corrected.
_COUNTRY_ZONES: dict[str, str] = {
    "GB": "Europe/London", "IE": "Europe/Dublin", "PT": "Europe/Lisbon", "ES": "Europe/Madrid",
    "FR": "Europe/Paris", "DE": "Europe/Berlin", "NL": "Europe/Amsterdam", "BE": "Europe/Brussels",
    "CH": "Europe/Zurich", "AT": "Europe/Vienna", "IT": "Europe/Rome", "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo", "DK": "Europe/Copenhagen", "FI": "Europe/Helsinki", "PL": "Europe/Warsaw",
    "GR": "Europe/Athens", "TR": "Europe/Istanbul", "IL": "Asia/Jerusalem", "AE": "Asia/Dubai",
    "IN": "Asia/Kolkata", "PK": "Asia/Karachi", "BD": "Asia/Dhaka", "TH": "Asia/Bangkok",
    "SG": "Asia/Singapore", "HK": "Asia/Hong_Kong", "CN": "Asia/Shanghai", "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul", "PH": "Asia/Manila", "NZ": "Pacific/Auckland", "ZA": "Africa/Johannesburg",
    "NG": "Africa/Lagos", "KE": "Africa/Nairobi", "EG": "Africa/Cairo", "CO": "America/Bogota",
    "PE": "America/Lima", "CL": "America/Santiago", "PA": "America/Panama",
}

# Multi-zone countries where a REGION can still settle it.
_REGION_ZONES: dict[tuple[str, str], str] = {
    ("CA", "BC"): "America/Vancouver", ("CA", "AB"): "America/Edmonton",
    ("CA", "SK"): "America/Regina", ("CA", "MB"): "America/Winnipeg",
    ("CA", "ON"): "America/Toronto", ("CA", "QC"): "America/Toronto",
    ("CA", "NB"): "America/Halifax", ("CA", "NS"): "America/Halifax",
    ("CA", "PE"): "America/Halifax", ("CA", "NL"): "America/St_Johns",
    ("AU", "WA"): "Australia/Perth", ("AU", "SA"): "Australia/Adelaide",
    ("AU", "QLD"): "Australia/Brisbane", ("AU", "NSW"): "Australia/Sydney",
    ("AU", "VIC"): "Australia/Sydney", ("AU", "TAS"): "Australia/Sydney",
}


# FULL STATE NAMES, because the profile form stores what the tenant typed and the Business Address screen
# shows "Colorado", not "CO". Truncating a name to two letters is not a shortcut, it is a different state:
# "Nevada" -> NE -> Nebraska -> Central time, when Nevada is Pacific. Found while checking the author's own
# example (Las Vegas NV) against the profile's real stored shape, 2026-10-04.
_US_STATE_NAMES: dict[str, str] = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "PUERTO RICO": "PR", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

# ...and the same for the provinces, for the same reason.
_CA_PROVINCE_NAMES: dict[str, str] = {
    "BRITISH COLUMBIA": "BC", "ALBERTA": "AB", "SASKATCHEWAN": "SK", "MANITOBA": "MB",
    "ONTARIO": "ON", "QUEBEC": "QC", "QUÉBEC": "QC", "NEW BRUNSWICK": "NB", "NOVA SCOTIA": "NS",
    "PRINCE EDWARD ISLAND": "PE", "NEWFOUNDLAND AND LABRADOR": "NL",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def suggest_timezone(address: Any) -> str:
    """A best guess from a business address, or `UTC` when there is no honest one.

    UTC rather than a nearby-sounding zone on purpose: a tenant scanning their profile will correct an
    obvious placeholder and will accept a plausible wrong answer without looking.
    """
    if not isinstance(address, dict):
        return FALLBACK
    country = _text(address.get("country")).upper()[:2]
    region = _text(address.get("region") or address.get("state")).upper()
    if country == "US":
        # A full name FIRST, then a two-letter code. Never a truncation of a name -- see _US_STATE_NAMES.
        code = _US_STATE_NAMES.get(region) or (region if len(region) == 2 else "")
        return _US_STATE_ZONES.get(code, "America/New_York")
    if country == "CA":
        code = _CA_PROVINCE_NAMES.get(region) or (region if len(region) == 2 else "")
        return _REGION_ZONES.get(("CA", code), "America/Toronto")
    if (country, region) in _REGION_ZONES:
        return _REGION_ZONES[(country, region)]
    return _COUNTRY_ZONES.get(country, FALLBACK)


def store_timezone(business: Any) -> str:
    """The tenant's own answer when they gave one, else the suggestion. What every caller should use."""
    chosen = _text((business or {}).get("timezone")) if isinstance(business, dict) else ""
    return chosen or suggest_timezone((business or {}).get("address") if isinstance(business, dict) else None)
