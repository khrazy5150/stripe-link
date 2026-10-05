import json
import logging
import os
import time
from base64 import b64encode
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

class StripeCheckoutError(RuntimeError):
    """Stripe rejected the Checkout Session and said why. Carries Stripe's own message."""


logger = logging.getLogger(__name__)
# Lambda leaves the root logger at WARNING, so every `logger.info` in this module has been swallowed since
# it was written -- including "checkout shipping not charged", the line whose whole job is to say out loud
# why a buyer was not charged for postage. A diagnostic nobody can hear is the same silence it was added to
# remove. `page_publish` already sets its own level; this follows it (2026-10-01).
logger.setLevel(logging.INFO)

from stripe_link.common import error_response, json_response, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain import commerce_eligibility
from stripe_link.domain.bnpl import checkout_payment_method_types
from stripe_link.domain.fees import (application_fee_percent, build_fee_context, cached_billing_config,
                                     calculate_price, normalize_tier_id)
from stripe_link.domain.shipping_charges import checkout_shipping, stripe_option_payload
from stripe_link.domain.shipping_zones import allowed_countries as zone_allowed_countries
from stripe_link.domain.shipping_zones import offerable_countries as zone_offerable_countries
from stripe_link.domain.opportunities import STAGE_CHECKOUT, STAGE_POST_PURCHASE, stage_opportunities
from stripe_link.domain.pricing import (
    PricingError,
    find_price,
    load_offer_products,
    load_offer_services,
    resolve_offer,
)
from stripe_link.domain import tips
from stripe_link.domain.coupon_grants import is_grant_code
from stripe_link.silo import current_silo
from stripe_link.domain.coupon_rules import evaluate as evaluate_coupon_rule
from stripe_link.domain.coupon_rules import is_platform_evaluated, lines_from_resolved
from stripe_link.stripe_coupons import create_disposable_coupon
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.runtime.error_pages import render_error_page
from stripe_link.repositories.documents import (
    coupon_grants_repository,
    coupons_repository,
    offers_repository,
    experiments_repository,
    pages_repository,
    products_repository,
    services_repository,
    sites_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_platform_secrets import checkout_credentials


STRIPE_CHECKOUT_SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"

# Presentment currencies where we re-add Link to an explicit payment_method_types list (Link's established
# markets). Outside these we omit it to avoid a guaranteed retry; the fallback ladder also drops Link if an
# account lacks it. Link supports more over time — widen as needed.
LINK_CURRENCIES = {"usd", "eur", "gbp", "cad", "aud", "nzd"}


class CouponUnavailable(RuntimeError):
    """The page promised a discount this checkout cannot apply."""


def coupon_covers_offer(coupon: dict, offer_id: str) -> bool:
    """Whether this coupon may be used on this offer.

    `applies_to_offer_ids` has been stored and validated since the module was written and read by NOTHING,
    so a coupon scoped to one offer worked on every offer (found 2026-09-22). An empty list means "any
    offer", which is what every coupon created so far carries.

    This is ELIGIBILITY -- may this code be used here at all -- and not the same question as which PRODUCTS
    within a cart get discounted. Stripe's `applies_to.products` is the mechanism for the latter, and it
    silently ignored both documented syntaxes when tested against a live connected account on 2026-09-22:
    accepted, then `applies_to: null` on create and on retrieve. Relying on it would mean believing a
    scoping that is not happening, so product-level discounting is deliberately NOT attempted here.
    """
    scoped = coupon.get("applies_to_offer_ids") or []
    if not scoped:
        return True
    return str(offer_id or "") in {str(item) for item in scoped}


def resolve_targeted_grant(code, tenant_id, mode, grants_repo=None, coupons_repo=None, offer_id=""):
    """A recipient's own code, as `(promotion_code_id, stripe_customer_id)`. `("", "")` when the code is not
    a grant at all, which is the ordinary shared-coupon case and must fall through untouched.

    The customer id comes back because it is REQUIRED, not informational: the promotion code is scoped to
    that customer at Stripe (which is what makes it non-transferable), so a session that does not name them
    is refused the discount. Checkout has no other way to know who is on the other end -- the visitor has
    typed nothing yet.

    The grant lives or dies with its coupon. A tenant who turns a campaign off has turned off every code
    they sent, and the recipient is told the offer ended rather than being quietly charged full price.
    """
    code = str(code or "").strip().upper()
    if not code or not tenant_id or not is_grant_code(code):
        return "", ""
    try:
        repo = grants_repo or (coupon_grants_repository(mode=mode) if os.environ.get("COUPON_GRANTS_TABLE") else None)
        if repo is None:
            return "", ""
        grant = repo.get(tenant_id, code)
    except Exception:  # noqa: BLE001 - an unreadable grants table falls back to the shared-coupon path
        return "", ""
    if not grant:
        return "", ""
    if str(grant.get("status") or "") != "active":
        raise CouponUnavailable(code)

    from handlers.coupons import coupon_is_usable

    try:
        coupons = coupons_repo or (coupons_repository(mode=mode) if os.environ.get("COUPONS_TABLE") else None)
        coupon = coupons.get(tenant_id, str(grant.get("coupon_id") or "")) if coupons else None
    except Exception as exc:  # noqa: BLE001 - never charge a surprise full price on a read failure
        raise CouponUnavailable(code) from exc
    if not coupon or not coupon_is_usable(coupon, int(time.time())):
        raise CouponUnavailable(code)
    if not coupon_covers_offer(coupon, offer_id):
        raise CouponUnavailable(code)
    promo_id = str(grant.get("stripe_promo_code_id") or "")
    customer_id = str(grant.get("stripe_customer_id") or "")
    if not promo_id or not customer_id:
        raise CouponUnavailable(code)
    return promo_id, customer_id


def resolve_platform_coupon(code, tenant_id, mode, coupons_repo=None, offer_id=""):
    """The tenant's coupon document when WE evaluate it rather than Stripe (Option B), else None.

    Tried before the Stripe-evaluated path because a platform coupon has no `stripe_promo_code_id` to
    resolve -- the Stripe object does not exist until a cart gives the rule something to be worth.
    """
    code = str(code or "").strip().upper()
    if not code or not tenant_id:
        return None
    try:
        from handlers.coupons import coupon_is_usable

        repo = coupons_repo or (coupons_repository(mode=mode) if os.environ.get("COUPONS_TABLE") else None)
        if repo is None:
            return None
        for coupon in repo.list_for_tenant(tenant_id) or []:
            if str(coupon.get("code") or "").strip().upper() != code:
                continue
            if not is_platform_evaluated(coupon):
                return None   # Stripe's to evaluate; let the ordinary path answer
            # Past this point the code IS ours, so every refusal is a refusal -- never a fall-through to
            # full price, which is the failure this module exists to prevent.
            if not coupon_is_usable(coupon, int(time.time())):
                raise CouponUnavailable(code)
            if not coupon_covers_offer(coupon, offer_id):
                raise CouponUnavailable(code)
            return coupon
        return None
    except CouponUnavailable:
        raise
    except Exception:  # noqa: BLE001 - an unreadable table falls through to the Stripe-evaluated path
        return None


def resolve_campaign_promotion_code(code, tenant_id, mode, coupons_repo=None, offer_id=""):
    """The Stripe promotion-code id for a campaign coupon. "" when no coupon was asked for at all.

    Resolved from the CODE against the tenant's own record, because that record is what says whether the
    tenant still INTENDS to offer it -- `coupon_is_usable` encodes status, expiry and the redemption cap.
    The id it stores is the real Stripe promotion code (plans/COUPONS_COMPLETION.md C1), so no second
    lookup at Stripe is needed.

    Raises CouponUnavailable when a code WAS asked for and cannot be honoured. Deliberately not a silent
    fall-through to full price: the visitor arrived from a ticket promising a specific price, and charging
    them more without saying so is the worst of the available outcomes (decision, 2026-09-22). They can
    still buy at full price from the ordinary page.

    A published page cannot know a coupon was disabled after it was published -- its section carries only
    the code and expiry copied at publish -- so this is the only place that can tell the visitor.
    """
    code = str(code or "").strip().upper()
    if not code:
        return ""
    if not tenant_id:
        raise CouponUnavailable(code)
    try:
        from handlers.coupons import coupon_is_usable

        repo = coupons_repo or (coupons_repository(mode=mode) if os.environ.get("COUPONS_TABLE") else None)
        if repo is None:
            raise CouponUnavailable(code)
        now = int(time.time())
        for coupon in repo.list_for_tenant(tenant_id) or []:
            if str(coupon.get("code") or "").strip().upper() != code:
                continue
            if not coupon_is_usable(coupon, now):
                raise CouponUnavailable(code)
            # Refused the same way as expired: the visitor is told the offer is not available here, rather
            # than being charged full price by a coupon that silently did not apply.
            if not coupon_covers_offer(coupon, offer_id):
                raise CouponUnavailable(code)
            promo_id = str(coupon.get("stripe_promo_code_id") or "")
            if not promo_id:
                raise CouponUnavailable(code)
            return promo_id
        raise CouponUnavailable(code)
    except CouponUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - an unreadable table must not charge a surprise full price
        raise CouponUnavailable(code) from exc


def handler(
    event,
    context,
    *,
    offers_repo=None,
    products_repo=None,
    services_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    coupons_repo=None,
    grants_repo=None,
    pages_repo=None,
    sites_repo=None,
    experiments_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"GET", "POST"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    params = query_params(event)
    tenant_id = tenant_id_from_event(event) or str(params.get("clientID") or "").strip()
    offer_id = str(params.get("offer") or params.get("offer_id") or "").strip()
    product_id = str(params.get("product_id") or "").strip()
    price_id = str(params.get("price_id") or "").strip()
    # Which SERVICE the buyer picked on a choice offer. Service cards carry an EMPTY product_id, so without
    # this the selection was invisible here and every service in the offer was charged
    # (plans/SERVICE_CHOICE.md).
    service_id = str(params.get("service_id") or "").strip()
    page_id = str(params.get("page_id") or "").strip()
    success_url = str(params.get("success_url") or "").strip()
    cancel_url = str(params.get("cancel_url") or "").strip()
    # A TIP JAR's amount comes from the buyer, so it arrives here and is re-decided server-side: a preset must
    # be one the price actually offers, and a typed amount must sit inside the platform's range
    # (plans/PAY_WHAT_YOU_WANT.md §5d). The page's number is an input, never the authority.
    tip_amount = str(params.get("tip_amount") or "").strip()
    tip_source = "custom" if str(params.get("tip_source") or "").strip() == "custom" else "preset"
    tip_recurring = str(params.get("tip_recurring") or "").strip() in {"1", "true", "yes"}

    if not tenant_id:
        return error_response("clientID or tenant_id is required.", code="missing_tenant")
    if not offer_id:
        return error_response("offer is required.", code="missing_offer")

    # A QUOTE, not a session: what shipping would cost, so a page element can show it and ask the buyer where
    # to send it. Lives on this function because it needs exactly what checkout already loads -- the offer, its
    # products and the tenant's shipping config -- and every grant for them (plans/SHIPPING_ELEMENT.md phase 6).
    #
    # Public, and for tiers 1 and 2 that costs nothing to abuse: the answer is a cached config read plus
    # arithmetic, with NO carrier call. The cache-and-throttle the plan calls for becomes a hard prerequisite
    # when tier 3 arrives and each quote spends money at a carrier.
    if str((event or {}).get("resource") or "").endswith("/shipping-quote"):
        return shipping_quote(
            tenant_id=tenant_id, offer_id=offer_id, product_id=product_id, price_id=price_id,
            quantity=str(params.get("quantity") or "1"),
            country=str(params.get("country") or "").strip().upper()[:2],
            # A carrier prices a journey between two postcodes, so tier 3 needs more than a country.
            # `region` is only required where carriers insist on it (US, CA, AU, BR, IN, MX...), and is
            # passed through rather than validated here: the carrier is the authority on its own address
            # rules, and guessing them in two places is how they drift.
            postal_code=str(params.get("postal_code") or "").strip()[:12],
            region=str(params.get("region") or "").strip()[:3],
            # The server cart, when the page keeps one. It describes what is actually being posted.
            cart_id=str(params.get("cart_id") or "").strip()[:64],
            mode=resolve_stripe_mode(event),
            offers_repo=offers_repo, products_repo=products_repo,
        )
    if not success_url or not cancel_url:
        return error_response("success_url and cancel_url are required.", code="missing_redirect_url")

    # The transaction runs in the request's Stripe mode; a published Buy URL carries ?mode= so live pages check
    # out live and test pages test (plans/STRIPE_MODE_DECOUPLING.md P2/P4). Entities load in this mode.
    mode = resolve_stripe_mode(event)
    offers_repo = offers_repo or offers_repository(mode=mode)
    products_repo = products_repo or products_repository(mode=mode)
    if services_repo is None:
        try:
            services_repo = services_repository(mode=mode)
        except Exception:  # noqa: BLE001 - services table optional; only needed for service offer items
            services_repo = None
    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen

    try:
        assert_billing_in_good_standing(tenant_repo.get(tenant_id, tenant_id))

        # A checkout initiated from a page may only transact when that page is published. The preview render
        # already shows a "DRAFT" screen instead of a working CTA, but this is the authoritative server-side
        # guard: a draft/unknown page_id cannot start a real transaction even if the API is called directly.
        if page_id:
            pages_repo = pages_repo or pages_repository(mode=mode)
            page = pages_repo.get(tenant_id, page_id)
            if not page or page.get("status") != "published":
                # GET /checkout is the CTA's own href — a browser lands here directly — so serve the branded
                # error page rather than raw JSON. (POST is the fetch/API path and keeps the JSON error.)
                if method == "GET":
                    return {
                        "statusCode": 403,
                        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                        "body": render_error_page(
                            403, "This page has not been published yet. Transactions are only available on "
                            "published pages — publish it from the dashboard first.",
                            title="Not published", badge="Draft",
                        ),
                    }
                return error_response(
                    "This page is not published. Transactions are only available on published pages.",
                    status_code=403, code="page_not_published",
                )

            # Published is not the same as authorized. A page detached from its Site is gone from every
            # hostname the platform governs, yet its artifact still serves and its baked CTA still reaches
            # here (plans/COMMERCE_ELIGIBILITY.md). Phase 1 only measures: the verdict is recorded and the
            # checkout proceeds, because refusing a legitimate sale is worse than the hole it closes.
            eligibility = commerce_eligibility.guard(
                path="checkout", tenant_id=tenant_id, page_id=page_id, stripe_mode=mode,
                sites_repo=sites_repo if sites_repo is not None else (
                    sites_repository(mode=mode) if os.environ.get("SITES_TABLE") else None),
                experiments_repo=experiments_repo if experiments_repo is not None else (
                    experiments_repository(mode=mode) if os.environ.get("EXPERIMENTS_TABLE") else None),
            )
            if eligibility["refuse"]:
                if method == "GET":
                    return {
                        "statusCode": 403,
                        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                        "body": render_error_page(
                            403, "This page isn't set up to take payments. Attach it to a site in the "
                            "dashboard, then try again.",
                            title="Not available", badge="Unavailable",
                        ),
                    }
                return error_response(
                    "This page is not authorized to take payments.",
                    status_code=403, code="page_not_eligible",
                )

        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        products_by_id = load_offer_products(tenant_id, offer, products_repo)
        # Pre-purchase order bumps (offer.funnel.order_bumps) may reference products the offer's items don't
        # include — load them so build_checkout_payload can emit their synced price as an optional_item.
        for bump in stage_opportunities(offer, STAGE_CHECKOUT):
            bump_product_id = str(bump.get("product_id") or "")
            if bump_product_id and bump_product_id not in products_by_id:
                bump_product = products_repo.get(tenant_id, bump_product_id)
                if bump_product:
                    products_by_id[bump_product_id] = bump_product
        services_by_id = load_offer_services(tenant_id, offer, services_repo)
        selected_prices = {product_id: price_id} if product_id and price_id else {}
        # A service card sends service_id + price_id (its product_id is empty), so the buyer's chosen price
        # is keyed by the SERVICE. Ids never collide across the two, so one map serves both.
        if service_id and price_id:
            selected_prices[service_id] = price_id
        resolved = resolve_offer(
            offer, products_by_id, selected_prices,
            services_by_id=services_by_id, selected_service_id=service_id,
        )
        apply_tip_amount(
            resolved, products_by_id,
            amount=tip_amount, source=tip_source, recurring=tip_recurring, tenant_id=tenant_id,
            tenant_repo=tenant_repo, billing_config_loader=billing_config_loader,
        )

        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
        api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
        if not api_key:
            return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

        fee_context = build_fee_context(
            tenant_id=tenant_id,
            offer=offer,
            products_by_id=products_by_id,
            resolved=resolved,
            tenant_repo=tenant_repo,
            billing_config_loader=billing_config_loader,
        )
        # Direct-charge (Connect) tenants can offer their enabled BNPL methods; legacy own-key tenants keep their
        # own Stripe account's payment-method settings untouched (plans/BNPL_PAYMENT_METHODS.md).
        bnpl_types = checkout_payment_method_types(
            (stripe_keys.get("payment_methods") or {}).get("bnpl"), resolved.get("currency"),
        ) if stripe_account else []
        checkout_payload = build_checkout_payload(
            tenant_id=tenant_id,
            offer=offer,
            products_by_id=products_by_id,
            resolved=resolved,
            success_url=success_url,
            cancel_url=cancel_url,
            page_id=page_id,
            fee_context=fee_context,
            apply_application_fee=bool(stripe_account),
            bnpl_payment_method_types=bnpl_types,
            coupon_code=str(params.get("coupon") or ""),
            mode=mode,
            coupons_repo=coupons_repo,
            grants_repo=grants_repo,
            discount_materializer=stripe_discount_materializer(api_key, stripe_account, opener),
            shipping_config=_tenant_shipping_config(tenant_id) if collect_shipping_for(
                offer, products_by_id) else None,
            # Where the BUYER said they want it sent, if a shipping element on the page asked. Declaring a
            # country lifts the unanimity restriction: we can price that one zone correctly instead of needing
            # every allowed destination to agree (plans/SHIPPING_ELEMENT.md phase 5).
            ship_to_country=str(params.get("ship_to_country") or "").strip().upper()[:2],
            # WHICH quote the buyer was looking at, and WHICH service they picked on it. Never an amount:
            # the price is read off the server's own row (plans/LIVE_SHIPPING_RATES.md phase 4).
            shipping_quote_id=str(params.get("shipping_quote") or "").strip()[:64],
            shipping_service=str(params.get("shipping_service") or "").strip()[:64],
            secret_cipher=secret_cipher,
        )
        stripe_response = create_checkout_session_with_bnpl_fallback(
            checkout_payload,
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
            had_bnpl=bool(bnpl_types),
        )
        checkout_url = stripe_response.get("url")
        if not checkout_url:
            return error_response("Stripe did not return a checkout URL.", status_code=502, code="checkout_error")
        return redirect_response(checkout_url)
    except tips.TipAmountError as exc:
        return error_response(str(exc), code="invalid_tip_amount")
    except CouponUnavailable:
        # The page promised a discount that can no longer be applied -- a coupon disabled or used up after
        # the page was published, which a baked artifact cannot know. Refusing is the honest answer:
        # charging the full price to someone who arrived from a ticket saying otherwise is worse.
        if method == "GET":
            return {
                "statusCode": 410,
                "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
                "body": render_error_page(
                    410, "This offer is no longer available. The coupon has ended or been withdrawn — "
                    "you can still buy at the regular price from the store.",
                    title="Offer ended", badge="Coupon",
                ),
            }
        return error_response(
            "This coupon is no longer available.", status_code=410, code="coupon_unavailable",
        )
    except BillingStatusError as exc:
        return error_response(str(exc), status_code=402, code="tenant_billing_hold")
    except PricingError as exc:
        return error_response(str(exc), code="checkout_error")
    except Exception as exc:
        return error_response(str(exc), status_code=500, code="checkout_error")


def apply_tip_amount(resolved, products_by_id, *, amount, source, tenant_id, recurring=False,
                     tenant_repo=None, billing_config_loader=None):
    """Price a TIP JAR line from the amount the buyer chose, in place.

    A `customer_chooses` price carries no unit_amount by design, so a resolved tip line arrives here worth
    zero. Left alone it would create a Checkout Session for $0.00 — the failure this whole feature exists to
    stop, in its other direction.

    A typed amount is grossed up by the SERVER's fee calculation, the same one the authoring form and the
    page's live estimate call, so the figure on the card and the figure on the statement come from one place.
    """
    for line in resolved.get("items") or []:
        # A SERVICE line has no product document to look a price up in -- its price lives on the service, and
        # `find_price` on an empty product raises rather than returning nothing. A service is also never a tip
        # jar (customer_chooses is a product pricing model), so there is nothing here for it either way.
        # Without this, every service checkout died on this line: "Price 'X' was not found on product ''"
        # (reported 2026-09-20, the first real purchase attempt of a service).
        if line.get("kind") == "service" or line.get("service_id"):
            continue
        product = products_by_id.get(line.get("product_id")) or {}
        price = find_price(product, line.get("price_id") or "")
        if not tips.is_tip_price(price):
            continue
        # A membership jar offers no one-off tip, so a request for one is refused rather than quietly
        # upgraded to a subscription: charging a buyer a repeating amount they did not ask for is the worse
        # of the two failures by a distance.
        if not recurring and not tips.allows_one_time(price):
            raise tips.TipAmountError("This tip jar only accepts a repeating tip.")
        if not amount:
            # No amount in the request: the line already resolved to the preset the page shows checked, so a
            # CTA clicked before any JS ran still charges a real, offered amount. A jar with no presets at
            # all has nothing to fall back to.
            if int(line.get("unit_amount") or 0) > 0:
                continue
            raise tips.TipAmountError("Choose an amount before checking out.")
        tenant_plan = "basic"
        if tenant_repo is not None:
            tenant_plan = normalize_tier_id((tenant_repo.get(tenant_id, tenant_id) or {}).get("tier_id"))

        def gross_up(keyed, _price=price, _product=product, _plan=tenant_plan):
            return calculate_price(
                tenant_keyed_amount=keyed,
                currency=_price.get("currency") or "usd",
                product_type=_product.get("product_type") or "digital",
                fee_handling=_price.get("fee_handling") or "standard",
                pricing_model="customer_chooses",
                tenant_plan=_plan,
                billing_config=cached_billing_config(billing_config_loader),
            )["unit_amount"]

        charge = tips.resolve_charge(price, amount, source=source, gross_up=gross_up)
        line["unit_amount"] = charge
        line["line_amount"] = charge * int(line.get("quantity") or 1)
        # FROZEN at transaction time, because it cannot be recovered later: a typed amount exists only in
        # this request. What the tenant keeps is what a refund returns (plans/PAY_WHAT_YOU_WANT.md §5f).
        line["tip_keyed_amount"] = tips.keyed_amount(price, charge, source=source)
        if recurring:
            # A repeating tip is a Stripe SUBSCRIPTION, so the interval has to reach the session. Refused
            # rather than quietly charged once when the price never offered one: a supporter who chose
            # "monthly" and was billed a single time got a different thing than the one they picked.
            if not price.get("allow_recurring"):
                raise tips.TipAmountError("This tip jar does not offer a repeating tip.")
            interval = str(price.get("recurring_interval") or "month")
            if interval not in tips.INTERVALS:
                interval = "month"
            line["recurring"] = {"interval": interval, "interval_count": 1}
        # A tip jar is never a Stripe-synced price: the amount is decided per buyer, so checkout prices it
        # inline. Clearing the id here is belt-and-braces -- a stale synced id would charge the wrong number.
        price.pop("stripe_price_id", None)
    resolved["subtotal"] = sum(int(line.get("line_amount") or 0) for line in resolved.get("items") or [])
    return resolved


def order_bump_optional_items(offer, products_by_id, key_mode):
    """The offer's pre-purchase order bumps, resolved to Stripe optional_items (opt-in "add this?" lines on
    the hosted Checkout page). Each bump references a product + one of its prices in the order_bump context;
    Stripe forbids inline price_data for optional_items, so an un-synced bump (no matching-mode
    stripe_price_id) is SKIPPED with a warning — the dashboard guard flags it before publish
    (plans/SALES_FUNNELS.md P2). Returns [(stripe_price_id, price_id)] in order.

    Order bumps are PRE-purchase: they ride the initial Checkout session, unlike the post-purchase one-click
    upsell/downsell steps.

    The third element is the price's `shipping_surcharge` -- the postage folded into what Stripe charges
    (domain/stripe_products.charged_unit_amount). It is returned HERE, where the bump is already resolved
    to its product and price, so the session can record what the surcharge was worth without resolving the
    offer a second time.
    """
    bumps = []
    for bump in stage_opportunities(offer, STAGE_CHECKOUT):
        product = products_by_id.get(bump.get("product_id")) or {}
        price = find_price(product, bump.get("price_id") or "")
        stripe_price_id = price.get("stripe_price_id")
        product_mode = product.get("stripe_mode")
        if not stripe_price_id or (product_mode is not None and product_mode != key_mode):
            print(f"[checkout] skipping order bump product='{bump.get('product_id')}' price='{bump.get('price_id')}' "
                  f"— not Stripe-synced for mode '{key_mode}' (optional_items require a synced price)")
            continue
        bumps.append((stripe_price_id, str(bump.get("price_id") or ""), int(price.get("shipping_surcharge") or 0)))
    return bumps


# A disposable Coupon is inert once the session it was made for has gone. `redeem_by` bounds it anyway:
# a Checkout Session expires within 24 hours, so a week is generous margin and still stops the object
# living forever.
DISPOSABLE_COUPON_TTL_SECONDS = 7 * 24 * 60 * 60


def stripe_discount_materializer(api_key, stripe_account="", opener=None, now=None):
    """A callable the payload builder can use to turn a computed amount into a Stripe object.

    Passed IN rather than reached for, so `build_checkout_payload` keeps making payloads instead of making
    network calls, and a test can watch what it would have created without a key.
    """
    if not api_key:
        return None
    expires_at = int(now or time.time()) + DISPOSABLE_COUPON_TTL_SECONDS

    def materialize(*, amount_off, currency, code, tenant_id):
        return create_disposable_coupon(
            amount_off=amount_off, currency=currency, code=code, tenant_id=tenant_id,
            expires_at=expires_at, api_key=api_key, stripe_account=stripe_account, opener=opener,
        )

    return materialize


def materialize_platform_discount(coupon, resolved, coupon_code, tenant_id, materializer):
    """Evaluate a platform rule against this cart and turn the result into something Stripe accepts.

    Returns a disposable Stripe Coupon id, or "" when the rule is worth nothing here.

    **A cart below every tier is NOT a refusal.** The tenant said "spend $100 to get 20%"; a buyer with $40
    in the cart has simply not met terms they can read, and charging them full price is exactly what the
    coupon promised. That is a different situation from a coupon that has been withdrawn or used up, where
    the visitor arrived on the strength of a ticket that no longer means anything -- those still raise.
    """
    result = evaluate_coupon_rule(coupon, lines_from_resolved(resolved))
    amount_off = int(result.get("amount_off") or 0)
    if amount_off <= 0:
        logger.info("checkout: coupon %s matched no tier (%s)", coupon_code, result.get("reason"))
        return ""
    if materializer is None:
        # Nothing can create the Stripe object, so the discount cannot be applied -- and the buyer DID
        # qualify. Refusing is the honest answer; charging full price here would be the silent failure.
        raise CouponUnavailable(str(coupon_code or ""))
    try:
        return materializer(
            amount_off=amount_off,
            currency=str((resolved or {}).get("currency") or "usd").lower(),
            code=str(coupon_code or "").strip().upper(),
            tenant_id=tenant_id,
        )
    except CouponUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a qualifying buyer must not be quietly charged full price
        raise CouponUnavailable(str(coupon_code or "")) from exc


def _flatten_params(value, prefix: str = "") -> dict[str, str]:
    """Nested dict -> Stripe's bracket form encoding.

    Written once rather than per field: a shipping rate nests three deep
    (`[shipping_rate_data][delivery_estimate][minimum][unit]`), and hand-writing those keys is how one gets
    quietly misspelled — Stripe ignores an unknown parameter rather than refusing it, so a typo there does not
    fail, it just silently drops the delivery estimate.
    """
    flat: dict[str, str] = {}
    if isinstance(value, dict):
        for key, inner in value.items():
            flat.update(_flatten_params(inner, f"{prefix}[{key}]"))
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            flat.update(_flatten_params(inner, f"{prefix}[{index}]"))
    elif isinstance(value, bool):
        flat[prefix] = "true" if value else "false"
    elif value is not None:
        flat[prefix] = str(value)
    return flat


def shipping_quote(*, tenant_id, offer_id, product_id, price_id, quantity, country, mode,
                   postal_code="", region="", cart_id="", offers_repo=None, products_repo=None,
                   quotes_repo=None, carts_repo=None, secret_cipher=None):
    """What shipping would cost this cart, and where it may be sent.

    Answers the two questions a page element needs and nothing else: which countries this tenant ships to, and
    what the chosen one costs. Returns `needs` rather than a price when it cannot say -- `carrier` for a live
    zone, `box_price` for a by-box cart with no priced box, `zone` for a destination nothing serves. **Never
    zero for "unknown"**: a page that renders an unknown as "Free shipping" makes a promise the tenant did not.
    """
    from handlers.shipping import live_rates_for
    from stripe_link.domain.shipping_charges import packed_box_price, resolve_options
    from stripe_link.domain.shipping_quotes import (
        build_quote,
        cache_id,
        fingerprint as quote_fingerprint,
        is_expired as quote_expired,
        normalize_destination,
    )
    from stripe_link.domain.shipping_zones import allowed_countries as zone_primary_countries
    from stripe_link.domain.shipping_zones import offerable_countries as zone_countries
    from stripe_link.domain.shipping_zones import rule_for as zone_rule_for

    offers_repo = offers_repo or offers_repository(mode=mode)
    products_repo = products_repo or products_repository(mode=mode)
    offer = offers_repo.get(tenant_id, offer_id)
    if not offer:
        return error_response("Offer not found.", status_code=404, code="offer_not_found")

    try:
        products_by_id = load_offer_products(tenant_id, offer, products_repo)
    except PricingError as exc:
        return error_response(str(exc), code="invalid_offer")

    # `collect_shipping_for`, not `ships_at_all`: the latter only reads the offer's eligibility FLAG, so a
    # digital offer with no flag set answered "ships: True" and an element would have rendered for a download.
    # Found by calling the deployed endpoint against a second real offer -- the link-in-bio one -- after the
    # first looked correct. One example is not a check.
    if not collect_shipping_for(offer, products_by_id):
        # Nothing to ask and nothing to charge. An element rendering this must show no selector at all rather
        # than an empty dropdown.
        return json_response({"ships": False, "countries": [], "options": [], "needs": "", "mode": ""})

    config = _tenant_shipping_config(tenant_id)
    countries = zone_countries(config)

    # THE REAL CART when there is one. A listicle page keeps a server-side cart, and quoting the selected
    # price card instead of the cart meant a buyer with three things in their basket was shown one item's
    # postage -- and the number never moved as they added more (author, 2026-10-01). Same reasoning as the
    # tenant-facing estimator in P0e: the thing being shipped is the cart, not a card.
    try:
        units = max(1, int(str(quantity or "1").strip() or "1"))
    except ValueError:
        units = 1
    items = _cart_lines(tenant_id, cart_id, mode, carts_repo=carts_repo) if cart_id else []
    from_cart = bool(items)
    if not from_cart:
        chosen_product = product_id or next((str(i.get("product_id") or "")
                                             for i in (offer.get("items") or []) if i.get("product_id")), "")
        items = [{"product_id": chosen_product, "price_id": price_id, "quantity": units}]

    # What the goods come to, which is what a free-above threshold is measured against -- so on a cart page
    # it has to be the WHOLE cart, not the card the buyer happens to have selected. Summed over the same
    # lines being packed, so the two can never disagree about what is in the basket.
    merchandise = 0
    for line in items:
        product = products_by_id.get(line.get("product_id")) or {}
        wanted = str(line.get("price_id") or "")
        for price in product.get("prices") or []:
            if not wanted or str(price.get("price_id") or "") == wanted:
                merchandise += int(price.get("unit_amount") or 0) * int(line.get("quantity") or 1)
                break

    target = country if country in countries else ""
    payload = {"ships": True, "countries": countries, "country": target,
               # WHICH OF THEM THE TENANT NAMED. With a catch-all the list runs to 233 entries, and the
               # element has to tell the tenant's own destinations apart from the expansion behind them:
               # the named ones keep the tenant's order at the top, the rest get sorted by the buyer's
               # own language. The server cannot do that sorting -- it does not know the buyer's locale,
               # and these are codes, not names.
               "primary_countries": zone_primary_countries(config),
               "options": [], "needs": "", "mode": "", "source": ""}
    if not countries:
        # The offer ships, but the TENANT has configured no zones -- so there is nowhere to offer and nothing
        # to price. Distinct from `country`, which means "choose one of these": asking a buyer to pick from an
        # empty dropdown is not a question. Caught by hitting the live endpoint against a real tenant, where
        # `needs: country` alongside `countries: []` was advice nobody could act on.
        payload["needs"] = "zones"
        return json_response(payload)
    if not target:
        # A country is required to price anything -- zones ARE destinations. Returning the list without a price
        # is the honest answer to "what are my choices", and the element asks again once one is picked.
        payload["needs"] = "country"
        return json_response(payload)

    priced = packed_box_price(items, products_by_id, config, target)

    # TIER 3 -- a real carrier quote for a real address (plans/LIVE_SHIPPING_RATES.md phase 2).
    #
    # Only a LIVE zone reaches a carrier. free / flat / flat_rate_box are arithmetic over the tenant's own
    # settings and must stay free to ask, which is what makes this endpoint safe to leave public.
    destination = normalize_destination({"country": target, "postal_code": postal_code, "region": region})
    parcels, live_options, quote = [], None, None
    if zone_rule_for(config, target).get("type") == "live":
        if not destination["postal_code"]:
            # A country is not an address. Carriers price a journey between two postcodes, and asking for
            # one is the entire reason this element grew a second field.
            payload["needs"] = "postal_code"
            return json_response(payload)
        parcels = _quote_parcels(items, products_by_id, config)
        if not parcels:
            return json_response({**payload, **_unmeasured_free(tenant_id, offer_id, target)})

        fingerprint = quote_fingerprint(offer_id=offer_id, items=items, parcels=parcels,
                                        destination=destination)
        quote_id = cache_id(tenant_id=tenant_id, mode=mode, cart_fingerprint=fingerprint)
        now = int(time.time())
        quotes = quotes_repo or _shipping_quotes_repo(mode)
        # The row IS the cache. A buyer toggling services, reloading, or coming back in ten minutes reads
        # the answer we already have -- one `get`, no carrier call, no index to maintain.
        quote = _read_quote(quotes, tenant_id, quote_id)
        if quote and not quote_expired(quote, now):
            live_options = quote.get("options") or []
        else:
            rated = live_rates_for(config, tenant_id, parcels=parcels, destination=destination,
                                   secret_cipher=secret_cipher or KmsSecretCipher())
            if rated["error"]:
                # Named, never swallowed. "We could not get rates" is a truthful thing to show a buyer;
                # an empty list rendered as free shipping is not.
                payload["needs"] = "carrier"
                payload["rate_error"] = rated["error"]
                return json_response(payload)
            live_options = rated["options"]

    result = resolve_options(offer, config, country=target, merchandise_amount=merchandise,
                             item_count=units, box_amount=priced["amount"],
                             live_options=live_options)
    payload.update({
        "options": [{"label": opt["label"], "amount": opt["amount"],
                     "service_token": opt.get("service_token", ""),
                     "carrier": opt.get("carrier", ""),
                     "transit_days_min": opt.get("transit_days_min"),
                     "transit_days_max": opt.get("transit_days_max")}
                    for opt in result["options"]],
        "needs": result["needs"], "mode": result["mode"], "source": result["source"],
    })

    # A quote is minted for ANY priced answer, not only a live one: checkout reads the amount off the row
    # whatever produced it, so a flat zone gets the same tamper-proofing as a carrier rate for free.
    if result["options"] and not result["needs"]:
        payload.update(_mint_quote(
            quotes_repo, mode, tenant_id=tenant_id, offer_id=offer_id, items=items, parcels=parcels,
            destination=destination, options=result["options"], source=result["source"],
            existing=quote, currency="usd"))

    # A by-box zone whose cart cannot be packed at all is the SAME unmeasured case as a live one: there is
    # no parcel, so there is no price, so it ships free rather than erroring at the buyer.
    if result["needs"] == "box_price" and priced["reason"] == "no_dimensions":
        return json_response({**payload, **_unmeasured_free(tenant_id, offer_id, target)})

    # Why it could not be priced, for the element to show something truthful instead of a blank.
    if result["needs"] == "box_price" and priced["reason"]:
        payload["box_reason"] = priced["reason"]
    return json_response(payload)


def _unmeasured_free(tenant_id, offer_id, country):
    """What a buyer is told when the TENANT has not measured the goods: nothing, and no charge.

    plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0a. This looks like it contradicts "never render an unknown as
    free", and it refines it instead. Two different unknowns:

    - **The carrier could not be reached.** Ours, transient, fixable by retrying -- the buyer gets an error
      and a retry button, because a second attempt may well work.
    - **The tenant supplied no dimensions.** Theirs, not transient, and *a buyer cannot act on it at all*.
      Showing them an error over a measurement they have never heard of costs the tenant the sale for no
      possible benefit.

    So the buyer ships free and the TENANT is the one told -- loudly, on the Shipping and Products screens,
    and in this log line. `unmeasured` rides in the response so the dashboard's own preview can say why a
    price it expected is missing.
    """
    logger.info("shipping free: products are unmeasured", extra={
        "tenant_id": tenant_id, "offer_id": offer_id, "country": country})
    return {"options": [{"label": "Shipping", "amount": 0, "service_token": "",
                         "carrier": "", "transit_days_min": None, "transit_days_max": None}],
            "mode": "free", "needs": "", "source": "unmeasured", "unmeasured": True}


def _cart_lines(tenant_id, cart_id, mode, carts_repo=None):
    """A server cart's lines, shaped for the packer. `[]` on any failure, which falls back to the card.

    Only product lines: a service has no parcel, and `resolved_items_for_checkout` refuses them for cart
    checkout anyway. Deliberately does NOT re-resolve prices -- a quote needs quantities and products, and
    reaching for the pricing path here would make a shipping question depend on a billing one.
    """
    try:
        from stripe_link.repositories.documents import carts_repository

        repo = carts_repo or carts_repository(mode=mode)
        cart = repo.get(tenant_id, cart_id) or {}
    except Exception as exc:  # noqa: BLE001 - a cart that will not read costs a better quote, not the page
        logger.warning("shipping quote: cart unreadable",
                       extra={"tenant_id": tenant_id, "cart_id": cart_id,
                              "error": f"{type(exc).__name__}: {exc}"})
        return []
    lines = []
    for line in cart.get("line_items") or []:
        product_id = str((line or {}).get("product_id") or "").strip()
        if not product_id:
            continue
        lines.append({"product_id": product_id,
                      "price_id": str(line.get("price_id") or ""),
                      "quantity": max(1, int(line.get("quantity") or 1))})
    return lines


def _quote_parcels(items, products_by_id, config):
    """The cart as parcels, packed exactly the way the label flow packs it.

    Same `packable_items` + `pack` + `tenant_boxes` the tenant's own rate preview uses, so a buyer is never
    quoted for a parcel the tenant would not actually post.
    """
    from stripe_link.domain.shipping import packable_items, tenant_boxes
    from stripe_link.domain.shipping_packing import pack

    return pack(packable_items(items, products_by_id), tenant_boxes(config or {}))


def _shipping_quotes_repo(mode):
    """The quote store, or None. **Constructing it is itself allowed to fail.**

    The guard is around the FACTORY CALL and not only around the reads, because that is where this has
    gone wrong before: `_tenant_shipping_config`'s first version called a factory with a keyword it did not
    accept, and a try that only wrapped the query would have let the TypeError through. A buyer's page must
    survive a missing table, a missing env var and a bad signature alike -- all three cost a carrier call,
    none of them cost a sale.
    """
    try:
        from stripe_link.repositories.documents import shipping_quotes_repository

        return shipping_quotes_repository(mode=mode)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shipping quote store unavailable",
                       extra={"error": f"{type(exc).__name__}: {exc}"})
        return None


def _read_quote(quotes, tenant_id, quote_id):
    """Never fatal. A quote cache that cannot be read costs a carrier call, not a sale."""
    if quotes is None:
        return None
    try:
        return quotes.get(tenant_id, quote_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shipping quote unreadable", extra={"tenant_id": tenant_id, "quote_id": quote_id,
                                                           "error": f"{type(exc).__name__}: {exc}"})
        return None


def _mint_quote(quotes_repo, mode, *, tenant_id, offer_id, items, parcels, destination, options,
                source, existing, currency):
    """Persist what we just offered, and hand the buyer its id.

    Returns the fields to merge into the response. On ANY storage failure it returns `{}` -- the buyer
    still sees prices and still checks out; checkout simply falls back to re-deriving from zones, which is
    exactly today's behaviour. A shipping quote that cannot be saved must not cost a sale.
    """
    from stripe_link.domain.shipping_quotes import (
        build_quote,
        cache_id,
        fingerprint as quote_fingerprint,
        is_expired as quote_expired,
    )

    now = int(time.time())
    fingerprint = quote_fingerprint(offer_id=offer_id, items=items, parcels=parcels,
                                    destination=destination)
    quote_id = cache_id(tenant_id=tenant_id, mode=mode, cart_fingerprint=fingerprint)
    if existing and not quote_expired(existing, now) and existing.get("quote_id") == quote_id:
        return {"quote_id": quote_id, "expires_at": int(existing.get("expires_at") or 0)}
    record = build_quote(quote_id=quote_id, tenant_id=tenant_id, mode=mode, offer_id=offer_id,
                         destination=destination, parcels=parcels, items=items, options=options,
                         source=source, currency=currency, now=now)
    store = quotes_repo or _shipping_quotes_repo(mode)
    if store is None:
        return {}
    try:
        # `put(document)`, one argument -- the repository reads tenant_id off the document itself. Passing
        # a tenant positionally raised on every real call while every test passed, because the test
        # doubles implemented the signature this code assumed rather than the one the repository has.
        store.put(record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shipping quote not saved", extra={"tenant_id": tenant_id,
                                                          "error": f"{type(exc).__name__}: {exc}"})
        return {}
    return {"quote_id": quote_id, "expires_at": record["expires_at"]}


def _shipping_from_quote(*, quote_id, service_token, tenant_id, mode, offer, items, products_by_id,
                         shipping_config, secret_cipher, allowed_countries, quotes_repo=None):
    """The one shipping option the buyer already chose, re-derived from the server's own record.

    plans/LIVE_SHIPPING_RATES.md phase 4. Returns `{option, quote_id, destination, reason}` with `option`
    None whenever the quote may not be used -- the caller then falls back to the zone path, which is what a
    buyer who never touched the element gets.

    **The amount is never an input.** It is read off the stored row, so the worst a tampered query string
    can do is name a service the quote does not hold, which lands on the quote's own cheapest option.

    The destination comes from the ROW rather than the request, because the row was written by this server
    and the request was not. The country is still cross-checked against the countries Stripe will be told
    to accept: a price for one country and an address field open to another is the one combination that
    could charge the wrong postage without anybody tampering.
    """
    from stripe_link.domain.shipping_quotes import (
        FALLBACK,
        REQUOTE,
        USE_CHEAPEST,
        fingerprint as quote_fingerprint,
        validate,
    )

    blank = {"option": None, "quote_id": "", "destination": {}, "reason": ""}
    if not quote_id:
        return dict(blank, reason="no_quote")
    quote = _read_quote(quotes_repo or _shipping_quotes_repo(mode), tenant_id, quote_id)
    if not quote:
        return dict(blank, reason="missing")

    destination = quote.get("destination") or {}
    country = str(destination.get("country") or "")
    if allowed_countries and country not in allowed_countries:
        # A quote for somewhere this session will not accept an address for. Refusing is the safe half of
        # the address-mismatch problem -- the half Stripe DOES let us close.
        return dict(blank, reason="country_not_allowed")

    parcels = _quote_parcels(items, products_by_id, shipping_config)
    cart_fingerprint = quote_fingerprint(offer_id=offer.get("offer_id") or "", items=items,
                                         parcels=parcels, destination=destination)
    verdict = validate(quote, tenant_id=tenant_id, mode=mode, offer_id=offer.get("offer_id") or "",
                       cart_fingerprint=cart_fingerprint, service_token=service_token,
                       now=int(time.time()))

    if verdict["action"] == FALLBACK:
        logger.info("checkout ignored a shipping quote",
                    extra={"tenant_id": tenant_id, "quote_id": quote_id, "reason": verdict["reason"]})
        return dict(blank, reason=verdict["reason"])

    if verdict["action"] == REQUOTE:
        # Expired, or the cart moved under the buyer. Asking the carrier again beats charging a number
        # that has rotted -- and the buyer still sees the final figure on Stripe's own page before they
        # confirm, so a changed price is disclosed rather than hidden.
        refreshed = _requote(tenant_id=tenant_id, mode=mode, offer=offer, items=items,
                             products_by_id=products_by_id, parcels=parcels, destination=destination,
                             shipping_config=shipping_config, secret_cipher=secret_cipher,
                             service_token=service_token, quotes_repo=quotes_repo)
        logger.info("checkout re-quoted shipping",
                    extra={"tenant_id": tenant_id, "quote_id": quote_id, "reason": verdict["reason"],
                           "repriced": bool(refreshed["option"])})
        return refreshed or dict(blank, reason=verdict["reason"])

    if verdict["action"] == USE_CHEAPEST:
        logger.info("checkout fell back to the quote's cheapest service",
                    extra={"tenant_id": tenant_id, "quote_id": quote_id,
                           "requested": service_token, "reason": verdict["reason"]})

    option = verdict["option"]
    if not option:
        return dict(blank, reason=verdict["reason"] or "no_option")
    return {"option": option, "quote_id": str(quote.get("quote_id") or quote_id),
            "destination": destination, "reason": verdict["reason"]}


def _requote(*, tenant_id, mode, offer, items, products_by_id, parcels, destination, shipping_config,
             secret_cipher, service_token, quotes_repo=None):
    """One carrier call to replace a quote that no longer describes this purchase.

    Mints a NEW row rather than mutating the old one: the quote a buyer agreed to is immutable, and an
    order records which quote it actually transacted on (author, 2026-10-01).

    Falls back to the zone path on any failure. A carrier that cannot be reached at the pay button must
    not take the sale down with it.
    """
    from handlers.shipping import live_rates_for
    from stripe_link.domain.shipping_charges import packed_box_price, resolve_options
    from stripe_link.domain.shipping_quotes import cheapest_option, option_for
    from stripe_link.domain.shipping_zones import rule_for as zone_rule_for

    blank = {"option": None, "quote_id": "", "destination": destination, "reason": "requote_failed"}
    country = destination.get("country") or ""
    live_options = None
    if zone_rule_for(shipping_config, country).get("type") == "live":
        rated = live_rates_for(shipping_config, tenant_id, parcels=parcels, destination=destination,
                               secret_cipher=secret_cipher or KmsSecretCipher())
        if rated["error"]:
            return blank
        live_options = rated["options"]

    priced = packed_box_price(items, products_by_id, shipping_config, country)
    result = resolve_options(offer, shipping_config, country=country,
                             merchandise_amount=0, item_count=max(1, len(items or [])),
                             box_amount=priced["amount"], live_options=live_options)
    if not result["options"] or result["needs"]:
        return blank
    fresh = _mint_quote(quotes_repo, mode, tenant_id=tenant_id, offer_id=offer.get("offer_id") or "",
                        items=items, parcels=parcels, destination=destination,
                        options=result["options"], source=result["source"], existing=None,
                        currency="usd")
    chosen = option_for({"options": result["options"]}, service_token)         or cheapest_option({"options": result["options"]})
    return {"option": chosen, "quote_id": fresh.get("quote_id", ""), "destination": destination,
            "reason": "requoted"}


def collect_shipping_for(offer, products_by_id):
    """Whether this offer needs a shipping config read at all, so a digital sale pays for no lookup."""
    from stripe_link.domain.shipping_charges import ships_at_all

    if not ships_at_all(offer):
        return False
    for item in (offer.get("items") or []):
        product = products_by_id.get(str(item.get("product_id") or ""))
        fulfillment = (product or {}).get("fulfillment") or {}
        if fulfillment.get("requires_shipping") or (product or {}).get("product_type") == "physical":
            return True
    return False


def _tenant_shipping_config(tenant_id):
    """The tenant's zones and services. NEVER fatal, and never a blocker.

    A settings table that blinked must not refuse a sale. With no config the payload falls back to the
    hardcoded allowed countries and charges nothing for shipping, which is exactly the behaviour every
    tenant had before zones existed.
    """
    try:
        from stripe_link.repositories.documents import RepositoryError, shipping_config_repository

        return shipping_config_repository().get(tenant_id) or {}
    except Exception as exc:  # noqa: BLE001
        # Broad, and the reason is stated rather than assumed: this runs in the BUYER's path, and a shipping
        # config that cannot be read must never cost a sale. But broad catches hide bugs -- the first version
        # of this function called the factory with a `mode=` keyword it does not accept, and this guard would
        # have swallowed that TypeError, silently disabling shipping charges for every tenant while looking
        # like a working fallback. So the failure is LOGGED with its exception type, and a test asserts the
        # fallback shape, because "it silently worked" is how the other four went unnoticed.
        logger.warning("checkout: shipping config unreadable, no shipping charged",
                       extra={"tenant_id": tenant_id, "error": f"{type(exc).__name__}: {exc}"})
        return {}


def build_checkout_payload(
    *,
    tenant_id,
    offer,
    products_by_id,
    resolved,
    success_url,
    cancel_url,
    page_id="",
    fee_context=None,
    apply_application_fee=False,
    bnpl_payment_method_types=None,
    coupon_code="",
    mode="test",
    coupons_repo=None,
    grants_repo=None,
    discount_materializer=None,
    shipping_config=None,
    ship_to_country="",
    shipping_quote_id="",
    shipping_service="",
    secret_cipher=None,
    quotes_repo=None,
):
    checkout = offer.get("checkout") or {}
    # The session's mode follows the lines it actually carries, in BOTH directions.
    #
    # It used to start from the offer's stored checkout.mode and only ever UPGRADE to subscription. That is
    # fine while an offer sells one kind of price, and wrong the moment it offers a choice: an offer stored
    # as "subscription" whose buyer picks the one-time option would send Stripe a subscription session with
    # no recurring line, which Stripe refuses outright.
    #
    # resolve_offer_item and resolve_service_offer_item both stamp the line through recurring_terms(), which
    # is gated on the price's own pricing_model -- so the resolved lines are the authority on what is being
    # charged, and the stored mode is only ever a stale copy of it.
    mode = "subscription" if any((item or {}).get("recurring") for item in resolved.get("items") or []) else "payment"
    # The Stripe key was chosen from the offer's stripe_mode, so that IS the active key's mode. A stored
    # stripe_price_id only belongs to the account of the same mode — if a product's own stripe_mode disagrees
    # (a wrong-environment id from a bad copy or manual tinkering), we must NOT send it (it 500s at Stripe).
    key_mode = "live" if offer.get("stripe_mode") == "live" else "test"
    payload = {
        "mode": "subscription" if mode == "subscription" else "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "billing_address_collection": "required",
        "metadata[tenant_id]": tenant_id,
        "metadata[offer_id]": offer.get("offer_id") or "",
    }
    # A coupon carried in from a campaign page: the visitor tapped a ticket that already named the code, so
    # applying it here means the discount is on the page they land on instead of behind a field they have to
    # find and retype (plans/COUPON_ELEMENT.md).
    #
    # Stripe REFUSES `discounts` and `allow_promotion_codes` together, so a pre-applied coupon wins and the
    # manual field is dropped for that one checkout. That is the right way round: the buyer already has a
    # better code than anything they would type.
    #
    # A TARGETED code is tried first, and by a direct read: it is one recipient's own code, so it is not in
    # the tenant's shared list and the shared lookup would refuse it. It also drags its customer along --
    # see `resolve_targeted_grant`.
    offer_id_for_coupon = str((offer or {}).get('offer_id') or '')
    applied_promotion_code, grant_customer_id = resolve_targeted_grant(
        coupon_code, tenant_id, mode, grants_repo, coupons_repo, offer_id=offer_id_for_coupon,
    )
    # A rule Stripe has no vocabulary for -- a spend ladder, today (Option B). We work out what it is worth
    # against THIS cart and hand Stripe the number as a one-checkout Coupon.
    applied_coupon_id = ""
    if not applied_promotion_code:
        platform_coupon = resolve_platform_coupon(
            coupon_code, tenant_id, mode, coupons_repo, offer_id=offer_id_for_coupon,
        )
        if platform_coupon is not None:
            applied_coupon_id = materialize_platform_discount(
                platform_coupon, resolved, coupon_code, tenant_id, discount_materializer,
            )
        else:
            applied_promotion_code = resolve_campaign_promotion_code(
                coupon_code, tenant_id, mode, coupons_repo, offer_id=offer_id_for_coupon,
            )
    if applied_promotion_code:
        payload["discounts[0][promotion_code]"] = applied_promotion_code
    elif applied_coupon_id:
        payload["discounts[0][coupon]"] = applied_coupon_id
    elif checkout.get("allow_promotion_codes") is True:
        payload["allow_promotion_codes"] = "true"
    if applied_promotion_code or applied_coupon_id:
        # Carried so the webhook can mark WHICH code was used. Reading it back off the session means
        # expanding the discount object; the code itself is what the tenant's campaign view is keyed on.
        payload["metadata[coupon_code]"] = str(coupon_code or "").strip().upper()
    if grant_customer_id:
        payload["customer"] = grant_customer_id

    collect_shipping = False
    shippable_units = 0
    first_product_id = ""
    first_price_id = ""
    first_product_name = ""
    service_items = []
    for index, item in enumerate(resolved.get("items") or []):
        prefix = f"line_items[{index}]"
        if item.get("kind") == "service" or item.get("service_id"):
            # First-class service line: no product doc; price comes straight from the resolved item.
            service_items.append(item)
            payload[f"{prefix}[price_data][currency]"] = item.get("currency") or "usd"
            payload[f"{prefix}[price_data][unit_amount]"] = str(int(item.get("unit_amount") or 0))
            payload[f"{prefix}[price_data][product_data][name]"] = item.get("label") or item.get("product_name") or "Service"
            # A recurring service line MUST carry its interval: the session is in subscription mode because
            # this line is recurring, and Stripe rejects a subscription line whose price_data has no
            # `recurring` block. The product branch below has always done this; the service branch did not,
            # so flipping the mode without it would have produced a 400 from Stripe rather than a charge.
            service_recurring = item.get("recurring") or {}
            if service_recurring:
                payload[f"{prefix}[price_data][recurring][interval]"] = service_recurring.get("interval") or "month"
                payload[f"{prefix}[price_data][recurring][interval_count]"] = str(
                    int(service_recurring.get("interval_count") or 1))
            payload[f"{prefix}[quantity]"] = str(int(item.get("quantity") or 1))
            if index == 0:
                first_product_name = item.get("product_name") or "Service"
            continue
        product = products_by_id.get(item.get("product_id")) or {}
        price = find_price(product, item.get("price_id") or "")
        if index == 0:
            first_product_id = item.get("product_id") or ""
            first_price_id = item.get("price_id") or ""
            first_product_name = product.get("name") or item.get("product_name") or "Product"
        stripe_price_id = price.get("stripe_price_id")
        # Only honor the id when the product's mode matches the active key's. Absent stripe_mode = trust it
        # (legacy docs); an EXPLICIT mismatch = a wrong-env id, so ignore it and price inline instead.
        product_mode = product.get("stripe_mode")
        if stripe_price_id and product_mode is not None and product_mode != key_mode:
            print(f"[checkout] ignoring cross-mode stripe_price_id for product '{item.get('product_id')}' "
                  f"(product stripe_mode={product_mode}, active key mode={key_mode}); pricing inline instead")
            stripe_price_id = ""
        if stripe_price_id:
            payload[f"{prefix}[price]"] = stripe_price_id
        else:
            payload[f"{prefix}[price_data][currency]"] = item.get("currency") or "usd"
            payload[f"{prefix}[price_data][unit_amount]"] = str(int(item.get("unit_amount") or 0))
            payload[f"{prefix}[price_data][product_data][name]"] = product.get("name") or item.get("product_name") or "Product"
            if product.get("description"):
                payload[f"{prefix}[price_data][product_data][description]"] = product.get("description")
            # The resolved line wins: a tip's interval is decided per checkout, and the product's price
            # document carries none.
            recurring = item.get("recurring") or price.get("recurring") or {}
            if recurring:
                payload[f"{prefix}[price_data][recurring][interval]"] = recurring.get("interval") or "month"
                payload[f"{prefix}[price_data][recurring][interval_count]"] = str(int(recurring.get("interval_count") or 1))
        payload[f"{prefix}[quantity]"] = str(int(item.get("quantity") or 1))
        if product.get("product_type") == "physical":
            collect_shipping = True
            # Only PHYSICAL units count toward per-item shipping: a cart of three shirts and an ebook is
            # three things to post, not four (domain/shipping_charges.resolve_amount).
            shippable_units += int(item.get("quantity") or 1)

    # Booking metadata so the webhook can fan out 1..N appointments + no_booking invoice lines
    # (STORY-2.3). service_lines carries ALL service lines; service_booking_mode coordinates grouping.
    # (Stripe caps a metadata value at 500 chars — fine for the handful of services a real offer holds.)
    if service_items:
        first = service_items[0]
        payload["metadata[service_booking_mode]"] = str(offer.get("service_booking_mode") or "single_visit")
        payload["metadata[service_lines]"] = json.dumps([
            {
                "service_id": s.get("service_id") or "",
                "price_id": s.get("price_id") or "",
                "service_name": s.get("product_name") or s.get("label") or "Service",
                "unit_amount": int(s.get("unit_amount") or 0),
                "currency": s.get("currency") or "usd",
                "quantity": int(s.get("quantity") or 1),
                "booking_flow": s.get("booking_flow") or "pay_then_book",
                "fulfillment_mode": s.get("fulfillment_mode") or "scheduled",
                "duration_minutes": int(s.get("duration_minutes") or 0),
                "default_fulfiller_id": s.get("default_fulfiller_id") or "",
                # A RECURRING service grants booking credits per cycle instead of an appointment at
                # purchase (plans/RECURRING_SERVICES.md §4b). The webhook cannot re-derive this -- it sees a
                # Stripe session, not the offer -- so it travels with the line, like everything else here.
                "recurring": bool(s.get("recurring")),
                "bookings_per_cycle": int(s.get("bookings_per_cycle") or 0),
            }
            for s in service_items
        ], separators=(",", ":"))
        # Routing hint for the webhook dispatch (first line).
        payload["metadata[service_id]"] = first.get("service_id") or ""
        payload["metadata[service_price_id]"] = first.get("price_id") or ""
        payload["metadata[booking_flow]"] = first.get("booking_flow") or "pay_then_book"
        payload["metadata[service_name]"] = first.get("product_name") or first.get("label") or "Service"

    # SUBSCRIPTION mode collects an address too. It was restricted to `payment`, which meant a recurring
    # physical product -- a monthly tub of creatine -- never asked the buyer where to send it, so neither
    # the first order nor any renewal had a destination and the whole thing was unshippable by design
    # (found 2026-09-25: six subscription_cycle orders in prod, every one with no address).
    if collect_shipping and payload["mode"] in {"payment", "subscription"}:
        # WHERE the tenant will ship, from their own zones rather than a platform guess. Hardcoded US and CA
        # until now, which meant a tenant who configured a UK zone still could not receive a UK order -- a
        # rule they wrote and the platform ignored (plans/SHIPPING_ELEMENT.md). Falls back to the old pair
        # when no zones are configured, which is every tenant until they set some: an empty allowed list
        # would take checkout down, and a silent behaviour change for tenants who configured nothing is not
        # an improvement.
        destinations = zone_allowed_countries(shipping_config or {}) or ["US", "CA"]
        # A DECLARED destination narrows the list to itself. The address is still collected -- a parcel needs a
        # street -- but the buyer cannot switch COUNTRY at the pay button, which is what would otherwise
        # invalidate the price we quoted them. Within one country, tiers 1 and 2 are destination-independent,
        # so the rest of the address cannot move the number.
        #
        # Ignored unless the tenant actually ships there: a country typed into a URL is not a zone.
        #
        # Tested against EVERYTHING the tenant ships to, catch-all included -- not against `destinations`,
        # which is deliberately the narrow Stripe-safe list. A buyer who picked Mexico from the element's
        # dropdown has named a country the tenant's "Everywhere else" zone really does serve, and the
        # element has already rated it; refusing it here would collect the declaration and then ignore it.
        # Once declared there is one destination, so the unanimity problem that keeps the undeclared list
        # narrow does not arise.
        if ship_to_country and ship_to_country in zone_offerable_countries(shipping_config or {}):
            destinations = [ship_to_country]
        for index, country in enumerate(destinations):
            payload[f"shipping_address_collection[allowed_countries][{index}]"] = country
        # A PHONE NUMBER, because a carrier may need one to deliver. Couriers call the recipient for a
        # failed delivery, a gate code or a signature, and the number has to have been collected by then --
        # `destination_address_from_session` and the label buyer have both carried `customer.phone` since
        # they were written, but hosted Checkout never asked for it, so it was always empty.
        #
        # ONLY where there is a parcel. Stripe's hosted Checkout has no optional mode for this field: when
        # collection is on the buyer must fill it in, so enabling it everywhere would put a required field
        # in front of every download and tip for no delivery that could ever need it.
        payload["phone_number_collection[enabled]"] = "true"

    # What shipping COSTS the buyer (plans/SHIPPING_CHARGES.md phase 6). The last thing wired, deliberately:
    # Checkout is the one consumer that cannot be corrected after the fact, because a session that quoted the
    # wrong postage has already told someone a price.
    #
    # PAYMENT MODE ONLY, and that is a decision rather than an oversight. Two unresolved things gate
    # subscriptions:
    #   1. Whether the chosen shipping recurs on every invoice or applies only to the first is UNVERIFIED
    #      against Stripe's current behaviour. A monthly box needs postage each cycle; a one-shipment
    #      subscription does not, and guessing wrong either double-charges a buyer every month or ships
    #      eleven parcels free.
    #   2. A subscription fee is a PERCENT, not an amount, so with buyer-chosen shipping the absolute
    #      platform fee cannot be made exact -- the denominator has to assume which option they pick. See
    #      `fees.application_fee_percent`.
    # A subscription therefore still collects an address (it must, to ship at all) and charges nothing for
    # postage, which is exactly today's behaviour and is safe.
    # Written as a set to read in parallel with the address-collection condition above: an address is
    # collected in BOTH modes, postage is charged in ONE.
    if collect_shipping and payload["mode"] in {"payment"}:
        # What the buyer is charged. `checkout_shipping` resolves the tenant's ZONES through the offer's
        # override -- but only offers a price when every allowed destination agrees on one, because Stripe
        # fixes this list when the session opens and never asks us again. Per-destination pricing needs the
        # buyer's country BEFORE the session, which is the Shipping Element's job (phase 5).
        # A QUOTE the buyer already chose from, when the shipping element asked (phase 4 of
        # plans/LIVE_SHIPPING_RATES.md). The amount comes off the server's own row -- the browser sends a
        # quote id and a service token and never an amount -- so the only thing a tampered parameter can
        # do is name a service that is not in the quote, which falls back to the quote's own cheapest.
        # `key_mode`, NOT `mode`: `mode` is rebound above to the SESSION mode (payment/subscription),
        # while a quote is stamped with the STRIPE mode (test/live) it was rated under. Passing `mode`
        # here made every quote fail validation as a mode mismatch and silently fall back to the zone
        # path -- which for a live zone means no shipping charge at all, the exact bug this work exists
        # to fix. Caught by the integrity tests rather than in production.
        quoted = _shipping_from_quote(
            quote_id=shipping_quote_id, service_token=shipping_service, tenant_id=tenant_id,
            mode=key_mode,
            offer=offer, items=resolved.get("items") or [], products_by_id=products_by_id,
            shipping_config=shipping_config or {}, secret_cipher=secret_cipher,
            allowed_countries=destinations, quotes_repo=quotes_repo)
        if quoted["option"]:
            options = [quoted["option"]]
            payload["metadata[shipping_quote_id]"] = quoted["quote_id"]
            payload["metadata[shipping_service]"] = str(quoted["option"].get("service_token") or "")
            # BOTH postal codes become answerable later: this is the one we quoted, and the webhook reads
            # the one Stripe actually collected. A variance that cannot name the two addresses is an
            # assertion rather than an explanation (author, 2026-10-01).
            payload["metadata[shipping_postal_code]"] = quoted["destination"].get("postal_code", "")
            payload["metadata[shipping_quoted_amount]"] = str(int(quoted["option"].get("amount") or 0))
        else:
            # No quote, or one we may not use. Exactly the path a buyer who never touched the element takes.
            decision = checkout_shipping(
                offer, shipping_config or {},
                merchandise_amount=int(resolved.get("subtotal") or 0),
                item_count=max(1, shippable_units),
                # The cart itself, so a by-box zone can be priced from the boxes it actually packs into.
                items=resolved.get("items") or [],
                products_by_id=products_by_id,
                # One destination when the buyer declared one, so zones that disagree no longer force us to
                # charge nothing -- there is only one zone to satisfy.
                countries=destinations,
            )
            options = decision["options"]
            if decision["reason"]:
                # Said out loud rather than silently shipping free: a tenant whose zones are not being
                # charged needs to know which of their own settings stopped it.
                logger.info("checkout shipping not charged", extra={
                    "tenant_id": tenant_id, "offer_id": offer.get("offer_id"),
                    "reason": decision["reason"], "quote_reason": quoted["reason"]})
        for index, option in enumerate(
                stripe_option_payload(options, currency=resolved.get("currency", "usd"))):
            for key, value in _flatten_params(option).items():
                payload[f"shipping_options[{index}]{key}"] = value
    # Pre-purchase order bumps → Stripe optional_items (opt-in on the hosted page; charged in the same
    # session if the buyer adds them). plans/SALES_FUNNELS.md P2.
    order_bumps = order_bump_optional_items(offer, products_by_id, key_mode)
    for index, (stripe_price_id, _price_id, _surcharge) in enumerate(order_bumps):
        payload[f"optional_items[{index}][price]"] = stripe_price_id
        payload[f"optional_items[{index}][quantity]"] = "1"

    # A tip is a different kind of transaction and has to be recognisable as one downstream: the receipt
    # carries a manage link only for a repeating tip, and the refund rule reads the keyed amount.
    tip_line = next((item for item in resolved.get("items") or [] if item.get("tip_keyed_amount")), None)
    if tip_line:
        payload["metadata[tip]"] = "1"
        payload["metadata[tip_keyed_amount]"] = str(int(tip_line.get("tip_keyed_amount") or 0))
        if tip_line.get("recurring"):
            interval = str((tip_line.get("recurring") or {}).get("interval") or "month")
            payload["metadata[tip_recurring]"] = interval
            # Session metadata does NOT reach the subscription, and a renewal invoice arrives months later
            # carrying only what the SUBSCRIPTION knows. Without this the webhook cannot tell a tip renewal
            # from any other invoice, and the supporter's next manage link never gets minted.
            payload["subscription_data[metadata][tip]"] = "1"
            payload["subscription_data[metadata][tip_recurring]"] = interval
            payload["subscription_data[metadata][tenant_id]"] = tenant_id
            payload["subscription_data[metadata][tip_keyed_amount]"] = str(int(tip_line.get("tip_keyed_amount") or 0))

    # A TRIAL, when the subscribing line carries one. Trials belong to the SUBSCRIPTION, never to the Stripe
    # Price -- which is why they are read off the resolved line here rather than baked in at sync time.
    if payload["mode"] == "subscription":
        trial_line = next(
            (item for item in resolved.get("items") or []
             if item.get("recurring") and int(item.get("trial_period_days") or 0) > 0),
            None,
        )
        if trial_line:
            payload["subscription_data[trial_period_days]"] = str(int(trial_line["trial_period_days"]))
            trial_price = int(trial_line.get("trial_price") or 0)
            if trial_price > 0:
                # A PAID trial. Stripe has no such thing -- its trial is free by definition, and Checkout
                # always renders "X days free" with no way to reword it -- so the fee is charged as its own
                # one-time line beside the subscription. Same shape the legacy builder used
                # (stripe-cart create_checkout.py, "Added paid trial line item").
                #
                # Indexed at the item COUNT: every resolved item consumes its own line index above, services
                # included, so this is the first free one and cannot overwrite a real line.
                index = len(resolved.get("items") or [])
                prefix = f"line_items[{index}]"
                payload[f"{prefix}[price_data][currency]"] = str(trial_line.get("currency") or "usd")
                payload[f"{prefix}[price_data][unit_amount]"] = str(trial_price)
                payload[f"{prefix}[price_data][product_data][name]"] = (
                    f"{trial_line.get('product_name') or first_product_name or 'Subscription'} trial")
                payload[f"{prefix}[quantity]"] = "1"

    payload["metadata[clientID]"] = tenant_id
    payload["metadata[client_id]"] = tenant_id
    payload["metadata[product_id]"] = first_product_id
    payload["metadata[price_id]"] = first_price_id
    payload["metadata[product_name]"] = first_product_name
    payload["metadata[page_id]"] = str(page_id or "")
    payload["metadata[funnel_id]"] = ""
    # The bumps' STRIPE price ids offered, so fulfillment can flag which completed line items were bumps
    # (what was actually purchased comes from the session's line_items). plans/SALES_FUNNELS.md P2.
    payload["metadata[order_bump_ids]"] = ",".join(sid for sid, _price_id, _surcharge in order_bumps)
    # ...and how much of each bump's price is POSTAGE, so the order can record it as shipping revenue
    # rather than product revenue. Stamped here because this is the last moment both facts are in hand:
    # the webhook sees Stripe line items, which carry one amount and no idea what it is made of.
    #
    # Written only when some bump actually carries a surcharge, so the overwhelming majority of sessions
    # (digital offers, bumps that need no extra postage) carry no extra metadata key at all.
    bump_postage = ",".join(f"{sid}:{surcharge}" for sid, _price_id, surcharge in order_bumps if surcharge)
    if bump_postage:
        payload["metadata[order_bump_shipping]"] = bump_postage

    # Mirror the session's identifying metadata onto the SUBSCRIPTION, so every future renewal invoice can
    # say what it is for. A renewal is a fresh order the tenant must fulfil, and the cycle invoice Stripe
    # generates carries only what the subscription carries -- without this it arrives anonymous, and the
    # renewal can be recorded but not attributed to the offer or page that sold it.
    #
    # Only set for subscriptions, and only for keys that exist: Stripe rejects an empty metadata VALUE far
    # less gracefully than a missing key. Tips set their own subscription metadata above and are unaffected.
    if payload["mode"] == "subscription":
        for key in ("tenant_id", "clientID", "client_id", "offer_id", "page_id",
                    "product_id", "price_id", "product_name", "product_type", "tenant_plan"):
            value = payload.get(f"metadata[{key}]")
            if value:
                payload.setdefault(f"subscription_data[metadata][{key}]", value)
    payload["metadata[post_checkout_entry]"] = "thank_you"

    # WHICH SILO created this (plans/SILO_MODEL.md S1). One prod-shaped deployment can serve several silos
    # and a tenant may live in more than one, so nothing about the connected account says where an event
    # came from -- the object has to carry it. Write-only for now: nothing reads this yet, which is what
    # makes it safe to ship ahead of the resolver.
    #
    # Omitted rather than guessed when the silo is unknown. A wrong stamp is worse than none: the read
    # rule (unstamped means sandbox, never production) is written down in exactly one place, and a guess
    # here would quietly bypass it.
    silo = current_silo()
    if silo:
        payload["metadata[silo]"] = silo
        # Renewals are generated by Stripe months later and carry none of OUR metadata, so the
        # subscription has to hold it -- the same reason tip_recurring is copied here.
        if payload.get("mode") == "subscription":
            payload.setdefault("subscription_data[metadata][silo]", silo)
        else:
            # And the session's own PaymentIntent, because **Stripe does not propagate session metadata
            # to it** -- observed on real objects 2026-09-23, not taken from the docs: three transactions
            # produced sessions carrying `silo` whose PaymentIntents carried nothing.
            #
            # It matters for the events that name a CHARGE rather than a session -- a refund, a dispute.
            # Those resolve today by asking whether this silo holds the order, which works until the order
            # is in the OTHER silo. That is not hypothetical: one purchase is already split, its session
            # order in production and its downsell in sandbox (plans/SILO_MODEL.md, Evidence).
            #
            # `payment_intent_data` is payment-mode only; subscription mode routes through
            # subscription_data above, and a RENEWAL's PaymentIntent is created by Stripe from the
            # subscription, so nothing here reaches it.
            payload.setdefault("payment_intent_data[metadata][silo]", silo)

    # One-click post-purchase upsells charge OFF-SESSION against the buyer's saved card, so when this offer has
    # a post-purchase opportunity the checkout must create a customer and save the payment method for reuse
    # (otherwise the upsell page has no customer to charge). Subscription mode already creates a customer +
    # saves the PM; only payment mode needs these flags (plans/OFFER_MODEL_REDESIGN.md §6).
    if payload.get("mode") == "payment" and stage_opportunities(offer, STAGE_POST_PURCHASE):
        # Stripe REFUSES customer_creation alongside an explicit customer, and a targeted coupon supplies
        # one. Nothing is lost: the customer already exists, which is the whole point of the flag.
        if not payload.get("customer"):
            payload["customer_creation"] = "always"
        # Save the PM for the one-click upsell, but SCOPE it to card/link. A top-level
        # payment_intent_data[setup_future_usage] is REJECTED by BNPL methods (Klarna/Afterpay/Zip) —
        # "setup_future_usage is unsupported for payment method afterpay_clearpay" — which 400s the whole
        # Checkout Session whenever we also offer installments, silently dropping every method to the account
        # defaults. Per-method options keep card/link reusable while letting BNPL coexist; BNPL buyers simply
        # aren't eligible for the one-click upsell (they can't be charged off-session anyway).
        payload["payment_method_options[card][setup_future_usage]"] = "off_session"
        payload["payment_method_options[link][setup_future_usage]"] = "off_session"

    if fee_context:
        payload["metadata[product_type]"] = fee_context.get("product_type", "")
        payload["metadata[tenant_plan]"] = fee_context.get("tenant_plan", "")
        platform_fee = int(fee_context.get("platform_fee") or 0)
        subtotal = int(fee_context.get("subtotal") or 0)
        if apply_application_fee and platform_fee > 0 and subtotal > 0:
            if payload["mode"] == "subscription":
                # The denominator is everything the BUYER is charged, not merchandise alone. Stripe applies
                # `application_fee_percent` to each invoice's whole total, so once a shipping line exists a
                # percent computed against the merchandise subtotal would charge a fee on postage -- which
                # `domain/fees.FEE_APPLIES_TO_SHIPPING` says is exempt. See that module for the full trap.
                charged_total = subtotal + int(fee_context.get("shipping_amount") or 0)
                percent = application_fee_percent(platform_fee, charged_total)
                payload["subscription_data[application_fee_percent]"] = f"{percent:.2f}"
            else:
                payload["payment_intent_data[application_fee_amount]"] = str(platform_fee)

    # BNPL / installment methods the tenant enabled + that are capability-active + currency-eligible for this
    # session (plans/BNPL_PAYMENT_METHODS.md). Setting payment_method_types is explicit, so we must include card;
    # only override when there's at least one BNPL method to add, and only for one-time payment mode with NO
    # recurring line (BNPL doesn't do recurring — guard on both the mode AND any recurring price_data line).
    # Otherwise leave payment methods to the account's Stripe defaults, as before.
    has_recurring = any("[recurring]" in key for key in payload)
    if bnpl_payment_method_types and payload.get("mode") == "payment" and not has_recurring:
        # An explicit payment_method_types list SUPPRESSES Link (Stripe shows Link only when 'link' is listed);
        # without a list Link rides in via the account defaults. Since we only set an explicit list to add BNPL,
        # re-add 'link' here so enabling installments doesn't quietly drop Link (the fallback below removes it if
        # the account has no Link). Card first, then Link, then the BNPL methods.
        currency = str((resolved or {}).get("currency") or "").lower()
        lead = ["card"] + (["link"] if currency in LINK_CURRENCIES else [])
        types = lead + [t for t in bnpl_payment_method_types if t and t not in lead]
        for index, pmt in enumerate(types):
            payload[f"payment_method_types[{index}]"] = pmt
    return payload


def create_checkout_session_with_bnpl_fallback(payload, *, api_key, stripe_account="", opener=None, had_bnpl=False):
    """Create the Checkout Session with a retry ladder for the explicit payment_method_types list (card + Link +
    the tenant's BNPL). On failure we degrade in the order that keeps the most, so an edge account never crashes
    checkout and rarely loses more than necessary (plans/BNPL_PAYMENT_METHODS.md):
      1) drop 'link' — the account may not have Link enabled; keeps BNPL + platform control;
      2) drop the whole explicit list → the account's default methods (a BNPL method went ineligible at charge
         time, e.g. the merchant turned it off in their own dashboard, or a per-transaction Stripe rule)."""
    try:
        return create_stripe_checkout_session(payload, api_key=api_key, stripe_account=stripe_account, opener=opener)
    except Exception as original:
        # A retry here means an explicit method (a BNPL method that went ineligible, or Link) was rejected;
        # log it so a silent drop-to-defaults is visible in the checkout logs.
        logger.warning("checkout: retrying without some payment methods after error: %s", original)
        ladder = []
        without_link = _payload_without_payment_method_type(payload, "link")
        if without_link is not None:
            ladder.append(without_link)
        if had_bnpl:
            ladder.append({key: value for key, value in payload.items() if not key.startswith("payment_method_types[")})
        if not ladder:
            raise
        last_exc = original
        for attempt in ladder:
            try:
                return create_stripe_checkout_session(attempt, api_key=api_key, stripe_account=stripe_account, opener=opener)
            except Exception as exc:  # noqa: BLE001 - try the next rung; re-raise the last if all fail
                last_exc = exc
        raise last_exc


def _payload_without_payment_method_type(payload, drop):
    """A copy of `payload` with `drop` removed from the payment_method_types[i] list and the survivors re-indexed;
    None if `drop` isn't present (so the caller can skip that retry rung)."""
    def _index(key):
        return int(key[len("payment_method_types["):-1])
    keys = sorted((k for k in payload if k.startswith("payment_method_types[")), key=_index)
    values = [payload[k] for k in keys]
    if drop not in values:
        return None
    out = {k: v for k, v in payload.items() if not k.startswith("payment_method_types[")}
    for index, value in enumerate(v for v in values if v != drop):
        out[f"payment_method_types[{index}]"] = value
    return out


def create_stripe_checkout_session(payload, *, api_key, stripe_account="", opener=None):
    opener = opener or urlopen
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    request = Request(
        STRIPE_CHECKOUT_SESSIONS_URL,
        data=urlencode(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        # `json` is imported at module scope. A function-local `import json` here would make the name local
        # to this WHOLE function, leaving it unbound in the except clause below -- which silently swallowed
        # Stripe's explanation the first time this was written.
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Stripe ALWAYS explains a 400 in the response body; urllib's str() is only "HTTP Error 400: Bad
        # Request". Losing the body meant a failed checkout said nothing at all in the logs -- the reason
        # had to be rediscovered by replaying the payload against Stripe by hand.
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message") or ""
        except Exception:  # noqa: BLE001 - a body we cannot parse must not replace the original error
            pass
        if detail:
            logger.error("stripe: checkout session rejected: %s", detail)
            raise StripeCheckoutError(detail) from exc
        raise


def redirect_response(url):
    return {
        "statusCode": 303,
        "headers": {
            "Location": url,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
        },
        "body": "",
    }
