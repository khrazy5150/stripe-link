import re
from decimal import Decimal
from typing import Any

from stripe_link.domain.composition import ELEMENTS, supported_goals


class DocumentValidationError(ValueError):
    pass


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# Advanced Color Settings overrides accept common CSS color forms (hex, rgb/rgba, hsl/hsla) — preset tokens
# aren't all hex (social presets use rgba), so restricting overrides to hex would reject valid colors.
CSS_COLOR_PATTERN = re.compile(
    r"^(#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|(?:rgb|rgba|hsl|hsla)\([0-9.,%\s/]+\))$"
)
FONT_FAMILY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")
HTTP_URL_PATTERN = re.compile(r"^https?://[^\s\"'<>]+$")
# The legal section types ARE the element catalog keys, so derive them from composition_rules.json rather
# than keeping a second copy here. The two had been identical by hand-maintenance alone, and the drift bites
# late and confusingly: adding an element made it composable and renderable but not *storable*, which
# surfaced only as a 400 from /pages/render. Empty means the rules file failed to load (composition.py
# degrades rather than raising at import) — accept any type then instead of rejecting every page; the
# renderer already falls back to an empty section for a type it doesn't know.
SUPPORTED_PAGE_SECTION_TYPES = set(ELEMENTS.keys())
# schema.org itemCondition values we support, keyed by the tenant-facing value stored on the product.
# Structured data may only state a condition the tenant chose — see product_json_ld().
PRODUCT_CONDITIONS = {
    "new": "https://schema.org/NewCondition",
    "refurbished": "https://schema.org/RefurbishedCondition",
    "used": "https://schema.org/UsedCondition",
    "damaged": "https://schema.org/DamagedCondition",
}
SUPPORTED_PAGE_TEMPLATES = {"universal_bundle"}
# The goal enum comes from composition_rules.json — the composer's source of truth — so the goals a page may
# store can never drift from the goals the composer understands. Empty means the rules file failed to load
# (composition.py degrades rather than raising at import); accept any string then instead of rejecting every
# page. See plans/LANDING_PAGE_GOAL_COMPOSITION.md.
SUPPORTED_PAGE_GOALS = set(supported_goals())
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
    # Socialite palettes (plans/SOCIALITE_PARITY.md)
    "linkedin-blue",
    "instagram-gradient",
    "tiktok-dark",
    "youtube-red",
    "twitter-dark",
    "professional-gray",
}
SUPPORTED_FONT_SERVICES = {"system", "junior-bay"}
SUPPORTED_FONT_FALLBACKS = {"system", "sans-serif", "serif", "monospace"}
SUPPORTED_APP_CONFIG_ENVIRONMENTS = {"dev", "prod"}
SUPPORTED_PLATFORM_FEE_TIERS = {"basic", "standard", "pro"}
SUPPORTED_PLATFORM_FEE_CLASSES = {"physical", "digital", "tip_jar"}
SUPPORTED_STRIPE_FEE_RATE_TYPES = {"domestic_card", "international_card"}
OFFER_UI_ONLY_FIELDS = {"intentLabel", "image", "productSummary"}
PRODUCT_FIELD_ORDER = [
    "schema_version",
    "document_type",
    "tenant_id",
    "product_id",
    "stripe_product_id",
    "stripe_mode",
    "canonical",
    "status",
    "name",
    "description",
    "images",
    "product_intent",
    "product_type",
    "product_category",
    "sku",
    "condition",
    "refund_policy",
    "variants",
    "stripe_metadata",
    "prices",
    "default_price_id",
    "fulfillment",
    "sync",
    "created_at",
    "updated_at",
    "tags",
]


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    return value


def order_product_document(document: dict[str, Any]) -> dict[str, Any]:
    document = canonical_product_document(document)
    ordered: dict[str, Any] = {}
    for field in PRODUCT_FIELD_ORDER:
        if field in document:
            ordered[field] = document[field]
    for field, value in document.items():
        if field not in ordered and field != "tags":
            ordered[field] = value
    if "tags" in document:
        ordered["tags"] = document["tags"]
    return ordered


def canonical_product_document(document: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(document)
    if "status" not in canonical:
        canonical["status"] = "archived" if canonical.get("active") is False else "active"
    canonical.pop("active", None)

    prices = []
    for price in canonical.get("prices") or []:
        if not isinstance(price, dict):
            prices.append(price)
            continue
        clean_price = dict(price)
        clean_price.pop("product_id", None)
        clean_price.pop("stripe_mode", None)
        clean_price.pop("active", None)
        metadata = clean_price.get("metadata")
        if isinstance(metadata, dict) and metadata.get("items") == str(clean_price.get("quantity")):
            metadata = dict(metadata)
            metadata.pop("items", None)
            if metadata:
                clean_price["metadata"] = metadata
            else:
                clean_price.pop("metadata", None)
        prices.append(clean_price)
    if "prices" in canonical:
        canonical["prices"] = prices
    return canonical


def product_stripe_sync_gate(document: dict[str, Any]) -> dict[str, str]:
    if not document.get("canonical"):
        return {"status": "skipped", "reason": "document not canonical"}
    return {"status": "ready"}


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


def validate_font_settings(fonts: Any, label: str) -> None:
    if fonts is None:
        return
    if not isinstance(fonts, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    if fonts.get("service") is not None:
        require_enum(fonts, "service", SUPPORTED_FONT_SERVICES, f"{label}.service")
    for role in ["body", "heading", "accent"]:
        font = fonts.get(role)
        if font is None:
            continue
        if not isinstance(font, dict):
            raise DocumentValidationError(f"{label}.{role} must be an object.")
        family = font.get("family")
        if family is not None and (not isinstance(family, str) or not FONT_FAMILY_PATTERN.match(family)):
            raise DocumentValidationError(f"{label}.{role}.family must be a safe font family.")
        if font.get("fallback") is not None:
            require_enum(font, "fallback", SUPPORTED_FONT_FALLBACKS, f"{label}.{role}.fallback")


def validate_thank_you_page(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    has_page_id = value.get("page_id") not in (None, "")
    has_url = value.get("url") not in (None, "")
    if has_page_id == has_url:
        raise DocumentValidationError(f"{label} must define exactly one of page_id or url.")
    if has_page_id:
        require_string(value, "page_id", f"{label}.page_id")
    if has_url:
        url = require_string(value, "url", f"{label}.url")
        if not HTTP_URL_PATTERN.match(url):
            raise DocumentValidationError(f"{label}.url must be an HTTP(S) URL.")


def validate_funnel_steps(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise DocumentValidationError(f"{label} must be a non-empty array.")
    step_ids: set[str] = set()
    targets: list[tuple[str, str]] = []
    for index, step in enumerate(value):
        step_label = f"{label}[{index}]"
        if not isinstance(step, dict):
            raise DocumentValidationError(f"{step_label} must be an object.")
        step_id = require_string(step, "step_id", f"{step_label}.step_id")
        if step_id in step_ids:
            raise DocumentValidationError(f"Duplicate funnel step id '{step_id}'.")
        step_ids.add(step_id)
        require_string(step, "page_id", f"{step_label}.page_id")
        for field in ["on_accept", "on_decline"]:
            if step.get(field) is not None:
                targets.append((f"{step_label}.{field}", require_string(step, field, f"{step_label}.{field}")))
    for target_label, target in targets:
        if target != "thank_you" and target not in step_ids:
            raise DocumentValidationError(f"{target_label} target '{target}' must reference a funnel step_id or thank_you.")


def validate_page_post_checkout(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise DocumentValidationError("Page post_checkout must be an object.")
    has_funnel_id = value.get("funnel_id") not in (None, "")
    has_inline_config = "thank_you_page" in value or "funnel_steps" in value
    if has_funnel_id and has_inline_config:
        raise DocumentValidationError("Page post_checkout must use either funnel_id or inline configuration, not both.")
    if has_funnel_id:
        require_string(value, "funnel_id", "Page post_checkout.funnel_id")
        return
    if not has_inline_config:
        raise DocumentValidationError("Page post_checkout must define thank_you_page or funnel_id.")
    if "thank_you_page" not in value:
        raise DocumentValidationError("Page post_checkout.thank_you_page is required for inline configuration.")
    validate_thank_you_page(value.get("thank_you_page"), "Page post_checkout.thank_you_page")
    if "funnel_steps" in value:
        validate_funnel_steps(value.get("funnel_steps"), "Page post_checkout.funnel_steps")


def require_positive_int(document: dict[str, Any], field: str, label: str | None = None) -> int:
    value = document.get(field)
    field_label = label or field
    if isinstance(value, bool):
        raise DocumentValidationError(f"{field_label} must be a positive integer.")
    if isinstance(value, Decimal):
        if value <= 0 or value != value.to_integral_value():
            raise DocumentValidationError(f"{field_label} must be a positive integer.")
        return int(value)
    if not isinstance(value, int) or value <= 0:
        raise DocumentValidationError(f"{field_label} must be a positive integer.")
    return value


def optional_non_negative_int(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is None:
        return
    if isinstance(value, bool):
        raise DocumentValidationError(f"{label or field} must be a non-negative integer.")
    if isinstance(value, Decimal):
        if value < 0 or value != value.to_integral_value():
            raise DocumentValidationError(f"{label or field} must be a non-negative integer.")
        return
    if not isinstance(value, int) or value < 0:
        raise DocumentValidationError(f"{label or field} must be a non-negative integer.")


def optional_non_negative_number(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DocumentValidationError(f"{label or field} must be a non-negative number.")
    if Decimal(str(value)) < 0:
        raise DocumentValidationError(f"{label or field} must be a non-negative number.")


def require_percent_number(document: dict[str, Any], field: str, label: str | None = None) -> None:
    field_label = label or field
    if field not in document:
        raise DocumentValidationError(f"{field_label} must be provided.")
    optional_non_negative_number(document, field, field_label)
    if Decimal(str(document[field])) > 100:
        raise DocumentValidationError(f"{field_label} must be no more than 100.")


def require_fee_rate(document: dict[str, Any], field: str, label: str | None = None) -> None:
    value = document.get(field)
    field_label = label or field
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DocumentValidationError(f"{field_label} must be a number between 0 and 1.")
    if Decimal(str(value)) < 0 or Decimal(str(value)) > 1:
        raise DocumentValidationError(f"{field_label} must be a number between 0 and 1.")


def validate_price_fee_breakdown(breakdown: Any, label: str) -> None:
    if breakdown is None:
        return
    if not isinstance(breakdown, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    for field in ["tenant_keyed_amount", "stripe_fee", "platform_fee", "net_payout"]:
        if field not in breakdown:
            raise DocumentValidationError(f"{label}.{field} must be provided.")
        optional_non_negative_int(breakdown, field, f"{label}.{field}")


def validate_stripe_fee_schedule(schedule: Any, label: str) -> None:
    if schedule is None:
        return
    if not isinstance(schedule, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    if schedule.get("document_type") != "stripe_fee_schedule":
        raise DocumentValidationError(f"{label}.document_type must be 'stripe_fee_schedule'.")
    require_string(schedule, "effective_date", f"{label}.effective_date")
    rates = schedule.get("rates")
    if not isinstance(rates, dict):
        raise DocumentValidationError(f"{label}.rates must be an object.")
    for rate_name in sorted(SUPPORTED_STRIPE_FEE_RATE_TYPES):
        rate = rates.get(rate_name)
        if not isinstance(rate, dict):
            raise DocumentValidationError(f"{label}.rates.{rate_name} must be an object.")
        if "percentage" not in rate:
            raise DocumentValidationError(f"{label}.rates.{rate_name}.percentage must be provided.")
        optional_non_negative_number(rate, "percentage", f"{label}.rates.{rate_name}.percentage")
        if Decimal(str(rate["percentage"])) > 100:
            raise DocumentValidationError(f"{label}.rates.{rate_name}.percentage must be no more than 100.")
        if "fixed_cents" not in rate:
            raise DocumentValidationError(f"{label}.rates.{rate_name}.fixed_cents must be provided.")
        optional_non_negative_int(rate, "fixed_cents", f"{label}.rates.{rate_name}.fixed_cents")


def validate_global_billing_config(document: dict[str, Any]) -> None:
    require_object(document, "Global billing config document")
    require_fields(
        document,
        [
            "schema_version",
            "document_type",
            "effective_date",
            "canonical",
            "platform_fees",
            "payment_processing",
            "created_at",
            "updated_at",
        ],
    )
    if document.get("document_type") != "global_billing_config":
        raise DocumentValidationError("Global billing config document_type must be 'global_billing_config'.")
    if document.get("canonical") is not True:
        raise DocumentValidationError("Global billing config canonical must be true.")
    require_string(document, "effective_date", "Global billing config effective_date")
    optional_non_negative_int(document, "created_at", "Global billing config created_at")
    optional_non_negative_int(document, "updated_at", "Global billing config updated_at")

    platform_fees = require_object(document.get("platform_fees"), "Global billing config platform_fees")
    if platform_fees.get("unit") != "percent":
        raise DocumentValidationError("Global billing config platform_fees.unit must be 'percent'.")
    tiers = require_object(platform_fees.get("tiers"), "Global billing config platform_fees.tiers")
    for tier in sorted(SUPPORTED_PLATFORM_FEE_TIERS):
        fee_tier = require_object(tiers.get(tier), f"Global billing config platform_fees.tiers.{tier}")
        for fee_class in sorted(SUPPORTED_PLATFORM_FEE_CLASSES):
            require_percent_number(
                fee_tier,
                fee_class,
                f"Global billing config platform_fees.tiers.{tier}.{fee_class}",
            )

    payment_processing = require_object(
        document.get("payment_processing"),
        "Global billing config payment_processing",
    )
    schedules = require_object(
        payment_processing.get("schedules"),
        "Global billing config payment_processing.schedules",
    )
    if not schedules:
        raise DocumentValidationError("Global billing config payment_processing.schedules must not be empty.")
    for schedule_key, schedule in schedules.items():
        if not isinstance(schedule_key, str) or not schedule_key:
            raise DocumentValidationError("Global billing config payment_processing.schedules keys must be strings.")
        schedule_doc = require_object(
            schedule,
            f"Global billing config payment_processing.schedules.{schedule_key}",
        )
        require_string(
            schedule_doc,
            "merchant_loc",
            f"Global billing config payment_processing.schedules.{schedule_key}.merchant_loc",
        )
        require_string(
            schedule_doc,
            "settlement_currency",
            f"Global billing config payment_processing.schedules.{schedule_key}.settlement_currency",
        )
        rates = require_object(
            schedule_doc.get("rates"),
            f"Global billing config payment_processing.schedules.{schedule_key}.rates",
        )
        if "domestic_card" not in rates:
            raise DocumentValidationError(
                f"Global billing config payment_processing.schedules.{schedule_key}.rates.domestic_card must be provided."
            )
        for rate_name, rate in rates.items():
            if not isinstance(rate_name, str) or not rate_name:
                raise DocumentValidationError(
                    f"Global billing config payment_processing.schedules.{schedule_key}.rates keys must be strings."
                )
            rate_doc = require_object(
                rate,
                f"Global billing config payment_processing.schedules.{schedule_key}.rates.{rate_name}",
            )
            require_percent_number(
                rate_doc,
                "percentage",
                f"Global billing config payment_processing.schedules.{schedule_key}.rates.{rate_name}.percentage",
            )
            if "fixed_cents" not in rate_doc:
                raise DocumentValidationError(
                    f"Global billing config payment_processing.schedules.{schedule_key}.rates.{rate_name}.fixed_cents must be provided."
                )
            optional_non_negative_int(
                rate_doc,
                "fixed_cents",
                f"Global billing config payment_processing.schedules.{schedule_key}.rates.{rate_name}.fixed_cents",
            )
            require_string(
                rate_doc,
                "condition",
                f"Global billing config payment_processing.schedules.{schedule_key}.rates.{rate_name}.condition",
            )


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


def validate_product_lead_capture(document: dict[str, Any]) -> None:
    lead_capture = document.get("lead_capture")
    if document.get("product_intent") == "lead_gen" and not isinstance(lead_capture, dict):
        raise DocumentValidationError("Product lead_capture must be provided for lead generation products.")
    if lead_capture is None:
        return
    if not isinstance(lead_capture, dict):
        raise DocumentValidationError("Product lead_capture must be an object.")
    action = require_enum(
        lead_capture,
        "action",
        {"capture_email", "capture_phone", "capture_email_phone", "call_number", "external_url", "open_form", "social_redirect"},
        "Product lead_capture.action",
    )
    require_string(lead_capture, "title", "Product lead_capture.title")
    require_string(lead_capture, "description", "Product lead_capture.description")
    if action in {"capture_email", "capture_phone", "capture_email_phone"}:
        fields = lead_capture.get("fields")
        if not isinstance(fields, list) or not fields:
            raise DocumentValidationError("Product lead_capture.fields must be a non-empty array for capture actions.")
        for field in fields:
            if not isinstance(field, dict):
                raise DocumentValidationError("Each Product lead_capture.fields item must be an object.")
            require_string(field, "name", "Product lead_capture.fields.name")
            require_string(field, "type", "Product lead_capture.fields.type")
            optional_bool(field, "required", "Product lead_capture.fields.required")
        return
    target = lead_capture.get("target")
    if not isinstance(target, dict):
        raise DocumentValidationError("Product lead_capture.target must be an object for target actions.")
    expected_type = {
        "call_number": "phone",
        "external_url": "url",
        "open_form": "form",
        "social_redirect": "social",
    }[action]
    if target.get("type") != expected_type:
        raise DocumentValidationError(f"Product lead_capture.target.type must be '{expected_type}'.")
    if action == "open_form":
        require_string(target, "form_id", "Product lead_capture.target.form_id")
    else:
        require_string(target, "value", "Product lead_capture.target.value")
    if action == "social_redirect":
        require_string(target, "platform", "Product lead_capture.target.platform")
    optional_string(target, "open", "Product lead_capture.target.open")


def validate_product_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "product", "product_id")
    require_string(document, "name")
    require_string(document, "default_price_id")
    for legacy_field in ["requires_shipping", "package_dimensions", "local_metadata"]:
        if legacy_field in document:
            raise DocumentValidationError(f"Product {legacy_field} is no longer supported; use the canonical product shape.")
    if "canonical" not in document:
        raise DocumentValidationError("Product canonical must be provided.")
    optional_bool(document, "canonical")
    if "active" in document:
        raise DocumentValidationError("Product active is no longer supported; use status.")
    require_enum(document, "status", {"active", "archived"}, "Product status")
    optional_string(document, "stripe_product_id")
    if document.get("stripe_mode") is not None:
        require_enum(document, "stripe_mode", {"test", "live"})
    optional_string(document, "description")
    if document.get("product_intent") is not None:
        require_enum(document, "product_intent", {"transaction", "lead_gen"}, "Product product_intent")
    optional_string(document, "product_type")
    require_string(document, "product_category", "Product product_category")
    # Both optional: they enrich structured data (sku, itemCondition) and pages without them still render.
    optional_string(document, "sku", "Product sku")
    if document.get("condition") is not None:
        require_enum(document, "condition", set(PRODUCT_CONDITIONS), "Product condition")
    optional_string_list(document, "images")
    validate_product_lead_capture(document)
    if "tags" not in document:
        raise DocumentValidationError("Product tags must be provided.")
    optional_string_list(document, "tags")
    fulfillment = document.get("fulfillment")
    if not isinstance(fulfillment, dict):
        raise DocumentValidationError("Product fulfillment must be an object.")
    for field in ["requires_shipping", "ship_from", "weight_lb", "dimensions"]:
        if field not in fulfillment:
            raise DocumentValidationError(f"Product fulfillment.{field} must be provided.")
    optional_bool(fulfillment, "requires_shipping", "Product fulfillment.requires_shipping")
    optional_non_negative_number(fulfillment, "weight_lb", "Product fulfillment.weight_lb")
    ship_from = fulfillment.get("ship_from")
    if ship_from is not None and not isinstance(ship_from, dict):
        raise DocumentValidationError("Product fulfillment.ship_from must be an object when provided.")
    dimensions = fulfillment.get("dimensions")
    if not isinstance(dimensions, dict):
        raise DocumentValidationError("Product fulfillment.dimensions must be an object.")
    for field in ["length_in", "width_in", "height_in"]:
        if field not in dimensions:
            raise DocumentValidationError(f"Product fulfillment.dimensions.{field} must be provided.")
        optional_non_negative_number(dimensions, field, f"Product fulfillment.dimensions.{field}")

    refund_policy = document.get("refund_policy")
    if refund_policy is not None:
        if not isinstance(refund_policy, dict):
            raise DocumentValidationError("Product refund_policy must be an object.")
        optional_string(refund_policy, "source", "Product refund_policy.source")
        require_string(refund_policy, "short_label", "Product refund_policy.short_label")
        require_string(refund_policy, "full_policy", "Product refund_policy.full_policy")
        optional_string(refund_policy, "condition", "Product refund_policy.condition")
        optional_string(refund_policy, "return_method", "Product refund_policy.return_method")

    sync = document.get("sync")
    if not isinstance(sync, dict):
        raise DocumentValidationError("Product sync must be an object.")
    sync_status = sync.get("status")
    if sync_status is not None and sync_status not in {"pending", "success", "failed", "drift", "not_applicable"}:
        raise DocumentValidationError("Product sync.status must be one of: failed, not_applicable, pending, success, or null.")
    optional_non_negative_int(sync, "last_synced_at", "Product sync.last_synced_at")
    optional_string(sync, "error", "Product sync.error")

    digital_asset = document.get("digital_asset")
    if digital_asset is not None:
        if not isinstance(digital_asset, dict):
            raise DocumentValidationError("Product digital_asset must be an object.")
        require_string(digital_asset, "asset_id", "Product digital_asset.asset_id")
        require_string(digital_asset, "bucket_key", "Product digital_asset.bucket_key")
        require_string(digital_asset, "filename", "Product digital_asset.filename")

    prices = document.get("prices")
    if not isinstance(prices, list) or not prices:
        raise DocumentValidationError("Product prices must be a non-empty array.")

    price_ids = set()
    for price in prices:
        if not isinstance(price, dict):
            raise DocumentValidationError("Each product price must be an object.")
        for field in ["price_id", "currency"]:
            require_string(price, field, f"price.{field}")
        optional_string(price, "stripe_price_id", "price.stripe_price_id")
        pricing_model = price.setdefault("pricing_model", "one_time")
        if pricing_model not in {"one_time", "recurring", "customer_chooses"}:
            raise DocumentValidationError("price.pricing_model must be one of: customer_chooses, one_time, recurring.")
        if pricing_model == "customer_chooses":
            optional_non_negative_int(price, "unit_amount", "price.unit_amount")
            optional_non_negative_int(price, "min_amount", "price.min_amount")
            optional_non_negative_int(price, "suggested_amount", "price.suggested_amount")
        else:
            if price.get("unit_amount") is None:
                raise DocumentValidationError("price.unit_amount must be provided unless pricing_model is customer_chooses.")
            optional_non_negative_int(price, "unit_amount", "price.unit_amount")
        require_positive_int(price, "quantity", "price.quantity")
        if "label" in price:
            raise DocumentValidationError("price.label is no longer supported; labels belong on offer items.")
        if "nickname" in price:
            raise DocumentValidationError("price.nickname is no longer supported.")
        if "product_id" in price:
            raise DocumentValidationError("price.product_id is redundant; product prices inherit the parent product_id.")
        if "stripe_mode" in price:
            raise DocumentValidationError("price.stripe_mode is redundant; product prices inherit the parent stripe_mode.")
        if "active" in price:
            raise DocumentValidationError("price.active is no longer supported; use product status for lifecycle state.")
        optional_string(price, "context", "price.context")
        optional_string(price, "badge", "price.badge")
        optional_string(price, "description", "price.description")
        optional_string(price, "image_url", "price.image_url")
        optional_non_negative_int(price, "discount_pct", "price.discount_pct")
        optional_non_negative_int(price, "compare_at_unit_amount", "price.compare_at_unit_amount")
        optional_non_negative_int(price, "tenant_keyed_amount", "price.tenant_keyed_amount")
        validate_price_fee_breakdown(price.get("fee_breakdown"), "price.fee_breakdown")
        if len(price.get("currency", "")) != 3 or price.get("currency", "") != price.get("currency", "").lower():
            raise DocumentValidationError("price.currency must be a lowercase 3-letter currency code.")
        if price.get("price_id") in price_ids:
            raise DocumentValidationError(f"Duplicate product price_id '{price.get('price_id')}'.")
        price_ids.add(price.get("price_id"))

    if document.get("default_price_id") not in price_ids:
        raise DocumentValidationError("Product default_price_id must reference one of its prices.")


def validate_offer_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "offer", "offer_id")
    ui_only_fields = sorted(field for field in OFFER_UI_ONLY_FIELDS if field in document)
    if ui_only_fields:
        raise DocumentValidationError(f"Offer contains UI-only fields: {', '.join(ui_only_fields)}.")
    require_string(document, "name")
    if document.get("status") is not None:
        require_enum(document, "status", {"draft", "active", "archived"}, "Offer status")
    require_enum(document, "product_intent", {"transaction", "lead_gen"}, "Offer product_intent")
    require_enum(document, "stripe_mode", {"test", "live"}, "Offer stripe_mode")
    # offer_type drives landing-page rendering: single/bundle -> pick-one price selector; listicle -> a
    # carousel of the offer's items, each add-to-cart (plans/LISTICLE_AND_CART.md). Optional, default single.
    if document.get("offer_type") is not None:
        require_enum(document, "offer_type", {"single", "bundle", "listicle"}, "Offer offer_type")
    if document.get("context") is not None:
        require_enum(document, "context", {"standard", "sale", "flash_sale", "upsell", "downsell", "order_bump"}, "Offer context")
    # The Offer coordinates how its scheduled services are delivered (single_visit collapses them
    # into one appointment; separate_visits gives each its own). Optional; defaults to single_visit.
    if document.get("service_booking_mode") is not None:
        require_enum(document, "service_booking_mode", {"single_visit", "separate_visits"}, "Offer service_booking_mode")
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise DocumentValidationError("Offer items must be a non-empty array.")

    for item in items:
        if not isinstance(item, dict):
            raise DocumentValidationError("Each offer item must be an object.")
        # An item references exactly one of a product or a service (STORY-2.1).
        has_product = bool(item.get("product_id"))
        has_service = bool(item.get("service_id"))
        if has_product == has_service:
            raise DocumentValidationError("Offer item must reference exactly one of product_id or service_id.")
        if has_service:
            # An offer may carry N service items; the Offer's service_booking_mode coordinates how the
            # scheduled ones are grouped into appointments (STORY-2.1).
            require_string(item, "service_id", "offer item service_id")
            # Service items use the fixed price_id path only (no selectable_prices / packages).
            if item.get("selectable_prices"):
                raise DocumentValidationError("Service offer items must use price_id, not selectable_prices.")
            require_string(item, "price_id", "offer item price_id")
            require_positive_int(item, "quantity", "offer item quantity")
            if item.get("booking_flow") is not None:
                require_enum(item, "booking_flow", {"book_then_pay", "pay_then_book"}, "offer item booking_flow")
            if document.get("product_intent") != "transaction":
                raise DocumentValidationError("Service offer items require product_intent 'transaction'.")
            optional_string(item, "presentation_context", "offer item presentation_context")
            continue
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
                optional_string(price, "label", "selectable price label")
                optional_string(price, "badge", "selectable price badge")
                optional_string(price, "description", "selectable price description")
                optional_string(price, "image_url", "selectable price image_url")
                optional_non_negative_int(price, "display_discount_pct", "selectable price display_discount_pct")
                if price.get("price_id") in selectable_price_ids:
                    raise DocumentValidationError(f"Duplicate selectable price_id '{price.get('price_id')}'.")
                selectable_price_ids.add(price.get("price_id"))
            if not selectable_price_ids:
                raise DocumentValidationError("selectable_prices must include at least one price_id.")
            if item.get("default_price_id") not in selectable_price_ids:
                raise DocumentValidationError("default_price_id must reference one of selectable_prices.")

    discount = document.get("discount")
    if not isinstance(discount, dict):
        raise DocumentValidationError("Offer discount must be an object.")
    discount_mode = require_enum(discount, "mode", {"none", "auto", "coupon_code", "promotion_code"}, "Offer discount.mode")
    if document.get("product_intent") == "lead_gen" and discount_mode != "none":
        raise DocumentValidationError("Lead generation offers cannot include payment discounts.")
    if discount_mode == "coupon_code":
        require_string(discount, "coupon_id", "Offer discount.coupon_id")
    if discount_mode == "promotion_code":
        require_string(discount, "promotion_code", "Offer discount.promotion_code")
    if discount_mode == "auto":
        require_enum(discount, "type", {"percent", "fixed"}, "Offer discount.type")
        optional_non_negative_number(discount, "value", "Offer discount.value")
        require_enum(discount, "duration", {"once", "repeating", "forever"}, "Offer discount.duration")
        optional_bool(discount, "first_time_only", "Offer discount.first_time_only")
        if discount.get("type") == "fixed":
            currency = require_string(discount, "currency", "Offer discount.currency")
            if len(currency) != 3 or currency != currency.lower():
                raise DocumentValidationError("Offer discount.currency must be a lowercase 3-letter currency code.")
        if discount.get("duration") == "repeating":
            require_positive_int(discount, "duration_months", "Offer discount.duration_months")

    checkout = document.get("checkout")
    if document.get("product_intent") == "transaction":
        if not isinstance(checkout, dict):
            raise DocumentValidationError("Offer checkout must be an object.")
        require_enum(checkout, "mode", {"payment", "subscription"}, "Offer checkout.mode")
        optional_bool(checkout, "allow_promotion_codes", "Offer checkout.allow_promotion_codes")
        if checkout.get("phone_number_collection") is not None:
            require_enum(checkout, "phone_number_collection", {"inherit", "enabled", "disabled"}, "Offer checkout.phone_number_collection")
        metadata = checkout.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise DocumentValidationError("Offer checkout.metadata must be an object.")
    elif checkout is not None:
        raise DocumentValidationError("Lead generation offers must not include checkout.")

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
        optional_string(presentation, "subheadline", "Offer presentation.subheadline")
        optional_string(presentation, "badge", "Offer presentation.badge")
        optional_string(presentation, "cta_label", "Offer presentation.cta_label")
        optional_string(presentation, "hero_image_url", "Offer presentation.hero_image_url")
        cta = presentation.get("cta")
        if cta is not None:
            if not isinstance(cta, dict):
                raise DocumentValidationError("Offer presentation.cta must be an object.")
            require_enum(cta, "type", {"buy", "call", "email", "external", "download", "booking", "appointment"}, "Offer presentation.cta.type")
            optional_string(cta, "label", "Offer presentation.cta.label")
            optional_string(cta, "target", "Offer presentation.cta.target")


def validate_coupon_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "coupon", "coupon_id")
    require_string(document, "stripe_coupon_id", "Coupon stripe_coupon_id")
    require_string(document, "stripe_promo_code_id", "Coupon stripe_promo_code_id")
    code = require_string(document, "code", "Coupon code")
    if not re.match(r"^[A-Z0-9_-]+$", code):
        raise DocumentValidationError("Coupon code must contain only uppercase letters, numbers, underscores, or hyphens.")
    optional_string(document, "name", "Coupon name")
    require_enum(document, "stripe_mode", {"test", "live"}, "Coupon stripe_mode")
    require_enum(document, "status", {"active", "inactive", "expired", "fully_redeemed"}, "Coupon status")
    if document.get("canonical") is not True:
        raise DocumentValidationError("Coupon canonical must be true.")

    discount = require_object(document.get("discount"), "Coupon discount")
    discount_type = require_enum(discount, "type", {"percent", "fixed"}, "Coupon discount.type")
    optional_non_negative_number(discount, "value", "Coupon discount.value")
    if discount_type == "percent" and Decimal(str(discount.get("value", 0))) > 100:
        raise DocumentValidationError("Coupon percent discount.value cannot exceed 100.")
    if discount_type == "fixed":
        currency = require_string(discount, "currency", "Coupon discount.currency")
        if len(currency) != 3 or currency != currency.lower():
            raise DocumentValidationError("Coupon discount.currency must be a lowercase 3-letter currency code.")
    require_enum(discount, "duration", {"once", "repeating", "forever"}, "Coupon discount.duration")
    if discount.get("duration") == "repeating":
        require_positive_int(discount, "duration_months", "Coupon discount.duration_months")

    restrictions = require_object(document.get("restrictions"), "Coupon restrictions")
    optional_non_negative_int(restrictions, "expires_at", "Coupon restrictions.expires_at")
    for field in ["max_redemptions", "max_redemptions_per_customer"]:
        value = restrictions.get(field)
        if value is not None:
            require_positive_int(restrictions, field, f"Coupon restrictions.{field}")
    optional_bool(restrictions, "first_time_only", "Coupon restrictions.first_time_only")
    optional_non_negative_int(restrictions, "minimum_amount", "Coupon restrictions.minimum_amount")
    if restrictions.get("minimum_amount") is not None:
        currency = require_string(restrictions, "minimum_amount_currency", "Coupon restrictions.minimum_amount_currency")
        if len(currency) != 3 or currency != currency.lower():
            raise DocumentValidationError("Coupon restrictions.minimum_amount_currency must be a lowercase 3-letter currency code.")

    applies_to_offer_ids = document.get("applies_to_offer_ids")
    if not isinstance(applies_to_offer_ids, list):
        raise DocumentValidationError("Coupon applies_to_offer_ids must be an array.")
    if any(not isinstance(offer_id, str) or not offer_id.strip() for offer_id in applies_to_offer_ids):
        raise DocumentValidationError("Coupon applies_to_offer_ids must contain only non-empty strings.")
    optional_non_negative_int(document, "redemption_count", "Coupon redemption_count")

    sync = require_object(document.get("sync"), "Coupon sync")
    if sync.get("status") != "synced":
        raise DocumentValidationError("Coupon sync.status must be synced.")
    optional_non_negative_int(sync, "last_synced_at", "Coupon sync.last_synced_at")
    if sync.get("error") is not None:
        raise DocumentValidationError("Coupon sync.error must be null.")

    optional_non_negative_int(document, "created_at", "Coupon created_at")
    optional_non_negative_int(document, "updated_at", "Coupon updated_at")


def validate_page_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "page", "page_id")
    require_string(document, "name")
    require_string(document, "offer_id")
    if document.get("status") is not None:
        require_enum(document, "status", {"draft", "published", "archived"})
    # goal is optional: pages created before the goal axis simply compose from the offer_type base.
    if document.get("goal") is not None:
        if SUPPORTED_PAGE_GOALS:
            require_enum(document, "goal", SUPPORTED_PAGE_GOALS, "Page goal")
        else:
            optional_string(document, "goal", "Page goal")
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
                if not isinstance(key, str) or not isinstance(value, str) or not CSS_COLOR_PATTERN.match(value):
                    raise DocumentValidationError("Page theme.tokens values must be valid CSS colors.")
        validate_font_settings(theme.get("fonts"), "Page theme.fonts")

    validate_page_post_checkout(document.get("post_checkout"))

    composition = document.get("composition")
    if composition is not None:
        if not isinstance(composition, dict):
            raise DocumentValidationError("Page composition must be an object.")
        overrides = composition.get("overrides")
        if overrides is not None and not isinstance(overrides, dict):
            raise DocumentValidationError("Page composition.overrides must be an object.")

    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DocumentValidationError("Page sections must be a non-empty array.")
    section_ids = set()
    for section in sections:
        if not isinstance(section, dict):
            raise DocumentValidationError("Each page section must be an object.")
        section_id = require_string(section, "id", "Page section id")
        if SUPPORTED_PAGE_SECTION_TYPES:
            section_type = require_enum(section, "type", SUPPORTED_PAGE_SECTION_TYPES, "Page section type")
        else:
            section_type = require_string(section, "type", "Page section type")
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
            optional_string(section, "avatar_url", "Hero avatar_url")
            optional_string(section, "brand_text", "Hero brand_text")
            optional_bool(section, "brand_overlay", "Hero brand_overlay")
            if section.get("brand_position") is not None:
                require_enum(section, "brand_position", {"top-left", "top-right", "bottom-left", "bottom-right"}, "Hero brand_position")
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
            optional_bool(section, "enabled", "Refund policy enabled")
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
        elif section_type == "testimonials":
            optional_string(section, "heading", "Testimonials heading")
            items = optional_limited_object_list(section, "items", 12, "Testimonials")
            for item in items:
                require_string(item, "quote", "Testimonial quote")
                optional_string(item, "author", "Testimonial author")
                optional_string(item, "role", "Testimonial role")
                optional_string(item, "avatar_url", "Testimonial avatar_url")
        elif section_type == "rating":
            optional_string(section, "label", "Rating label")
            value = section.get("value")
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 5):
                raise DocumentValidationError("Rating value must be a number between 0 and 5.")
            count = section.get("count")
            if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
                raise DocumentValidationError("Rating count must be a non-negative integer.")
        elif section_type == "client_marquee":
            optional_string(section, "heading", "Client marquee heading")
            logos = optional_limited_object_list(section, "logos", 24, "Client marquee logos")
            for logo in logos:
                require_string(logo, "image_url", "Client marquee logo image_url")
                optional_string(logo, "name", "Client marquee logo name")
        elif section_type == "product_carousel":
            optional_string(section, "heading", "Product carousel heading")
            optional_string_list(section, "offer_ids", "Product carousel offer_ids")
            if isinstance(section.get("offer_ids"), list) and len(section["offer_ids"]) > 24:
                raise DocumentValidationError("Product carousel supports at most 24 offers.")
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


def validate_app_config(document: dict[str, Any]) -> None:
    require_object(document, "App config document")
    require_fields(document, ["schema_version", "document_type", "config_key", "environment", "environments"])
    if document.get("document_type") != "app_config":
        raise DocumentValidationError("App config document_type must be 'app_config'.")
    if document.get("config_key") != "app_config":
        raise DocumentValidationError("App config config_key must be 'app_config'.")
    if document.get("environment") != "global":
        raise DocumentValidationError("App config environment must be 'global'.")
    optional_non_negative_int(document, "created_at", "App config created_at")
    optional_non_negative_int(document, "updated_at", "App config updated_at")
    environments = document.get("environments")
    if not isinstance(environments, dict):
        raise DocumentValidationError("App config environments must be an object.")
    for environment in sorted(SUPPORTED_APP_CONFIG_ENVIRONMENTS):
        config = environments.get(environment)
        if not isinstance(config, dict):
            raise DocumentValidationError(f"App config environments.{environment} must be an object.")
        for field in ["label", "api_base_url", "dashboard_url", "checkout_base_url"]:
            require_string(config, field, f"App config environments.{environment}.{field}")
        for field in ["api_base_url", "dashboard_url", "checkout_base_url", "pages_base_url", "favicon_url", "public_asset_base_url"]:
            value = config.get(field)
            if value is not None and (not isinstance(value, str) or not HTTP_URL_PATTERN.match(value)):
                raise DocumentValidationError(f"App config environments.{environment}.{field} must be an HTTP URL.")
        feature_flags = config.get("feature_flags")
        if feature_flags is not None:
            if not isinstance(feature_flags, dict):
                raise DocumentValidationError(f"App config environments.{environment}.feature_flags must be an object.")
            for key, value in feature_flags.items():
                if not isinstance(key, str) or not isinstance(value, bool):
                    raise DocumentValidationError(f"App config environments.{environment}.feature_flags values must be boolean.")
    dashboard = document.get("dashboard")
    if dashboard is not None:
        if not isinstance(dashboard, dict):
            raise DocumentValidationError("App config dashboard must be an object.")
        optional_non_negative_int(dashboard, "display_order", "App config dashboard.display_order")
        editable_sections = dashboard.get("editable_sections")
        if editable_sections is not None and (
            not isinstance(editable_sections, list) or any(not isinstance(item, str) for item in editable_sections)
        ):
            raise DocumentValidationError("App config dashboard.editable_sections must be an array of strings.")
    metadata = document.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise DocumentValidationError("App config metadata must be an object.")


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
        for theme in custom_themes:
            if not isinstance(theme, dict):
                raise DocumentValidationError("Each user preferences custom color theme must be an object.")
            require_fields(theme, ["theme_id", "name", "tokens"])
            tokens = theme.get("tokens")
            if not isinstance(tokens, dict):
                raise DocumentValidationError("User preferences custom color theme tokens must be an object.")
            for key, value in tokens.items():
                if not isinstance(key, str) or not isinstance(value, str) or not HEX_COLOR_PATTERN.match(value):
                    raise DocumentValidationError("User preferences custom color theme tokens values must be hex colors.")
            validate_font_settings(theme.get("fonts"), "User preferences custom color theme fonts")
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


def validate_lead_submission(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "lead_id", "offer_id", "fields", "created_at"])
    if document.get("document_type") != "lead_submission":
        raise DocumentValidationError("Lead submission document_type must be 'lead_submission'.")
    if not isinstance(document.get("fields"), dict) or not document["fields"]:
        raise DocumentValidationError("Lead submission fields must be a non-empty object.")
    if document.get("status", "new") not in {"new", "contacted", "qualified", "archived"}:
        raise DocumentValidationError("Lead submission status is invalid.")
    consent = document.get("consent")
    if consent is not None and not isinstance(consent, dict):
        raise DocumentValidationError("Lead submission consent must be an object.")


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


def validate_refund(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "refund_id", "order_id", "amount", "created_at"])
    if document.get("document_type") != "refund":
        raise DocumentValidationError("Refund document_type must be 'refund'.")
    if not isinstance(document.get("amount"), int) or isinstance(document.get("amount"), bool) or document["amount"] < 0:
        raise DocumentValidationError("Refund amount must be a non-negative integer (cents).")


def validate_webhook_event(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "event_id", "event_type", "processed_at"])
    if document.get("document_type") != "webhook_event":
        raise DocumentValidationError("Webhook event document_type must be 'webhook_event'.")


_LEDGER_ENTRY_TYPES = {
    "sale", "refund", "dispute", "dispute_won", "shipping_cost",
    "cost_adjustment", "fee_adjustment", "tax_remittance", "adjustment",
}
_LEDGER_AMOUNT_COMPONENTS = {"gross", "stripe_fee", "platform_fee", "tax", "cogs", "shipping_cost"}


def validate_ledger_entry(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "entry_id", "entry_type", "occurred_at", "mode", "currency", "amounts", "idempotency_key"])
    if document.get("document_type") != "ledger_entry":
        raise DocumentValidationError("Ledger entry document_type must be 'ledger_entry'.")
    if document.get("entry_type") not in _LEDGER_ENTRY_TYPES:
        raise DocumentValidationError("Ledger entry entry_type is invalid.")
    if document.get("mode") not in {"test", "live"}:
        raise DocumentValidationError("Ledger entry mode must be 'test' or 'live'.")
    amounts = document.get("amounts")
    if not isinstance(amounts, dict):
        raise DocumentValidationError("Ledger entry amounts must be an object.")
    for key, value in amounts.items():
        if key not in _LEDGER_AMOUNT_COMPONENTS:
            raise DocumentValidationError(f"Unknown ledger amount component '{key}'.")
        if not isinstance(value, int) or isinstance(value, bool):
            raise DocumentValidationError("Ledger amount components must be integers (minor units).")


def validate_calendar_connection(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "connection_id", "provider", "status"])
    if document.get("document_type") != "calendar_connection":
        raise DocumentValidationError("Calendar connection document_type must be 'calendar_connection'.")
    if document.get("provider") not in {"google"}:
        raise DocumentValidationError("Calendar connection provider is invalid.")
    if document.get("status") not in {"connected", "revoked", "error"}:
        raise DocumentValidationError("Calendar connection status is invalid.")


def validate_route(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "short_code", "target_type"])
    if document.get("document_type") != "route":
        raise DocumentValidationError("Route document_type must be 'route'.")
    target_type = document.get("target_type")
    if target_type not in {"page", "url", "experiment"}:
        raise DocumentValidationError("Route target_type must be 'page', 'url', or 'experiment'.")
    required_target = {"page": "target_page_id", "url": "target_url", "experiment": "target_experiment_id"}[target_type]
    require_fields(document, [required_target])


def validate_experiment(document: dict[str, Any]) -> None:
    require_fields(
        document,
        ["schema_version", "document_type", "tenant_id", "experiment_id", "name", "status", "control_page_id", "variants"],
    )
    if document.get("document_type") != "experiment":
        raise DocumentValidationError("Experiment document_type must be 'experiment'.")
    if document.get("status") not in {"draft", "running", "paused", "completed"}:
        raise DocumentValidationError("Experiment status must be 'draft', 'running', 'paused', or 'completed'.")

    variants = document.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        raise DocumentValidationError("Experiment must have at least two variants.")

    keys: set[str] = set()
    page_ids: set[str] = set()
    total_weight = 0
    for variant in variants:
        if not isinstance(variant, dict):
            raise DocumentValidationError("Each experiment variant must be an object.")
        require_fields(variant, ["key", "page_id", "weight"])
        key = variant["key"]
        if key in keys:
            raise DocumentValidationError("Experiment variant keys must be unique.")
        keys.add(key)
        page_ids.add(variant["page_id"])
        weight = variant.get("weight")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
            raise DocumentValidationError("Experiment variant weight must be a non-negative integer.")
        total_weight += weight

    if total_weight <= 0:
        raise DocumentValidationError("Experiment variant weights must sum to a positive number.")
    if document.get("control_page_id") not in page_ids:
        raise DocumentValidationError("Experiment control_page_id must match one of the variants.")


def validate_legal_page(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "page_id"])
    if document.get("document_type") != "legal_page":
        raise DocumentValidationError("Legal page document_type must be 'legal_page'.")
    if document.get("page_id") not in {"terms", "privacy", "refund"}:
        raise DocumentValidationError("Legal page page_id must be 'terms', 'privacy', or 'refund'.")


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
    fulfillment_mode = document.get("fulfillment_mode")
    if fulfillment_mode is not None and fulfillment_mode not in {"scheduled", "no_booking"}:
        raise DocumentValidationError("Service fulfillment_mode must be scheduled or no_booking.")
    no_booking = fulfillment_mode == "no_booking"
    required = ["schema_version", "document_type", "tenant_id", "service_id", "name", "price"]
    if not no_booking:
        # Scheduled services (the default) need a duration to size the calendar slot; a no_booking
        # service has no slot, so duration_minutes is optional/absent.
        required.append("duration_minutes")
    require_fields(document, required)
    if document.get("document_type") != "service":
        raise DocumentValidationError("Service document_type must be 'service'.")
    if not no_booking and int(document.get("duration_minutes") or 0) <= 0:
        raise DocumentValidationError("Service duration_minutes must be positive.")
    price = document.get("price")
    if not isinstance(price, dict):
        raise DocumentValidationError("Service price must be an object.")
    require_fields(price, ["currency", "unit_amount"])
    prices = document.get("prices")
    if prices is not None:
        if not isinstance(prices, list):
            raise DocumentValidationError("Service prices must be an array.")
        for entry in prices:
            if not isinstance(entry, dict):
                raise DocumentValidationError("Each service price must be an object.")
            require_fields(entry, ["price_id", "currency", "unit_amount"])
            context = entry.get("context")
            if context is not None and context not in {"standard", "sale", "flash_sale"}:
                raise DocumentValidationError("Service price context must be standard, sale, or flash_sale.")
            if entry.get("fee_handling") is not None and entry.get("fee_handling") not in {"standard", "net_guaranteed"}:
                raise DocumentValidationError("Service price fee_handling must be standard or net_guaranteed.")
    if document.get("booking_flow") is not None and document.get("booking_flow") not in {"book_then_pay", "pay_then_book"}:
        raise DocumentValidationError("Service booking_flow must be book_then_pay or pay_then_book.")
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
    require_fields(document, ["schema_version", "document_type", "tenant_id", "appointment_id", "services", "status", "customer"])
    if document.get("document_type") != "appointment":
        raise DocumentValidationError("Appointment document_type must be 'appointment'.")
    # services[] is the single canonical shape; a single service is a one-element array. There is no
    # scalar service_id (greenfield — no back-compat, no mirror).
    services = document.get("services")
    if not isinstance(services, list) or not services:
        raise DocumentValidationError("Appointment services must be a non-empty array.")
    for line in services:
        if not isinstance(line, dict):
            raise DocumentValidationError("Each appointment service line must be an object.")
        require_fields(line, ["service_id", "price_id", "duration_minutes"])
    # A paid-but-unscheduled appointment (pay_then_book) has no time yet; require the time fields
    # only once it is scheduled (STORY-3.1).
    if not document.get("awaiting_schedule"):
        require_fields(document, ["starts_at", "ends_at", "timezone"])
    if document.get("source") is not None and document.get("source") not in {"booking_page", "offer", "invoice"}:
        raise DocumentValidationError("Appointment source must be booking_page, offer, or invoice.")
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
