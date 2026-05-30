from typing import Any


class DocumentValidationError(ValueError):
    pass


def require_fields(document: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if document.get(field) in ("", None, [])]
    if missing:
        raise DocumentValidationError(f"Missing required field(s): {', '.join(missing)}.")


def validate_product_document(document: dict[str, Any]) -> None:
    require_fields(document, [
        "schema_version",
        "document_type",
        "tenant_id",
        "product_id",
        "name",
        "prices",
        "default_price_id",
    ])
    if document.get("document_type") != "product":
        raise DocumentValidationError("Product document_type must be 'product'.")
    prices = document.get("prices")
    if not isinstance(prices, list) or not prices:
        raise DocumentValidationError("Product prices must be a non-empty array.")

    product_id = document.get("product_id")
    product_mode = document.get("stripe_mode")
    price_ids = set()
    for price in prices:
        if not isinstance(price, dict):
            raise DocumentValidationError("Each product price must be an object.")
        require_fields(price, ["price_id", "product_id", "currency", "unit_amount", "quantity", "label"])
        if price.get("product_id") != product_id:
            raise DocumentValidationError(f"Price '{price.get('price_id')}' must belong to product '{product_id}'.")
        if product_mode and price.get("stripe_mode") and price.get("stripe_mode") != product_mode:
            raise DocumentValidationError(
                f"Price '{price.get('price_id')}' stripe_mode must match product stripe_mode '{product_mode}'."
            )
        price_ids.add(price.get("price_id"))

    if document.get("default_price_id") not in price_ids:
        raise DocumentValidationError("Product default_price_id must reference one of its prices.")


def validate_offer_document(document: dict[str, Any]) -> None:
    require_fields(document, [
        "schema_version",
        "document_type",
        "tenant_id",
        "offer_id",
        "name",
        "items",
        "checkout",
    ])
    if document.get("document_type") != "offer":
        raise DocumentValidationError("Offer document_type must be 'offer'.")
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise DocumentValidationError("Offer items must be a non-empty array.")

    for item in items:
        if not isinstance(item, dict):
            raise DocumentValidationError("Each offer item must be an object.")
        require_fields(item, ["product_id"])
        has_fixed_price = bool(item.get("price_id"))
        has_selectable_prices = bool(item.get("selectable_prices"))
        if has_fixed_price == has_selectable_prices:
            raise DocumentValidationError("Offer item must use either price_id or selectable_prices, but not both.")
        if has_fixed_price and not item.get("quantity"):
            raise DocumentValidationError("Fixed-price offer items require quantity.")
        if has_selectable_prices:
            selectable_price_ids = {
                price.get("price_id")
                for price in item.get("selectable_prices", [])
                if isinstance(price, dict) and price.get("price_id")
            }
            if not selectable_price_ids:
                raise DocumentValidationError("selectable_prices must include at least one price_id.")
            if item.get("default_price_id") not in selectable_price_ids:
                raise DocumentValidationError("default_price_id must reference one of selectable_prices.")

    checkout = document.get("checkout")
    if not isinstance(checkout, dict) or not checkout.get("mode"):
        raise DocumentValidationError("Offer checkout.mode is required.")


def validate_page_document(document: dict[str, Any]) -> None:
    require_fields(document, [
        "schema_version",
        "document_type",
        "tenant_id",
        "page_id",
        "name",
        "route",
        "offer_id",
        "sections",
    ])
    if document.get("document_type") != "page":
        raise DocumentValidationError("Page document_type must be 'page'.")
    route = document.get("route")
    if not isinstance(route, dict) or not route.get("slug"):
        raise DocumentValidationError("Page route.slug is required.")
    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DocumentValidationError("Page sections must be a non-empty array.")
    for section in sections:
        if not isinstance(section, dict):
            raise DocumentValidationError("Each page section must be an object.")
        require_fields(section, ["id", "type"])
    refund_policy = document.get("refund_policy")
    if refund_policy is not None:
        if not isinstance(refund_policy, dict):
            raise DocumentValidationError("Page refund_policy must be an object.")
        require_fields(refund_policy, ["source", "short_label", "full_policy"])


def validate_tenant_profile(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "owner"])
    if document.get("document_type") != "tenant_profile":
        raise DocumentValidationError("Tenant profile document_type must be 'tenant_profile'.")
    owner = document.get("owner")
    if not isinstance(owner, dict):
        raise DocumentValidationError("Tenant profile owner must be an object.")
    require_fields(owner, ["first_name", "last_name", "email"])


def validate_stripe_keys_document(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "mode"])
    if document.get("document_type") != "stripe_keys":
        raise DocumentValidationError("Stripe keys document_type must be 'stripe_keys'.")
    if document.get("mode") not in {"test", "live"}:
        raise DocumentValidationError("Stripe keys mode must be 'test' or 'live'.")
    if not (document.get("publishable_key") or document.get("connect_account_id")):
        raise DocumentValidationError("Stripe keys require publishable_key or connect_account_id.")


def validate_tenant_config(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id"])
    if document.get("document_type") != "tenant_config":
        raise DocumentValidationError("Tenant config document_type must be 'tenant_config'.")
    page_defaults = document.get("page_defaults")
    if page_defaults is not None:
        if not isinstance(page_defaults, dict):
            raise DocumentValidationError("Tenant config page_defaults must be an object.")
        upsell = page_defaults.get("upsell")
        if upsell is not None:
            if not isinstance(upsell, dict):
                raise DocumentValidationError("Tenant config page_defaults.upsell must be an object.")
            require_fields(upsell, ["headline", "subheadline", "accept_button_text", "decline_button_text"])
        thank_you = page_defaults.get("thank_you")
        if thank_you is not None:
            if not isinstance(thank_you, dict):
                raise DocumentValidationError("Tenant config page_defaults.thank_you must be an object.")
            require_fields(thank_you, ["headline", "subtitle", "message"])
    checkout = document.get("checkout")
    if checkout is not None:
        if not isinstance(checkout, dict):
            raise DocumentValidationError("Tenant config checkout must be an object.")
        phone_collection = checkout.get("phone_number_collection")
        if phone_collection is not None:
            if not isinstance(phone_collection, dict):
                raise DocumentValidationError("Tenant config checkout.phone_number_collection must be an object.")
            if not isinstance(phone_collection.get("enabled", False), bool):
                raise DocumentValidationError("Tenant config checkout.phone_number_collection.enabled must be boolean.")
    custom_domains = document.get("custom_domains")
    if custom_domains is not None:
        if not isinstance(custom_domains, dict):
            raise DocumentValidationError("Tenant config custom_domains must be an object.")
        domains = custom_domains.get("domains") or []
        if not isinstance(domains, list):
            raise DocumentValidationError("Tenant config custom_domains.domains must be an array.")
        for domain in domains:
            if not isinstance(domain, dict):
                raise DocumentValidationError("Each custom domain must be an object.")
            require_fields(domain, ["domain", "target_page_id", "status"])


def validate_user_preferences(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "user_id"])
    if document.get("document_type") != "user_preferences":
        raise DocumentValidationError("User preferences document_type must be 'user_preferences'.")
    landing_pages = document.get("landing_pages")
    if landing_pages is not None:
        if not isinstance(landing_pages, dict):
            raise DocumentValidationError("User preferences landing_pages must be an object.")
        custom_themes = landing_pages.get("custom_color_themes") or []
        if not isinstance(custom_themes, list):
            raise DocumentValidationError("User preferences landing_pages.custom_color_themes must be an array.")
        if len(custom_themes) > 10:
            raise DocumentValidationError("User preferences can include at most 10 custom color themes.")
    authoring_defaults = document.get("authoring_defaults")
    if authoring_defaults is not None:
        if not isinstance(authoring_defaults, dict):
            raise DocumentValidationError("User preferences authoring_defaults must be an object.")
        refund_policies = authoring_defaults.get("refund_policies") or {}
        if not isinstance(refund_policies, dict):
            raise DocumentValidationError("User preferences refund_policies must be an object.")
        for key, policy in refund_policies.items():
            if key not in {"physical", "digital", "subscription"}:
                raise DocumentValidationError(f"Unsupported refund policy class '{key}'.")
            if not isinstance(policy, dict):
                raise DocumentValidationError("Each refund policy must be an object.")
            require_fields(policy, ["refund_window", "condition", "return_method", "short_label", "full_policy"])


def validate_user_profile(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "user_id", "email", "display_name"])
    if document.get("document_type") != "user_profile":
        raise DocumentValidationError("User profile document_type must be 'user_profile'.")
    profile_images = document.get("profile_images")
    if profile_images is not None:
        if not isinstance(profile_images, dict):
            raise DocumentValidationError("User profile profile_images must be an object.")
        images = profile_images.get("images") or []
        if not isinstance(images, list):
            raise DocumentValidationError("User profile profile_images.images must be an array.")
        if len(images) > 10:
            raise DocumentValidationError("User profile can include at most 10 profile images.")
        for image in images:
            if not isinstance(image, dict):
                raise DocumentValidationError("Each profile image must be an object.")
            require_fields(image, ["image_id", "url", "uploaded_at"])
    auth = document.get("auth")
    if auth is not None and not isinstance(auth, dict):
        raise DocumentValidationError("User profile auth must be an object.")
    subscription = document.get("subscription")
    if subscription is not None and not isinstance(subscription, dict):
        raise DocumentValidationError("User profile subscription must be an object.")


def validate_notification(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "notification_id", "type", "title", "created_at"])
    if document.get("document_type") != "notification":
        raise DocumentValidationError("Notification document_type must be 'notification'.")
    if document.get("status", "unread") not in {"unread", "read", "archived"}:
        raise DocumentValidationError("Notification status is invalid.")


def validate_refund_request(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "refund_request_id", "status", "customer", "order_id", "created_at"])
    if document.get("document_type") != "refund_request":
        raise DocumentValidationError("Refund request document_type must be 'refund_request'.")
    customer = document.get("customer")
    if not isinstance(customer, dict):
        raise DocumentValidationError("Refund request customer must be an object.")
    require_fields(customer, ["email"])
    if document.get("status") not in {"new", "manual_review", "approved", "rejected", "refunded", "closed"}:
        raise DocumentValidationError("Refund request status is invalid.")
    if document.get("risk_level", "unknown") not in {"low", "medium", "high", "unknown"}:
        raise DocumentValidationError("Refund request risk_level is invalid.")


def validate_shipping_config(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "provider", "ship_from_address", "return_address", "default_parcel"])
    if document.get("document_type") != "shipping_config":
        raise DocumentValidationError("Shipping config document_type must be 'shipping_config'.")
    provider = document.get("provider")
    if not isinstance(provider, dict):
        raise DocumentValidationError("Shipping config provider must be an object.")
    require_fields(provider, ["name"])
    if provider.get("name") not in {"shippo", "easypost", "shipstation", "easyship", "mock"}:
        raise DocumentValidationError("Shipping provider is invalid.")
    for field in ["ship_from_address", "return_address"]:
        address = document.get(field)
        if not isinstance(address, dict):
            raise DocumentValidationError(f"Shipping config {field} must be an object.")
        require_fields(address, ["name", "street1", "city", "state", "postal_code", "country"])
    parcel = document.get("default_parcel")
    if not isinstance(parcel, dict):
        raise DocumentValidationError("Shipping config default_parcel must be an object.")
    require_fields(parcel, ["length", "width", "height", "weight", "distance_unit", "mass_unit"])


def validate_customer(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "customer_id", "contact", "summary"])
    if document.get("document_type") != "customer":
        raise DocumentValidationError("Customer document_type must be 'customer'.")
    contact = document.get("contact")
    if not isinstance(contact, dict):
        raise DocumentValidationError("Customer contact must be an object.")
    require_fields(contact, ["email"])
    summary = document.get("summary")
    if not isinstance(summary, dict):
        raise DocumentValidationError("Customer summary must be an object.")
    if int(summary.get("total_orders") or 0) < 0:
        raise DocumentValidationError("Customer total_orders cannot be negative.")
    transaction_history = document.get("transaction_history") or []
    if not isinstance(transaction_history, list):
        raise DocumentValidationError("Customer transaction_history must be an array.")
    for transaction in transaction_history:
        if not isinstance(transaction, dict):
            raise DocumentValidationError("Each customer transaction must be an object.")
        require_fields(transaction, ["transaction_id", "type", "created_at"])


def validate_service(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "service_id", "name", "duration_minutes", "price"])
    if document.get("document_type") != "service":
        raise DocumentValidationError("Service document_type must be 'service'.")
    if int(document.get("duration_minutes") or 0) <= 0:
        raise DocumentValidationError("Service duration_minutes must be positive.")
    price = document.get("price")
    if not isinstance(price, dict):
        raise DocumentValidationError("Service price must be an object.")
    require_fields(price, ["currency", "unit_amount"])
    booking_rules = document.get("booking_rules") or {}
    if not isinstance(booking_rules, dict):
        raise DocumentValidationError("Service booking_rules must be an object.")
    allowed = document.get("allowed_fulfillers") or []
    if not isinstance(allowed, list):
        raise DocumentValidationError("Service allowed_fulfillers must be an array.")
    for fulfiller in allowed:
        if not isinstance(fulfiller, dict):
            raise DocumentValidationError("Each allowed fulfiller must be an object.")
        require_fields(fulfiller, ["fulfiller_id", "enabled"])


def validate_fulfiller(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "fulfiller_id", "email", "display_name", "status"])
    if document.get("document_type") != "fulfiller":
        raise DocumentValidationError("Fulfiller document_type must be 'fulfiller'.")
    if document.get("status") not in {"active", "inactive", "invited"}:
        raise DocumentValidationError("Fulfiller status is invalid.")
    compensation = document.get("compensation") or {}
    if not isinstance(compensation, dict):
        raise DocumentValidationError("Fulfiller compensation must be an object.")
    require_fields(compensation, ["type", "amount"])
    availability = document.get("availability") or {}
    if not isinstance(availability, dict):
        raise DocumentValidationError("Fulfiller availability must be an object.")
    validate_weekly_hours(availability.get("weekly_hours") or [])


def validate_tenant_availability(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "availability_id", "timezone", "slot_interval_minutes", "lead_time_minutes", "weekly_hours"])
    if document.get("document_type") != "tenant_availability":
        raise DocumentValidationError("Tenant availability document_type must be 'tenant_availability'.")
    if int(document.get("slot_interval_minutes") or 0) <= 0:
        raise DocumentValidationError("Tenant availability slot_interval_minutes must be positive.")
    validate_weekly_hours(document.get("weekly_hours") or [])


def validate_availability_exception(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "exception_id", "starts_at", "ends_at", "type"])
    if document.get("document_type") != "availability_exception":
        raise DocumentValidationError("Availability exception document_type must be 'availability_exception'.")
    if document.get("type") not in {"block", "open"}:
        raise DocumentValidationError("Availability exception type is invalid.")
    if document.get("fulfiller_scope") == "specific" and not document.get("fulfiller_id"):
        raise DocumentValidationError("Specific availability exceptions require fulfiller_id.")


def validate_appointment(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "appointment_id", "service_id", "starts_at", "ends_at", "timezone", "status", "customer"])
    if document.get("document_type") != "appointment":
        raise DocumentValidationError("Appointment document_type must be 'appointment'.")
    if document.get("status") not in {"reserved", "booked", "paid", "checked_in", "completed", "canceled", "no_show"}:
        raise DocumentValidationError("Appointment status is invalid.")
    customer = document.get("customer")
    if not isinstance(customer, dict):
        raise DocumentValidationError("Appointment customer must be an object.")
    require_fields(customer, ["email"])


def validate_invoice(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "invoice_id", "status", "customer", "line_items", "amounts"])
    if document.get("document_type") != "invoice":
        raise DocumentValidationError("Invoice document_type must be 'invoice'.")
    if document.get("status") not in {"draft", "open", "paid", "void", "uncollectible", "deleted"}:
        raise DocumentValidationError("Invoice status is invalid.")
    customer = document.get("customer")
    if not isinstance(customer, dict):
        raise DocumentValidationError("Invoice customer must be an object.")
    require_fields(customer, ["email"])
    line_items = document.get("line_items")
    if not isinstance(line_items, list) or not line_items:
        raise DocumentValidationError("Invoice line_items must be a non-empty array.")
    for item in line_items:
        if not isinstance(item, dict):
            raise DocumentValidationError("Each invoice line item must be an object.")
        require_fields(item, ["description", "quantity", "unit_amount"])
        if int(item.get("quantity") or 0) <= 0:
            raise DocumentValidationError("Invoice line item quantity must be positive.")
    amounts = document.get("amounts")
    if not isinstance(amounts, dict):
        raise DocumentValidationError("Invoice amounts must be an object.")
    require_fields(amounts, ["currency", "subtotal", "total", "amount_due", "amount_paid"])


def validate_weekly_hours(weekly_hours: list[dict[str, Any]]) -> None:
    if not isinstance(weekly_hours, list) or len(weekly_hours) != 7:
        raise DocumentValidationError("weekly_hours must contain seven day objects.")
    valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    for day in weekly_hours:
        if not isinstance(day, dict):
            raise DocumentValidationError("Each weekly_hours entry must be an object.")
        require_fields(day, ["day", "enabled"])
        if day.get("day") not in valid_days:
            raise DocumentValidationError("weekly_hours day is invalid.")
        if day.get("enabled"):
            require_fields(day, ["start_time", "end_time"])
