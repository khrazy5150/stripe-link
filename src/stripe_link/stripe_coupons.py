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
STRIPE_CUSTOMERS_URL = "https://api.stripe.com/v1/customers"


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


def coupon_payload(discount: dict[str, Any], restrictions: dict[str, Any], name: str = "",
                   applies_to_product_ids: "list[str] | tuple[str, ...]" = ()) -> dict[str, Any]:
    """Our discount, as Stripe's Coupon fields.

    `max_redemptions` and `redeem_by` belong on the COUPON (a cap on the discount itself) rather than on the
    promotion code, so the cap holds however many codes ever point at it.

    `applies_to_product_ids` are STRIPE product ids, and scope the discount to those line items
    (plans/COUPONS_COMPLETION.md, Option A). **Stripe never echoes this field back** -- `applies_to` reads
    `null` on create and on retrieve whether or not a scope was set -- so it is verified by the DISCOUNT it
    produces, never by the response. Reading the echo is what made this look broken for a day.
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
    for index, product_id in enumerate(applies_to_product_ids or ()):
        payload[f"applies_to[products][{index}]"] = str(product_id)
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
    applies_to_product_ids: "list[str] | tuple[str, ...]" = (),
) -> tuple[str, str]:
    """Create both objects and return `(stripe_coupon_id, stripe_promo_code_id)`.

    Raises StripeCouponError with Stripe's own words if either call fails. The caller persists NOTHING on
    failure — a coupon document whose Stripe objects do not exist is a promise the platform cannot keep.

    If the Coupon succeeds and the Promotion Code fails, the Coupon is deliberately LEFT in Stripe: it is
    inert without a code pointing at it, and deleting on a failure path is how the wrong one gets deleted.
    """
    created = _post(
        STRIPE_COUPONS_URL, coupon_payload(discount, restrictions, name, applies_to_product_ids),
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


def _get(url: str, params: dict[str, Any], *, api_key: str, stripe_account: str = "",
         opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    opener = opener or urlopen
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Stripe-Version": "2024-06-20",
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    request = Request(f"{url}?{urlencode(params)}", headers=headers, method="GET")
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message") or ""
        except Exception:  # noqa: BLE001
            pass
        raise StripeCouponError(detail or f"Stripe rejected the request ({exc.code}).") from exc


def find_or_create_customer(
    email: str, *, api_key: str, stripe_account: str = "", opener: Callable[..., Any] | None = None,
) -> str:
    """The Stripe Customer id for an email, creating one if Stripe has never seen it.

    Email is the identity we actually hold. A guest checkout creates NO Stripe Customer -- `session.customer`
    comes back null -- so past buyers are known to us by email and to Stripe by nothing (verified against
    real orders, 2026-09-22). A targeted code has to be scoped to a Customer, so this is where one gets made.

    Matching on email is Stripe's own lookup and can return several; the FIRST is taken, which is what the
    dashboard shows and what a subsequent charge would attach to.
    """
    email = str(email or "").strip().lower()
    if not email:
        raise StripeCouponError("An email is required to issue a targeted coupon.")
    found = _get(STRIPE_CUSTOMERS_URL, {"email": email, "limit": 1},
                 api_key=api_key, stripe_account=stripe_account, opener=opener)
    existing = (found.get("data") or [None])[0]
    if existing and existing.get("id"):
        return str(existing["id"])
    created = _post(STRIPE_CUSTOMERS_URL, {"email": email},
                    api_key=api_key, stripe_account=stripe_account, opener=opener)
    customer_id = str(created.get("id") or "")
    if not customer_id:
        raise StripeCouponError("Stripe did not return a customer id.")
    return customer_id


def create_targeted_promotion_code(
    *, stripe_coupon_id: str, code: str, customer_id: str, max_redemptions: int | None = None,
    expires_at: int | None = None, api_key: str, stripe_account: str = "",
    opener: Callable[..., Any] | None = None,
) -> str:
    """A promotion code only ONE customer can use, pointing at the campaign's shared Coupon.

    `customer` is what makes it non-transferable: a recipient who forwards it gives away nothing, which is
    strictly stronger than a per-customer counter on a shared code -- and Stripe cannot do the latter at
    all, because everyone holding a shared code is the same anonymous buyer until they pay.

    `max_redemptions` here means "how many times THAT customer may use it", and is OPTIONAL: a targeted
    coupon with no cap is still bound to one person. It exists for the loss-leader case, not as something
    every grant must carry (author, 2026-09-22).
    """
    payload: dict[str, Any] = {"coupon": stripe_coupon_id, "code": code, "customer": customer_id}
    if max_redemptions:
        payload["max_redemptions"] = str(int(max_redemptions))
    if expires_at:
        payload["expires_at"] = str(int(expires_at))
    created = _post(STRIPE_PROMOTION_CODES_URL, payload, api_key=api_key, stripe_account=stripe_account,
                    idempotency_key=f"grant:{code}", opener=opener)
    promo_id = str(created.get("id") or "")
    if not promo_id:
        raise StripeCouponError("Stripe did not return a promotion code id.")
    return promo_id


def create_disposable_coupon(
    *, amount_off: int, currency: str, api_key: str, stripe_account: str = "",
    code: str = "", tenant_id: str = "", expires_at: int | None = None,
    opener: Callable[..., Any] | None = None,
) -> str:
    """A Stripe Coupon for ONE checkout, carrying an amount we worked out ourselves (Option B).

    This is the adapter between our pricing engine and Stripe's discount mechanism -- NOT the tenant's
    coupon, which stays a durable, immutable rule in our own table. Stripe Checkout has no inline discount
    (`discounts[0][amount_off]` is rejected outright: "Received unknown parameters"), so an object is the
    only way to put a computed amount in front of a buyer AS a discount, with Stripe's own presentation.

    **Deliberately not deleted after use.** Deleting it immediately was verified safe for an OPEN session
    (the discount is materialized inline and survives), but "delete, then the buyer pays" was never tested,
    and inventing that path on a money route is how a receipt loses its discount. Instead the object bounds
    itself: `max_redemptions: 1` means it can never be reused, and `redeem_by` makes it inert. Sweeping old
    ones is a chore; a discount that silently vanishes from a paid order is an incident.
    """
    amount_off = int(amount_off or 0)
    if amount_off <= 0:
        raise StripeCouponError("A disposable coupon needs a positive amount.")
    payload: dict[str, Any] = {
        "amount_off": str(amount_off),
        "currency": str(currency or "usd").lower(),
        "duration": "once",
        # One checkout, one use. An id that escaped could not be spent a second time.
        "max_redemptions": "1",
        "name": f"{code} (applied at checkout)" if code else "Discount applied at checkout",
    }
    if expires_at:
        payload["redeem_by"] = str(int(expires_at))
    if code:
        payload["metadata[jb_coupon_code]"] = code
    if tenant_id:
        payload["metadata[jb_tenant_id]"] = tenant_id
    payload["metadata[jb_disposable]"] = "true"
    created = _post(STRIPE_COUPONS_URL, payload, api_key=api_key, stripe_account=stripe_account, opener=opener)
    coupon_id = str(created.get("id") or "")
    if not coupon_id:
        raise StripeCouponError("Stripe did not return a coupon id for the computed discount.")
    return coupon_id
