import os
import time
import uuid

from stripe_link.common import error_response, json_response, parse_json_body, path_params, query_params, tenant_id_from_event
from stripe_link.domain.documents import DocumentValidationError, validate_invoice
from stripe_link.domain.fees import cached_billing_config, calculate_price, normalize_tier_id
from stripe_link.domain.invoicing import (
    DEFAULT_DAYS_UNTIL_DUE,
    invoice_currency,
    invoice_email_content,
    invoice_from_appointment,
    invoice_from_order,
    invoice_total,
    stripe_customer_params,
    stripe_invoice_params,
    stripe_invoiceitem_params,
)
from stripe_link.kms_secrets import KmsSecretCipher
from stripe_link.mailer import send_email
from stripe_link.repositories.documents import (
    RepositoryError,
    appointments_repository,
    invoices_repository,
    stripe_keys_repository,
    tenant_profiles_repository,
)
from stripe_link.stripe_client import StripeApiError, stripe_request
from stripe_link.stripe_platform_secrets import checkout_credentials


def handler(event, context, repository=None, stripe_repo=None, tenant_repo=None, secret_cipher=None, opener=None, mailer_send=None, billing_config_loader=None, appointments_repo=None):
    repository = repository or invoices_repository()
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")
    if method == "OPTIONS":
        return json_response({})
    if method == "POST" and path.endswith("/from-appointment"):
        return invoice_from_appointment_route(event, repository, appointments_repo=appointments_repo)
    if method == "POST" and path.endswith("/from-order"):
        return invoice_from_order_route(event, repository, appointments_repo=appointments_repo)
    if method == "POST" and path.endswith("/send"):
        return send_invoice_route(event, repository, stripe_repo=stripe_repo, tenant_repo=tenant_repo,
                                  secret_cipher=secret_cipher, opener=opener, mailer_send=mailer_send,
                                  billing_config_loader=billing_config_loader)
    if method in {"POST", "PUT"}:
        return save_invoice(event, repository)
    if method == "GET":
        invoice_id = path_params(event).get("invoice_id")
        if invoice_id:
            return get_invoice(event, repository, invoice_id)
        return list_invoices(event, repository)
    return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")


def send_invoice_route(event, repository, *, stripe_repo, tenant_repo, secret_cipher, opener, mailer_send, billing_config_loader):
    tenant_id = tenant_id_from_event(event)
    invoice_id = path_params(event).get("invoice_id")
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not invoice_id:
        return error_response("invoice_id is required.", code="missing_invoice_id")

    invoice = repository.get(tenant_id, invoice_id)
    if not invoice:
        return error_response("Invoice not found.", status_code=404, code="not_found")
    if invoice.get("status") == "paid":
        return error_response("Invoice is already paid.", status_code=409, code="already_paid")
    customer = invoice.get("customer") or {}
    if not str(customer.get("email") or "").strip():
        return error_response("Invoice customer email is required.", code="missing_customer_email")
    line_items = invoice.get("line_items") or []
    if not line_items:
        return error_response("Invoice has no line items.", code="empty_invoice")

    mode = "live" if invoice.get("stripe_mode") == "live" else ("live" if os.environ.get("ENVIRONMENT") == "prod" else "test")
    stripe_repo = stripe_repo or stripe_keys_repository()
    tenant_repo = tenant_repo or tenant_profiles_repository()
    secret_cipher = secret_cipher or KmsSecretCipher()
    stripe_keys = stripe_repo.get(tenant_id, mode=mode) or {}
    api_key, stripe_account = checkout_credentials(tenant_id, mode, stripe_keys, secret_cipher)
    if not api_key:
        return error_response(f"{mode} Stripe keys are not configured.", status_code=400, code="stripe_not_configured")

    profile = tenant_repo.get(tenant_id, tenant_id) or {}
    business_name = str(profile.get("business_name") or "")
    support_email = str(profile.get("support_email") or "")
    currency = invoice_currency(invoice)
    tenant_plan = normalize_tier_id(profile.get("tier_id"))
    fee = calculate_price(
        tenant_keyed_amount=invoice_total(invoice), currency=currency, product_type="digital",
        tenant_plan=tenant_plan, billing_config=cached_billing_config(billing_config_loader),
    )
    application_fee = int(fee.get("breakdown", {}).get("platform_fee") or 0) if stripe_account else 0
    now = int(time.time())

    try:
        customer_id = invoice.get("stripe_customer_id")
        if not customer_id:
            created = stripe_request("POST", "/customers", api_key=api_key, stripe_account=stripe_account, data=stripe_customer_params(customer), opener=opener)
            customer_id = created.get("id")
        for item in line_items:
            stripe_request("POST", "/invoiceitems", api_key=api_key, stripe_account=stripe_account, data=stripe_invoiceitem_params(customer_id, item, currency), opener=opener)
        metadata = {"tenant_id": tenant_id, "invoice_id": invoice_id, "product_type": "digital", "tenant_plan": tenant_plan}
        stripe_invoice = stripe_request(
            "POST", "/invoices", api_key=api_key, stripe_account=stripe_account,
            data=stripe_invoice_params(customer_id, application_fee=application_fee, metadata=metadata, footer=str((invoice.get("presentation") or {}).get("footer") or "")),
            opener=opener, idempotency_key=f"invoice_{invoice_id}",
        )
        finalized = stripe_request("POST", f"/invoices/{stripe_invoice['id']}/finalize", api_key=api_key, stripe_account=stripe_account, opener=opener)
    except StripeApiError as exc:
        return error_response(str(exc), status_code=502, code="stripe_error")

    hosted_url = finalized.get("hosted_invoice_url") or ""
    content = invoice_email_content(invoice, hosted_url, business_name=business_name, support_email=support_email)
    send = mailer_send or send_email
    sent = False
    try:
        send(to=customer["email"], subject=content["subject"], html=content["html"], text=content["text"], from_name=business_name, reply_to=support_email)
        sent = True
    except Exception:  # noqa: BLE001 - a delivery failure must not lose the finalized invoice
        pass

    prior_delivery = invoice.get("delivery") if isinstance(invoice.get("delivery"), dict) else {}
    delivery = {
        **prior_delivery,
        "days_until_due": DEFAULT_DAYS_UNTIL_DUE,
        "share_url": hosted_url,
        "recipient_email": customer["email"],
        "send_count": int(prior_delivery.get("send_count") or 0) + (1 if sent else 0),
    }
    if sent:
        delivery["sent_at"] = now
    payment = {**(invoice.get("payment") if isinstance(invoice.get("payment"), dict) else {}), "hosted_invoice_url": hosted_url}
    if finalized.get("invoice_pdf"):
        payment["invoice_pdf_url"] = finalized.get("invoice_pdf")

    updated = {
        **invoice,
        "stripe_invoice_id": finalized.get("id"),
        "stripe_customer_id": customer_id,
        "stripe_mode": mode,
        "payment": payment,
        "delivery": delivery,
        "collection_method": "send_invoice",
        "status": "open",
        "finalized_at": now,
        "updated_at": now,
    }
    repository.put(updated)
    return json_response({"invoice": updated, "hosted_invoice_url": hosted_url, "delivered": sent})


def invoice_from_appointment_route(event, repository, *, appointments_repo=None):
    """Create a draft invoice from a book-then-pay appointment (STORY-6.4). Idempotent per
    appointment: returns the existing linked invoice if one was already created."""
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")
    appointment_id = str(body.get("appointment_id") or "").strip()
    if not appointment_id:
        return error_response("appointment_id is required.", code="missing_appointment_id")

    appointments_repo = appointments_repo or (appointments_repository() if os.environ.get("SERVICES_TABLE") else None)
    if not appointments_repo:
        return error_response("Appointments are not available.", status_code=400, code="appointments_unavailable")
    appointment = appointments_repo.get(tenant_id, appointment_id)
    if not appointment:
        return error_response("Appointment not found.", status_code=404, code="not_found")

    for existing in repository.list_for_tenant(tenant_id):
        if appointment_id in ((existing.get("source") or {}).get("appointment_ids") or []):
            return json_response({"invoice": existing, "created": False})

    now = int(time.time())
    invoice = invoice_from_appointment(appointment, invoice_id=f"inv_{uuid.uuid4().hex[:12]}", now=now)
    try:
        validate_invoice(invoice)
        saved = repository.put(invoice)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_invoice")
    return json_response({"invoice": saved, "created": True}, status_code=201)


def invoice_from_order_route(event, repository, *, appointments_repo=None):
    """Create (idempotently) one invoice for a book-then-pay order, covering all its appointments
    (one line per service line). Returns the existing invoice if one was already created (STORY-3.3)."""
    tenant_id = tenant_id_from_event(event)
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")
    order_id = str(body.get("order_id") or "").strip()
    if not order_id:
        return error_response("order_id is required.", code="missing_order_id")

    appointments_repo = appointments_repo or (appointments_repository() if os.environ.get("SERVICES_TABLE") else None)
    if not appointments_repo:
        return error_response("Appointments are not available.", status_code=503, code="appointments_unavailable")
    appointments = [a for a in appointments_repo.list_for_tenant(tenant_id) if str(a.get("order_id") or "") == order_id]
    if not appointments:
        return error_response("No appointments found for this order.", status_code=404, code="not_found")

    for existing in repository.list_for_tenant(tenant_id):
        if (existing.get("source") or {}).get("order_id") == order_id:
            return json_response({"invoice": existing, "created": False})

    now = int(time.time())
    invoice = invoice_from_order(appointments, invoice_id=f"inv_{uuid.uuid4().hex[:12]}", now=now)
    try:
        validate_invoice(invoice)
        saved = repository.put(invoice)
    except (DocumentValidationError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_invoice")
    return json_response({"invoice": saved, "created": True}, status_code=201)


def save_invoice(event, repository):
    try:
        document = parse_json_body(event)
        validate_invoice(document)
        saved = repository.put(document)
        return json_response({"invoice": saved}, status_code=201)
    except (DocumentValidationError, ValueError, RepositoryError) as exc:
        return error_response(str(exc), code="invalid_invoice")


def get_invoice(event, repository, invoice_id):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    invoice = repository.get(tenant_id, invoice_id)
    if not invoice:
        return error_response("Invoice not found.", status_code=404, code="not_found")
    return json_response({"invoice": invoice})


def list_invoices(event, repository):
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    params = query_params(event)
    invoices = filter_invoices(repository.list_for_tenant(tenant_id), params)
    invoices.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return json_response({"invoices": invoices, "count": len(invoices)})


def filter_invoices(invoices, params):
    status = str(params.get("status") or "").strip()
    customer = str(params.get("customer") or "").strip().lower()
    filtered = []
    for invoice in invoices:
        invoice_customer = invoice.get("customer") or {}
        haystack = f"{invoice_customer.get('name', '')} {invoice_customer.get('email', '')}".lower()
        if status and invoice.get("status") != status:
            continue
        if customer and customer not in haystack:
            continue
        filtered.append(invoice)
    return filtered
