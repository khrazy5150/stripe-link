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
    dimensions_consequence,
    label_readiness,
    mark_failed,
    mark_purchased,
    packable_items,
    product_readiness,
    return_address,
    unmeasured_products,
    shipment_id_for,
    tenant_boxes,
)
from stripe_link.domain.shipping_packing import pack
from stripe_link.domain.shipping_rating import rate_parcels
from stripe_link.domain.opportunities import STAGE_CHECKOUT, stage_opportunities
from stripe_link.domain.carriers import carrier_options
from stripe_link.domain.shipping_providers import ProviderError, provider_for
from stripe_link.kms_secrets import KmsSecretCipher, is_encrypted_secret_ref
from stripe_link.domain.fulfilment_groups import group_parcels
from stripe_link.domain.shipment_notice import notify_buyer, revision_for
from stripe_link.domain.shipping import sender_address
from stripe_link.domain.shipping_promise import revised_sentence
from stripe_link.repositories.documents import (
    RepositoryError,
    offers_repository,
    orders_repository,
    products_repository,
    refund_requests_repository,
    shipments_repository,
    shipping_config_repository,
    user_profiles_repository,
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
            refund_requests_repo=None, offers_repo=None, now_fn=lambda: int(time.time())):
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
    if _action(event) == "rate-preview" and method == "POST":
        return preview_rates(event, repository, secret_cipher, products_repo=products_repo,
                             offers_repo=offers_repo)
    if _action(event) == "carriers" and method == "GET":
        return list_carriers(event, repository, secret_cipher)
    if _action(event) == "parcel-templates" and method == "GET":
        return list_parcel_templates(event, repository, secret_cipher)
    if _action(event) == "pack-preview" and method == "POST":
        return pack_preview(event, repository)
    if _action(event) == "measure" and method == "POST":
        return measure_products(event, repository, products_repo=products_repo)
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
            # What an UNMEASURED product costs this tenant, given the zones they actually configured --
            # so the product form can say something true rather than one sentence that fits every case
            # (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0b).
            "dimensions_consequence": dimensions_consequence(config),
            # The same gap `product_readiness` states in prose, in a shape a screen can EDIT. The warning
            # becomes the fix (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0d).
            "unmeasured_products": _unmeasured_catalogue(tenant_id, products_repo,
                                                         resolve_stripe_mode(event)),
        })
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def _unmeasured_catalogue(tenant_id: str, products_repo=None, mode: str = "test") -> list[dict]:
    """`unmeasured_products` over the tenant's catalogue. Best-effort, like its prose sibling."""
    try:
        repo = products_repo or (products_repository(mode=mode) if os.environ.get("PRODUCTS_TABLE") else None)
        return unmeasured_products(repo.list_for_tenant(tenant_id)) if repo else []
    except Exception:  # noqa: BLE001 - advice must never cost the tenant their save
        return []


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
            "dimensions_consequence": dimensions_consequence(saved),
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


# Real, public addresses used purely as a RATING SAMPLE. A carrier will not quote a postcode that does not
# exist, and -- found by calling the live API -- Shippo refuses outright when the origin and destination are
# identical ("From and To Addresses are identical"), which is what defaulting to the tenant's own ship-from
# produced. So the sample is a genuine metro address in the tenant's own country, far enough from anywhere to
# be a representative domestic rate. The tenant can type their own instead.
SAMPLE_DESTINATIONS = {
    "US": [
        {"name": "Sample", "street1": "350 5th Ave", "city": "New York", "state": "NY",
         "postal_code": "10001", "country": "US"},
        {"name": "Sample", "street1": "1 Dr Carlton B Goodlett Pl", "city": "San Francisco", "state": "CA",
         "postal_code": "94102", "country": "US"},
    ],
    "CA": [
        {"name": "Sample", "street1": "290 Bremner Blvd", "city": "Toronto", "state": "ON",
         "postal_code": "M5V 3L9", "country": "CA"},
        {"name": "Sample", "street1": "1055 Canada Pl", "city": "Vancouver", "state": "BC",
         "postal_code": "V6C 0C3", "country": "CA"},
    ],
    "GB": [
        {"name": "Sample", "street1": "10 Downing St", "city": "London", "state": "",
         "postal_code": "SW1A 2AA", "country": "GB"},
        {"name": "Sample", "street1": "1 St Peter's Sq", "city": "Manchester", "state": "",
         "postal_code": "M2 3AE", "country": "GB"},
    ],
}


def _sample_destination(from_address: dict, typed: dict) -> dict:
    """Where to rate TO. The tenant's own words first, then a real sample in their country.

    **Never the origin itself.** Found by calling the live API: Shippo refuses outright when the addresses
    match ("From and To Addresses are identical"), and that refusal reads like our bug rather than their rule.
    Defaulting to the tenant's own ship-from -- which seemed the most helpful thing -- guaranteed it.

    TWO samples per country, because one is not enough: a tenant whose warehouse IS in the sample city would
    hit the same refusal. The first whose postcode differs from the origin wins.
    """
    typed = {k: v for k, v in (typed or {}).items() if v}
    country = str(typed.get("country") or from_address.get("country") or "US").strip().upper()[:2]
    samples = SAMPLE_DESTINATIONS.get(country) or SAMPLE_DESTINATIONS["US"]
    origin = str(from_address.get("postal_code") or "").strip().lower()

    if typed.get("postal_code"):
        # They asked for somewhere specific. Honoured even if it is their own address -- the carrier's refusal
        # is then an answer to a question they actually asked, and it is translated into plain words.
        return {**samples[0], **typed}
    chosen = next((s for s in samples if str(s["postal_code"]).strip().lower() != origin), samples[0])
    return {**chosen, **typed}


def record_shipping_cost_entry(order, shipment, *, now, ledger_repo=None):
    """Append what the carrier charged to the transaction ledger.

    Its own entry rather than an edit to the sale: the ledger is append-only, and the label is bought after
    the sale -- sometimes days after. Keyed on the shipment, so a retried purchase cannot double-count
    postage the tenant only bought once.

    Returns True when written. **Never raises** -- a bookkeeping append must not read as a failed label.
    """
    from stripe_link.domain.ledger import shipping_cost_entry_from_shipment

    try:
        entry = shipping_cost_entry_from_shipment(shipment, order, now_epoch=now)
        if not entry:
            return False
        repo = ledger_repo
        if repo is None:
            if not os.environ.get("LEDGER_TABLE"):
                return False
            from stripe_link.repositories.documents import ledger_repository

            repo = ledger_repository(mode=entry.get("mode"))
        repo.append(entry)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[shipping] shipping cost not recorded for order "
              f"{(order or {}).get('order_id')}: {type(exc).__name__}: {exc}")
        return False


def record_shipping_variance(order, shipment, tenant_id, *, mode, now, actuals_repo=None):
    """Compare the label's real cost with the quote the buyer agreed to, and keep both.

    plans/LIVE_SHIPPING_RATES.md phase 5. Writes a `shipping_actual` row, keyed per ORDER because two
    buyers can share one quote but never share a label.

    **It does NOT write back to the order**, deliberately. This function holds read-only access to orders,
    and a `{**order, ...}` put from here would race the webhook's own updates and silently clobber
    whichever lost -- a bookkeeping note is not worth corrupting an order over. The Orders view reads the
    variance from its own record instead.

    Returns the variance, or `{}` when there is nothing to compare -- an order with no quote, or a label
    with no cost. **Never raises.** The label is bought and the parcel is going; a bookkeeping failure
    must not read as a failed purchase.

    Flagging is ONE-DIRECTIONAL by the author's rule: a label cheaper than the quote is recorded as a
    saving and raises nothing.
    """
    from stripe_link.domain.shipping_quotes import build_actual

    agreed = (order or {}).get("shipping_quote") or {}
    cost = (shipment or {}).get("cost") or {}
    if not agreed.get("quote_id") or cost.get("amount") is None:
        return {}
    try:
        record = build_actual(
            quote_id=agreed.get("quote_id", ""),
            order_id=str((order or {}).get("order_id") or ""),
            service_token=str(shipment.get("service") or agreed.get("service_token") or ""),
            amount=cost.get("amount"), quoted_amount=agreed.get("quoted_amount"),
            destination={"postal_code": agreed.get("actual_postal_code"),
                         "country": ((order or {}).get("shipping_address") or {}).get("country")},
            quoted_destination={"postal_code": agreed.get("quoted_postal_code"),
                                "country": ((order or {}).get("shipping_address") or {}).get("country")},
            carrier=str(shipment.get("carrier") or ""),
            currency=str(cost.get("currency") or "usd"), now=now)
        # The ORIGINAL service, kept beside what actually shipped. A carrier that could not carry the
        # quoted service is a different exception from a price that moved, and conflating them would tell
        # the tenant their postage went up when in fact the buyer's chosen speed was never available.
        record["quoted_service_token"] = str(agreed.get("service_token") or "")
        record["service_substituted"] = bool(
            record["quoted_service_token"] and record["service_token"] != record["quoted_service_token"])
        # tenant_id lives ON the document: `put` takes one argument and keys from it.
        record["tenant_id"] = tenant_id
        (actuals_repo or _shipping_actuals_repo(mode)).put(record)
    except Exception as exc:  # noqa: BLE001
        print(f"[shipping] variance not recorded for order "
              f"{(order or {}).get('order_id')}: {type(exc).__name__}: {exc}")
        return {}
    return record


def _shipping_actuals_repo(mode):
    from stripe_link.repositories.documents import shipping_actuals_repository

    return shipping_actuals_repository(mode=mode)


def live_rates_for(config, tenant_id, *, parcels, destination, secret_cipher):
    """Live carrier rates for a BUYER's parcels, to a BUYER's address.

    plans/LIVE_SHIPPING_RATES.md phase 2. Lives here rather than in `handlers/checkout` because this is
    where the provider key is named and decrypted (`SECRET_MODE` / `SECRET_FIELD`), and a second place that
    knows how to open a carrier credential is a second place to get it wrong.

    Returns `{options, error}` and **never raises**. Every failure -- no provider, no key, no ship-from
    address, a carrier having a bad minute -- comes back as a reason, because the caller is a landing page
    and the honest answer there is "we could not get rates", never a 500 and never a silent zero.
    """
    from stripe_link.domain.shipping_rating import rate_parcels

    provider_config = dict((config or {}).get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    if not name or not secret_ref:
        return {"options": [], "error": "no_provider"}
    from_address = sender_address((config or {}).get("ship_from_address") or {},
                                  *_seller_contact(tenant_id, None))
    if not from_address.get("postal_code"):
        # A carrier prices a JOURNEY. Without an origin there is nothing to price, and Shippo rejects the
        # request rather than guessing -- so this is caught here where it can be named.
        return {"options": [], "error": "no_ship_from"}
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable key is one answer, not a broken page
        return {"options": [], "error": f"key_unreadable: {type(exc).__name__}"}
    return rate_parcels(provider_for(name, api_key), from_address=from_address,
                        to_address=destination, parcels=parcels)


def preview_rates(event, repository, secret_cipher, *, products_repo=None, offers_repo=None):
    """What the carriers would charge for a sample parcel, so a tenant can DISCOVER real services.

    plans/SHIPPING_ELEMENT.md. The author, 2026-09-30: let a tenant pick products and a box, ask for rates, and
    adopt one as a Service.

    **What this is for is the service IDENTITY, not the price.** A `service_code` a tenant invents never matches
    a real rate -- Shippo's token for USPS ground is `usps_ground_advantage`, and "ground" can never be quoted,
    with nothing to say so until a buyer sees no options. The amounts here are CONTEXT: they tell a tenant what
    a flat rate should be set to. They are deliberately not written into a zone, because a rate is
    destination-specific and stale within days while `usps_ground_advantage` is stable and is exactly what a
    later live quote has to match.

    The destination defaults to the tenant's OWN ship-from address -- a real domestic sample needs no typing,
    and carriers refuse to quote a made-up one.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = parse_json_body(event)
    offer_id = str(body.get("offer_id") or "").strip()
    product_ids = [str(pid).strip() for pid in (body.get("product_ids") or []) if str(pid).strip()]
    if not offer_id and not product_ids:
        return error_response("Choose an offer or at least one product to rate.", code="missing_subject")

    config = repository.get(tenant_id) or {}
    from_address = config.get("ship_from_address") or {}
    if not from_address.get("postal_code"):
        return error_response("Add your ship-from address before previewing rates.",
                              code="missing_ship_from")
    destination = _sample_destination(from_address, body.get("to_address") or {})

    mode = resolve_stripe_mode(event)
    products_repo = products_repo or products_repository(mode=mode)
    quantities = body.get("quantities") or {}

    if offer_id:
        offer = (offers_repo or offers_repository(mode=mode)).get(tenant_id, offer_id)
        if not offer:
            return error_response("Offer not found.", status_code=404, code="offer_not_found")
        lines = [{"product_id": str(item.get("product_id") or ""),
                  "quantity": max(1, int(item.get("quantity") or 1))}
                 for item in (offer.get("items") or []) if item.get("product_id")]
        bump_lines = [{"product_id": str(bump.get("product_id") or ""), "quantity": 1}
                      for bump in stage_opportunities(offer, STAGE_CHECKOUT) if bump.get("product_id")]
    else:
        lines = [{"product_id": pid, "quantity": max(1, int(quantities.get(pid) or 1))}
                 for pid in product_ids]
        bump_lines = []
    if not lines:
        return error_response("That offer has nothing to ship.", code="nothing_to_ship")

    products = {}
    for line in lines + bump_lines:
        pid = line["product_id"]
        if pid in products:
            continue
        product = products_repo.get(tenant_id, pid)
        if not product:
            return error_response(f"Product '{pid}' was not found.", status_code=404,
                                  code="product_not_found")
        products[pid] = product

    boxes = tenant_boxes(config)
    wanted_box = str(body.get("box") or "").strip()
    if wanted_box:
        # A tenant comparing boxes wants THIS box rated, not the one the packer prefers.
        boxes = [box for box in boxes if str(box.get("name") or "") == wanted_box] or boxes
    parcels = pack(packable_items(lines, products), boxes)
    if not parcels:
        # NOT an error. This is the P0a answer said in the estimator's own terms: nothing measurable, so
        # nothing to charge, so the offer ships free. Refusing with a 400 told a tenant their request was
        # malformed when the truth was that their catalogue is.
        return json_response({
            "rates": [], "parcels": [], "parcel_count": 0, "ships_free": True,
            "unmeasured": _unmeasured_names(lines, products),
            "destination": {"country": destination.get("country", ""),
                            "postal_code": destination.get("postal_code", "")},
        })

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    if not name or not secret_ref:
        return error_response("Connect a shipping provider to preview live rates.",
                              code="missing_provider")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        )
        provider = provider_for(name, api_key)
        # EVERY parcel, summed -- the same `rate_parcels` a buyer's quote runs, so the preview cannot
        # disagree with checkout. It used to rate `parcels[0]` only, which is right when a tenant is
        # comparing boxes and wrong the moment the subject is an ORDER: a three-parcel bundle was shown one
        # parcel's price (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0e).
        rated = rate_parcels(provider, from_address=from_address, to_address=destination, parcels=parcels)
        if rated["error"]:
            raise ProviderError(rated["error"])
        rates = rated["options"]
    except ProviderError as exc:
        message = str(exc)
        if "identical" in message.lower():
            # Carrier-speak turned into something actionable. Reached when a tenant types their OWN postcode
            # as the destination, which is a reasonable thing to try.
            message = ("Rate to somewhere other than your own address — carriers will not quote a shipment "
                       "that starts and ends at the same place.")
        return error_response(message, status_code=502, code="provider_error")
    except Exception as exc:  # noqa: BLE001 - a failed preview is an ANSWER, never a 500
        return error_response(f"Could not reach the carrier: {type(exc).__name__}", status_code=502,
                              code="provider_error")

    return json_response({
        "rates": sorted(rates, key=lambda rate: int(rate.get("amount") or 0)),
        "parcel": parcels[0],
        # THE BREAKDOWN, not just a price. "3 parcels: Small x2, Medium x1" tells a tenant their products
        # are unmeasured far more plainly than a readiness list does, because it shows the consequence.
        "parcels": [{"box_name": pp.get("box_name") or pp.get("box") or "",
                     "length": pp.get("length"), "width": pp.get("width"), "height": pp.get("height"),
                     "weight": pp.get("weight"), "strategy": pp.get("strategy")} for pp in parcels],
        "parcel_count": len(parcels),
        "ships_free": False,
        "unmeasured": _unmeasured_names(lines, products),
        # WHAT AN ORDER BUMP WOULD ADD. Computed here because this is where a tenant is already looking at
        # shipping, and because a bump taken on Stripe's hosted page can never be priced at checkout --
        # `optional_items` are chosen after `shipping_options` is fixed. Disclosure is the whole remedy
        # available (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P2).
        **_bump_exposure(lines, bump_lines, products, boxes),
        "destination": {"country": destination.get("country", ""),
                        "postal_code": destination.get("postal_code", "")},
    })


def _unmeasured_names(lines, products):
    """Which of these products have no size of their own -- named, because "2 of 3" is not actionable."""
    names = []
    for line in lines or []:
        product = (products or {}).get(line.get("product_id")) or {}
        own = ((product.get("fulfillment") or {}).get("item_dimensions") or {})
        if not all(float(own.get(f) or 0) > 0 for f in ("length_in", "width_in", "height_in")):
            names.append(str(product.get("name") or line.get("product_id") or "a product"))
    return names


def _bump_exposure(lines, bump_lines, products, boxes):
    """How many extra parcels an order bump adds, which is postage the tenant will never be paid for.

    Returns `{}` when the offer has no bump. Parcel COUNT rather than a price: pricing it would mean a
    second carrier call for a figure whose point is "this is not free", and the count is what a tenant can
    act on -- a bump that adds no parcel is genuinely free to ship.
    """
    if not bump_lines:
        return {}
    base = len(pack(packable_items(lines, products), boxes))
    withbump = len(pack(packable_items(list(lines) + list(bump_lines), products), boxes))
    return {"bump_parcel_delta": max(0, withbump - base),
            "bump_products": [str((products.get(b["product_id"]) or {}).get("name") or b["product_id"])
                              for b in bump_lines]}


def measure_products(event, repository, *, products_repo=None):
    """Write item dimensions for several products at once.

    plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0d. `product_readiness` has named the unmeasured products
    since 2026-09-24 and the count has not moved: 2 of 15 dev, 0 of 4 prod. A better warning will not move
    it either -- **fourteen empty forms is the obstacle, not one form**. So the warning becomes the fix:
    the tenant measures everything from the screen already telling them it is missing, instead of opening
    a modal per product.

    It lives on the shipping handler rather than the products one because there is no general product
    update endpoint, and adding one to write four fields would be a much larger door than the job needs.
    Writes ONLY `fulfillment.item_dimensions` and the bare weight; everything else on the product is
    carried through untouched.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    rows = parse_json_body(event).get("measurements") or []
    if not rows:
        return error_response("Nothing to measure.", code="missing_measurements")

    repo = products_repo or products_repository(mode=resolve_stripe_mode(event))
    saved, skipped = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = str(row.get("product_id") or "").strip()
        dims = {field: row.get(field) for field in ("length_in", "width_in", "height_in", "weight_lb")}
        if not product_id or not all(_positive_number(dims[f])
                                     for f in ("length_in", "width_in", "height_in", "weight_lb")):
            # A partial row is not a measurement. Writing three of four sides would produce a product that
            # still cannot be rated while looking like it can -- worse than leaving it blank.
            skipped.append(product_id or "(no id)")
            continue
        product = repo.get(tenant_id, product_id)
        if not product:
            skipped.append(product_id)
            continue
        fulfillment = dict(product.get("fulfillment") or {})
        fulfillment["item_dimensions"] = {
            "length_in": float(dims["length_in"]), "width_in": float(dims["width_in"]),
            "height_in": float(dims["height_in"]), "weight_lb": float(dims["weight_lb"]),
        }
        try:
            repo.put({**product, "fulfillment": fulfillment})
            saved.append(product_id)
        except RepositoryError:
            skipped.append(product_id)

    products = repo.list_for_tenant(tenant_id) or []
    return json_response({
        "saved": saved, "skipped": skipped,
        "product_readiness": product_readiness(products),
        "unmeasured_products": unmeasured_products(products),
    })


def _positive_number(value) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def pack_preview(event, repository):
    """Which of the tenant's own boxes this product ships in, and what the parcel weighs. No carrier call.

    plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0c. The product form's own copy already promises this --
    *"Normally we work the box out from the sizes above"* -- and then never showed what was worked out, so
    a tenant overriding it was guessing against an answer they could not see.

    Takes dimensions INLINE rather than a product id, because the wizard asks before anything is saved: a
    preview that only worked for existing products would be absent exactly where the decision is made.

    Deliberately no rating. A price needs a destination this form has no business asking for, and the BOX
    is the answer that matters here -- it is what tells a tenant their override is unnecessary, or that
    three unmeasured items are about to ship as three parcels.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    body = parse_json_body(event)
    items = []
    for index, raw in enumerate(body.get("items") or []):
        if not isinstance(raw, dict):
            continue
        item = {"product_id": str(raw.get("product_id") or f"item_{index}"),
                "quantity": max(1, int(raw.get("quantity") or 1)),
                "weight": raw.get("weight"), "item_weight": raw.get("weight"),
                "compressible": bool(raw.get("compressible")),
                "ships_alone": bool(raw.get("ships_alone"))}
        for field in ("length", "width", "height"):
            if raw.get(field):
                item[field] = raw[field]
        package = raw.get("package") or {}
        if all(package.get(f) for f in ("length", "width", "height")):
            item["package"] = {f: package[f] for f in ("length", "width", "height")}
            item["package"]["weight"] = package.get("weight") or raw.get("weight")
        items.append(item)
    if not items:
        return json_response({"parcels": [], "reason": "no_items"})

    config = repository.get(tenant_id) or {}
    parcels = pack(items, tenant_boxes(config))
    return json_response({
        "parcels": [{"box_name": p.get("box_name") or p.get("box") or "",
                     "length": p.get("length"), "width": p.get("width"), "height": p.get("height"),
                     "weight": p.get("weight"), "strategy": p.get("strategy")}
                    for p in parcels],
        # Empty parcels is the P0a case, said in the form's own terms: nothing to pack, so nothing to
        # charge. The consequence banner beside it already explains what that costs this tenant.
        "reason": "" if parcels else "no_dimensions",
        "box_count": len(tenant_boxes(config)),
    })


def list_parcel_templates(event, repository, secret_cipher):
    """Carrier-supplied packaging the tenant can adopt as a box.

    plans/LIVE_SHIPPING_RATES.md phase 7. The rating path already forwards a box's `template` to the
    provider (`_shippo_parcel`), so this is the missing half: nothing ever told a tenant WHICH templates
    exist, which made the feature unreachable.

    Why it matters beside live rates rather than instead of them: a carrier flat-rate container is the one
    package whose price really is destination-independent, because the carrier says so. **A tenant's own
    carton never is**, whatever its dimensions -- it is rated on size, weight and distance like anything
    else, which is what the live path is for.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    config = repository.get(tenant_id) or {}
    provider = config.get("provider") or {}
    name = str(provider.get("name") or "").strip()
    key_ref = str(provider.get("api_key_ref") or "").strip()
    if not name or not key_ref:
        # An empty list with a reason, not an error: a tenant with no carrier has no carrier packaging,
        # and a 4xx here would read as "something is broken" rather than "connect a carrier first".
        return json_response({"templates": [], "reason": "no_provider"})
    try:
        api_key = secret_cipher.decrypt(
            key_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        )
        templates = provider_for(name, api_key).parcel_templates()
    except ProviderError as exc:
        return json_response({"templates": [], "reason": str(exc)[:200]})
    except Exception as exc:  # noqa: BLE001 - a picker that cannot populate is not a broken screen
        return json_response({"templates": [], "reason": f"{type(exc).__name__}"})
    return json_response({"templates": templates, "reason": ""})


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


def _fulfilment_group_for(order, tenant_id, orders_repo):
    """Every order that ships in the same box as this one, parent first.

    Reads the tenant's orders to find the siblings. Falls back to the order alone, because a group of one
    is the common case and an unreadable list must not stop a tenant buying a label.
    """
    try:
        from stripe_link.domain.fulfilment_groups import group_key, group_orders

        key = group_key(order)
        siblings = [o for o in (orders_repo.list_for_tenant(tenant_id) or [])
                    if group_key(o) == key]
        for members in group_orders(siblings):
            if any(str(o.get("order_id")) == str(order.get("order_id")) for o in members):
                return members
    except Exception as exc:  # noqa: BLE001
        print(f"[fulfilment] group lookup failed for {order.get('order_id')}: {type(exc).__name__}: {exc}")
    return [order]


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
    payload = parse_json_body(event)
    order_id = str(payload.get("order_id") or "").strip()
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

    # THE WHOLE GROUP, not just this order. An upsell is its own order because it is its own charge, and
    # rating them separately is how a funnel that collected $6.20 of postage was offered $18.20 of labels
    # -- three boxes to one address (plans/FULFILMENT_GROUPS.md). The buyer was charged $0 for those
    # upsells BECAUSE they ride along, so this has to pack what that promise priced.
    products_by_id = {str(p.get("product_id") or ""): p for p in products if p.get("product_id")}
    group = _fulfilment_group_for(order, tenant_id, orders)
    parcels = group_parcels(group, products_by_id=products_by_id, boxes=tenant_boxes(config),
                            index=product_index(products))
    if not parcels:
        return error_response("Nothing in this order needs a parcel.", code="nothing_to_pack")
    # ONE LINE, ONE LABEL. A group needing three boxes is three rates and three labels, each asked for by
    # index -- which `shipment_id_for(..., sequence=N)` was already built to key. The old answer here was
    # to refuse the whole order and tell the tenant to post it manually.
    parcel_index = max(0, int(payload.get("parcel_index") or 0))
    _group_parcel_count = len(parcels)
    if parcel_index >= _group_parcel_count:
        return error_response(f"This group has {_group_parcel_count} parcel(s).", code="no_such_parcel")
    parcels = [parcels[parcel_index]]

    provider_config = dict(config.get("provider") or {})
    name = str(provider_config.get("name") or "")
    secret_ref = str(provider_config.get("api_key_ref") or "")
    try:
        api_key = secret_cipher.decrypt(
            secret_ref, tenant_id=tenant_id, mode=SECRET_MODE, field=SECRET_FIELD,
        ) if secret_ref else ""
        rates = provider_for(name, api_key).rates(
            # THE EMAIL HAS TO BE ON THE RATE, not on the purchase. `buy_label` names a `rate_id` and
            # nothing else, so the sender address the carrier sees was fixed when this ran -- a rate
            # created without an email produces a rate id that cannot be bought, and the failure surfaces
            # one click later with the carrier's wording. Fixing only the purchase looked right and
            # changed nothing (2026-10-05).
            from_address=sender_address(config.get("ship_from_address") or {},
                                        *_seller_contact(tenant_id, None)),
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
        # WHICH BOX OF HOW MANY, so the screen can draw a line per parcel and the tenant can see what goes
        # in each. `parcel_index` rides back to the label purchase, where it becomes the shipment sequence.
        "parcel_index": parcel_index,
        "parcel_count": _group_parcel_count,
        "ships_with": [str(o.get("order_id") or "") for o in group],
        "rates": selection["candidates"],
        "selected": selection["rate"],
        "selection_reason": selection["reason"],
        "withheld": selection["withheld"],
        # WHAT THE BUYER WAS SOLD, beside what the carrier will now actually carry
        # (plans/LIVE_SHIPPING_RATES.md phase 5, the author's fourth decision). A service the carrier
        # cannot quote for the real address is NOT a price variance and must not be silently substituted:
        # the tenant sees the alternatives and their costs, and is told the original delivery estimate no
        # longer applies -- a buyer promised four days by UPS Ground Saver did not agree to whatever else
        # happens to be going.
        **quoted_service_status(order, rates),
    })


def quoted_service_status(order, rates):
    """Whether the service the buyer actually paid for is still available for this address.

    Returns `{}` when no quote priced the order -- most orders, and nothing to say about them. Otherwise
    `{"quoted_service": {...}}` carrying the token, whether it is still offered, and its price now.
    """
    agreed = (order or {}).get("shipping_quote") or {}
    token = str(agreed.get("service_token") or "")
    if not token:
        return {}
    match = next((r for r in rates or [] if str(r.get("service_token") or "") == token), None)
    return {"quoted_service": {
        "service_token": token,
        "quoted_amount": int(agreed.get("quoted_amount") or 0),
        "available": match is not None,
        "amount_now": int(match.get("amount") or 0) if match else None,
        # Said explicitly rather than left to inference. The buyer saw a delivery promise attached to the
        # service they chose; if that service cannot carry this parcel, the promise is void and the tenant
        # is the one who has to decide what to tell them.
        "estimate_still_applies": match is not None,
    }}


def _seller_contact(tenant_id, user_profiles_repo):
    """`(business, owner_email)` for the tenant, or `({}, "")`. Never raises: a missing profile means the
    ship-from address has to carry its own email, which is the next thing checked anyway."""
    try:
        repo = user_profiles_repo or (user_profiles_repository()
                                      if os.environ.get("USER_PROFILES_TABLE") else None)
        if repo is None:
            return {}, ""
        owner = repo.get(tenant_id, tenant_id) or {}
        return (owner.get("business") or {}), str(owner.get("email") or "")
    except Exception:  # noqa: BLE001
        return {}, ""


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
    # ONE SHIPMENT PER PARCEL. `sequence` already existed for a deliberate split and is exactly this: a
    # group needing two boxes buys `shp_<order>_outbound_1` and `_outbound_2`, so a double-clicked Buy
    # Label still loses the conditional write on its own parcel rather than buying a second label for it.
    shipment_id = shipment_id_for(order_id, sequence=max(1, int(body.get("parcel_index") or 0) + 1))
    existing = shipments.get(tenant_id, shipment_id)
    if existing and existing.get("status") in {"purchased", "shipped"}:
        # The second click, or the retry. Hand back the label that was already bought rather than buying
        # a second one at the carrier.
        return json_response({"shipment": existing, "already_bought": True})

    parcel = body.get("parcel") if isinstance(body.get("parcel"), dict) else None
    if not parcel:
        return error_response("Re-quote this order before buying.", code="missing_parcel")

    now = int(now_fn())
    # AN EMAIL ON THE SENDER, or the carrier refuses the purchase. Shippo rejects a label with
    # `address_from.email must not be empty` and does NOT reject a RATE request, so a tenant can price
    # parcels all week and only meet the gap at the moment they try to post one. Falls back to the
    # business email, then the account they sign in with -- all three are the seller.
    from_address = sender_address(config.get("ship_from_address") or {},
                                  *_seller_contact(tenant_id, user_profiles_repo))
    if not str(from_address.get("email") or "").strip():
        # Named where it can be fixed, rather than relayed in the carrier's words.
        return error_response(
            "Add an email address to your ship-from address on the Shipping screen — carriers will not "
            "issue a label without one.", code="ship_from_email_required")
    try:
        claim = build_shipment(order=order, from_address=from_address, parcel=parcel, now=now)
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

    # WHAT THE CARRIER CHARGED, against what the buyer was quoted. The second half of the audit pair, and
    # the moment `ledger.shipping_margin` stops being None (plans/LIVE_SHIPPING_RATES.md phase 5).
    # Best-effort: the label is bought and the parcel is going. A bookkeeping write must never turn a
    # successful purchase into an error the tenant thinks they should retry.
    record_shipping_variance(order, saved, tenant_id, mode=mode, now=now)
    # THE OTHER HALF OF SHIPPING MARGIN. `shipping_cost` sat in the ledger's AMOUNT_COMPONENTS with no
    # builder and no writer, so `summarize`'s `shipping_margin` could only ever be None and a tenant could
    # never learn whether their postage pricing made or lost money. Best-effort, like everything after the
    # label is bought: the postage is paid and the parcel is going.
    record_shipping_cost_entry(order, saved, now=now)

    # The buyer is told the same way the manual path tells them -- one builder, one mailer. Best-effort
    # HERE, unlike the manual path: the label is already bought and paid for, so a bounced address must
    # not turn a successful purchase into an error the tenant thinks they should retry.
    # THE SAME CORRECTION THE MANUAL PATH SENDS. This path shipped the old email -- no arrival date, no
    # explanation -- so a buyer whose tenant BOUGHT postage got less than one whose tenant typed a tracking
    # number in by hand. One builder, one computation, both callers (plans/THANK_YOU_PAGE.md P4).
    revised = revision_for(order, saved, tenant_id, mode)
    if revised:
        saved["delivery_revision"] = revised
    notified = notify_buyer(order, saved, tenant_id, has_tracking=True,
                            user_profiles_repo=user_profiles_repo, mailer_send=mailer_send,
                            arrival_line=revised_sentence(revised))
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
