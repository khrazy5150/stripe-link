import os
import time

from stripe_link.common import (
    error_response,
    json_response,
    parse_json_body,
    resolve_stripe_mode,
    tenant_id_from_event,
)
from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
from stripe_link.domain.fulfilment import order_fulfilment_state, product_index
from stripe_link.domain.handover import handover_groups
from stripe_link.domain.rate_policy import select_rate
from stripe_link.domain.returns import RETURN_STATES, return_deadline, return_label_expired
from stripe_link.domain.shipping import (
    ShipmentError,
    build_shipment,
    label_readiness,
    mark_failed,
    mark_purchased,
    packable_items,
    product_readiness,
    return_address,
    shipment_id_for,
    tenant_boxes,
)
from stripe_link.domain.shipping_packing import pack
from stripe_link.domain.carriers import carrier_options
from stripe_link.domain.shipping_providers import ProviderError, provider_for
from stripe_link.kms_secrets import KmsSecretCipher, is_encrypted_secret_ref
from stripe_link.domain.shipment_notice import notify_buyer
from stripe_link.repositories.documents import (
    RepositoryError,
    orders_repository,
    products_repository,
    refund_requests_repository,
    shipments_repository,
    shipping_config_repository,
)


REDACTED_SECRET = "********"
# Provider api_key_ref values that are already stored references, not a freshly-typed key.
KNOWN_SECRET_REF_PREFIXES = ("kms:v1:", "kms://", "secretsmanager://")
# Encryption context values binding a provider key ciphertext to this document/field.
SECRET_MODE = "shipping"
SECRET_FIELD = "provider.api_key_ref"


def _action(event) -> str:
    """The trailing path segment: /shipping, /shipping/test, /shipping/rates."""
    path = str((event or {}).get("resource") or (event or {}).get("path") or "")
    return path.rstrip("/").rsplit("/", 1)[-1].lower()


def handler(event, context, repository=None, secret_cipher=None, products_repo=None, orders_repo=None,
            shipments_repo=None, user_profiles_repo=None, mailer_send=None,
            refund_requests_repo=None, now_fn=lambda: int(time.time())):
    repository = repository or shipping_config_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    # /shipping/test BEFORE the save branch: it is a POST too, and a save would try to validate a body
    # that a connection test does not send.
    path = str((event or {}).get("path") or (event or {}).get("resource") or "")
    if method == "POST" and path.rstrip("/").endswith("/test"):
        return test_shipping_connection(event, repository, secret_cipher)
    if _action(event) in {"pickups", "manifests"} and method == "POST":
        return handover(event, repository, secret_cipher, _action(event),
                        shipments_repo=shipments_repo, now_fn=now_fn)
    if _action(event) == "return-labels" and method == "POST":
        return buy_return_label(event, repository, secret_cipher, orders_repo=orders_repo,
                                shipments_repo=shipments_repo, refund_requests_repo=refund_requests_repo,
                                now_fn=now_fn)
    if _action(event) == "labels" and method == "POST":
        return buy_label(event, repository, secret_cipher, products_repo=products_repo,
                         orders_repo=orders_repo, shipments_repo=shipments_repo,
                         user_profiles_repo=user_profiles_repo, mailer_send=mailer_send, now_fn=now_fn)
    if _action(event) == "carriers" and method == "GET":
        return list_carriers(event, repository, secret_cipher)
    if _action(event) == "rates" and method == "POST":
        return quote_rates(event, repository, secret_cipher, products_repo=products_repo,
                           orders_repo=orders_repo)
    if method in {"POST", "PUT"}:
        return save_shipping_config(event, repository, secret_cipher, products_repo)
    if method == "GET":
        tenant_id = tenant_id_from_event(event)
        if not tenant_id:
            return error_response("tenant_id is required.", code="missing_tenant")
        config = repository.get(tenant_id)
        if not config:
            return error_response("Shipping config not found.", status_code=404, code="not_found")
        return json_response({
            "shipping_config": redact_shipping_config(config),
            "readiness": label_readiness(config),
            # Separate from `readiness` on purpose: that one is about THIS document and blocks labels,
            # while this is about the catalogue and costs money without blocking anything.
            "product_readiness": catalogue_readiness(
                tenant_id, products_repo, resolve_stripe_mode(event)),
        })
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def catalogue_readiness(tenant_id: str, products_repo=None, mode: str = "test") -> list[str]:
    """What the PRODUCTS still need before an order can be packed into one box.

    Best-effort and never raises: this is advice on a settings screen, and a products table that will not
    read is not a reason to fail the shipping config the tenant came here to save. An empty list on
    failure under-reports, which is the right direction for a hint -- the packer itself still falls back
    to one parcel per item, so nothing is silently mis-shipped by the advice going missing.
    """
    try:
        repo = products_repo or (products_repository(mode=mode) if os.environ.get("PRODUCTS_TABLE") else None)
        if repo is None:
            return []
        return product_readiness(repo.list_for_tenant(tenant_id))
    except Exception:  # noqa: BLE001 - a hint must never cost the tenant their save
        return []


def save_shipping_config(event, repository, secret_cipher, products_repo=None):
    try:
        document = parse_json_body(event)
        tenant_id = str(document.get("tenant_id") or "").strip()
        existing = repository.get(tenant_id) if tenant_id else None
        document = prepare_provider_secret(document, existing, secret_cipher)
        validate_shipping_config(document)
        saved = repository.put(document)
        # Readiness travels with every response so the screen never has to compute it from unsaved form
        # state -- which is how it came to say "Ready to buy labels" about boxes a failed save had dropped.
        return json_response({
            "shipping_config": redact_shipping_config(saved),
            "readiness": label_readiness(saved),
            "product_readiness": catalogue_readiness(
                tenant_id, products_repo, resolve_stripe_mode(event)),
        }, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_shipping_config")


def _looks_like_secret_ref(value: str) -> bool:
    return is_encrypted_secret_ref(value) or value.startswith(KNOWN_SECRET_REF_PREFIXES)


def prepare_provider_secret(document, existing, secret_cipher):
    """Encrypt a newly-entered provider API key, or preserve/clear the stored one.

    The provider key is saved as a unit with its provider name: an unchanged key is
    preserved only while the provider is unchanged; selecting a different provider without
    entering a new key clears the old key so a key never lingers on the wrong provider.
    """
    provider = dict(document.get("provider") or {})
    existing_provider = dict((existing or {}).get("provider") or {})
    tenant_id = str(document.get("tenant_id") or "").strip()

    submitted = str(provider.get("api_key_ref") or "").strip()
    new_name = provider.get("name")
    old_name = existing_provider.get("name")
    old_ref = existing_provider.get("api_key_ref")

    if submitted and submitted != REDACTED_SECRET and not _looks_like_secret_ref(submitted):
        # A freshly-typed plaintext key: encrypt it and mark the connection untested.
        provider["api_key_ref"] = secret_cipher.encrypt(
            submitted, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD
        )
        provider["connection_status"] = "untested"
        provider.pop("last_tested_at", None)
    elif submitted and _looks_like_secret_ref(submitted):
        # Already a stored reference (e.g. seeded fixture): keep it as-is.
        provider["api_key_ref"] = submitted
    elif old_ref and new_name == old_name:
        # No new key and the same provider: preserve the stored key and its status.
        provider["api_key_ref"] = old_ref
        provider.setdefault("connection_status", existing_provider.get("connection_status") or "untested")
        if existing_provider.get("last_tested_at") is not None:
            provider.setdefault("last_tested_at", existing_provider["last_tested_at"])
    else:
        # No key, or the provider changed without a new key: drop it.
        provider.pop("api_key_ref", None)
        provider["connection_status"] = "not_configured"
        provider.pop("last_tested_at", None)

    document["provider"] = provider
    return document


def redact_shipping_config(config):
    if not config:
        return config
    redacted = dict(config)
    provider = dict(redacted.get("provider") or {})
    if provider.get("api_key_ref"):
        provider["api_key_ref"] = REDACTED_SECRET
    redacted["provider"] = provider
    return redacted


def test_shipping_connection(event, repository, secret_cipher, now_fn=lambda: int(time.time())):
    """Prove the saved key actually works, and record the answer on the config.

    `connection_status` has existed since the schema was written and could only ever say "untested": nothing
    tested it, and there was no endpoint to. The dashboard has been displaying a field that nothing could
    advance.

    The key is decrypted here and never leaves: it is not returned, not logged, and not put in an error.
    A provider's own error text is passed through because it is how a tenant learns what is wrong -- and
    the adapters build those messages from the response BODY, never from the request, whose headers carry
    the key.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    config = repository.get(tenant_id)
    if not config:
        return error_response("Shipping config not found.", status_code=404, code="not_found")

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    if not secret_ref and name != "mock":
        return error_response("Save a provider API key before testing the connection.",
                              code="missing_api_key")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        result = provider_for(name, api_key).test_connection()
        status, message, carriers = "connected", str(result.get("message") or "Connected."), result.get("carriers") or []
    except ProviderError as exc:
        status, message, carriers = "failed", str(exc), []
    except Exception as exc:  # noqa: BLE001 - a failed test is an ANSWER, never a 500
        status, message, carriers = "failed", f"Could not test the connection: {type(exc).__name__}", []

    provider_config["connection_status"] = status
    provider_config["last_tested_at"] = now_fn()
    saved = repository.put({**config, "provider": provider_config})
    return json_response({
        "shipping_config": redact_shipping_config(saved),
        "connection": {"status": status, "message": message, "carriers": carriers},
        "readiness": label_readiness(saved),
    }, status_code=200 if status == "connected" else 502)


def list_carriers(event, repository, secret_cipher):
    """Which carriers this tenant may pick from. Their CONNECTED ones when we can ask, else the registry.

    plans/SHIPPING_ELEMENT.md. The Services and Allowed-Carriers fields were free text, which invites typos --
    and worse, invites a service code no carrier recognises. A picker cannot fix the second problem on its own
    (that is what the rate viewer is for) but it removes the first entirely.

    Asking the provider beats the static list because it is the tenant's OWN answer: someone with no UPS
    account should not be offered UPS. When there is no provider, no key, or the provider is unreachable, the
    registry still gives a picker -- which is the whole point, since a field that falls back to free text
    falls back to the bug.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    registry = carrier_options()
    payload = {"carriers": registry, "source": "registry", "connected": []}
    config = repository.get(tenant_id) or {}
    provider = config.get("provider") or {}
    name = str(provider.get("name") or "").strip()
    key_ref = str(provider.get("api_key_ref") or "").strip()
    if not name or not key_ref:
        return json_response(payload)

    try:
        # Same call shape as `test_shipping_connection` -- decrypt needs the tenant/mode/field, and omitting
        # them raises rather than returning a wrong key.
        api_key = secret_cipher.decrypt(
            key_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        )
        connected = provider_for(name, api_key, base_url=str(provider.get("base_url") or "")) \
            .test_connection().get("carriers") or []
    except Exception as exc:  # noqa: BLE001 - follows test_shipping_connection: a failed lookup is an ANSWER
        # NOT fatal: a picker backed by the registry is still a picker, and the whole point is that this field
        # never falls back to free text. The reason is reported so a tenant whose list looks short is not left
        # guessing, rather than silently getting the generic set.
        payload["message"] = f"Showing the standard carriers: {type(exc).__name__}"
        return json_response(payload)

    known = {str(option.get("key") or "").lower(): option for option in registry}
    # Their connected carriers first, each enriched with the registry's label and services where we know them.
    # A carrier the registry has never heard of is still offered -- the provider is the authority on what this
    # account can quote, and dropping it would hide a carrier the tenant actually has.
    carriers = []
    for code in connected:
        slug = str(code or "").strip().lower()
        if not slug:
            continue
        carriers.append(known.get(slug) or {"key": slug, "label": slug.upper(), "services": []})
    payload.update({"carriers": carriers or registry,
                    "source": "provider" if carriers else "registry",
                    "connected": [str(code).lower() for code in connected]})
    return json_response(payload)


def quote_rates(event, repository, secret_cipher, *, products_repo=None, orders_repo=None):
    """Rates for ONE order, packed by the same `pack()` every other caller uses.

    Rated on demand -- when a row is selected or expanded -- and never for a whole page at once. Every
    lookup is a provider shipment creation: a network call per order, rate-limited and slow, and rating
    forty rows nobody has acted on is waste that makes the screen feel broken.

    The returned rates are DISPLAY. The purchase re-rates, because a cached rate id can expire and a price
    shown ten minutes ago is not a price.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    order_id = str(parse_json_body(event).get("order_id") or "").strip()
    if not order_id:
        return error_response("An order id is required.", code="missing_order")

    config = repository.get(tenant_id)
    if not config:
        return error_response("Shipping config not found.", status_code=404, code="not_found")
    blockers = label_readiness(config)
    if blockers:
        return error_response(" ".join(blockers), code="not_ready")

    mode = resolve_stripe_mode(event)
    orders = orders_repo or orders_repository(mode=mode)
    order = orders.get(tenant_id, order_id)
    if not order:
        return error_response("Order not found.", status_code=404, code="order_not_found")

    products = (products_repo or products_repository(mode=mode)).list_for_tenant(tenant_id) or []
    state = order_fulfilment_state(
        order,
        products_by_id={str(p.get("product_id") or ""): p for p in products if p.get("product_id")},
        index=product_index(products),
    )
    # The same gate the row showed. Rating an ineligible order would let the screen and this endpoint
    # disagree about eligibility, which is the disagreement the server-side gates exist to prevent.
    if not state["eligible"]:
        return error_response(" ".join(state["reasons"]) or "This order cannot be shipped.",
                              code="not_eligible")

    parcels = pack(packable_items(state["lines"], {str(p.get("product_id") or ""): p for p in products}),
                   tenant_boxes(config))
    if not parcels:
        return error_response("Nothing in this order needs a parcel.", code="nothing_to_pack")
    if len(parcels) > 1:
        # Multi-parcel orders are out of scope for this slice and must say so rather than quietly quoting
        # postage for one box and shipping three (plans/ORDER_FULFILMENT.md, "Deliberately not").
        return error_response(
            f"This order needs {len(parcels)} parcels, and buying multi-parcel labels is not supported "
            "yet — mark it shipped manually once you have posted it.",
            code="multi_parcel")

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        rates = provider_for(name, api_key).rates(
            from_address=config.get("ship_from_address") or {},
            to_address=order.get("shipping_address") or {},
            parcel=parcels[0],
        )
    except ProviderError as exc:
        return error_response(str(exc), status_code=502, code="provider_error")

    # The policy lives on `rate_options` -- the object that was already about rates and that nothing had
    # ever written to -- rather than in a second, overlapping object beside it.
    selection = select_rate(rates, config.get("rate_options"))
    return json_response({
        "order_id": order_id,
        "parcel": parcels[0],
        "rates": selection["candidates"],
        "selected": selection["rate"],
        "selection_reason": selection["reason"],
        "withheld": selection["withheld"],
    })


def buy_label(event, repository, secret_cipher, *, products_repo=None, orders_repo=None,
              shipments_repo=None, user_profiles_repo=None, mailer_send=None,
              now_fn=lambda: int(time.time())):
    """Buy ONE label. Idempotent on the order, because a label is money that cannot be un-spent.

    Bulk is the CLIENT driving this endpoint with limited concurrency: twenty purchases cannot happen
    inside one API Gateway request, and a timeout mid-batch would leave the tenant not knowing which
    labels were bought -- the worst possible failure for an action that spends money.

    The shipment row is claimed BEFORE the provider is called (`build_shipment` starts at `purchasing`),
    so a crash between the two leaves a row saying "we were buying this" rather than a silently bought
    label nobody recorded.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = parse_json_body(event)
    order_id = str(body.get("order_id") or "").strip()
    rate_id = str(body.get("rate_id") or "").strip()
    if not order_id or not rate_id:
        return error_response("An order id and a rate id are required.", code="missing_rate")

    config = repository.get(tenant_id)
    if not config:
        return error_response("Shipping config not found.", status_code=404, code="not_found")
    blockers = label_readiness(config)
    if blockers:
        return error_response(" ".join(blockers), code="not_ready")

    mode = resolve_stripe_mode(event)
    orders = orders_repo or orders_repository(mode=mode)
    order = orders.get(tenant_id, order_id)
    if not order:
        return error_response("Order not found.", status_code=404, code="order_not_found")

    shipments = shipments_repo or shipments_repository(mode=mode)
    shipment_id = shipment_id_for(order_id)
    existing = shipments.get(tenant_id, shipment_id)
    if existing and existing.get("status") in {"purchased", "shipped"}:
        # The second click, or the retry. Hand back the label that was already bought rather than buying
        # a second one at the carrier.
        return json_response({"shipment": existing, "already_bought": True})

    parcel = body.get("parcel") if isinstance(body.get("parcel"), dict) else None
    if not parcel:
        return error_response("Re-quote this order before buying.", code="missing_parcel")

    now = int(now_fn())
    try:
        claim = build_shipment(order=order, from_address=config.get("ship_from_address") or {},
                               parcel=parcel, now=now)
    except ShipmentError as exc:
        return error_response(str(exc), code="invalid_shipment")
    try:
        shipments.put(claim)
    except RepositoryError as exc:
        return error_response(str(exc), code="shipment_not_saved")

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    label_format = str((config.get("label_options") or {}).get("format") or "pdf")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        purchase = provider_for(name, api_key).buy_label(
            rate_id=rate_id, label_format=label_format,
            # Derived from the order, so a retry asks the CARRIER for the same label too.
            idempotency_key=shipment_id)
    except ProviderError as exc:
        failed = mark_failed(claim, str(exc), now=now)
        try:
            shipments.put(failed)
        except RepositoryError:
            pass
        return error_response(str(exc), status_code=502, code="provider_error")

    amount = body.get("amount")
    # Reshape the adapter's flat answer into the shape Shipment.schema.json declares: `provider` is an
    # OBJECT carrying the ids needed to reconcile a label that was bought but not saved.
    purchase_record = {
        **{k: v for k, v in purchase.items() if k != "provider" and not k.startswith("provider_")},
        "provider": {
            "name": str(purchase.get("provider") or name),
            "rate_id": rate_id,
            "transaction_id": str(purchase.get("provider_transaction_id") or ""),
            "idempotency_key": shipment_id,
        },
    }
    if amount is not None:
        purchase_record["cost"] = {"amount": int(amount), "currency": str(body.get("currency") or "usd")}
    purchased = mark_purchased(claim, purchase=purchase_record, now=now)
    try:
        saved = shipments.put(purchased)
    except RepositoryError as exc:
        return error_response(str(exc), code="shipment_not_saved")

    # The buyer is told the same way the manual path tells them -- one builder, one mailer. Best-effort
    # HERE, unlike the manual path: the label is already bought and paid for, so a bounced address must
    # not turn a successful purchase into an error the tenant thinks they should retry.
    notified = notify_buyer(order, saved, tenant_id, has_tracking=True,
                            user_profiles_repo=user_profiles_repo, mailer_send=mailer_send)
    if notified.get("sent"):
        saved["notified_at"] = now
        try:
            shipments.put(saved)
        except RepositoryError:
            pass

    return json_response({"shipment": saved, "notification": notified}, status_code=201)


def buy_return_label(event, repository, secret_cipher, *, orders_repo=None, shipments_repo=None,
                     refund_requests_repo=None, now_fn=lambda: int(time.time())):
    """A label for the parcel coming BACK. The reverse of buy_label on the same primitive.

    Two things differ, and both are about money:

    1. **It is bought against a refund request that is already waiting for goods.** Issuing a return label
       for a refund nobody approved gives away postage for a parcel the tenant never asked for.
    2. **It expires.** The buyer has a short window to actually post it (the tenant's
       `return_window_days`, default 3). A label left open indefinitely holds the tenant's money hostage
       while the refund window -- which is finite, and shorter still for BNPL -- runs down.

    Return labels are commonly PAY-ON-SCAN, so an unused one usually costs nothing. That is what makes a
    short expiry safe rather than punitive, and it must be verified per carrier before it is relied on.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = parse_json_body(event)
    request_id = str(body.get("refund_request_id") or "").strip()
    rate_id = str(body.get("rate_id") or "").strip()
    parcel = body.get("parcel") if isinstance(body.get("parcel"), dict) else None
    if not request_id or not rate_id or not parcel:
        return error_response("A refund request, a rate and a parcel are required.",
                              code="missing_return_label")

    requests_repo = refund_requests_repo or refund_requests_repository()
    refund_request = requests_repo.get(tenant_id, request_id)
    if not refund_request:
        return error_response("Refund request not found.", status_code=404, code="not_found")
    if str(refund_request.get("status") or "") not in RETURN_STATES:
        return error_response("This refund request is not waiting on a return.", code="not_returning")
    # The forfeit. A second free label after the window lapsed is the tenant paying twice for a buyer who
    # did not post it the first time.
    if return_label_expired(refund_request, now=int(now_fn())):
        return error_response(
            "The return window for this refund has passed, so free return postage no longer applies.",
            code="return_window_passed")

    config = repository.get(tenant_id)
    if not config:
        return error_response("Shipping config not found.", status_code=404, code="not_found")
    blockers = label_readiness(config)
    if blockers:
        return error_response(" ".join(blockers), code="not_ready")

    mode = resolve_stripe_mode(event)
    orders = orders_repo or orders_repository(mode=mode)
    order = orders.get(tenant_id, str(refund_request.get("order_id") or ""))
    if not order:
        return error_response("Order for this refund request was not found.", status_code=404,
                              code="order_not_found")

    shipments = shipments_repo or shipments_repository(mode=mode)
    shipment_id = shipment_id_for(str(order.get("order_id") or ""), "return")
    existing = shipments.get(tenant_id, shipment_id)
    if existing and existing.get("status") in {"purchased", "shipped"}:
        return json_response({"shipment": existing, "already_bought": True})

    now = int(now_fn())
    # Reversed: the parcel travels from the BUYER back to the tenant's return address.
    from_address = order.get("shipping_address") or {}
    to_address = return_address(config)
    try:
        claim = build_shipment(
            order={**order, "shipping_address": to_address},
            from_address=from_address, parcel=parcel, kind="return", now=now)
    except ShipmentError as exc:
        return error_response(str(exc), code="invalid_shipment")
    claim["refund_request_id"] = request_id
    claim["expires_at"] = return_deadline(refund_request, now=now)
    try:
        shipments.put(claim)
    except RepositoryError as exc:
        return error_response(str(exc), code="shipment_not_saved")

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        purchase = provider_for(name, api_key).buy_label(
            rate_id=rate_id,
            label_format=str((config.get("label_options") or {}).get("format") or "pdf"),
            idempotency_key=shipment_id)
    except ProviderError as exc:
        failed = mark_failed(claim, str(exc), now=now)
        try:
            shipments.put(failed)
        except RepositoryError:
            pass
        return error_response(str(exc), status_code=502, code="provider_error")

    purchase_record = {
        **{k: v for k, v in purchase.items() if k != "provider" and not k.startswith("provider_")},
        "provider": {"name": str(purchase.get("provider") or name), "rate_id": rate_id,
                     "transaction_id": str(purchase.get("provider_transaction_id") or ""),
                     "idempotency_key": shipment_id},
    }
    amount = body.get("amount")
    if amount is not None:
        purchase_record["cost"] = {"amount": int(amount), "currency": str(body.get("currency") or "usd")}
    purchased = mark_purchased(claim, purchase=purchase_record, now=now)
    purchased["refund_request_id"] = request_id
    purchased["expires_at"] = claim["expires_at"]
    try:
        saved = shipments.put(purchased)
    except RepositoryError as exc:
        return error_response(str(exc), code="shipment_not_saved")

    # The request remembers its label, so the screen can show the buyer's tracking without a second lookup.
    refund_request["return_shipment_id"] = shipment_id
    refund_request["return_label_expires_at"] = saved["expires_at"]
    try:
        requests_repo.put(refund_request)
    except RepositoryError:
        pass

    return json_response({"shipment": saved, "refund_request": refund_request,
                          "expires_at": saved["expires_at"]}, status_code=201)


def handover(event, repository, secret_cipher, kind, *, shipments_repo=None,
             now_fn=lambda: int(time.time())):
    """Schedule a pickup, or create a manifest, for ONE carrier's labels from ONE day.

    That constraint is the carrier's: a manifest lists the labels a driver will scan, and a driver scans
    one carrier's parcels from one address on one day. Sending a mixed batch fails at the carrier, so the
    batch is validated here before a request is made rather than after it is refused.

    Only labels WE bought can be handed over. A parcel the tenant marked shipped themselves has no
    provider transaction, so there is nothing for the carrier to scan -- it is excluded by `manifestable`,
    not rejected with an error, because the tenant did nothing wrong.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = parse_json_body(event)
    carrier = str(body.get("carrier") or "").strip().lower()
    day = str(body.get("ship_date") or "").strip()
    if not carrier or not day:
        return error_response("A carrier and a ship date are required.", code="missing_batch")

    config = repository.get(tenant_id)
    if not config:
        return error_response("Shipping config not found.", status_code=404, code="not_found")
    blockers = label_readiness(config)
    if blockers:
        return error_response(" ".join(blockers), code="not_ready")

    shipments = shipments_repo or shipments_repository(mode=resolve_stripe_mode(event))
    groups = handover_groups(shipments.list_for_tenant(tenant_id) or [])
    group = next((g for g in groups if g["carrier"] == carrier and g["ship_date"] == day), None)
    if not group:
        return error_response(
            f"No {carrier.upper()} labels bought on {day} are waiting to be handed over.",
            code="nothing_to_hand_over")

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    ship_from = config.get("ship_from_address") or {}
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        provider = provider_for(name, api_key)
        account = _carrier_account_for(provider, carrier)
        if not account:
            return error_response(
                f"Your {name} account has no active {carrier.upper()} carrier account to hand these to.",
                code="no_carrier_account")
        if kind == "pickups":
            result = provider.schedule_pickup(
                carrier_account=account,
                location={"address": ship_from,
                          "building_location_type": str(body.get("building_location_type") or "Front Door")},
                transactions=group["transactions"],
                start_time=str(body.get("start_time") or ""),
                end_time=str(body.get("end_time") or ""))
        else:
            result = provider.create_manifest(
                carrier_account=account,
                ship_date=day,
                address_from=provider.create_address(ship_from),
                transactions=group["transactions"])
    except ProviderError as exc:
        return error_response(str(exc), status_code=502, code="provider_error")

    now = int(now_fn())
    stamped = []
    for shipment in group["shipments"]:
        updated = dict(shipment)
        if kind == "manifests":
            # Recorded so the same labels are never manifested twice -- a carrier refuses the second, and
            # the tenant would have no way to tell which document their parcels are actually on.
            updated["manifest_id"] = str(result.get("manifest_id") or "")
        else:
            updated["pickup_id"] = str(result.get("pickup_id") or "")
            updated["pickup_confirmation"] = str(result.get("confirmation_code") or "")
        updated["updated_at"] = now
        try:
            stamped.append(shipments.put(updated))
        except RepositoryError:
            stamped.append(updated)

    return json_response({kind[:-1]: result, "shipments": len(stamped),
                          "carrier": carrier, "ship_date": day}, status_code=201)


def _carrier_account_for(provider, carrier: str) -> str:
    """The provider's account id for this carrier, which a pickup and a manifest both have to name."""
    try:
        accounts = provider.carrier_accounts() or []
    except ProviderError:
        return ""
    for account in accounts:
        if str(account.get("carrier") or "").lower() == carrier and account.get("active"):
            return str(account.get("account_id") or "")
    return ""
