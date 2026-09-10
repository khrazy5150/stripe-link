import re
from decimal import Decimal
from typing import Any

from stripe_link.domain.business_types import BUSINESS_TYPES
from stripe_link.domain.cart import CART_STATUSES, MAX_CART_LINES, MAX_LINE_QTY
from stripe_link.domain.composition import ELEMENTS, supported_goals
from stripe_link.domain.semantic_schema import OFFER_SEMANTIC_MODEL_SCHEMA, check_schema


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


def optional_string(document: dict[str, Any], field: str, label: str | None = None, *, max_length: int | None = None) -> None:
    value = document.get(field)
    if value is not None and not isinstance(value, str):
        raise DocumentValidationError(f"{label or field} must be a string.")
    if max_length is not None and isinstance(value, str) and len(value) > max_length:
        raise DocumentValidationError(f"{label or field} must be at most {max_length} characters.")


def validate_gtin(value: Any) -> None:
    """A GTIN (UPC-12 / EAN-13 / ISBN-13 / ITF-14 / GTIN-8) with a valid mod-10 check digit, when present.
    An invalid GTIN makes Google reject the whole merchant listing, so reject it here rather than emit it
    (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-06). Empty/absent is fine — the field is optional."""
    if value is None:
        return
    if not isinstance(value, str):
        raise DocumentValidationError("Product gtin must be a string.")
    if not value.strip():
        return  # blank/whitespace treated as absent
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) not in (8, 12, 13, 14):
        raise DocumentValidationError("Product gtin must be 8, 12, 13, or 14 digits (UPC/EAN/ISBN/ITF-14/GTIN-8).")
    body, check = digits[:-1], int(digits[-1])
    total, weight = 0, 3
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 1 if weight == 3 else 3
    if (10 - (total % 10)) % 10 != check:
        raise DocumentValidationError("Product gtin check digit is invalid — verify the barcode number.")


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
    # Editable thank-you copy + optional sections (SALES_FUNNELS.md P3.5) — overrides the synthesized terminus's
    # defaults. Only meaningful for a page_id (self-hosted) terminus; harmless on a url terminus.
    for field in ("headline", "subheadline", "message", "next_steps_title", "footer_headline",
                  "footer_message", "home_button_text", "download_button_text", "download_url"):
        optional_string(value, field, f"{label}.{field}", max_length=300)
    optional_string(value, "headline_icon", f"{label}.headline_icon", max_length=16)
    for field in ("enable_celebration", "enable_next_steps", "enable_footer", "show_home_button", "enable_download"):
        optional_bool(value, field, f"{label}.{field}")
    if value.get("next_steps") is not None:
        cards = value.get("next_steps")
        if not isinstance(cards, list) or len(cards) > 6:
            raise DocumentValidationError(f"{label}.next_steps must be an array of at most 6 cards.")
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                raise DocumentValidationError(f"{label}.next_steps[{index}] must be an object.")
            optional_string(card, "icon", f"{label}.next_steps[{index}].icon", max_length=16)
            optional_string(card, "title", f"{label}.next_steps[{index}].title", max_length=120)
            optional_string(card, "desc", f"{label}.next_steps[{index}].desc", max_length=300)


# The customer-facing copy for the synthesized post-purchase pages (upsell_pages.DEFAULT_UPSELL_SCAFFOLD).
# Blank overrides fall back to the runtime defaults, so every field is optional here.
UPSELL_SCAFFOLD_TEXT_FIELDS = (
    "headline", "subheadline", "accept_label", "decline_label", "price_label",
    "downsell_headline", "downsell_note",
    "carousel_headline", "carousel_subheadline", "carousel_add_label", "carousel_dismiss_label",
    "carousel_proceed_label", "downsell_carousel_headline",
)


def validate_upsell_scaffold(value: Any, label: str) -> None:
    """The per-page post-purchase copy overrides (SALES_FUNNELS.md P3.5). All fields optional — a blank field
    falls back to the runtime default (upsell_pages.upsell_scaffold)."""
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object.")
    for field in UPSELL_SCAFFOLD_TEXT_FIELDS:
        optional_string(value, field, f"{label}.{field}", max_length=300)
    optional_bool(value, "countdown_enabled", f"{label}.countdown_enabled")
    optional_bool(value, "savings_badge", f"{label}.savings_badge")
    if value.get("countdown_minutes") is not None:
        minutes = value.get("countdown_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not (1 <= minutes <= 60):
            raise DocumentValidationError(f"{label}.countdown_minutes must be an integer from 1 to 60.")


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
    if "upsell_scaffold" in value:
        validate_upsell_scaffold(value.get("upsell_scaffold"), "Page post_checkout.upsell_scaffold")


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


# Screen readers announce the whole string and search engines truncate well before this; a limit also
# stops a description field being used as hidden keyword copy.
IMAGE_ALT_MAX_LENGTH = 250


def optional_image_dims(document: dict[str, Any], label: str = "image_dims") -> None:
    """Validate the optional image_dims sidecar: a compact map of image URL/rendition-base -> [w, h].

    Captured from the upload pipeline (the processor reports source dimensions) so the renderer can
    reserve layout space and hint crawlers. Advisory metadata — kept lenient, but shape-checked so a
    malformed map can't reach the renderer: keys are strings, values are two positive integers.
    """
    value = document.get("image_dims")
    if value is None:
        return
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object mapping image URL to [width, height].")
    for key, pair in value.items():
        if not isinstance(key, str) or not key:
            raise DocumentValidationError(f"{label} keys must be non-empty image URLs.")
        # Numbers loaded from DynamoDB arrive as Decimal, so accept any positive real (bool excluded).
        if (not isinstance(pair, list) or len(pair) != 2
                or any(isinstance(n, bool) or not isinstance(n, (int, float, Decimal)) or n <= 0 for n in pair)):
            raise DocumentValidationError(f"{label}['{key}'] must be [width, height] positive numbers.")


def optional_image_alts(document: dict[str, Any], label: str = "image_alts") -> None:
    """Validate the optional image_alts sidecar: a compact map of image URL/rendition-base -> alt text.

    Keyed by ASSET, not by placement, exactly like image_dims: the same photo used on two sections is
    described once, and the description follows it wherever it is reused. Captured in the builder's upload
    field, so every surface that uploads an image gets the input without its own schema field.

    Advisory, like image_dims -- a malformed entry must never block a render, but the shape is checked so
    it cannot reach the renderer. Blank values are allowed and simply mean "no override": the renderer then
    falls back to the alt derived from surrounding data, which is what it did before this existed.
    """
    value = document.get("image_alts")
    if value is None:
        return
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{label} must be an object mapping image URL to alt text.")
    for key, text in value.items():
        if not isinstance(key, str) or not key:
            raise DocumentValidationError(f"{label} keys must be non-empty image URLs.")
        if not isinstance(text, str):
            raise DocumentValidationError(f"{label}['{key}'] must be a string.")
        if len(text) > IMAGE_ALT_MAX_LENGTH:
            raise DocumentValidationError(
                f"{label}['{key}'] must be {IMAGE_ALT_MAX_LENGTH} characters or fewer."
            )


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
    # Merchant-listing identifiers (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-06). All optional; brand is the
    # manufacturer (Apple) — distinct from the storefront brand. Google matches products by GTIN, or by
    # brand+mpn together. An invalid GTIN is worse than none, so its check digit is validated when present.
    optional_string(document, "brand", "Product brand", max_length=70)
    optional_string(document, "mpn", "Product mpn", max_length=70)
    validate_gtin(document.get("gtin"))
    optional_string_list(document, "images")
    optional_image_dims(document, "Product image_dims")
    optional_image_alts(document, "Product image_alts")
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


def validate_offer_funnel(document: dict[str, Any]) -> None:
    """The optional in-offer funnel: order_bumps (pre-purchase optional_items) + upsells/downsells
    (post-purchase one-click). Each entry references a product + one of its prices (plans/SALES_FUNNELS.md P2)."""
    funnel = document.get("funnel")
    if funnel is None:
        return
    if not isinstance(funnel, dict):
        raise DocumentValidationError("Offer funnel must be an object.")
    for key in ("order_bumps", "upsells", "downsells"):
        entries = funnel.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise DocumentValidationError(f"Offer funnel {key} must be an array.")
        for entry in entries:
            if not isinstance(entry, dict):
                raise DocumentValidationError(f"Each offer funnel {key} entry must be an object.")
            require_string(entry, "product_id", f"offer funnel {key} product_id")
            require_string(entry, "price_id", f"offer funnel {key} price_id")


def _validate_offer_item(document: dict[str, Any], item: dict[str, Any]) -> None:
    """Validate one product/service line — the price/product rules shared by a legacy item and a purchase
    opportunity (they carry the same product_id/service_id + price_id or selectable_prices shape)."""
    if not isinstance(item, dict):
        raise DocumentValidationError("Each offer item must be an object.")
    # An item references exactly one of a product or a service (STORY-2.1).
    has_product = bool(item.get("product_id"))
    has_service = bool(item.get("service_id"))
    if has_product == has_service:
        raise DocumentValidationError("Offer item must reference exactly one of product_id or service_id.")
    if has_service:
        require_string(item, "service_id", "offer item service_id")
        if item.get("selectable_prices"):
            raise DocumentValidationError("Service offer items must use price_id, not selectable_prices.")
        require_string(item, "price_id", "offer item price_id")
        require_positive_int(item, "quantity", "offer item quantity")
        if item.get("booking_flow") is not None:
            require_enum(item, "booking_flow", {"book_then_pay", "pay_then_book"}, "offer item booking_flow")
        if document.get("product_intent") != "transaction":
            raise DocumentValidationError("Service offer items require product_intent 'transaction'.")
        optional_string(item, "presentation_context", "offer item presentation_context")
        return
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


def validate_purchase_opportunities(document: dict[str, Any], opportunities: list[Any]) -> None:
    """Validate the normalized offer model (plans/OFFER_MODEL_REDESIGN.md): each opportunity carries a stage,
    an optional placement, and one product/service line (validated by _validate_offer_item)."""
    for opp in opportunities:
        if not isinstance(opp, dict):
            raise DocumentValidationError("Each purchase opportunity must be an object.")
        require_enum(opp, "stage", {"landing", "checkout", "post_purchase"}, "purchase opportunity stage")
        placement = opp.get("placement")
        if placement is not None:
            if not isinstance(placement, dict):
                raise DocumentValidationError("Purchase opportunity placement must be an object.")
            if placement.get("surface") is not None:
                require_enum(placement, "surface", {"primary", "order_bump", "upsell", "downsell"}, "opportunity placement surface")
            if placement.get("strategy") not in (None, "", "single", "carousel", "sequence"):
                raise DocumentValidationError("Opportunity placement strategy must be 'single', 'carousel', or 'sequence'.")
        _validate_offer_item(document, opp)


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
        require_enum(document, "offer_type", {"single", "bundle", "listicle", "social_media"}, "Offer offer_type")
    if document.get("context") is not None:
        require_enum(document, "context", {"standard", "sale", "flash_sale", "upsell", "downsell", "order_bump"}, "Offer context")
    # The Offer coordinates how its scheduled services are delivered (single_visit collapses them
    # into one appointment; separate_visits gives each its own). Optional; defaults to single_visit.
    if document.get("service_booking_mode") is not None:
        require_enum(document, "service_booking_mode", {"single_visit", "separate_visits"}, "Offer service_booking_mode")
    validate_offer_funnel(document)
    # New model (purchase_opportunities) is the source of truth when present; otherwise validate legacy items.
    # An offer must carry one or the other (plans/OFFER_MODEL_REDESIGN.md).
    opportunities = document.get("purchase_opportunities")
    if isinstance(opportunities, list) and opportunities:
        validate_purchase_opportunities(document, opportunities)
    elif str(document.get("offer_type") or "") == "social_media":
        # A link-in-bio page is a ZERO-PRIMARY-OFFER page (plans/SOCIAL_MEDIA_PAGES.md §2): identity header
        # plus a grid whose cards each resolve their OWN offer. It genuinely has no conversion of its own,
        # so requiring an item would mean inventing one -- a $0 phantom product sitting in the tenant's
        # catalogue forever, or borrowing a real offer the page is not about and emitting false Product
        # markup. Both were considered and rejected 2026-09-09; an empty offer is the honest encoding.
        #
        # Safe because the read path already degrades rather than assuming: landing_presentation returns
        # kind="none", first_offer_product returns {}, stage_opportunities yields nothing.
        items = document.get("items")
        if isinstance(items, list):
            for item in items:
                _validate_offer_item(document, item)
    else:
        items = document.get("items")
        if not isinstance(items, list) or not items:
            raise DocumentValidationError("Offer must have purchase_opportunities or a non-empty items array.")
        for item in items:
            _validate_offer_item(document, item)

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
        # The brand shown on the page. Optional; the tenant picks one of their business's brand names, else
        # the renderer falls back to the business name, then the product name — never the internal offer name.
        optional_string(presentation, "brand", "Offer presentation.brand")
        optional_string(presentation, "hero_image_url", "Offer presentation.hero_image_url")
        cta = presentation.get("cta")
        if cta is not None:
            if not isinstance(cta, dict):
                raise DocumentValidationError("Offer presentation.cta must be an object.")
            require_enum(cta, "type", {"buy", "call", "email", "external", "download", "booking", "appointment"}, "Offer presentation.cta.type")
            optional_string(cta, "label", "Offer presentation.cta.label")
            optional_string(cta, "target", "Offer presentation.cta.target")
    optional_image_dims(document, "Offer image_dims")
    optional_image_alts(document, "Offer image_alts")
    # Server-owned denormalized cache of the OfferSemanticModel (plans/OFFER_SEMANTIC_P4.md). Reserved now
    # (P4.0); the WRITE path lands with the AI enrichment tier. Validated when present so a persisted cache is
    # always well-formed — the dashboard never sends it (it is server-authoritative).
    if document.get("semantic_model") is not None:
        validate_semantic_model(document["semantic_model"])


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


# Sections that make a page offer-less (a storefront/catalog/profile page renders no single primary offer).
_OFFERLESS_SECTION_TYPES = {"catalog_grid", "seller_profile", "brand_hero"}


def is_offerless_page(document: dict[str, Any]) -> bool:
    """True when a page carries a storefront/category/profile section and therefore needs no primary offer_id
    (plans/SITE_OBJECT.md §2.5b/2.7)."""
    return any(
        isinstance(s, dict) and s.get("type") in _OFFERLESS_SECTION_TYPES
        for s in (document.get("sections") or [])
    )


def validate_page_pricing_modes(document: dict[str, Any]) -> None:
    """Per-Landing-Page Sale / Flash-Sale toggles (plans/SALES_FUNNELS.md P1). `/sale` and `/flash-sale` are
    context views of `/` that swap the price context; the dates that drive them live on the page. Both blocks
    optional; only shape + the "flash needs an expiration" rule are enforced here (the "product has no such
    price" warning is a builder/UX concern, not a document invariant)."""
    sale = document.get("sale")
    if sale is not None:
        if not isinstance(sale, dict):
            raise DocumentValidationError("Page sale must be an object.")
        optional_bool(sale, "enabled", "Page sale.enabled")
        optional_non_negative_int(sale, "ends_at", "Page sale.ends_at")  # absent = perpetual

    flash = document.get("flash_sale")
    if flash is not None:
        if not isinstance(flash, dict):
            raise DocumentValidationError("Page flash_sale must be an object.")
        optional_bool(flash, "enabled", "Page flash_sale.enabled")
        optional_non_negative_int(flash, "starts_on", "Page flash_sale.starts_on")
        optional_non_negative_int(flash, "ends_at", "Page flash_sale.ends_at")
        if flash.get("enabled"):
            ends_at = flash.get("ends_at")
            if not isinstance(ends_at, (int, Decimal)) or isinstance(ends_at, bool) or int(ends_at) <= 0:
                raise DocumentValidationError("You must set an expiration date in order to enable this feature.")
            starts_on = flash.get("starts_on")
            if isinstance(starts_on, (int, Decimal)) and not isinstance(starts_on, bool) and int(starts_on) >= int(ends_at):
                raise DocumentValidationError("Page flash_sale.starts_on must be before ends_at.")


def validate_page_document(document: dict[str, Any]) -> None:
    require_document_fields(document, "page", "page_id")
    require_string(document, "name")
    # An offer-less page (storefront homepage / category / seller profile) has no single primary offer, so
    # offer_id is optional there (plans/SITE_OBJECT.md §2.5b/2.7). Every other page still requires one — a
    # landing page renders exactly one offer.
    if is_offerless_page(document):
        optional_string(document, "offer_id", "Page offer_id")
    else:
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

    optional_image_dims(document, "Page image_dims")
    optional_image_alts(document, "Page image_alts")

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
    validate_page_pricing_modes(document)

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
            # Both optional: a listicle's hero is TARGET-BOUND — its static copy is blank and the H1/subheadline
            # are filled from the offer's current product at render (see runtime/html.render_hero). So a blank
            # hero section is a valid document, not an error; a missing H1 is a quality WARNING, not a hard fail.
            optional_string(section, "headline", "Hero section headline")
            optional_string(section, "subheadline", "Hero section subheadline")
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
            if section.get("avatar_placement") is not None:
                require_enum(section, "avatar_placement", {"overlay", "inline", "centered"},
                             "Hero avatar_placement")
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
            optional_bool(section, "centered", "Content block centered")
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
        elif section_type == "brand_hero":
            optional_string(section, "headline", "Brand hero headline")
            optional_string(section, "tagline", "Brand hero tagline")
            optional_string(section, "logo_url", "Brand hero logo URL")
        elif section_type == "related_products":
            # Cards are resolved at publish from the Site's other pages in this page's category; the tenant
            # only sets the heading (plans/SITE_OBJECT.md §2.5b Slice 3 / SEO-13).
            optional_string(section, "heading", "Related products heading")
            if section.get("limit") is not None:
                require_positive_int(section, "limit", "Related products limit")
        elif section_type == "seller_profile":
            # Content is DERIVED from the Site Organization (identity/contact/social/catalog) — the tenant
            # only sets the heading (TENANT_PROFILE_REQUIREMENTS §4).
            optional_string(section, "heading", "Store profile heading")
        elif section_type == "catalog_grid":
            optional_string(section, "heading", "Catalog grid heading")
            # A collection-embed: the grid's items come from the referenced Collection at publish
            # (plans/SITE_COLLECTIONS.md P1), instead of the inline scope/category/items below.
            optional_string(section, "collection_id", "Catalog grid collection_id")
            # A category-driven grid stores a category key and resolves its cards from the Site catalog at
            # publish; a scope="all" grid resolves to EVERY offer page on the Site (a brand-first storefront
            # homepage that fills itself); a curated grid stores explicit items (plans/SITE_OBJECT.md §2.5b).
            optional_string(section, "category", "Catalog grid category")
            if section.get("scope") is not None:
                require_enum(section, "scope", {"all"}, "Catalog grid scope")
            items = optional_limited_object_list(section, "items", 48, "Catalog grid items")
            for item in items:
                require_string(item, "offer_id", "Catalog grid item offer_id")
                optional_string(item, "slug", "Catalog grid item slug")
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
    # The store's font preference (plans/FONT_SERVICE.md §9). Same shape the page carries, so one validator
    # covers both and resolve_families reads them identically -- the only difference is which wins.
    fonts = document.get("fonts")
    if fonts is not None:
        validate_font_settings(fonts, "Tenant profile fonts")
        optional_bool(fonts, "override_presets", "Tenant profile fonts.override_presets")
    # The store's avatar, resolved BY REFERENCE at render: a page that has not overridden it shows whatever
    # this points at today, so updating it updates every page at once. A page-level avatar_url overrides it
    # for that page only. Same home and same reasoning as the font preference above.
    optional_string(document, "avatar_url", "Tenant profile avatar_url", max_length=2048)
    require_fields(owner, ["first_name", "last_name", "email"])
    # Platform->tenant SaaS billing fields (plans/SAAS_BILLING_PAYWALL.md). All optional.
    status = document.get("billing_status")
    if status is not None and status not in {"trial", "active", "past_due", "canceled", "suspended", "trial_expired"}:
        raise DocumentValidationError("Tenant profile billing_status is invalid.")
    if "billing_exempt" in document and not isinstance(document.get("billing_exempt"), bool):
        raise DocumentValidationError("Tenant profile billing_exempt must be a boolean.")
    for field in ("billing_plan_key", "billing_price_id", "stripe_customer_id", "stripe_subscription_id"):
        optional_string(document, field, f"Tenant profile {field}")
    for field in ("current_period_end", "trial_ends_at"):
        value = document.get(field)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise DocumentValidationError(f"Tenant profile {field} must be a non-negative integer.")


def validate_stripe_keys_document(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id", "mode"])
    if document.get("document_type") != "stripe_keys":
        raise DocumentValidationError("Stripe keys document_type must be 'stripe_keys'.")
    if document.get("mode") not in {"test", "live"}:
        raise DocumentValidationError("Stripe keys mode must be 'test' or 'live'.")
    if not (document.get("publishable_key") or document.get("connect_account_id")):
        raise DocumentValidationError("Stripe keys require publishable_key or connect_account_id.")
    # Per-tenant BNPL toggles + cached Stripe capability status (plans/BNPL_PAYMENT_METHODS.md). Optional.
    payment_methods = document.get("payment_methods")
    if payment_methods is not None:
        if not isinstance(payment_methods, dict):
            raise DocumentValidationError("Stripe keys payment_methods must be an object.")
        optional_string(payment_methods, "account_country", "payment_methods.account_country", max_length=2)
        bnpl = payment_methods.get("bnpl")
        if bnpl is not None:
            if not isinstance(bnpl, dict):
                raise DocumentValidationError("Stripe keys payment_methods.bnpl must be an object.")
            for method, entry in bnpl.items():
                if not isinstance(entry, dict):
                    raise DocumentValidationError(f"payment_methods.bnpl.{method} must be an object.")
                if not isinstance(entry.get("enabled", False), bool):
                    raise DocumentValidationError(f"payment_methods.bnpl.{method}.enabled must be boolean.")
                status = entry.get("capability_status")
                if status is not None and status not in {"active", "pending", "inactive", "unrequested"}:
                    raise DocumentValidationError(f"payment_methods.bnpl.{method}.capability_status is invalid.")


def validate_tenant_config(document: dict[str, Any]) -> None:
    require_fields(document, ["schema_version", "document_type", "tenant_id"])
    if document.get("document_type") != "tenant_config":
        raise DocumentValidationError("Tenant config document_type must be 'tenant_config'.")
    page_defaults = document.get("page_defaults")
    if page_defaults is not None:
        if not isinstance(page_defaults, dict):
            raise DocumentValidationError("Tenant config page_defaults must be an object.")
        # page_defaults hold the tenant's DEFAULT funnel-page copy (Configuration → seeds new landing pages,
        # SALES_FUNNELS.md P3.5). Every field is optional so a tenant can fill in only what they care about.
        upsell = page_defaults.get("upsell")
        if upsell is not None:
            if not isinstance(upsell, dict):
                raise DocumentValidationError("Tenant config page_defaults.upsell must be an object.")
            for field in ("headline", "subheadline", "accept_button_text", "decline_button_text",
                          "price_label", "downsell_headline", "downsell_note"):
                optional_string(upsell, field, f"page_defaults.upsell.{field}", max_length=300)
        thank_you = page_defaults.get("thank_you")
        if thank_you is not None:
            if not isinstance(thank_you, dict):
                raise DocumentValidationError("Tenant config page_defaults.thank_you must be an object.")
            for field in ("headline", "subtitle", "message", "headline_icon", "next_steps_title",
                          "footer_headline", "footer_message", "home_button_text", "download_button_text", "download_url"):
                optional_string(thank_you, field, f"page_defaults.thank_you.{field}", max_length=300)
            for field in ("enable_celebration", "enable_next_steps", "enable_footer", "show_home_button", "enable_download"):
                optional_bool(thank_you, field, f"page_defaults.thank_you.{field}")
            if thank_you.get("next_steps") is not None:
                cards = thank_you.get("next_steps")
                if not isinstance(cards, list) or len(cards) > 6:
                    raise DocumentValidationError("page_defaults.thank_you.next_steps must be an array of at most 6 cards.")
                for index, card in enumerate(cards):
                    if not isinstance(card, dict):
                        raise DocumentValidationError(f"page_defaults.thank_you.next_steps[{index}] must be an object.")
                    optional_string(card, "icon", f"page_defaults.thank_you.next_steps[{index}].icon", max_length=16)
                    optional_string(card, "title", f"page_defaults.thank_you.next_steps[{index}].title", max_length=120)
                    optional_string(card, "desc", f"page_defaults.thank_you.next_steps[{index}].desc", max_length=300)
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
    validate_business_identity(document.get("business"))


_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


def normalize_e164(value: Any) -> str:
    """Best-effort E.164 normalization: strip human formatting (spaces, dashes, parens, dots) and treat a
    leading international '00' dialing prefix as '+'. Deliberately does NOT invent a country code — a number
    typed without a leading '+' stays without one, so validation rejects it with a clear hint rather than
    guessing (and mis-attributing) a country. E.164 is what the registration flow (Cognito) already requires
    for the account phone; this brings the business phone / Organization telephone in line."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    # North American Numbering Plan: recover the +1 for a bare NANP number — 1 + 10 digits, or a plain 10-digit
    # national number (the everyday US/Canada format). Non-NANP tenants enter a full "+<country>" number, guided
    # by the field hint; a number that is neither stays without a "+" so validation asks for the country.
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    return digits


def require_e164(document: dict[str, Any], field: str, label: str) -> None:
    """An optional phone that, when present, is normalized in place to E.164 and then validated. Canonicalizing
    at validation means downstream consumers (Organization JSON-LD, SMS) get a clean number regardless of what
    the client sent."""
    value = document.get(field)
    if value in (None, ""):
        return
    normalized = normalize_e164(value)
    if not _E164_RE.match(normalized):
        raise DocumentValidationError(
            f"{label} must be a valid phone number in international format, e.g. +12065551234."
        )
    document[field] = normalized


# Common country names/aliases → ISO 3166-1 alpha-2. Not exhaustive: the dashboard offers a full country
# picker (alpha-2), so this mainly heals legacy free-text and API input. Unrecognized values pass through.
_COUNTRY_ALIASES = {
    "USA": "US", "US": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "AMERICA": "US",
    "CANADA": "CA", "CA": "CA",
    "UNITED KINGDOM": "GB", "UK": "GB", "GB": "GB", "GREAT BRITAIN": "GB", "ENGLAND": "GB",
    "SCOTLAND": "GB", "WALES": "GB", "NORTHERN IRELAND": "GB",
    "AUSTRALIA": "AU", "AU": "AU", "NEW ZEALAND": "NZ", "NZ": "NZ", "IRELAND": "IE", "IE": "IE",
    "MEXICO": "MX", "MX": "MX", "GERMANY": "DE", "DE": "DE", "FRANCE": "FR", "FR": "FR",
    "SPAIN": "ES", "ES": "ES", "ITALY": "IT", "IT": "IT", "NETHERLANDS": "NL", "NL": "NL",
    "INDIA": "IN", "IN": "IN", "JAPAN": "JP", "JP": "JP", "BRAZIL": "BR", "BR": "BR",
}


def normalize_country(value: Any) -> str:
    """Normalize a country to its ISO 3166-1 alpha-2 code (matches Stripe, Google Business Profile, and
    schema.org PostalAddress.addressCountry). Recognized names/aliases map to a code; an existing 2-letter
    code is upper-cased; anything else passes through unchanged so an unusual entry is never lost."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.replace(".", "").upper().strip()
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    if len(key) == 2 and key.isalpha():
        return key
    return raw


def _normalize_address_country(address: Any) -> None:
    """Canonicalize address.country to alpha-2 in place, so NAP stays consistent across Stripe/GBP/JSON-LD."""
    if isinstance(address, dict) and address.get("country"):
        address["country"] = normalize_country(address["country"])


def validate_business_identity(business: Any) -> None:
    """The tenant's business identity — name, brand(s), and NAP contact. A lightweight precursor to the
    canonical Business Profile (plans/BUSINESS_PROFILE_AND_GBP.md); GBP will later override/enrich it.
    All fields optional: it drives landing-page brand defaults and (later) LocalBusiness JSON-LD, and an
    untouched profile simply falls back to the product name for brand. Kept on the user_profile for now."""
    if business is None:
        return
    if not isinstance(business, dict):
        raise DocumentValidationError("User profile business must be an object.")
    optional_string(business, "name", "business.name")
    optional_string(business, "email", "business.email")
    require_e164(business, "phone", "Business phone")
    # Per-field provenance (source: stripe|manual|gbp|derived) so an auto-seed (Stripe Connect, later GBP)
    # never clobbers a tenant's own value. Fill-empty-only is the guarantee; this records where a value came
    # from (plans/BUSINESS_PROFILE_AND_GBP.md).
    sources = business.get("sources")
    if sources is not None:
        if not isinstance(sources, dict) or any(not isinstance(v, str) for v in sources.values()):
            raise DocumentValidationError("business.sources must be a map of field name to source string.")
    brands = business.get("brands")
    if brands is not None:
        if not isinstance(brands, list) or any(not isinstance(brand, str) for brand in brands):
            raise DocumentValidationError("business.brands must be an array of strings.")
    address = business.get("address")
    if address is not None:
        if not isinstance(address, dict):
            raise DocumentValidationError("business.address must be an object.")
        # PostalAddress-shaped so it maps straight to LocalBusiness JSON-LD when the local-SEO work lands.
        for field in ("street", "locality", "region", "postal_code", "country"):
            optional_string(address, field, f"business.address.{field}")
        _normalize_address_country(address)


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


def validate_cart(document: dict[str, Any]) -> None:
    """A server-side cart (plans/LISTICLE_AND_CART.md L2). Line prices are re-resolved server-side
    (domain/cart.py), so this shape-check guards persistence, not pricing trust."""
    require_fields(document, ["schema_version", "document_type", "tenant_id", "cart_id", "offer_id", "created_at"])
    if document.get("document_type") != "cart":
        raise DocumentValidationError("Cart document_type must be 'cart'.")
    items = document.get("line_items")
    # An emptied cart (last line removed) is valid — check the type, not truthiness.
    if not isinstance(items, list):
        raise DocumentValidationError("Cart line_items must be an array.")
    if len(items) > MAX_CART_LINES:
        raise DocumentValidationError(f"Cart may hold at most {MAX_CART_LINES} line items.")
    for line in items:
        if not isinstance(line, dict):
            raise DocumentValidationError("Each cart line must be an object.")
        if not str(line.get("product_id") or "").strip() and not str(line.get("service_id") or "").strip():
            raise DocumentValidationError("Each cart line needs a product_id or service_id.")
        if not str(line.get("price_id") or "").strip():
            raise DocumentValidationError("Each cart line needs a price_id.")
        qty = line.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or not (1 <= qty <= MAX_LINE_QTY):
            raise DocumentValidationError(f"Cart line qty must be an integer from 1 to {MAX_LINE_QTY}.")
        amount = line.get("unit_amount")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise DocumentValidationError("Cart line unit_amount must be a non-negative integer.")
    # Slice D recovery fields (all optional).
    if document.get("email") is not None and not isinstance(document.get("email"), str):
        raise DocumentValidationError("Cart email must be a string.")
    if document.get("status", "open") not in CART_STATUSES:
        raise DocumentValidationError("Cart status must be 'open' or 'converted'.")
    if document.get("email_opted_out") is not None and not isinstance(document.get("email_opted_out"), bool):
        raise DocumentValidationError("Cart email_opted_out must be a boolean.")
    if document.get("page_url") is not None and not isinstance(document.get("page_url"), str):
        raise DocumentValidationError("Cart page_url must be a string.")
    if document.get("recovery") is not None and not isinstance(document.get("recovery"), dict):
        raise DocumentValidationError("Cart recovery must be an object.")


def validate_cart_token(document: dict[str, Any]) -> None:
    """An opaque identified-link / recovery token (plans/LISTICLE_AND_CART.md L2 Slice D)."""
    require_fields(document, ["schema_version", "document_type", "tenant_id", "token", "email", "created_at"])
    if document.get("document_type") != "cart_token":
        raise DocumentValidationError("Cart token document_type must be 'cart_token'.")
    if not str(document.get("token") or "").strip():
        raise DocumentValidationError("Cart token token is required.")
    if "@" not in str(document.get("email") or ""):
        raise DocumentValidationError("Cart token email must be an email address.")


REVIEW_TARGET_TYPES = {"product", "offer", "business"}
REVIEW_STATUSES = {"pending", "approved", "rejected"}
REVIEW_SOURCES = {"manual", "first_party", "gbp"}


def validate_review(document: dict[str, Any]) -> None:
    """A first-party review (plans/REVIEWS.md). Targets a product/offer/business; rating 1-5; author + body are
    rendered verbatim in the initial HTML and the JSON-LD. Only approved, non-GBP reviews are markup-eligible
    (Google forbids aggregating third-party/GBP reviews into your own AggregateRating)."""
    require_fields(document, ["schema_version", "document_type", "tenant_id", "review_id", "target", "rating", "author", "body"])
    if document.get("document_type") != "review":
        raise DocumentValidationError("Review document_type must be 'review'.")
    target = document.get("target")
    if not isinstance(target, dict) or target.get("type") not in REVIEW_TARGET_TYPES or not str(target.get("id") or "").strip():
        raise DocumentValidationError("Review target must be an object with a type (product|offer|business) and an id.")
    rating = document.get("rating")
    if not isinstance(rating, int) or isinstance(rating, bool) or not (1 <= rating <= 5):
        raise DocumentValidationError("Review rating must be an integer from 1 to 5.")
    require_string(document, "author", "Review author")
    require_string(document, "body", "Review body")
    optional_string(document, "title", "Review title", max_length=200)
    optional_string(document, "response", "Review response")
    optional_string(document, "review_date", "Review date")
    if document.get("status", "pending") not in REVIEW_STATUSES:
        raise DocumentValidationError("Review status must be one of: pending, approved, rejected.")
    if document.get("source", "manual") not in REVIEW_SOURCES:
        raise DocumentValidationError("Review source must be one of: manual, first_party, gbp.")


COLLECTION_RULES = {"manual", "all", "category"}


def validate_collection(document: dict[str, Any]) -> None:
    """A Collection (plans/SITE_COLLECTIONS.md): an ordered, curated group of a Site's landing pages with its own
    presentation. Reusable as a page section (a collection-embed) and — via the Site routing table, NEVER on this
    entity — optionally reachable at a path. Pure data: a Collection is URL-unaware (no slug, no `routable`). Its
    members are page references derived by `rule`: `manual` (explicit ordered members[]), `all` (every offer page
    on the Site), or `category` (offer pages in `category`)."""
    require_fields(document, ["schema_version", "document_type", "tenant_id", "collection_id", "site_id", "name"])
    if document.get("document_type") != "collection":
        raise DocumentValidationError("Collection document_type must be 'collection'.")
    require_string(document, "collection_id", "Collection id")
    require_string(document, "site_id", "Collection site_id")
    require_string(document, "name", "Collection name")
    if document.get("environment") is not None:
        require_enum(document, "environment", {"live", "test"}, "Collection environment")
    rule = document.get("rule", "manual")
    if rule not in COLLECTION_RULES:
        raise DocumentValidationError("Collection rule must be one of: manual, all, category.")
    if rule == "category":
        require_string(document, "category", "Collection category")
    else:
        optional_string(document, "category", "Collection category")
    optional_string_list(document, "members", "Collection members")  # ordered page_id references (manual rule)
    presentation = document.get("presentation")
    if presentation is not None:
        if not isinstance(presentation, dict):
            raise DocumentValidationError("Collection presentation must be an object.")
        optional_string(presentation, "heading", "Collection heading")


def validate_semantic_model(model: Any) -> None:
    """The OfferSemanticModel (plans/OFFER_SEMANTIC_ANALYZER.md). Pure meaning — `facts` (stable values) +
    `interpretation` (opinions). This is the runtime contract the AI enrichment tier's output is validated
    against (plans/OFFER_SEMANTIC_P4.md); the deterministic analyzer already conforms.

    The check is DRIVEN BY THE SCHEMA (domain/semantic_schema.py :: OFFER_SEMANTIC_MODEL_SCHEMA) so the
    validator and schemas/OfferSemanticModel.schema.json can never disagree — the validator IS the schema. No
    `jsonschema` dependency (the repo keeps third-party deps out); check_schema is a small in-repo interpreter."""
    if not isinstance(model, dict):
        raise DocumentValidationError("Semantic model must be an object.")
    errors = check_schema(model, OFFER_SEMANTIC_MODEL_SCHEMA)
    if errors:
        raise DocumentValidationError("Semantic model is invalid: " + "; ".join(errors[:6]))


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


# Site (the public aggregate root — plans/SITE_OBJECT.md, schemas/Site.schema.json v2).
SITE_STATUSES = {"draft", "active", "archived"}
SITE_ENVIRONMENTS = {"test", "live"}
SITE_HOSTING_TYPES = {"platform", "custom"}
SITE_INDEXING_ELIGIBILITY = {"blocked", "pending", "eligible", "revoked"}
SITE_ENTITY_TYPES = {
    "Organization", "OnlineStore", "LocalBusiness", "HomeAndConstructionBusiness",
    "HealthAndBeautyBusiness", "FoodEstablishment", "ProfessionalService", "Store",
}
# The allowlist and everything else about same_as verification lives in domain/social_links.py, so the
# renderer, the validator and the verifier cannot drift. Re-exported here because callers import it from
# documents.
from stripe_link.domain.social_links import (  # noqa: E402
    SAME_AS_HOSTS,
    SAME_AS_MAX,
    VERIFICATION_STATES,
    is_allowed_host,
    same_as_host,
)
# Local-business identity on Site.organization (Business Profile Phase 1): opening hours + geo let the
# renderer emit full LocalBusiness JSON-LD. Days are schema.org DayOfWeek names; times are 24h HH:MM.
_ORG_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Page roles are metadata (JSON-LD @type / sitemap / robots / nav eligibility) — never a renderer branch.
# funnel_step is a post-checkout upsell/downsell page: routable on the custom domain but always noindex.
SITE_PAGE_TYPES = {
    "landing", "homepage", "collection", "category", "about", "contact", "faq",
    "legal", "checkout", "thank_you", "funnel_step", "blog", "article", "search_results",
}
_HOSTNAME_RE = re.compile(r"^(?!https?://)([a-z0-9-]+\.)+[a-z]{2,}$")
_SITE_SLUG_RE = re.compile(r"^/$|^/[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")


def validate_site(document: dict[str, Any]) -> None:
    """The Site: a tenant's public website (plans/SITE_OBJECT.md). Owns hostname(s), the Organization
    identity, navigation, SEO, indexing eligibility, and a slug->page route map. Enforces the load-bearing
    constraints; the full shape lives in schemas/Site.schema.json v2."""
    require_document_fields(document, "site", "site_id")
    if not re.match(r"^site_[A-Za-z0-9]+$", str(document.get("site_id") or "")):
        raise DocumentValidationError("Site site_id must match ^site_[A-Za-z0-9]+$.")
    require_enum(document, "environment", SITE_ENVIRONMENTS, "Site environment")
    require_string(document, "name", "Site name")
    require_enum(document, "status", SITE_STATUSES, "Site status")

    # hosting: the Site owns its hostname(s). platform_hostname permanent; custom_domain optional.
    hosting = document.get("hosting")
    if not isinstance(hosting, dict):
        raise DocumentValidationError("Site hosting must be an object.")
    require_enum(hosting, "type", SITE_HOSTING_TYPES, "Site hosting.type")
    platform_hostname = hosting.get("platform_hostname")
    if not isinstance(platform_hostname, str) or not _HOSTNAME_RE.match(platform_hostname):
        raise DocumentValidationError("Site hosting.platform_hostname must be a bare hostname.")
    custom_domain = hosting.get("custom_domain")
    if custom_domain is not None and not (isinstance(custom_domain, str) and _HOSTNAME_RE.match(custom_domain)):
        raise DocumentValidationError("Site hosting.custom_domain must be a bare hostname or null.")
    if hosting.get("type") == "custom" and not custom_domain:
        raise DocumentValidationError("Site hosting.type 'custom' requires a custom_domain.")
    verification = hosting.get("verification")
    if verification is not None and not isinstance(verification, dict):
        raise DocumentValidationError("Site hosting.verification must be an object.")

    validate_site_organization(document.get("organization"))

    navigation = document.get("navigation")
    if navigation is not None:
        if not isinstance(navigation, dict):
            raise DocumentValidationError("Site navigation must be an object.")
        for key in ("primary", "footer"):
            menu = navigation.get(key)
            if menu is not None and (not isinstance(menu, list) or any(not (isinstance(s, str) and _SITE_SLUG_RE.match(s)) for s in menu)):
                raise DocumentValidationError(f"Site navigation.{key} must be an array of slugs.")

    indexing = document.get("indexing")
    if indexing is not None:
        if not isinstance(indexing, dict):
            raise DocumentValidationError("Site indexing must be an object.")
        if indexing.get("eligibility") is not None:
            require_enum(indexing, "eligibility", SITE_INDEXING_ELIGIBILITY, "Site indexing.eligibility")
        # The tenant's "discover in search" switch (default True): when False every page is noindex and the
        # storefront chrome renders in its plain no-SEO form. See connect_sync.site_seo_enabled.
        optional_bool(indexing, "seo_enabled", "Site indexing.seo_enabled")

    # seo: site-wide SEO config — webmaster verification tokens (SEO-16), title suffix, IndexNow key.
    seo = document.get("seo")
    if seo is not None:
        if not isinstance(seo, dict):
            raise DocumentValidationError("Site seo must be an object.")
        for field in ("title_suffix", "google_site_verification", "bing_site_verification",
                      "pinterest_site_verification", "indexnow_key", "default_og_image", "description_cta"):
            optional_string(seo, field, f"Site seo.{field}")

    # pages: slug-keyed route map. May be empty — a Site can exist before any pages attach (the Site is
    # the aggregate root; pages hang off it). A page_id belongs to at most one Site (checked at the handler).
    pages = document.get("pages")
    if pages is None:
        pages = {}
    if not isinstance(pages, dict):
        raise DocumentValidationError("Site pages must be an object.")
    for slug, entry in pages.items():
        if not (isinstance(slug, str) and _SITE_SLUG_RE.match(slug)):
            raise DocumentValidationError(f"Site page slug '{slug}' is invalid.")
        if not isinstance(entry, dict):
            raise DocumentValidationError(f"Site page '{slug}' must be an object.")
        if not re.match(r"^page_[A-Za-z0-9]+$", str(entry.get("page_id") or "")):
            raise DocumentValidationError(f"Site page '{slug}' page_id must match ^page_[A-Za-z0-9]+$.")
        if entry.get("page_type") is not None:
            require_enum(entry, "page_type", SITE_PAGE_TYPES, f"Site page '{slug}' page_type")
        optional_string(entry, "label", f"Site page '{slug}' label", max_length=80)
        optional_bool(entry, "enabled", f"Site page '{slug}' enabled")
        # Denormalized at publish so a category page resolves its grid off the route map without loading every
        # page: the offer a landing page renders, and its product category (plans/SITE_OBJECT.md §2.5b Slice 2).
        # `category` on a page_type=category entry is instead the category that page LISTS.
        optional_string(entry, "offer_id", f"Site page '{slug}' offer_id")
        optional_string(entry, "category", f"Site page '{slug}' category")
        # A Sale/Flash-Sale context view (plans/SALES_FUNNELS.md P1c) points at a base page but serves its
        # sibling artifact rendered in this price context.
        if entry.get("price_context") is not None:
            require_enum(entry, "price_context", {"sale", "flash_sale"}, f"Site page '{slug}' price_context")
        # A reserved post-purchase funnel slug (/upsell //downsell //thank-you, plans/SALES_FUNNELS.md P2b)
        # points at the base sales page but serves a synthetic funnel artifact the resolver derives from the
        # role + the offer's sequence/carousel strategy.
        if entry.get("funnel_role") is not None:
            require_enum(entry, "funnel_role", {"upsell", "downsell", "thank_you"}, f"Site page '{slug}' funnel_role")
        if entry.get("strategy") is not None:
            require_enum(entry, "strategy", {"sequence", "carousel"}, f"Site page '{slug}' strategy")

    optional_non_negative_int(document, "revision", "Site revision")
    for field in ("created_at", "updated_at"):
        value = document.get(field)
        # DynamoDB returns numbers as Decimal, so a Site re-validated after a read (e.g. connecting a domain)
        # carries Decimal timestamps — accept an integral Decimal as well as a plain int.
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or (isinstance(value, Decimal) and value % 1 != 0):
            raise DocumentValidationError(f"Site {field} must be an integer.")


def validate_site_organization(organization: Any) -> None:
    """The Site's single-source-of-truth public identity (SITE_OBJECT.md §2.1). Every field optional; only
    verifiable data is ever emitted. Shape-checked so malformed identity can't reach the renderer."""
    if organization is None:
        return
    if not isinstance(organization, dict):
        raise DocumentValidationError("Site organization must be an object.")
    optional_string(organization, "name", "organization.name", max_length=120)
    optional_string(organization, "legal_name", "organization.legal_name", max_length=200)
    if organization.get("entity_type") is not None:
        require_enum(organization, "entity_type", SITE_ENTITY_TYPES, "organization.entity_type")
    if organization.get("business_type") is not None:
        require_enum(organization, "business_type", BUSINESS_TYPES, "organization.business_type")
    optional_string(organization, "description", "organization.description", max_length=500)
    require_e164(organization, "telephone", "Organization phone")
    optional_string(organization, "email", "organization.email")
    optional_string(organization, "founding_date", "organization.founding_date")
    address = organization.get("address")
    if address is not None:
        if not isinstance(address, dict):
            raise DocumentValidationError("organization.address must be an object.")
        for field in ("street", "locality", "region", "postal_code", "country"):
            optional_string(address, field, f"organization.address.{field}")
        _normalize_address_country(address)
    logo = organization.get("logo")
    if logo is not None and not isinstance(logo, dict):
        raise DocumentValidationError("organization.logo must be an object.")
    for list_field in ("area_served", "currencies"):
        if organization.get(list_field) is not None:
            optional_string_list(organization, list_field, f"organization.{list_field}")
    same_as = organization.get("same_as")
    if same_as is not None:
        if not isinstance(same_as, list):
            raise DocumentValidationError("organization.same_as must be an array.")
        if len(same_as) > SAME_AS_MAX:
            raise DocumentValidationError(f"organization.same_as allows at most {SAME_AS_MAX} entries.")
        for entry in same_as:
            if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                raise DocumentValidationError("Each organization.same_as entry must be an object with a url.")
            host = same_as_host(entry["url"])
            if not is_allowed_host(host):
                raise DocumentValidationError(f"organization.same_as host '{host}' is not an allowed profile host.")
            # The pre-2026-09-09 boolean. It gated sameAs while being client-settable, so it was an
            # impersonation hole rather than a guarantee. Rejected rather than ignored: a payload still
            # sending it is asserting something we must not silently drop on the floor.
            if "verified" in entry:
                raise DocumentValidationError(
                    "organization.same_as no longer accepts 'verified'; verification state is server-owned.")
            verification = entry.get("verification")
            if verification is not None:
                if not isinstance(verification, dict):
                    raise DocumentValidationError("organization.same_as verification must be an object.")
                if verification.get("state") not in VERIFICATION_STATES:
                    raise DocumentValidationError(
                        f"organization.same_as verification.state must be one of {sorted(VERIFICATION_STATES)}.")

    # Local-business fields (Business Profile Phase 1) — power full LocalBusiness JSON-LD. All optional.
    optional_string(organization, "place_id", "organization.place_id", max_length=200)
    if organization.get("review_destination") is not None and organization.get("review_destination") not in {"junior_bay", "google"}:
        raise DocumentValidationError("organization.review_destination must be 'junior_bay' or 'google'.")
    gbp_url = organization.get("gbp_url")
    if gbp_url is not None and not (isinstance(gbp_url, str) and gbp_url.startswith(("http://", "https://"))):
        raise DocumentValidationError("organization.gbp_url must be an HTTP(S) URL.")
    geo = organization.get("geo")
    if geo is not None:
        if not isinstance(geo, dict):
            raise DocumentValidationError("organization.geo must be an object.")
        for coord in ("latitude", "longitude"):
            value = geo.get(coord)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise DocumentValidationError(f"organization.geo.{coord} must be a number.")
    hours = organization.get("opening_hours")
    if hours is not None:
        if not isinstance(hours, list):
            raise DocumentValidationError("organization.opening_hours must be an array.")
        for spec in hours:
            if not isinstance(spec, dict):
                raise DocumentValidationError("Each organization.opening_hours entry must be an object.")
            days = spec.get("days")
            if not isinstance(days, list) or not days or any(d not in _ORG_DAYS for d in days):
                raise DocumentValidationError("organization.opening_hours[].days must be a non-empty list of day names (Monday..Sunday).")
            for field in ("opens", "closes"):
                if not (isinstance(spec.get(field), str) and _HHMM_RE.match(spec.get(field, ""))):
                    raise DocumentValidationError(f"organization.opening_hours[].{field} must be a 24h time (HH:MM).")


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
    optional_image_dims(document, "Service image_dims")
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
            if entry.get("fee_handling") is not None and entry.get("fee_handling") not in {"standard", "split", "net_guaranteed"}:
                raise DocumentValidationError("Service price fee_handling must be standard, split, or net_guaranteed.")
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
