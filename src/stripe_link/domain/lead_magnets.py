"""A Page Ribbon's downloadable file, and what a visitor must give up to get it.

The rules live here rather than in the handler because ONE fact decides everything: what the published page
document says. A visitor's browser sends whatever it likes, so "was email required?" can only be answered by
reading the section — never by trusting the request that is trying to satisfy it.
"""

from typing import Any

COLLECTABLE_FIELDS = ("email", "phone")


def find_ribbon(page: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    """The page_ribbon section with this id, or None. Type is checked, not assumed: a section id is
    client-supplied, and pointing it at some other section must not reach this code path."""
    target = str(section_id or "").strip()
    if not target:
        return None
    for section in (page or {}).get("sections") or []:
        if str(section.get("id") or "") == target and str(section.get("type") or "") == "page_ribbon":
            return section
    return None


# How the file reaches the visitor. Both hand over the SAME asset by the same signed URL — the difference
# is whether the browser follows it now or an inbox does later, which is why one endpoint serves both.
DELIVERY_BY_ACTION = {"download": "download", "email_file": "email"}


def download_offer(section: dict[str, Any]) -> dict[str, Any] | None:
    """The {asset, required, delivery} contract for a ribbon whose button hands over a file, or None.

    Returns None unless the section carries a file-handing action AND an asset — a ribbon set to something
    else must not become a download endpoint because someone guessed its id.

    `email_file` always requires an email, whatever the section's checkboxes say: there is nowhere to send
    it otherwise. That is a property of the delivery, not a tenant preference, so it is enforced here
    rather than left to the builder to remember.
    """
    cta = (section or {}).get("cta") or {}
    delivery = DELIVERY_BY_ACTION.get(str(cta.get("action") or ""))
    if not delivery:
        return None
    asset = cta.get("asset")
    if not isinstance(asset, dict) or not str(asset.get("bucket_key") or "").strip():
        return None
    required = [field for field in COLLECTABLE_FIELDS if bool(cta.get(f"collect_{field}"))]
    if delivery == "email" and "email" not in required:
        required = ["email"] + required
    return {"asset": asset, "required": required, "delivery": delivery}


def missing_fields(required: list[str], submitted: dict[str, Any]) -> list[str]:
    """Which required fields the visitor did not actually provide. Whitespace is not an answer."""
    return [field for field in required if not str(submitted.get(field) or "").strip()]
