"""Suggested Google Search ad copy for one offer (plans/ADS_PRIMITIVE.md, Guided Promo Mode).

Lives here, beside `attention_copy`, for the reason written at the top of that module: this function holds
the provider adapter, the BYOK configuration and the usage counter, so generating in `../sam/attention`
would mean a second stack re-reaching all three. Attention owns the campaign and validates whatever the
tenant finally saves; this only proposes text, and every suggestion is edited and approved by the tenant
before anything reaches Google.

**Grounded in the offer, not a prompt box.** The prompt is built from the offer's semantic model (the same
derivation the page's SEO reads), its landing products' own descriptions and the place the tenant chose. A
tenant cannot type an instruction into it, and every field is capped and newline-collapsed so a product
description can say more only within its own budget.

**Google's limits are enforced in `parse`, never trusted to the model:** headlines 3-15 of at most 30
characters, descriptions 2-4 of at most 90, keywords at most 80. An answer that cannot fill the minimums
is `{}`, and the caller refunds the generation.
"""
from __future__ import annotations

from typing import Any

MAX_FIELD = 300
MAX_PRODUCTS = 3
HEADLINE_LENGTH, MAX_HEADLINES, MIN_HEADLINES = 30, 15, 3
DESCRIPTION_LENGTH, MAX_DESCRIPTIONS, MIN_DESCRIPTIONS = 90, 4, 2
KEYWORD_LENGTH, MAX_KEYWORDS, MAX_NEGATIVES = 80, 20, 20
OBJECTIVES = {"traffic": "visits to the landing page", "leads": "enquiries from the landing page",
              "sales": "purchases on the landing page"}

SYSTEM = (
    "You write Google Search ads for a small business. You write plainly and specifically, in the seller's "
    "own terms. You never invent prices, discounts, guarantees, awards, statistics, reviews, delivery times "
    "or medical, legal or financial claims. If the facts do not say it, you leave it out. You follow Google "
    "Ads editorial rules: no all-caps words, no repeated punctuation, no exclamation mark in a headline, no "
    "phone numbers, and no other company's trademark."
)


def _clean(value: Any, *, cap: int = MAX_FIELD) -> str:
    return " ".join(str(value if value is not None else "").split())[:cap].strip()


def usable(model: Any) -> bool:
    """An offer with no name gives the model nothing to be about, so it is declined before any spend."""
    primary = (((model or {}).get("facts") or {}).get("entities") or {}).get("primary") or {}
    return bool(_clean(primary.get("name")))


def build_prompt(model: dict, *, products: list[dict] | None = None, place: str = "", business: str = "",
                 objective: str = "traffic") -> str:
    facts = model.get("facts") or {}
    entities = facts.get("entities") or {}
    primary = entities.get("primary") or {}
    lines = [
        f"Write a Google Search ad that drives {OBJECTIVES.get(objective, OBJECTIVES['traffic'])}.",
        "Use only these facts about what is being advertised:",
        f"- What it is: {_clean(primary.get('name'))} ({_clean(primary.get('type'))})",
    ]
    secondary = [_clean(item.get("name")) for item in entities.get("secondary") or [] if isinstance(item, dict)]
    if any(secondary):
        lines.append(f"- Also included: {', '.join(name for name in secondary[:4] if name)}")
    brand = (facts.get("brand") or {}).get("name") if isinstance(facts.get("brand"), dict) else None
    if _clean(brand):
        lines.append(f"- Brand: {_clean(brand)}")
    if _clean(business):
        lines.append(f"- Business: {_clean(business)}")
    hierarchy = [_clean(level) for level in (facts.get("taxonomy") or {}).get("hierarchy") or []]
    if any(hierarchy):
        lines.append(f"- Category: {' > '.join(level for level in hierarchy if level)}")
    intent = facts.get("intent") or {}
    if _clean(intent.get("fulfillment")):
        lines.append(f"- Delivered as: {_clean(intent.get('fulfillment'))}")
    commerce = facts.get("commerce") or {}
    if commerce.get("purchase_model") == "recurring":
        lines.append("- Sold as a subscription")
    positioning = facts.get("positioning") or {}
    for field, label in (("problems", "Problems it solves"), ("transformations", "What changes for the buyer")):
        values = [_clean(value) for value in positioning.get(field) or []][:3]
        if any(values):
            lines.append(f"- {label}: {'; '.join(value for value in values if value)}")
    for product in (products or [])[:MAX_PRODUCTS]:
        description = _clean((product or {}).get("description"))
        if description:
            lines.append(f"- Product description: {description}")
    if _clean(place, cap=120):
        lines.append(f"- Where it is offered: {_clean(place, cap=120)}")
    lines.extend([
        "",
        f"Give 8 to {MAX_HEADLINES} headlines of at most {HEADLINE_LENGTH} characters each, varied: what it is, "
        "who it is for, a benefit stated in the facts, and a call to action.",
        f"Give {MIN_DESCRIPTIONS} to {MAX_DESCRIPTIONS} descriptions of at most {DESCRIPTION_LENGTH} characters each.",
        "Give up to 10 exact-match keywords and up to 10 phrase-match keywords: what a buyer would type to find "
        "this, lowercase, including the place when it is a local service.",
        "Give up to 10 negative keywords: words in searches that are clearly not buyers of this, such as free, "
        "jobs, salary, diy or used, only where they fit.",
    ])
    return "\n".join(lines)


def request_schema() -> dict[str, Any]:
    """No `maxItems` anywhere: Bedrock rejects it, silently degrading every call (see `attention_copy`)."""
    strings = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "headlines": {**strings, "description": f"Ad headlines, each at most {HEADLINE_LENGTH} characters."},
            "descriptions": {**strings, "description": f"Ad descriptions, each at most {DESCRIPTION_LENGTH} characters."},
            "keywords": {**strings, "description": "Exact-match keywords."},
            "phrase_keywords": {**strings, "description": "Phrase-match keywords."},
            "negative_keywords": {**strings, "description": "Negative keywords."},
        },
        "required": ["headlines", "descriptions", "keywords", "phrase_keywords", "negative_keywords"],
        "additionalProperties": False,
    }


def _fit(values: Any, length: int, limit: int, *, lower: bool = False, exclude: set[str] | None = None) -> list[str]:
    """Clean, drop what is too long (cutting a headline mid-word is worse than losing it), dedupe, cap."""
    out, seen = [], set(exclude or ())
    for value in values if isinstance(values, (list, tuple)) else []:
        text = _clean(value, cap=length + 1)
        text = text.lower() if lower else text
        key = text.casefold()
        if not text or len(text) > length or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) == limit:
            break
    return out


def parse(answer: Any) -> dict[str, Any]:
    """The suggestion the dashboard places in the draft form, or `{}` when it cannot fill Google's minimums."""
    if not isinstance(answer, dict):
        return {}
    headlines = _fit(answer.get("headlines"), HEADLINE_LENGTH, MAX_HEADLINES)
    descriptions = _fit(answer.get("descriptions"), DESCRIPTION_LENGTH, MAX_DESCRIPTIONS)
    keywords = _fit(answer.get("keywords"), KEYWORD_LENGTH, MAX_KEYWORDS, lower=True)
    phrase = _fit(answer.get("phrase_keywords"), KEYWORD_LENGTH, MAX_KEYWORDS, lower=True, exclude=set(keywords))
    positives = {term.casefold() for term in keywords + phrase}
    negatives = _fit(answer.get("negative_keywords"), KEYWORD_LENGTH, MAX_NEGATIVES, lower=True, exclude=positives)
    if len(headlines) < MIN_HEADLINES or len(descriptions) < MIN_DESCRIPTIONS or not (keywords or phrase):
        return {}
    return {"headlines": headlines, "descriptions": descriptions, "keywords": keywords,
            "phrase_keywords": phrase, "negative_keywords": negatives}
