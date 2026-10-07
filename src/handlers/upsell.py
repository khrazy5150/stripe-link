import os
import time
from urllib.request import urlopen

from stripe_link.common import error_response, json_response, parse_json_body, query_params, resolve_stripe_mode, tenant_id_from_event
from stripe_link.silo import current_silo
from stripe_link.domain.billing_status import BillingStatusError, assert_billing_in_good_standing
from stripe_link.domain.fees import build_fee_context
from stripe_link.domain.opportunities import STAGE_CHECKOUT, stage_opportunities
from stripe_link.domain.pricing import (
    PricingError, find_price, load_offer_products, resolve_offer)
from stripe_link.domain.shipping import destination_address_from_session
from stripe_link.domain.ledger import sale_entry_from_order
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.repositories.documents import (
    customers_repository,
    offers_repository,
    ledger_repository,
    orders_repository,
    products_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials


class UpsellError(Exception):
    pass


def handler(
    event,
    context,
    *,
    offers_repo=None,
    products_repo=None,
    stripe_repo=None,
    tenant_repo=None,
    orders_repo=None,
    customers_repo=None,
    secret_cipher=None,
    opener=None,
    billing_config_loader=None,
    now_fn=lambda: int(time.time()),
):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"GET", "POST"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    stripe_repo = stripe_repo or stripe_keys_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    opener = opener or urlopen
    mode = resolve_stripe_mode(event)

    if method == "GET":
        return get_upsell_session(event, stripe_repo=stripe_repo, secret_cipher=secret_cipher, opener=opener)

    return process_upsell(
        event,
        offers_repo=offers_repo or offers_repository(mode=mode),
        products_repo=products_repo or products_repository(mode=mode),
        stripe_repo=stripe_repo,
        tenant_repo=tenant_repo or tenant_profiles_repository(),
        orders_repo=orders_repo or orders_repository(mode=mode),
        customers_repo=customers_repo or customers_repository(mode=mode),
        secret_cipher=secret_cipher,
        opener=opener,
        billing_config_loader=billing_config_loader,
        now_fn=now_fn,
    )


def get_upsell_session(event, *, stripe_repo, secret_cipher, opener):
    params = query_params(event)
    tenant_id = tenant_id_from_event(event) or str(params.get("clientID") or "").strip()
    session_id = str(params.get("session_id") or "").strip()
    # The offer the page is ABOUT, so its postage can be disclosed on the accept button. Optional: a page
    # that does not send it simply gets no shipping figure, which is what every page did until now.
    offer_id = str(params.get("offer") or params.get("offer_id") or "").strip()
    # WHICH product this upsell sells. The offer is the funnel's SOURCE offer, so its items are the
    # original bundle -- quoting those would disclose the wrong parcel entirely.
    product_id = str(params.get("product_id") or "").strip()
    mode = "live" if str(params.get("mode") or "").strip() == "live" else "test"

    if not tenant_id:
        return error_response("clientID or tenant_id is required.", code="missing_tenant")
    if not session_id:
        return error_response("session_id is required.", code="missing_session")

    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

    try:
        session = stripe_request(
            "GET",
            f"/checkout/sessions/{session_id}",
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
            params=[
                ("expand[]", "customer"),
                ("expand[]", "payment_intent"),
                ("expand[]", "payment_intent.payment_method"),
            ],
        )
    except StripeApiError as exc:
        return error_response(exc.message, status_code=exc.status_code or 502, code="stripe_error")

    customer = session.get("customer")
    customer_id = customer.get("id") if isinstance(customer, dict) else (customer or "")
    payment_intent = session.get("payment_intent")
    payment_intent_id = payment_intent.get("id") if isinstance(payment_intent, dict) else (payment_intent or "")
    payment_method = payment_intent.get("payment_method") if isinstance(payment_intent, dict) else None
    payment_method_id = payment_method.get("id") if isinstance(payment_method, dict) else (payment_method or "")

    customer_details = session.get("customer_details") or {}
    shipping_details = session.get("shipping_details") or {}

    return json_response({
        "session": {
            "session_id": session_id,
            "customer_id": customer_id,
            "payment_intent_id": payment_intent_id,
            "payment_method_id": payment_method_id,
            "customer_email": customer_details.get("email") or session.get("customer_email") or "",
            "customer_name": customer_details.get("name") or "",
            "customer_phone": customer_details.get("phone") or "",
            "shipping_address": shipping_details.get("address"),
        },
        # WHAT POSTAGE WILL BE ADDED, so the button can say so BEFORE the buyer clicks. The accept label
        # states a price ("Yes, I'll Take This Deal for $29"); charging more than it says is a
        # misstatement to a buyer, not a rounding detail. The page is a published artifact and the
        # destination is only known per-session, so the figure has to arrive here rather than be baked in
        # (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P1).
        **({"shipping": _session_shipping_quote(
               event, tenant_id, offer_id, product_id, shipping_details,
               # The SAME baseline the charge will use, so the button and the card cannot disagree.
               baseline=session_shipping_baseline(session_id, api_key=api_key,
                                                  stripe_account=stripe_account, opener=opener),
               session_id=session_id)}
           if offer_id and product_id else {}),
        # WHEN THE PARCEL IS DUE, for the thank-you page's shipping element and the `{{arrival}}` token in
        # its cards (plans/THANK_YOU_PAGE.md P2). Read from the ORDER rather than recomputed: the promise
        # was settled when the order was written, and a date that moves on a page refresh is not a
        # promise. `{}` means no parcel, and the island then removes the element entirely.
        #
        # Served from this endpoint rather than a new route because the thank-you screen is a funnel step
        # like any other, it already calls this with the same `session_id`, and the stack is at 94.8% of
        # CloudFormation's transform limit -- a route costs template bytes we may need for something that
        # cannot be answered anywhere else.
        "delivery": _delivery_promise(tenant_id, session_id, mode=resolve_stripe_mode(event)),
    })


def _delivery_promise(tenant_id, session_id, *, mode, orders_repo=None):
    """The stored `delivery_estimate` for this checkout, or `{}`.

    Best-effort and read-only. A thank-you page that cannot reach the order shows the shell's own honest
    line ("we'll email tracking details") rather than an error, which is why every failure here is an
    empty dict and not an exception.
    """
    try:
        if not tenant_id or not session_id:
            return {}
        repo = orders_repo or (orders_repository(mode=mode) if os.environ.get("ORDERS_TABLE") else None)
        if repo is None:
            return {}
        # Deterministic: a checkout order is keyed `order_{session_id}` (`order_record_from_session`), so
        # this is one `get` rather than a scan.
        order = repo.get(tenant_id, f"order_{session_id}") or {}
        promise = order.get("delivery_estimate")
        if not isinstance(promise, dict) or not promise:
            return {}
        # WORDED HERE, not in the browser. `promise_sentence` and `arrival_phrase` are the one formatter;
        # a JS copy would be a second way to say the same date, and the element and the `{{arrival}}` token
        # in a tenant's card would start disagreeing on a page that shows both.
        from stripe_link.domain.shipping_promise import arrival_phrase, promise_sentence

        return dict(promise, sentence=promise_sentence(promise), arrival_phrase=arrival_phrase(promise))
    except Exception as exc:  # noqa: BLE001
        print(f"[delivery] promise unavailable for {session_id}: {type(exc).__name__}: {exc}")
        return {}


def _session_shipping_quote(event, tenant_id, offer_id, product_id, shipping_details, baseline=None,
                            session_id=""):
    """The postage the accept button must disclose. `{amount, service_token, reason}`; zeros on any failure.

    **It must quote exactly what the charge will quote**, or the button states one price and the card takes
    another. Two things made it disagree, and both are fixed here (author, 2026-10-02):

    - It rated `offer.items` -- the SOURCE offer's landing items, i.e. the whole bundle -- because an
      upsell page's CTA carries the offer the funnel derives from. The upsell is ONE product, named by
      `product_id`, and that is what gets charged.
    - It passed no `baseline`, so it priced a standalone parcel while the charge priced the delta. The
      button said "+ $6.11" for an item the charge added for $0.08.

    Best-effort by the same argument as the charge: a quote that cannot be had means no postage is
    charged, so a page that cannot show one is still telling the truth.
    """
    from stripe_link.repositories.documents import (offers_repository, orders_repository,
                                                     products_repository)

    try:
        mode = resolve_stripe_mode(event)
        offer = offers_repository(mode=mode).get(tenant_id, offer_id)
        if not offer:
            return {"amount": 0, "service_token": "", "reason": "offer_not_found"}
        products_repo = products_repository(mode=mode)
        # THE SAME BOX THE CHARGE WILL SEE. Disclosing a delta measured from the bare checkout quote while
        # charging one measured from the real parcel is how a button comes to state a price the card does
        # not take.
        baseline = box_so_far(baseline, tenant_id=tenant_id, session_id=session_id, offer=offer,
                              products_repo=products_repo, orders_repo=orders_repository(mode=mode))
        wanted = str(product_id or "").strip()
        if not wanted:
            return {"amount": 0, "service_token": "", "reason": "no_product"}
        product = products_repo.get(tenant_id, wanted)
        if not product:
            return {"amount": 0, "service_token": "", "reason": "product_not_found"}
        return quote_upsell_shipping(tenant_id, [{"product_id": wanted, "quantity": 1}],
                                     {wanted: product},
                                     destination=(shipping_details or {}).get("address") or {},
                                     mode=mode, baseline=baseline, products_repo=products_repo)
    except Exception as exc:  # noqa: BLE001 - a disclosure that failed must not break the page
        print(f"[upsell] shipping disclosure unavailable: {type(exc).__name__}: {exc}")
        return {"amount": 0, "service_token": "", "reason": "unavailable"}


def upsell_destination(session_id, *, api_key, stripe_account, opener):
    """Where an upsell ships: the address the ORIGINAL Checkout Session collected.

    Read from STRIPE rather than from two closer-looking sources, both of which are wrong:

    - **Not from the request body.** `get_upsell_session` already hands the browser this address, so it
      would be one line to accept it back -- and it would let anyone with the funnel page redirect someone
      else's parcel. A shipping destination is not a thing to take on a client's word.
    - **Not from the parent order row.** It looks equivalent and is not: the parent order is written by the
      WEBHOOK while this upsell is written by whichever backend the funnel page called, and on a test-mode
      sale those are different tables (the prod webhook handles test events; the sandbox API writes to dev).
      Measured 2026-09-25: three upsells in jb-orders-dev whose parents were all in jb-orders-prod. Stripe
      is the one place both environments agree.

    Best-effort. The money has already moved by the time this runs, so a failed lookup must cost the
    tenant an address on the order, never the order itself.
    """
    try:
        session = stripe_request(
            "GET", f"/checkout/sessions/{session_id}",
            api_key=api_key, stripe_account=stripe_account, opener=opener)
    except StripeApiError:
        return {}
    except Exception:  # noqa: BLE001 - see docstring: never fail an order that is already paid for
        return {}
    return destination_address_from_session(session)


def session_shipping_baseline(session_id, *, api_key, stripe_account, opener):
    """What the first sale already paid to post, read off the CHECKOUT SESSION. `{}` when unknown.

    plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P1. It used to read the ORDER, which the webhook writes -- and
    a buyer reaches the first upsell within seconds of paying, so the order was sometimes not there yet.
    The first upsell then fell back to a full standalone parcel while the second got the delta: in one real
    run, $6.27 and then $0.08 for comparable items (author, 2026-10-02).

    The SESSION carries the same facts the moment checkout completes -- `metadata[shipping_quote_id]` and
    `metadata[shipping_quoted_amount]` are stamped there at session creation -- so there is no window to
    lose. `{}` on any failure, and the caller then rates the upsell on its own.
    """
    try:
        session = stripe_request(
            "GET", f"/checkout/sessions/{session_id}",
            api_key=api_key, stripe_account=stripe_account, opener=opener,
            # The BUMP the buyer ticked is in here and nowhere else at this moment. It is not in the
            # shipping quote -- a bump is chosen on Stripe's page after the quote is stamped -- and the
            # order the webhook writes may not exist yet. Expanding costs nothing extra: this request is
            # already being made.
            params=[("expand[]", "line_items")])
    except Exception:  # noqa: BLE001 - not knowing is a fallback, never a failed sale
        return {}
    meta = session.get("metadata") or {}
    quote_id = str(meta.get("shipping_quote_id") or "")
    paid = int(meta.get("shipping_quoted_amount") or 0)
    if not quote_id or not paid:
        return {}
    mode = "live" if session.get("livemode") else "test"
    try:
        from stripe_link.repositories.documents import shipping_quotes_repository

        tenant_id = str(meta.get("tenant_id") or "")
        quote = shipping_quotes_repository(mode=mode).get(tenant_id, quote_id) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[upsell] shipping baseline quote unreadable: {type(exc).__name__}: {exc}")
        return {}
    lines = [{"product_id": str(line.get("product_id") or ""),
              "price_id": str(line.get("price_id") or ""),
              "quantity": max(1, int(line.get("quantity") or 1))}
             for line in (quote.get("items") or []) if line.get("product_id")]
    if not lines:
        return {}
    # WHICH STRIPE PRICES WERE ACTUALLY BOUGHT, so the caller can tell a bump that was ticked from one
    # that was merely offered, and WHAT POSTAGE came in through them. Both are carried out of here rather
    # than re-fetched, because this function already holds the session.
    taken = {}
    for line in ((session.get("line_items") or {}).get("data") or []):
        price = line.get("price") if isinstance(line.get("price"), dict) else {}
        stripe_price_id = str(price.get("id") or "")
        if stripe_price_id:
            taken[stripe_price_id] = taken.get(stripe_price_id, 0) + max(1, int(line.get("quantity") or 1))
    return {"items": lines, "amount": paid, "taken_price_ids": taken,
            "bump_shipping": _bump_postage_paid(meta.get("order_bump_shipping"), taken)}


def _bump_postage_paid(raw, taken_price_ids):
    """Postage already collected through the bump lines the buyer actually ticked.

    The surcharge is folded into the bump's own price (domain/stripe_products.charged_unit_amount), so it
    is money paid for the parcel that does not appear in the shipping line. A later upsell measuring its
    delta against the shipping line alone would be measuring against a figure that is short by this much.
    """
    total = 0
    for pair in str(raw or "").split(","):
        stripe_price_id, _, amount = pair.partition(":")
        quantity = taken_price_ids.get(stripe_price_id.strip(), 0)
        if not quantity:
            continue
        try:
            total += int(amount) * quantity
        except (TypeError, ValueError):
            continue
    return total


# How far to walk when looking for upsells already accepted and the step number is unknown. A funnel
# with more steps than this simply stops accumulating, which under-states the box rather than inventing
# one.
MAX_DISCOVERED_UPSELLS = 20


def box_so_far(baseline, *, tenant_id, session_id, sequence=None, offer=None, products_repo=None,
               orders_repo=None):
    """What is ALREADY in the parcel, and what has already been paid to post it.

    An upsell's postage is a DELTA, and a delta is only as honest as the thing it is measured from.
    `session_shipping_baseline` answers "what did the original checkout quote cover", which is NOT the
    same question -- it is blind to two things that are genuinely in the box by the time an upsell is
    offered:

      - **the order bump**, which is ticked on Stripe's hosted page after the shipping quote is stamped,
        and so appears in no quote anywhere; and
      - **every upsell the buyer has already accepted**, because each one was rated against this same
        original quote.

    While upsells were small the error was zero and invisible. It is not small when they are not.
    Measured on real products 2026-10-05: cart 620c, then two Whey Protein upsells. Each was rated against
    the original cart and charged 203c, so the buyer paid 1026c to post a parcel that costs 837c -- a
    **189c OVERCHARGE**, taken from the customer. The reverse is just as available: two upsells that each
    fit alone but together force a second parcel would each be charged nothing for it.

    So the baseline is cumulative. Items the buyer has bought and postage they have already paid both
    accumulate, and the delta is always "what does adding THIS cost on top of what is already going".

    Reads are best-effort: a baseline that cannot be completed is returned as far as it got, because an
    approximate delta beats refusing the sale.
    """
    if not baseline or not baseline.get("items"):
        return baseline
    items = list(baseline["items"])
    amount = int(baseline.get("amount") or 0) + int(baseline.get("bump_shipping") or 0)

    # THE BUMP. Resolved through the offer, because only the offer knows which products are offered as
    # bumps, and matched on the Stripe price ids the session says were bought.
    taken = baseline.get("taken_price_ids") or {}
    if taken and offer and products_repo:
        for bump in stage_opportunities(offer, STAGE_CHECKOUT):
            bump_product_id = str(bump.get("product_id") or "")
            if not bump_product_id:
                continue
            try:
                product = products_repo.get(tenant_id, bump_product_id)
            except Exception:  # noqa: BLE001
                continue
            price = find_price(product or {}, str(bump.get("price_id") or ""))
            quantity = taken.get(str(price.get("stripe_price_id") or ""), 0)
            if quantity:
                items.append({"product_id": bump_product_id, "price_id": str(bump.get("price_id") or ""),
                              "quantity": quantity})

    # EVERY UPSELL ALREADY ACCEPTED. Their order ids are deterministic and they are written synchronously
    # before the buyer can reach the next step, so this is a direct read per prior step -- no scan, and no
    # race of the kind that moved the baseline off the order in the first place.
    #
    # `sequence` is known on the charge (the page sends its funnel step) and NOT on the disclosure, which
    # is a plain GET for the page about to be shown. Rather than republish every funnel page to add the
    # step number, an absent one is DISCOVERED by walking the deterministic ids until one is missing --
    # bounded, and it finds exactly the steps already accepted. Both paths must agree, because the button
    # states a price and the charge takes one.
    if orders_repo:
        earlier = 0
        limit = (sequence - 1) if sequence else MAX_DISCOVERED_UPSELLS
        while earlier < limit:
            earlier += 1
            try:
                order = orders_repo.get(tenant_id, f"order_{session_id}_upsell_{earlier}")
            except Exception:  # noqa: BLE001
                continue
            if not order:
                if not sequence:
                    break  # a gap means there are no more; with a known sequence, keep checking the rest
                continue
            if str(order.get("status") or "") not in ("paid", "succeeded"):
                continue
            product_id = str((order.get("product") or {}).get("product_id") or "")
            if product_id:
                items.append({"product_id": product_id, "quantity": 1})
            amount += int(order.get("shipping_amount") or 0)

    return {"items": items, "amount": amount}


def process_upsell(
    event,
    *,
    offers_repo,
    products_repo,
    stripe_repo,
    tenant_repo,
    orders_repo,
    customers_repo,
    secret_cipher,
    opener,
    billing_config_loader,
    now_fn,
):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_json")

    tenant_id = tenant_id_from_event(event, body)
    session_id = str(body.get("session_id") or "").strip()
    offer_id = str(body.get("offer_id") or "").strip()
    product_id = str(body.get("product_id") or "").strip()
    price_id = str(body.get("price_id") or "").strip()
    customer_id = str(body.get("customer_id") or "").strip()
    sequence = int(body.get("sequence") or 1)
    mode = "live" if str(body.get("mode") or "").strip() == "live" else "test"
    customer_info = body.get("customer") if isinstance(body.get("customer"), dict) else {}

    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not session_id:
        return error_response("session_id is required.", code="missing_session")
    if not offer_id:
        return error_response("offer_id is required.", code="missing_offer")
    if not customer_id:
        return error_response("customer_id is required.", code="missing_customer")

    try:
        assert_billing_in_good_standing(tenant_repo.get(tenant_id, tenant_id))

        offer = offers_repo.get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="not_found")

        # An upsell product is a POST-PURCHASE opportunity of the offer, not a landing item, so resolving the
        # offer's landing items wouldn't price it. When the caller names the product + price (the funnel screen
        # does), charge that specific product@price as a standalone one-item upsell (plans/OFFER_MODEL_REDESIGN.md
        # §6). Falls back to resolving the offer itself when unnamed (legacy callers).
        if product_id and price_id:
            upsell_product = products_repo.get(tenant_id, product_id)
            if not upsell_product:
                return error_response("Upsell product not found.", status_code=404, code="not_found")
            products_by_id = {product_id: upsell_product}
            # A post-purchase charge is either the upsell price OR that product's downsell (the in-place swap on
            # decline/expiry, §6), so accept BOTH contexts. resolve_offer_item reads the item-level
            # allowed_price_contexts; without this a downsell price is rejected as an invalid context (which the
            # funnel screen surfaces as a misleading "card declined").
            fee_offer = {
                "offer_id": offer_id, "tenant_id": tenant_id, "status": "active",
                "product_intent": "transaction", "context": "upsell",
                "items": [{
                    "product_id": product_id, "price_id": price_id, "quantity": 1,
                    "allowed_price_contexts": ["upsell", "downsell"],
                }],
                "eligibility": {"allowed_price_contexts": ["upsell", "downsell"]},
                "discount": {"mode": "none"},
            }
            resolved = resolve_offer(fee_offer, products_by_id, {})
        else:
            products_by_id = load_offer_products(tenant_id, offer, products_repo)
            resolved = resolve_offer(offer, products_by_id, {})
            fee_offer = offer

        stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
        api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
        if not api_key:
            return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

        fee_context = build_fee_context(
            tenant_id=tenant_id,
            offer=fee_offer,
            products_by_id=products_by_id,
            resolved=resolved,
            tenant_repo=tenant_repo,
            billing_config_loader=billing_config_loader,
        )

        payment_method_id = resolve_customer_payment_method(
            customer_id,
            api_key=api_key,
            stripe_account=stripe_account,
            opener=opener,
        )
    except BillingStatusError as exc:
        return error_response(str(exc), status_code=402, code="tenant_billing_hold")
    except PricingError as exc:
        return error_response(str(exc), code="upsell_error")
    except UpsellError as exc:
        return error_response(str(exc), status_code=409, code="payment_method_unavailable")
    except StripeApiError as exc:
        return error_response(exc.message, status_code=exc.status_code or 502, code="stripe_error")

    subtotal = int(resolved.get("subtotal") or 0)
    currency = resolved.get("currency") or "usd"
    idempotency_key = f"upsell:{tenant_id}:{session_id}:{offer_id}:{sequence}"
    # Derived BEFORE the charge, because the PaymentIntent is going to carry it: it depends only on
    # the session and the sequence, both of which are already known.
    order_id = f"order_{session_id}_upsell_{sequence}"

    # WHERE IT GOES, looked up before the charge -- it was already fetched here for the order record, and
    # a shipping quote needs it too (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P1).
    shipping_address = upsell_destination(
        session_id, api_key=api_key, stripe_account=stripe_account, opener=opener)

    # WHAT POSTAGE COSTS ON AN UPSELL. Until now an upsell shipped for nothing: a tenant selling a second
    # physical item post-purchase paid to post it and was never paid for it, which is why the author
    # feared having to build shipping into every price.
    #
    # Unlike an order bump, this is NOT constrained. An upsell is a PaymentIntent we build ourselves, so
    # there is no fixed `shipping_options` and no session to reopen -- the destination is already known
    # and the packer and rater are already deployed. The assumption that it shared the bump's limitation
    # came from treating the two as one problem.
    upsell_shipping = quote_upsell_shipping(
        tenant_id, resolved.get("items") or [], products_by_id,
        destination=shipping_address, mode=mode, secret_cipher=secret_cipher,
        # What is already going, so this charges only what the extra item ADDS -- including the order
        # bump and every upsell already accepted, which the checkout quote alone cannot see.
        baseline=box_so_far(
            session_shipping_baseline(session_id, api_key=api_key, stripe_account=stripe_account,
                                      opener=opener),
            tenant_id=tenant_id, session_id=session_id, sequence=sequence, offer=offer,
            products_repo=products_repo, orders_repo=orders_repo),
        # So the delta can measure what is ALREADY in the box: `products_by_id` holds only the upsell.
        products_repo=products_repo)
    shipping_amount = int(upsell_shipping.get("amount") or 0)
    charged = subtotal + shipping_amount

    pi_params = {
        "amount": str(charged),
        "currency": currency,
        "customer": customer_id,
        "payment_method": payment_method_id,
        "confirmation_method": "automatic",
        "confirm": "true",
        "off_session": "true",
        "description": "One-click upsell",
        "metadata[tenant_id]": tenant_id,
        "metadata[upsell]": "true",
        # Which silo charged this (plans/SILO_MODEL.md S1). A one-click upsell is a PaymentIntent we
        # create directly rather than a session, so it needs the stamp of its own -- its later refund and
        # dispute events are resolvable from the order it writes, but the charge itself should still say
        # where it came from. Omitted rather than guessed when unknown, as everywhere else.
        **({"metadata[silo]": current_silo()} if current_silo() else {}),
        "metadata[original_session_id]": session_id,
        "metadata[offer_id]": offer_id,
        "metadata[product_type]": fee_context["product_type"],
        "metadata[tenant_plan]": fee_context["tenant_plan"],
    }
    platform_fee = int(fee_context.get("platform_fee") or 0)
    if stripe_account and subtotal > 0 and platform_fee > 0:
        # MERCHANDISE ONLY, and correct here by construction: `fee_context` was computed from the
        # subtotal, so adding postage to the charge above does not grow the platform's cut
        # (domain/fees.FEE_APPLIES_TO_SHIPPING).
        pi_params["application_fee_amount"] = str(platform_fee)
    if shipping_amount:
        pi_params["metadata[shipping_amount]"] = str(shipping_amount)
        pi_params["metadata[shipping_service]"] = str(upsell_shipping.get("service_token") or "")
    # WHICH ORDER THIS CHARGE IS, so `payment_intent.succeeded` can correct it without hunting for it
    # (plans/FEE_RECONCILIATION.md Phase 2). `tenant_id` is already here; together they are the order's
    # full primary key, which turns the webhook's job into one `get` instead of a scan or a second index.
    pi_params["metadata[order_id]"] = order_id

    try:
        payment_intent = stripe_request(
            "POST",
            "/payment_intents",
            api_key=api_key,
            stripe_account=stripe_account,
            data=pi_params,
            opener=opener,
            idempotency_key=idempotency_key,
        )
    except StripeApiError as exc:
        status_code = exc.status_code if exc.status_code and exc.status_code < 500 else 502
        code = "card_declined" if exc.stripe_code == "card_declined" else "stripe_error"
        # LOGGED, because the page could only ever say "Card declined" and the function said nothing at
        # all -- a real failure left no trace on either side of the wire (2026-10-05).
        print(f"[upsell] charge failed for {order_id}: {exc.stripe_code or 'stripe_error'}: {exc.message}")
        return error_response(exc.message, status_code=status_code, code=code)

    now = int(now_fn())
    # WHAT STRIPE ACTUALLY TOOK, not what we estimated it would. The webhook has trued every other sale
    # against the charge's balance transaction since the ledger shipped; an upsell kept the estimate,
    # because it is the one sale path the webhook never sees. The estimate rounds UP where Stripe rounds
    # down, so an upsell's recorded payout was systematically a cent or two light -- small, one-directional
    # and exactly the drift that makes a tenant stop trusting a report. Best-effort by the same rule as
    # everywhere else: an unsettled balance transaction leaves the estimate standing rather than replacing
    # a usable number with nothing.
    # MARKED AN ESTIMATE, AND NOT ASKED ABOUT. Three versions of this tried to read the real fee here --
    # a follow-up GET, then `expand[]` on the create, then both with the guard fixed -- and all three
    # failed for one reason nobody had measured: the balance transaction does not become readable for
    # ~90-100 seconds (two charges polled at 92s and 101s, 2026-10-04). Nothing asked inside the buyer's
    # request can win that, so asking at all was two Stripe calls spent to learn nothing, on the one path
    # where the buyer is waiting.
    #
    # `true_up_fees` with nothing is how the estimate gets NAMED rather than left unmarked, and that mark
    # is what the sweep selects on -- so this line is what hands the order to the thing that can actually
    # correct it (plans/FEE_RECONCILIATION.md).
    from handlers.stripe_webhook import true_up_fees

    upsell_fees = true_up_fees(fee_context["fees"], {})
    primary_item = (resolved.get("items") or [{}])[0]
    product = products_by_id.get(primary_item.get("product_id")) or {}
    product_name = product.get("name") or primary_item.get("product_name") or "Upsell"

    order_record = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "schema_version": "2026-05-29",
        "document_type": "order",
        # WHICH STRIPE MODE THIS SALE WAS IN. The repository stamps this on write, but the ledger is
        # handed this dict BEFORE that happens -- so without it here a live upsell recorded itself as
        # test money and vanished from live reports (found 2026-10-07). `stripe_mode` rather than `mode`
        # because that is the name storage filters on, and the one plans/STRIPE_MODE_STORAGE.md
        # standardises on; on a Stripe session `mode` already means payment-vs-subscription.
        "stripe_mode": mode,
        "session_id": session_id,
        # WHICH CHARGE THIS WAS. Absent since upsells were written, and every consequence of that is a
        # thing nobody could do: `sale_entry_from_order` fell back to keying the ledger row on the order
        # id and left its `stripe` block empty, so an upsell row could not be reconciled against Stripe
        # at all; a refund had no charge to reverse; and a later fee true-up had nothing to look up.
        # Found 2026-10-04 by asking why the true-up never fired and finding `pi = None` on the order.
        "payment_intent_id": str(payment_intent.get("id") or ""),
        "line_item_type": "upsell",
        "status": "paid" if payment_intent.get("status") == "succeeded" else payment_intent.get("status", "pending"),
        # What the buyer was CHARGED, postage included -- the order's total must be the amount that left
        # their card, or every downstream reconciliation disagrees with Stripe.
        "amount_total": charged,
        # ...and postage separated out beside it, so the ledger can partition it from merchandise exactly
        # as a first sale does (domain/ledger.BREAKDOWN_COMPONENTS).
        **({"shipping_amount": shipping_amount} if shipping_amount else {}),
        "currency": currency,
        "customer": {
            "name": customer_info.get("name", ""),
            "email": customer_info.get("email", ""),
            "phone": customer_info.get("phone", ""),
            "stripe_customer_id": customer_id,
        },
        "product": {
            "product_id": primary_item.get("product_id", ""),
            "price_id": primary_item.get("price_id", ""),
            "name": product_name,
        },
        "fees": upsell_fees,
        "attribution": {
            "offer_id": offer_id,
            "page_id": "",
            "funnel_id": "",
            "order_bump_ids": [],
            "post_checkout_entry": "upsell",
        },
        "metadata": {"upsell_sequence": str(sequence)},
        # Where the parcel goes. An upsell is charged off-session against the card the buyer already used,
        # so no second Checkout Session collects an address -- and without this the order looked like a
        # digital sale to every shipping gate downstream (found 2026-09-25 from three real upsells of a
        # PHYSICAL product, all recorded with no destination).
        **({"shipping_address": shipping_address} if shipping_address else {}),
        "created_at": str(now),
        "updated_at": now,
    }
    orders_repo.put(order_record)
    # ...and the LEDGER, which never heard about upsells at all: they are PaymentIntents we create
    # directly, so no checkout.session.completed fires and the webhook that appends every other sale is
    # never invoked. Their revenue, fees and postage were missing from every report.
    record_upsell_ledger_entry(order_record)

    update_customer_after_upsell(
        customers_repo,
        tenant_id=tenant_id,
        customer_id=customer_id,
        amount=charged,
        currency=currency,
        product_name=product_name,
        order_id=order_id,
        now=now,
    )

    return json_response({
        "upsell": {
            "order_id": order_id,
            "payment_intent_id": payment_intent.get("id", ""),
            "status": payment_intent.get("status", ""),
        }
    }, status_code=201)


def record_upsell_ledger_entry(order_record, ledger_repo=None):
    """Append the upsell's sale to the transaction ledger.

    An upsell wrote an ORDER and nothing else: it is a PaymentIntent we create directly, so no
    `checkout.session.completed` ever fires for it and the webhook -- which is what appends every other
    sale -- never hears about it. Real revenue, real fees and real postage were absent from every report
    (found 2026-10-02: two upsell orders on the books, neither in the ledger).

    Best-effort. The money has moved and the order is written; a bookkeeping append must not undo that.
    """
    try:
        # From the ORDER, which now declares its own mode -- the same field the entry will be stamped
        # with, so the repository it is written through and the row it writes cannot disagree.
        from stripe_link.domain.ledger import _order_mode

        repo = ledger_repo or (ledger_repository(mode=_order_mode(order_record))
                               if os.environ.get("LEDGER_TABLE") else None)
        if repo is None:
            return False
        # `source` is the ledger's provenance field and it defaults to "webhook", which is the one thing
        # an upsell is not: no `checkout.session.completed` fires for a PaymentIntent we create ourselves,
        # which is the entire reason this function exists. Reading the ledger to find out where a row came
        # from is the only purpose the field has, so a wrong answer is worse than none.
        entry = sale_entry_from_order(order_record, now_epoch=int(time.time()), source="upsell")
        if not entry:
            return False
        repo.append(entry)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[upsell] ledger entry not recorded: {type(exc).__name__}: {exc}")
        return False


def _rating_products(products_by_id, base_lines, *, tenant_id, products_repo):
    """`products_by_id` plus every baseline product missing from it; None when one cannot be loaded.

    The delta re-packs the FIRST sale's lines together with the upsell, so it needs the dimensions of
    things the upsell handler was never asked about: both call sites build their map from the ONE product
    being sold. Handing that map to the packer does not fail -- the three items already in the buyer's box
    arrive as products the map has never heard of, and each becomes a parcel of its own.

    That is the whole of the "+ $6.27 shipping" the author was shown on 2026-10-02 for a supplement riding
    in a box already posted: the combined rate was three phantom parcels plus the real one, so the
    difference against what was paid came out positive. Rated with a complete map the same order's
    combined rate is identical to its baseline, and the delta is zero -- which is what he expected to see.

    None rather than a partial map, because a combined rate short one product is not a conservative
    estimate, it is a wrong number with the authority of a carrier quote behind it. The caller falls back
    to a standalone rate, which over-charges in a direction a tenant can refund.
    """
    missing = {str(line.get("product_id") or "") for line in base_lines or []} - set(products_by_id)
    missing.discard("")
    if not missing:
        return dict(products_by_id)
    if products_repo is None:
        return None
    merged = dict(products_by_id)
    for product_id in missing:
        try:
            product = products_repo.get(tenant_id, product_id)
        except Exception as exc:  # noqa: BLE001 - an unreadable product means fall back, not fail
            print(f"[upsell] baseline product {product_id} unreadable: {type(exc).__name__}: {exc}")
            return None
        if not product:
            print(f"[upsell] baseline product {product_id} is gone; rating the upsell on its own")
            return None
        merged[product_id] = product
    return merged


def quote_upsell_shipping(tenant_id, items, products_by_id, *, destination, mode, secret_cipher=None,
                          baseline=None, products_repo=None):
    """What postage costs on a post-purchase upsell. Returns `{amount, service_token, reason}`.

    plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P1. Every failure is a zero with a reason, never an exception:
    the buyer has already clicked, and refusing a sale because a carrier was slow is a worse outcome than
    posting one parcel unpaid.

    **The tenant's own zones decide**, exactly as they do for a first sale -- a `free` offer's upsells stay
    free, a `flat` zone charges its amount, a `live` zone is rated. That is the whole point of routing this
    through `resolve_options` rather than inventing an upsell-specific rule: a second pricing path would
    drift from the first within a release.

    **It charges the DELTA, not a second parcel.** The author, 2026-10-02, on being shown "+ $6.11" for a
    single supplement added to an order already paying $6.11: *"the complete bundle costs $6.11, so there
    should be no additional shipping charge."* Right -- an item that rides in a parcel already going costs
    close to nothing to add, and billing a full second parcel for it is an overcharge dressed up as a
    quote. The original order's own lines are re-packed WITH the upsell, re-rated, and the buyer pays the
    difference; when it still fits the same box that difference is zero.

    A full standalone rate is the FALLBACK, for when the original quote cannot be found -- an older order,
    an expired row. Over-charging a tenant's own postage is recoverable where under-charging silently is
    not, so that remains the safe direction when nothing better is known.
    """
    from stripe_link.domain.shipping_charges import resolve_options
    from stripe_link.domain.shipping_zones import rule_for as zone_rule_for

    blank = {"amount": 0, "service_token": "", "reason": ""}
    country = str((destination or {}).get("country") or "").strip().upper()
    if not country:
        return dict(blank, reason="no_destination")
    try:
        from stripe_link.repositories.documents import shipping_config_repository

        config = shipping_config_repository().get(tenant_id) or {}
    except Exception as exc:  # noqa: BLE001 - a settings read must never cost a sale
        print(f"[upsell] shipping config unreadable: {type(exc).__name__}: {exc}")
        return dict(blank, reason="config_unreadable")

    # THE TENANT'S STATED POLICY (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P5). For many sellers "add it,
    # it ships with your order" is both true and a selling point, and adding one item to a parcel that is
    # already going often costs little. The point is that it is a DECISION with a number attached rather
    # than a default: the ledger records the real carrier cost either way, so `shipping_margin` reports
    # what the policy costs instead of hiding it.
    if (config.get("combined_shipping") or {}).get("extras_ship_free"):
        return dict(blank, reason="combined_shipping")

    from stripe_link.domain.shipping_charges import packed_box_price

    def rate_for(lines, pmap=None):
        """`(cheapest option, reason)`. The option is None when these lines cannot be priced, and the
        reason says WHY -- `unmeasured`, `carrier_error` and `no_options` are three different problems
        with three different fixes, and collapsing them would make a silent zero unexplainable."""
        pmap = products_by_id if pmap is None else pmap
        # A LINE WHOSE PRODUCT IS NOT IN THE MAP IS NOT A PARCEL. `packable_items` does not reject one --
        # an absent product document reads as a shippable thing of unknown size, and the packer duly
        # invents a box for it. That silence is what produced "+ $6.27" for an item the carrier carries
        # for nothing (author, 2026-10-02), so refuse to rate lines we cannot measure at all.
        if any(str(line.get("product_id") or "") not in pmap for line in lines or []):
            return None, "unknown_product"
        live = None
        if zone_rule_for(config, country).get("type") == "live":
            from handlers.checkout import _quote_parcels
            from handlers.shipping import live_rates_for

            parcels = _quote_parcels(lines, pmap, config)
            if not parcels:
                # P0a, and it applies to upsells for the same reason: a parcel nobody measured must not
                # produce a price.
                return None, "unmeasured"
            rated = live_rates_for(config, tenant_id, parcels=parcels, destination=destination,
                                   secret_cipher=secret_cipher or KmsSecretCipher())
            if rated["error"]:
                print(f"[upsell] shipping not charged, carrier said: {rated['error']}")
                return None, "carrier_error"
            live = rated["options"]
        priced = packed_box_price(lines, pmap, config, country)
        out = resolve_options({"shipping": {"eligible": True}, "items": lines}, config, country=country,
                              item_count=max(1, len(lines or [])),
                              box_amount=priced["amount"], live_options=live)
        if not out["options"]:
            return None, (out["needs"] or "no_options")
        # The CHEAPEST, because nobody is there to choose. An upsell is one click by design; interrupting
        # it with a service picker would cost more sales than ground-versus-overnight.
        return min(out["options"], key=lambda option: int(option.get("amount") or 0)), ""

    # THE DELTA. Re-pack what the buyer already bought together WITH this item, and charge the difference.
    # When it still fits the same box that difference is zero, which is the honest answer and the one the
    # author expected to see.
    base_lines = list((baseline or {}).get("items") or [])
    base_paid = int((baseline or {}).get("amount") or 0)
    rating_map = _rating_products(products_by_id, base_lines, tenant_id=tenant_id,
                                  products_repo=products_repo)
    if base_lines and base_paid and rating_map is not None:
        combined, _ = rate_for(base_lines + list(items or []), rating_map)
        if combined is not None:
            delta = max(0, int(combined.get("amount") or 0) - base_paid)
            return {"amount": delta, "service_token": str(combined.get("service_token") or ""),
                    "reason": "combined_delta"}

    chosen, reason = rate_for(items)
    if chosen is None:
        return dict(blank, reason=reason or "no_options")
    return {"amount": int(chosen.get("amount") or 0),
            "service_token": str(chosen.get("service_token") or ""), "reason": "standalone"}


PREFERRED_PAYMENT_METHOD_TYPES = ("card", "link")


def resolve_customer_payment_method(customer_id, *, api_key, stripe_account, opener):
    """Only use payment methods already attached to the customer, matching legacy behavior.

    Reusing a PaymentIntent's raw payment method without customer attachment triggers a
    Stripe error, so we always resolve through the customer's own attached methods.
    """
    customer = stripe_request(
        "GET",
        f"/customers/{customer_id}",
        api_key=api_key,
        stripe_account=stripe_account,
        opener=opener,
        params=[("expand[]", "invoice_settings.default_payment_method")],
    )
    default_pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
    if isinstance(default_pm, dict) and default_pm.get("id"):
        return default_pm["id"]
    if isinstance(default_pm, str) and default_pm:
        return default_pm

    # EVERY attached method, not just cards. Asking Stripe for `type=card` meant a buyer who checked out
    # with Stripe Link -- the one-click wallet Stripe offers on its own hosted Checkout, which attaches a
    # `link` PaymentMethod and no card -- had nothing here, so the upsell refused to charge a customer
    # who was perfectly chargeable. The page then reported it as "Card declined", which was wrong twice:
    # the card was not declined, and there was no card. Measured 2026-10-05 on a real failed upsell
    # (customer had exactly one method, `pm_...` of type `link`), and a 50c off-session probe against
    # that same method succeeded, so the method was never the problem -- the filter was.
    #
    # `type` is omitted rather than widened to a list because the parameter takes a single value, and the
    # unfiltered listing is the only call that answers "what can we charge?" in one request.
    payment_methods = stripe_request(
        "GET",
        "/payment_methods",
        api_key=api_key,
        stripe_account=stripe_account,
        opener=opener,
        params=[("customer", customer_id)],
    )
    data = [pm for pm in (payment_methods.get("data") or []) if pm.get("id")]
    # PREFERENCE, not a gate. Card first because it is the most reliable off-session, then Link; anything
    # else is still attempted rather than refused here -- Stripe is the authority on whether a saved
    # method can be confirmed with the buyer gone, and a wrong guess at that list silently drops upsell
    # revenue. A type that genuinely cannot be reused now fails at the charge, where the error says so
    # and gets logged.
    for wanted in PREFERRED_PAYMENT_METHOD_TYPES:
        for pm in data:
            if pm.get("type") == wanted:
                return pm["id"]
    if data:
        return data[0]["id"]
    raise UpsellError("No saved payment method is attached to this customer.")


def update_customer_after_upsell(customers_repo, *, tenant_id, customer_id, amount, currency, product_name, order_id, now):
    if not customers_repo or not customer_id:
        return None
    existing = customers_repo.get(tenant_id, customer_id)
    if not existing:
        return None

    summary = dict(existing.get("summary") or {})
    summary["total_orders"] = int(summary.get("total_orders") or 0) + 1
    summary["total_spent"] = int(summary.get("total_spent") or 0) + amount
    summary["last_purchase_at"] = now
    summary["last_product_name"] = product_name

    transaction_history = list(existing.get("transaction_history") or [])
    transaction_history.append({
        "transaction_id": order_id,
        "type": "order",
        "order_id": order_id,
        "amount": amount,
        "currency": currency,
        "created_at": now,
    })

    updated = {**existing, "summary": summary, "transaction_history": transaction_history, "updated_at": now}
    return customers_repo.put(updated)


