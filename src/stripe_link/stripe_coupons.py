"""Create a tenant's coupon and promotion code IN Stripe (plans/COUPONS_COMPLETION.md C1).

The module recorded coupons for a long time without ever creating them, while the schema said "Coupons are
persisted only after Stripe sync succeeds". This is the half that was missing.

Two objects, in order: a Coupon carries the DISCOUNT, a Promotion Code carries the CODE a buyer types and
the restrictions on using it. Stripe models them separately because one discount can be offered under
several codes; we create exactly one code per coupon, which is what the tenant means by "a coupon".

Standard library only — `src/requirements.txt` is deliberately empty and Stripe is called over urllib
everywhere in this codebase.
"""
from base64 import b64encode
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import logging

logger = logging.getLogger(__name__)

STRIPE_COUPONS_URL = "https://api.stripe.com/v1/coupons"
STRIPE_PROMOTION_CODES_URL = "https://api.stripe.com/v1/promotion_codes"


class StripeCouponError(RuntimeError):
    """Stripe refused to create the coupon, and said why. Carries Stripe's own message."""


def _post(url: str, payload: dict[str, Any], *, api_key: str, stripe_account: str = "",
          idempotency_key: str = "", opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    """POST a form-encoded body to Stripe and return the parsed object.

    The Idempotency-Key matters more here than almost anywhere: a retried save must not leave a tenant with
    two coupons and two codes for one intent, and the browser already allocates the coupon_id before it
    asks, so the key is stable across retries by construction.
    """
    opener = opener or urlopen
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    request = Request(url, data=urlencode(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Stripe ALWAYS explains a 4xx in the body; urllib's str() is only "HTTP Error 400: Bad Request".
        # Losing it once meant a failed checkout said nothing at all in the logs.
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message") or ""
        except Exception:  # noqa: BLE001 - a body we cannot parse must not replace the original error
            pass
        logger.error("stripe: coupon call rejected: %s", detail or exc)
        raise StripeCouponError(detail or f"Stripe rejected the request ({exc.code}).") from exc


def coupon_payload(discount: dict[str, Any], restrictions: dict[str, Any], name: str = "") -> dict[str, Any]:
    """Our discount, as Stripe's Coupon fields.

    `max_redemptions` and `redeem_by` belong on the COUPON (a cap on the discount itself) rather than on the
    promotion code, so the cap holds however many codes ever point at it.
    """
    payload: dict[str, Any] = {"duration": str(discount.get("duration") or "once")}
    if name:
        payload["name"] = name
    if str(discount.get("type")) == "percent":
        payload["percent_off"] = str(discount.get("value") or 0)
    else:
        payload["amount_off"] = str(int(discount.get("value") or 0))
        payload["currency"] = str(discount.get("currency") or "usd").lower()
    if payload["duration"] == "repeating":
        payload["duration_in_months"] = str(int(discount.get("duration_months") or 1))
    if restrictions.get("max_redemptions") is not None:
        payload["max_redemptions"] = str(int(restrictions["max_redemptions"]))
    if restrictions.get("expires_at"):
        payload["redeem_by"] = str(int(restrictions["expires_at"]))
    return payload


def promotion_code_payload(coupon_id: str, code: str, restrictions: dict[str, Any]) -> dict[str, Any]:
    """Our code + restrictions, as Stripe's Promotion Code fields.

    `max_redemptions_per_customer` is NOT here: Stripe has no per-customer cap on a promotion code. It is
    enforced by us or not at all (plans/COUPONS_COMPLETION.md C4) — silently sending it would be worse.
    """
    payload: dict[str, Any] = {"coupon": coupon_id, "code": code}
    if restrictions.get("expires_at"):
        payload["expires_at"] = str(int(restrictions["expires_at"]))
    if restrictions.get("first_time_only"):
        payload["restrictions[first_time_transaction]"] = "true"
    minimum = restrictions.get("minimum_amount")
    if minimum:
        payload["restrictions[minimum_amount]"] = str(int(minimum))
        payload["restrictions[minimum_amount_currency]"] = str(
            restrictions.get("minimum_amount_currency") or "usd").lower()
    return payload


def create_coupon_in_stripe(
    *, coupon_id: str, code: str, name: str, discount: dict[str, Any], restrictions: dict[str, Any],
    api_key: str, stripe_account: str = "", opener: Callable[..., Any] | None = None,
) -> tuple[str, str]:
    """Create both objects and return `(stripe_coupon_id, stripe_promo_code_id)`.

    Raises StripeCouponError with Stripe's own words if either call fails. The caller persists NOTHING on
    failure — a coupon document whose Stripe objects do not exist is a promise the platform cannot keep.

    If the Coupon succeeds and the Promotion Code fails, the Coupon is deliberately LEFT in Stripe: it is
    inert without a code pointing at it, and deleting on a failure path is how the wrong one gets deleted.
    """
    created = _post(
        STRIPE_COUPONS_URL, coupon_payload(discount, restrictions, name),
        api_key=api_key, stripe_account=stripe_account,
        idempotency_key=f"{coupon_id}:coupon", opener=opener,
    )
    stripe_coupon_id = str(created.get("id") or "")
    if not stripe_coupon_id:
        raise StripeCouponError("Stripe did not return a coupon id.")

    promo = _post(
        STRIPE_PROMOTION_CODES_URL, promotion_code_payload(stripe_coupon_id, code, restrictions),
        api_key=api_key, stripe_account=stripe_account,
        idempotency_key=f"{coupon_id}:promo", opener=opener,
    )
    stripe_promo_code_id = str(promo.get("id") or "")
    if not stripe_promo_code_id:
        raise StripeCouponError("Stripe did not return a promotion code id.")
    return stripe_coupon_id, stripe_promo_code_id


def set_promotion_code_active(
    stripe_promo_code_id: str, active: bool, *, api_key: str, stripe_account: str = "",
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Enable or disable the code at Stripe, so our record and Stripe can never disagree about it.

    `active` is one of only two mutable fields on a Promotion Code (the other is metadata) — which is the
    same reason a coupon's VALUE can never be edited after creation.
    """
    return _post(
        f"{STRIPE_PROMOTION_CODES_URL}/{stripe_promo_code_id}",
        {"active": "true" if active else "false"},
        api_key=api_key, stripe_account=stripe_account, opener=opener,
    )
