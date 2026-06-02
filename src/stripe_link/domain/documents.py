import re
from typing import Any


class DocumentValidationError(ValueError):
    pass


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
FONT_FAMILY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")
HTTP_URL_PATTERN = re.compile(r"^https?://[^\s\"'<>]+$")
SUPPORTED_PAGE_SECTION_TYPES = {
    "brand_label",
    "checkout_cta",
    "content_block",
    "countdown_timer",
    "faq",
    "headline",
    "hero",
    "hero_media",
    "legal_footer",
    "offer_price_selector",
    "refund_policy",
    "seo_title",
    "subheadline",
    "trust_badges",
}
SUPPORTED_PAGE_TEMPLATES = {"simple", "universal_bundle"}
SUPPORTED_THEME_PRESETS = {
    "techno-green",
    "rose-minimalist",
    "midnight-luxe",
    "trust-blue",
    "coral-sunrise",
    "clean-slate",
    "royal-velvet",
    "fire-sale",
    "natural-calm",
    "cyber-pulse",
}
SUPPORTED_FONT_SERVICES = {"system", "junior-bay"}
SUPPORTED_FONT_FALLBACKS = {"system", "sans-serif", "serif", "monospace"}


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    return value


def require_fields(document: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if document.get(field) in ("", None, [])]
    if missing:
        raise DocumentValidationError(f"Missing required field(s): {', '.join(missing)}.")


def require_string(document: dict[str, Any], field: str, label: str | None = None) -> str:
    value = document.get(field)
    field_label = label or field
    if not isinstance(value, str) or not value.strip():
        raise DocumentValidationError(f"{field_label} must be a non-empty string.")
    return value


def optional_string(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is not None and not isinstance(value, str):
        raise DocumentValidationError(f"{label or field} must be a string.")


def optional_bool(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is not None and not isinstance(value, bool):
        raise DocumentValidationError(f"{label or field} must be boolean.")


def require_positive_int(document: dict[str, Any], field: str, label: str | None = None) -> int:
    value = document.get(field)
    field_label = label or field
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DocumentValidationError(f"{field_label} must be a positive integer.")
    return value


def optional_non_negative_int(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise DocumentValidationError(f"{label or field} must be a non-negative integer.")


def require_enum(document: dict[str, Any], field: str, allowed: set[str], label: str | None = None) -> str:
    value = require_string(document, field, label)
    if value not in allowed:
        raise DocumentValidationError(f"{label or field} must be one of: {', '.join(sorted(allowed))}.")
    return value


def optional_string_list(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is None:
        return
    field_label = label or field
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DocumentValidationError(f"{field_label} must be an array of strings.")


def optional_limited_object_list(
    document: dict[str, Any],
    field: str,
    limit: int,
    label: str | None = None,
) -> list[dict[str, Any]]:
    value = document.get(field)
    if value is None:
        return []
    field_label = label or field
    if not isinstance(value, list):
        raise DocumentValidationError(f"{field_label} must be an array.")
    if len(value) > limit:
        raise DocumentValidationError(f"{field_label} must include no more than {limit} item(s).")
    for item in value:
        if not isinstance(item, dict):
            raise DocumentValidationError(f"Each {field_label} item must be an object.")
    return value


def require_document_fields(document: dict[str, Any], document_type: str, id_field: str) -> None:
    require_object(document, f"{document_type} document")
    for field in ["schema_version", "document_type", "tenant_id", id_field]:
        require_string(document, field)
    if document.get("document_type") != document_type:
        raise DocumentValidationError(f"{document_type.replace('_', ' ').title()} document_type must be '{document_type}'.")


def validate_product_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "product", "product_id")
    require_string(document, "name")
    require_string(document, "default_price_id")
    optional_bool(document, "active")
    if document.get("stripe_mode") is not None:
        require_enum(document, "stripe_mode", {"test", "live"})
    optional_string(document, "description")
    optional_string(document, "product_type")
    optional_string(document, "product_category")
    optional_bool(document, "requires_shipping")
    optional_string_list(document, "images")
    optional_string_list(document, "tags")
    fulfillment = document.get("fulfillment")
    if fulfillment is not None:
        if not isinstance(fulfillment, dict):
            raise DocumentValidationError("Product fulfillment must be an object.")
        optional_bool(fulfillment, "requires_shipping", "Product fulfillment.requires_shipping")
        optional_non_negative_int(fulfillment, "weight_oz", "Product fulfillment.weight_oz")
        ship_from = fulfillment.get("ship_from")
        if ship_from is not None and not isinstance(ship_from, dict):
            raise DocumentValidationError("Product fulfillment.ship_from must be an object when provided.")

    refund_policy = document.get("refund_policy")
    if refund_policy is not None:
        if not isinstance(refund_policy, dict):
            raise DocumentValidationError("Product refund_policy must be an object.")
        optional_string(refund_policy, "source", "Product refund_policy.source")
        require_string(refund_policy, "short_label", "Product refund_policy.short_label")
        require_string(refund_policy, "full_policy", "Product refund_policy.full_policy")
        optional_string(refund_policy, "condition", "Product refund_policy.condition")
        optional_string(refund_policy, "return_method", "Product refund_policy.return_method")

    prices = document.get("prices")
    if not isinstance(prices, list) or not prices:
        raise DocumentValidationError("Product prices must be a non-empty array.")

    product_id = document.get("product_id")
    product_mode = document.get("stripe_mode")
    price_ids = set()
    for price in prices:
        if not isinstance(price, dict):
            raise DocumentValidationError("Each product price must be an object.")
        for field in ["price_id", "product_id", "currency", "label"]:
            require_string(price, field, f"price.{field}")
        require_positive_int(price, "unit_amount", "price.unit_amount")
        require_positive_int(price, "quantity", "price.quantity")
        optional_bool(price, "active", "price.active")
        optional_string(price, "context", "price.context")
        optional_string(price, "badge", "price.badge")
        optional_string(price, "description", "price.description")
        optional_string(price, "image_url", "price.image_url")
        optional_non_negative_int(price, "discount_pct", "price.discount_pct")
        optional_non_negative_int(price, "regular_unit_amount", "price.regular_unit_amount")
        if len(price.get("currency", "")) != 3 or price.get("currency", "") != price.get("currency", "").lower():
            raise DocumentValidationError("price.currency must be a lowercase 3-letter currency code.")
        if price.get("stripe_mode") is not None:
            require_enum(price, "stripe_mode", {"test", "live"}, "price.stripe_mode")
        if price.get("product_id") != product_id:
            raise DocumentValidationError(f"Price '{price.get('price_id')}' must belong to product '{product_id}'.")
        if product_mode and price.get("stripe_mode") and price.get("stripe_mode") != product_mode:
            raise DocumentValidationError(
                f"Price '{price.get('price_id')}' stripe_mode must match product stripe_mode '{product_mode}'."
            )
        if price.get("price_id") in price_ids:
            raise DocumentValidationError(f"Duplicate product price_id '{price.get('price_id')}'.")
        price_ids.add(price.get("price_id"))

    if document.get("default_price_id") not in price_ids:
        raise DocumentValidationError("Product default_price_id must reference one of its prices.")


def validate_offer_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "offer", "offer_id")
    require_string(document, "name")
    optional_bool(document, "active")
    optional_string(document, "context")
    if document.get("offer_type") is not None:
        require_enum(document, "offer_type", {"single-offer", "bundle", "listicle"}, "Offer offer_type")

    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise DocumentValidationError("Offer items must be a non-empty array.")

    for item in items:
        if not isinstance(item, dict):
            raise DocumentValidationError("Each offer item must be an object.")
        require_string(item, "product_id", "offer item product_id")
        optional_string(item, "presentation_context", "offer item presentation_context")
        has_fixed_price = bool(item.get("price_id"))
        has_selectable_prices = bool(item.get("selectable_prices"))
        if has_fixed_price == has_selectable_prices:
            raise DocumentValidationError("Offer item must use either price_id or selectable_prices, but not both.")
        if has_fixed_price:
            require_string(item, "price_id", "offer item price_id")
            require_positive_int(item, "quantity", "offer item quantity")
        if has_selectable_prices:
            selectable_prices = item.get("selectable_prices")
            if not isinstance(selectable_prices, list) or not selectable_prices:
                raise DocumentValidationError("selectable_prices must be a non-empty array.")
            selectable_price_ids = set()
            for price in selectable_prices:
                if not isinstance(price, dict):
                    raise DocumentValidationError("Each selectable price must be an object.")
                require_string(price, "price_id", "selectable price price_id")
                require_positive_int(price, "quantity", "selectable price quantity")
                require_string(price, "label", "selectable price label")
                optional_string(price, "badge", "selectable price badge")
                optional_string(price, "description", "selectable price description")
                optional_string(price, "image_url", "selectable price image_url")
                optional_non_negative_int(price, "display_discount_pct", "selectable price display_discount_pct")
                optional_non_negative_int(price, "regular_unit_amount", "selectable price regular_unit_amount")
                if price.get("price_id") in selectable_price_ids:
                    raise DocumentValidationError(f"Duplicate selectable price_id '{price.get('price_id')}'.")
                selectable_price_ids.add(price.get("price_id"))
            if not selectable_price_ids:
                raise DocumentValidationError("selectable_prices must include at least one price_id.")
            if item.get("default_price_id") not in selectable_price_ids:
                raise DocumentValidationError("default_price_id must reference one of selectable_prices.")

    checkout = document.get("checkout")
    if not isinstance(checkout, dict):
        raise DocumentValidationError("Offer checkout must be an object.")
    require_enum(checkout, "mode", {"payment", "subscription", "setup"}, "Offer checkout.mode")
    optional_bool(checkout, "allow_promotion_codes", "Offer checkout.allow_promotion_codes")
    metadata = checkout.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise DocumentValidationError("Offer checkout.metadata must be an object.")

    eligibility = document.get("eligibility")
    if eligibility is not None:
        if not isinstance(eligibility, dict):
            raise DocumentValidationError("Offer eligibility must be an object.")
        optional_bool(eligibility, "requires_prior_purchase", "Offer eligibility.requires_prior_purchase")
        optional_string_list(eligibility, "allowed_price_contexts", "Offer eligibility.allowed_price_contexts")

    presentation = document.get("presentation")
    if presentation is not None:
        if not isinstance(presentation, dict):
            raise DocumentValidationError("Offer presentation must be an object.")
        optional_string(presentation, "headline", "Offer presentation.headline")
        optional_string(presentation, "badge", "Offer presentation.badge")
        optional_string(presentation, "cta_label", "Offer presentation.cta_label")
        optional_string(presentation, "hero_image_url", "Offer presentation.hero_image_url")


def validate_page_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "page", "page_id")
    require_string(document, "name")
    require_string(document, "offer_id")
    if document.get("status") is not None:
        require_enum(document, "status", {"draft", "published", "archived"})
    optional_non_negative_int(document, "revision")

    route = document.get("route")
    if not isinstance(route, dict) or not route.get("slug"):
        raise DocumentValidationError("Page route.slug is required.")
    slug = require_string(route, "slug", "Page route.slug")
    if not SLUG_PATTERN.match(slug):
        raise DocumentValidationError("Page route.slug must contain only lowercase letters, numbers, and hyphens.")

    seo = document.get("seo")
    if seo is not None:
        if not isinstance(seo, dict):
            raise DocumentValidationError("Page seo must be an object.")
        optional_string(seo, "title", "Page seo.title")
        optional_string(seo, "description", "Page seo.description")
        favicon_url = seo.get("favicon_url")
        if favicon_url is not None and (not isinstance(favicon_url, str) or not HTTP_URL_PATTERN.match(favicon_url)):
            raise DocumentValidationError("Page seo.favicon_url must be an HTTP(S) URL.")

    theme = document.get("theme")
    if theme is not None:
        if not isinstance(theme, dict):
            raise DocumentValidationError("Page theme must be an object.")
        if theme.get("template") is not None:
            require_enum(theme, "template", SUPPORTED_PAGE_TEMPLATES, "Page theme.template")
        if theme.get("preset") is not None:
            require_enum(theme, "preset", SUPPORTED_THEME_PRESETS, "Page theme.preset")
        color = theme.get("color")
        if color is not None:
            if not isinstance(color, dict):
                raise DocumentValidationError("Page theme.color must be an object.")
            for field in ["background", "text", "accent"]:
                value = color.get(field)
                if value is not None:
                    if not isinstance(value, str) or not HEX_COLOR_PATTERN.match(value):
                        raise DocumentValidationError(f"Page theme.color.{field} must be a hex color.")
        tokens = theme.get("tokens")
        if tokens is not None:
            if not isinstance(tokens, dict):
                raise DocumentValidationError("Page theme.tokens must be an object.")
            for key, value in tokens.items():
                if not isinstance(key, str) or not isinstance(value, str) or not HEX_COLOR_PATTERN.match(value):
                    raise DocumentValidationError("Page theme.tokens values must be hex colors.")
        fonts = theme.get("fonts")
        if fonts is not None:
            if not isinstance(fonts, dict):
                raise DocumentValidationError("Page theme.fonts must be an object.")
            if fonts.get("service") is not None:
                require_enum(fonts, "service", SUPPORTED_FONT_SERVICES, "Page theme.fonts.service")
            for role in ["body", "heading", "accent"]:
                font = fonts.get(role)
                if font is None:
                    continue
                if not isinstance(font, dict):
                    raise DocumentValidationError(f"Page theme.fonts.{role} must be an object.")
                family = font.get("family")
                if family is not None and (not isinstance(family, str) or not FONT_FAMILY_PATTERN.match(family)):
                    raise DocumentValidationError(f"Page theme.fonts.{role}.family must be a safe font family.")
                if font.get("fallback") is not None:
                    require_enum(font, "fallback", SUPPORTED_FONT_FALLBACKS, f"Page theme.fonts.{role}.fallback")

    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DocumentValidationError("Page sections must be a non-empty array.")
    section_ids = set()
    for section in sections:
        if not isinstance(section, dict):
            raise DocumentValidationError("Each page section must be an object.")
        section_id = require_string(section, "id", "Page section id")
        section_type = require_enum(section, "type", SUPPORTED_PAGE_SECTION_TYPES, "Page section type")
        if section_id in section_ids:
            raise DocumentValidationError(f"Duplicate page section id '{section_id}'.")
        section_ids.add(section_id)
        if section_type == "hero":
            optional_string(section, "headline", "Hero section headline")
            optional_string(section, "subheadline", "Hero section subheadline")
            if not (section.get("headline") or section.get("subheadline")):
                raise DocumentValidationError("Hero section requires headline or subheadline.")
        elif section_type == "countdown_timer":
            optional_bool(section, "enabled", "Countdown timer enabled")
            optional_bool(section, "sticky", "Countdown timer sticky")
            optional_bool(section, "persistent", "Countdown timer persistent")
            optional_bool(section, "transparent", "Countdown timer transparent")
            optional_bool(section, "marquee", "Countdown timer marquee")
            if section.get("duration_minutes") is not None:
                require_positive_int(section, "duration_minutes", "Countdown timer duration_minutes")
            optional_string(section, "label", "Countdown timer label")
            optional_string(section, "start_text", "Countdown timer start_text")
            optional_string(section, "end_text", "Countdown timer end_text")
            optional_string(section, "start_color", "Countdown timer start_color")
            optional_string(section, "end_color", "Countdown timer end_color")
        elif section_type == "seo_title":
            optional_string(section, "label", "SEO title label")
        elif section_type == "brand_label":
            optional_bool(section, "enabled", "Brand label enabled")
            optional_string(section, "label", "Brand label")
        elif section_type == "hero_media":
            optional_string_list(section, "images", "Hero media images")
        elif section_type == "headline":
            require_string(section, "text", "Headline text")
        elif section_type == "subheadline":
            require_string(section, "text", "Subheadline text")
        elif section_type == "trust_badges":
            optional_bool(section, "enabled", "Trust badges enabled")
            badges = optional_limited_object_list(section, "badges", 3, "Trust badges")
            for badge in badges:
                optional_string(badge, "emoji", "Trust badge emoji")
                require_string(badge, "label", "Trust badge label")
        elif section_type == "offer_price_selector":
            require_string(section, "offer_id", "Offer price selector offer_id")
            if section.get("offer_id") != document.get("offer_id"):
                raise DocumentValidationError("Offer price selector offer_id must match page offer_id.")
        elif section_type == "refund_policy":
            optional_string(section, "heading", "Refund policy heading")
        elif section_type == "faq":
            items = optional_limited_object_list(section, "items", 10, "FAQ items")
            for item in items:
                require_string(item, "question", "FAQ question")
                require_string(item, "answer", "FAQ answer")
        elif section_type == "content_block":
            blocks = optional_limited_object_list(section, "blocks", 10, "Content blocks")
            for block in blocks:
                require_string(block, "title", "Content block title")
                require_string(block, "text", "Content block text")
                optional_string(block, "image_url", "Content block image_url")
        elif section_type == "checkout_cta":
            optional_string(section, "label", "Checkout CTA label")
        elif section_type == "legal_footer":
            optional_string(section, "copyright", "Legal footer copyright")

    analytics = document.get("analytics")
    if analytics is not None:
        if not isinstance(analytics, dict):
            raise DocumentValidationError("Page analytics must be an object.")
        optional_string(analytics, "google_tag_id", "Page analytics.google_tag_id")
        optional_string(analytics, "pixel_id", "Page analytics.pixel_id")

    legal = document.get("legal")
    if legal is not None:
        if not isinstance(legal, dict):
            raise DocumentValidationError("Page legal must be an object.")
        optional_string(legal, "terms_url", "Page legal.terms_url")
        optional_string(legal, "privacy_url", "Page legal.privacy_url")
        optional_string(legal, "refund_url", "Page legal.refund_url")

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
