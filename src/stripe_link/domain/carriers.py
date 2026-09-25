"""Carriers, and turning a hand-typed tracking number into a link.

This exists for the MANUAL path only. When a provider sells the label it hands us the tracking URL --
Shippo returns `tracking_url_provider` and the legacy adapter read the equivalent from every provider it
supported; only its direct-USPS path ever built one by hand. So this table stays small on purpose.

Two things it must get right, because both are about not lying to a buyer:

1. **Not every parcel has a tracking number.** USPS First-Class MAIL -- letters, flats, postcards -- has no
   tracking unless extra services were bought, while USPS *parcel* service does. Tenants call both "first
   class". A form that demands a number leaves the tenant who posted a padded envelope unable to mark their
   own order shipped, and an email promising tracking that will never appear generates exactly the support
   message it was meant to prevent.
2. **Carrier URLs change.** `CARRIERS` is the seed; `carrier_registry()` takes an override so the deployed
   table can be corrected without a release, the same way the fee table already is
   (see feedback_deployed_config_outranks_code).

The service names below are a starting set and SHOULD BE VERIFIED against each carrier's current products
before being relied on -- USPS First-Class Package Service became Ground Advantage in 2023 and the retail
names have moved more than once. Getting a URL wrong is recoverable; getting `tracking: False` wrong tells
a tenant to omit a number they actually had.
"""
from typing import Any

OTHER = "other"

# carrier key -> {label, tracking_url (a {tracking_number} template), services}
# A service's `tracking` flag is about the SERVICE, never the carrier: USPS tracks parcels and does not
# track letter mail, and both are USPS.
CARRIERS: dict[str, dict[str, Any]] = {
    "usps": {
        "label": "USPS",
        "tracking_url": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}",
        "services": [
            {"key": "ground_advantage", "label": "USPS Ground Advantage", "tracking": True,
             "aka": "formerly First-Class Package Service"},
            {"key": "priority", "label": "Priority Mail", "tracking": True},
            {"key": "priority_express", "label": "Priority Mail Express", "tracking": True},
            {"key": "media_mail", "label": "Media Mail", "tracking": True},
            # The one that catches people out, and the reason the number is optional.
            {"key": "first_class_mail", "label": "First-Class Mail (letter or flat)", "tracking": False,
             "note": "Letter and flat rates include no tracking unless you bought extra services."},
        ],
    },
    "ups": {
        "label": "UPS",
        "tracking_url": "https://www.ups.com/track?tracknum={tracking_number}",
        "services": [
            {"key": "ground", "label": "UPS Ground", "tracking": True},
            {"key": "three_day_select", "label": "UPS 3 Day Select", "tracking": True},
            {"key": "second_day_air", "label": "UPS 2nd Day Air", "tracking": True},
            {"key": "next_day_air", "label": "UPS Next Day Air", "tracking": True},
        ],
    },
    "fedex": {
        "label": "FedEx",
        "tracking_url": "https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
        "services": [
            {"key": "ground", "label": "FedEx Ground", "tracking": True},
            {"key": "home_delivery", "label": "FedEx Home Delivery", "tracking": True},
            {"key": "express_saver", "label": "FedEx Express Saver", "tracking": True},
            {"key": "two_day", "label": "FedEx 2Day", "tracking": True},
            {"key": "overnight", "label": "FedEx Standard Overnight", "tracking": True},
        ],
    },
    "dhl_express": {
        "label": "DHL Express",
        "tracking_url": "https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}",
        "services": [{"key": "express", "label": "DHL Express", "tracking": True}],
    },
    # The escape hatch that stops this feature being permanently incomplete for want of a table row:
    # regional carriers, couriers, freight, a friend with a van. The tenant pastes the link.
    OTHER: {
        "label": "Other carrier",
        "tracking_url": "",
        "services": [],
        "requires_tracking_url": True,
    },
}


def carrier_registry(overrides: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The seed table, with any deployed corrections applied on top. Shallow per-carrier merge."""
    registry = {key: dict(value) for key, value in CARRIERS.items()}
    for key, override in (overrides or {}).items():
        if not isinstance(override, dict):
            continue
        registry[key] = {**registry.get(key, {}), **override}
    return registry


def carrier_options(overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What a carrier picker renders. `other` sorts last -- it is the exception, not a peer."""
    registry = carrier_registry(overrides)
    options = [{"key": key, **value} for key, value in registry.items() if key != OTHER]
    options.sort(key=lambda item: str(item.get("label") or ""))
    if OTHER in registry:
        options.append({"key": OTHER, **registry[OTHER]})
    return options


def find_service(carrier: str, service: str, overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A service by key OR by label, because a tenant's stored value may be either."""
    wanted = str(service or "").strip().lower()
    if not wanted:
        return None
    entry = carrier_registry(overrides).get(str(carrier or "").strip().lower()) or {}
    for candidate in entry.get("services") or []:
        if wanted in {str(candidate.get("key") or "").lower(), str(candidate.get("label") or "").lower()}:
            return candidate
    return None


def service_has_tracking(carrier: str, service: str, overrides: dict[str, Any] | None = None) -> bool | None:
    """True, False, or **None for "we do not know"** -- which is not the same as False.

    An unknown service must not be told "this has no tracking": the tenant may well have a number, and
    talking them out of entering it is worse than staying quiet.
    """
    found = find_service(carrier, service, overrides)
    if found is None:
        return None
    return bool(found.get("tracking", True))


def tracking_url(carrier: str, tracking_number: str, *, custom_url: str = "",
                 overrides: dict[str, Any] | None = None) -> str:
    """A link for this number, or "" when there cannot honestly be one.

    A pasted `custom_url` always wins: it is the tenant looking at the real thing, and it is the only
    option for a carrier this table has never heard of.
    """
    pasted = str(custom_url or "").strip()
    if pasted:
        return pasted if pasted.lower().startswith(("http://", "https://")) else ""
    number = str(tracking_number or "").strip()
    if not number:
        return ""
    template = str((carrier_registry(overrides).get(str(carrier or "").strip().lower()) or {}).get("tracking_url") or "")
    if not template:
        return ""
    return template.replace("{tracking_number}", _url_safe(number))


def _url_safe(number: str) -> str:
    """Tracking numbers are alphanumeric; spaces and dashes are how humans write them down."""
    from urllib.parse import quote
    return quote(number.replace(" ", "").replace("-", ""), safe="")


def detect_carrier(tracking_number: str) -> str:
    """A PREFILL, never an answer. Returns "" when the shape says nothing.

    A prefill that is usually right saves a click. A detection that is silently wrong sends a buyer to the
    wrong carrier's website, so this stays deliberately conservative and the tenant can always override.
    """
    number = str(tracking_number or "").strip().replace(" ", "").replace("-", "").upper()
    if not number:
        return ""
    if number.startswith("1Z") and len(number) == 18:
        return "ups"
    if number.isdigit():
        if len(number) in (20, 22, 26):
            return "usps"
        if len(number) in (12, 15):
            return "fedex"
        if len(number) == 10:
            return "dhl_express"
    # USPS international and certified formats: two letters, nine digits, two letters.
    if len(number) == 13 and number[:2].isalpha() and number[2:11].isdigit() and number[11:].isalpha():
        return "usps"
    return ""
