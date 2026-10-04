"""Where a catch-all zone actually reaches.

A zone's `destinations` may carry `*`, and `shipping_zones` resolves it correctly: it is the rule for every
country no earlier zone claimed. But two consumers need an ENUMERATION rather than a wildcard -- the page's
country dropdown, and Stripe's `shipping_address_collection[allowed_countries]`, which takes an explicit
list and has no notion of "the rest".

`allowed_countries` used to drop the catch-all for that reason, and documented it as the honest answer. It
was not. A tenant whose zones read "United States" and "Everywhere else" was shown a dropdown containing
only the United States -- the platform silently refusing a rule the tenant wrote, which is the exact failure
the zones plan exists to prevent (author, 2026-10-04: *"someone in Mexico, Canada, or the European Union
cannot purchase the item when the system says that they can"*).

A country the CARRIER cannot reach is a different matter and is answered a step later: the shipping element
rates live and reports that it cannot quote, before the buyer commits to anything. Refusing at the dropdown
would be the platform guessing at carrier coverage it does not know.
"""
from __future__ import annotations

# ISO 3166-1 alpha-2. Mirrors `dashboard/src/utils/countries.js`, which is the maintained copy; a test
# asserts the two agree, because a code in one and not the other is a country a buyer can pick on the page
# and not at Stripe, or the reverse.
ISO_COUNTRIES: tuple[str, ...] = (
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW", "AX",
    "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN", "BO", "BQ",
    "BR", "BS", "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK",
    "CL", "CM", "CN", "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM", "FO", "FR",
    "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL", "GM", "GN", "GP", "GQ", "GR", "GS",
    "GT", "GU", "GW", "GY", "HK", "HM", "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN",
    "IO", "IQ", "IR", "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS", "LT", "LU", "LV",
    "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK", "ML", "MM", "MN", "MO", "MP", "MQ",
    "MR", "MS", "MT", "MU", "MV", "MW", "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI",
    "NL", "NO", "NP", "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA", "SB", "SC",
    "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS", "ST", "SV",
    "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR",
    "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW"
)

# Stripe REFUSES these in `shipping_address_collection[allowed_countries]` -- sending one is a 400 that
# takes down checkout for every buyer, not just the one from that country. Sanctions and territories
# without an independent postal identity, per Stripe's own documented exclusion list.
STRIPE_UNSUPPORTED: frozenset[str] = frozenset({
    "AS", "CX", "CC", "CU", "HM", "IR", "KP", "MH", "FM", "NF", "MP", "PW", "SD", "SY", "UM", "VI",
})


def shippable_countries() -> list[str]:
    """Every country a catch-all zone may offer: ISO alpha-2 minus the ones Stripe will not accept."""
    return [code for code in ISO_COUNTRIES if code not in STRIPE_UNSUPPORTED]
