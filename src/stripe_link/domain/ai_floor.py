"""The §A.7 field floor: what the AI may never write, and what it may only RESTATE (pure -- no I/O).

Two mechanisms, because the measured failures came in two shapes.

STRUCTURAL. Some sections are resolver-owned outright and simply do not appear in the generation
schema, so the model cannot emit them and there is nothing to strip or review. Policy, legal, money,
platform-derived data, and fabricable social proof.

GROUNDEDNESS. The remaining sections are free text, and that is where every invented term actually
landed on 2026-09-27. The rule is not "never mention a refund" -- a brief that says "30-day
money-back guarantee" SHOULD produce copy saying so. The rule is that a claim in a governed class must
be traceable to the brief. Two of four models answered "can I cancel anytime?" with "yes, no lock-in,
no fees" from a brief that said nothing about cancellation; the cheapest turned "5g per serving, 60
per tub" into "one gummy daily" and added an efficacy claim. All three are ungrounded, and all three
are the kind of sentence a regulator or a chargeback reads as a promise.

This is NOT `composition.governed_sections`. That list decides what is VISIBLE by default; this one
decides what may be AUTHORED. They overlap (refund_policy is in both) and mean different things: the
AI may legitimately write a hero, which is governed for visibility.
"""

from __future__ import annotations

import re
from typing import Any

from stripe_link.domain.composition import element

# Sections the AI may never emit. Grouped by WHY, because the reason is what a future reader needs in
# order to judge whether a new section belongs here.
FLOOR_SECTIONS: dict[str, str] = {
    # Contract terms. An invented one is a representation the tenant never agreed to make.
    "refund_policy": "a refund window is a contract term; it comes from the tenant's policy",
    "legal_footer": "legal text, and jurisdiction-dependent",
    # Money. Platform-owned records, and wrong numbers here are the expensive kind of wrong.
    "checkout_cta": "carries price and the purchase action",
    "offer_price_selector": "prices come from the Price record",
    "price_highlight": "ditto -- a headline price is still a price",
    "coupon": "a discount the tenant did not create is a discount we would have to honour",
    # Derived from platform data. Generating these invents references that do not resolve.
    "structured_data": "search-engine markup, derived -- fabricated markup is the original §A.7 rule",
    "product_details": "the product record is the source",
    "product_carousel": "resolves real product ids",
    "catalog_grid": "resolves real product ids",
    "related_products": "resolves real product ids",
    "seller_profile": "the tenant's own identity",
    "tip_jar": "wired to a real Price",
    # Fabricable social proof. plans/REVIEWS.md exists to source these for real; a generated one is a
    # fabricated review no matter how it is labelled.
    "rating": "a rating is a number someone can check, and markup-eligible",
    "testimonials": "a generated testimonial is a fabricated review; real ones come from Reviews",
    # Manufactured urgency. A deadline the tenant did not set is a false scarcity claim.
    "countdown_timer": "a deadline the tenant did not set",
    # More fabricable proof, found while reading what the resolvers were about to permit. A logo wall
    # asserts who a business's clients ARE, and a trust badge asserts a certification -- both are
    # checkable facts about the world, which is the original §A.7 line.
    "client_marquee": "client logos assert real customers",
    "trust_badges": "a badge asserts a certification someone can check",
    # Shipping costs money and is COMPUTED, never written. The element's whole content arrives at runtime from
    # /shipping-quote -- destinations from the tenant's zones, prices from their boxes -- so there is nothing
    # here for a model to author, and a price it invented would be a commercial promise nobody made
    # (plans/SHIPPING_ELEMENT.md).
    "shipping": "destinations and rates are computed from the tenant's zones, never written",
    # Anything whose substance is a URL or an asset. The model has no way to know a real one, and an
    # invented link is a broken page at best and someone else's site at worst.
    "hero_media": "an image the AI cannot know the URL of",
    "video": "ditto, plus the video must exist",
    "before_after": "asserts a real, comparable result AND needs real images",
    "social_links": "the tenant's real accounts",
    "link_cards": "real destinations",
    # Identity. A brand is a fact about a business, resolved rather than written (see ai_resolvers).
    "brand_label": "the brand is resolved from the business, never invented",
    "brand_hero": "ditto",
}

# Claim classes for the free text the AI DOES write. `triggers` fire on the output; `evidence` is what
# must appear in the brief for the claim to be grounded. Deliberately broad on triggers and generous on
# evidence: a false positive costs one repair round, a false negative ships a promise.
CLAIM_CLASSES: dict[str, dict[str, Any]] = {
    "cancellation": {
        "label": "cancellation or renewal terms",
        "triggers": [r"cancel\s+(?:any\s*time|whenever|at\s+any)", r"no\s+(?:lock[\s-]?in|contract|commitment)",
                     r"no\s+cancell?ation\s+fee", r"cancel\s+or\s+pause", r"pause\s+any\s*time",
                     r"no\s+(?:hidden\s+)?fees?\b", r"skip\s+a\s+(?:month|delivery)"],
        "evidence": [r"cancel", r"lock[\s-]?in", r"commitment", r"contract", r"pause", r"skip"],
    },
    "guarantee": {
        "label": "a refund or money-back guarantee",
        "triggers": [r"money[\s-]?back", r"\brefund", r"\bguarantee", r"risk[\s-]?free",
                     r"\b\d+[\s-]?day\s+(?:trial|returns?)\b"],
        "evidence": [r"money[\s-]?back", r"refund", r"guarantee", r"return", r"trial"],
        "numeric": True,   # a 60-day guarantee is not a 30-day one
    },
    "shipping": {
        "label": "a shipping or delivery promise",
        "triggers": [r"free\s+(?:shipping|delivery)", r"ships?\s+(?:free|in|within)",
                     r"(?:next|same)[\s-]day\s+(?:delivery|shipping)", r"delivered\s+in\s+\d+"],
        "evidence": [r"ship", r"deliver", r"postage", r"freight"],
        "numeric": True,   # "ships in 2 days" is a different promise from "ships in 10"
    },
    "dosage": {
        "label": "dosage or usage instructions",
        "triggers": [r"\b(?:take|chew|swallow|apply|use)\s+(?:one|two|three|\d+)\b",
                     r"\b(?:one|two|three|\d+)\s+\w+\s+(?:daily|per\s+day|a\s+day|twice)",
                     r"\bdosage\b"],
        "evidence": [r"dose", r"dosage", r"serving", r"daily", r"per\s+day", r"directions", r"how\s+to\s+(?:take|use)"],
        # The NUMBER is the claim here. A brief saying "5g per serving, 60 per tub" licenses talking
        # about dosage but does not license "one gummy daily" -- it never said how many gummies make a
        # serving, and that invented 1 is what turns 5g into a per-gummy dose.
        "numeric": True,
        # The unit is the claim too. "per serving" and "per gummy" are different products.
        "exact_triggers": [r"per\s+(?:gummy|gummies|tablet|capsule|serving|dose|scoop|pill)"],
    },
    "efficacy": {
        "label": "an efficacy or health claim",
        "triggers": [r"you(?:'ll| will)\s+(?:notice|see|feel|experience|gain)", r"clinically\s+(?:proven|shown)",
                     r"\b(?:cures?|treats?|prevents?|heals?)\b", r"results?\s+in\s+\d+",
                     r"\bimproves?\s+(?:strength|endurance|performance|health|focus|sleep)\b",
                     r"\bscientifically\s+proven\b"],
        "evidence": [r"clinical", r"stud(?:y|ies)", r"proven", r"trial", r"research", r"efficac"],
    },
    "certification": {
        "label": "a certification or compliance claim",
        "triggers": [r"\bFDA[\s-]?(?:approved|registered)", r"\bGMP\b", r"\bcertified\b", r"\bUSDA\b",
                     r"\borganic\b", r"\bnon[\s-]?GMO\b", r"\bISO\s?\d+"],
        "evidence": [r"fda", r"gmp", r"certif", r"usda", r"organic", r"non[\s-]?gmo", r"iso"],
    },
}

# Section fields that carry free text worth checking. Anything else in a section is structural.
_TEXT_FIELDS = ("text", "heading", "question", "answer", "label", "value", "quote", "body", "title")

_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


_UNIT_STEMS = ("day", "week", "month", "year", "hour", "minute", "gummy", "gummies", "tablet",
               "capsule", "serving", "scoop", "pill", "tub", "bottle", "pack", "gram", "g", "mg")


def _quantities(text: str) -> set[str]:
    """Number-with-unit pairs, plus bare numbers, normalized.

    Unit-aware because a brief saying "60 gummies per tub" must NOT license "a 60-day guarantee" --
    the figure matches and the promise is entirely different. That was a real false negative before
    units were considered. A trailing "s" is stripped so "30 days" and "30-day" are one quantity.
    """
    lowered = str(text or "").lower()
    for word, digit in _NUMBER_WORDS.items():
        lowered = re.sub(rf"\b{word}\b", digit, lowered)
    found = set(re.findall(r"\d+", lowered))
    for number, unit in re.findall(r"(\d+)\s*-?\s*([a-z]+)", lowered):
        stem = unit[:-1] if unit.endswith("s") and unit[:-1] in _UNIT_STEMS else unit
        if stem in _UNIT_STEMS:
            found.add(f"{number} {stem}")
    return found


def _invented(clause: str, brief: str) -> set[str]:
    """Quantities in the clause that the brief never states, preferring the unit-qualified reading."""
    said, known = _quantities(clause), _quantities(brief)
    qualified = {q for q in said if " " in q}
    if qualified:
        return qualified - known
    return said - known


def may_generate_section(section_type: str) -> bool:
    """False for a section the AI must never author."""
    return str(section_type or "").strip() not in FLOOR_SECTIONS


def floor_reason(section_type: str) -> str:
    return FLOOR_SECTIONS.get(str(section_type or "").strip(), "")


def generatable_sections(candidates) -> list[str]:
    """The AI's section vocabulary: the caller's candidates minus the floor, minus anything unknown.

    Unknown types are dropped rather than passed through: `Page.schema.json` accepts any `type` string
    and renders nothing for one the catalog does not know, so a passthrough would validate and produce
    a blank page.
    """
    return [s for s in (candidates or []) if may_generate_section(s) and element(s)]


def _texts(section: dict[str, Any]):
    """Every free-text string in a section, with a path, including inside `items[]`."""
    for field in _TEXT_FIELDS:
        value = section.get(field)
        if isinstance(value, str) and value.strip():
            yield field, value
    for index, item in enumerate(section.get("items") or []):
        if isinstance(item, dict):
            for field in _TEXT_FIELDS:
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    yield f"items[{index}].{field}", value


def _grounded(class_key: str, brief: str) -> bool:
    """Does the brief license this class of claim at all?

    Class-level rather than phrase-level on purpose. A brief that never mentions cancellation cannot
    license ANY cancellation sentence, which is precisely the measured failure; whereas a brief that
    does discuss returns has authorized the model to talk about returns in its own words, and demanding
    a literal string match there would reject correct paraphrase.
    """
    haystack = str(brief or "").lower()
    return any(re.search(pattern, haystack) for pattern in CLAIM_CLASSES[class_key]["evidence"])


def _sentence_around(text: str, index: int) -> str:
    """The sentence containing `index`. A claim's numbers belong to its own sentence, not its neighbour's
    -- "You have 30 days to decide. Contact us for a refund." must not lend its 30 to the refund."""
    start = max((text.rfind(stop, 0, index) for stop in (".", "!", "?", "\n")), default=-1)
    end = min((pos for pos in (text.find(stop, index) for stop in (".", "!", "?", "\n")) if pos != -1),
              default=len(text))
    return text[start + 1:end]


def _first_violation(key, spec, lowered: str, brief_lower: str, licensed: bool) -> str:
    """The first ungrounded claim of this class in this string, described, or "".

    Three mechanisms, weakest to strongest, because the measured failures needed all three:
      1. CLASS -- a brief that never mentions cancellation licenses no cancellation sentence.
      2. EXACT -- some spans must appear verbatim: "per serving" and "per gummy" are different products.
      3. NUMERIC -- where the number IS the claim, every number must come from the brief. A brief
         giving "5g per serving, 60 per tub" permits discussing dosage but not inventing "one daily".
    """
    for pattern in spec.get("exact_triggers", []):
        match = re.search(pattern, lowered)
        if match and match.group(0) not in brief_lower:
            return f"states {spec['label']} the brief does not make (\"{match.group(0)}\")"
    for pattern in spec["triggers"]:
        match = re.search(pattern, lowered)
        if not match:
            continue
        if not licensed:
            return f"states {spec['label']} that the brief does not mention (\"{match.group(0)}\")"
        if spec.get("numeric"):
            # The number is rarely INSIDE the trigger: "money-back" matches, while the 90 that makes
            # it a different promise sits earlier in the sentence. So the sentence is the unit.
            clause = _sentence_around(lowered, match.start())
            invented = _invented(clause, brief_lower)
            if invented:
                return (f"states {spec['label']} with a figure the brief never gives "
                        f"({', '.join(sorted(invented))} in \"{clause.strip()[:80]}\")")
    return ""


def claim_violations(sections, brief: str = "") -> list[dict[str, str]]:
    """Ungrounded governed claims in generated copy, as `{section, path, claim_class, text, reason}`."""
    found: list[dict[str, str]] = []
    brief_lower = str(brief or "").lower()
    licensed = {key: _grounded(key, brief) for key in CLAIM_CLASSES}
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or section.get("type") or "?")
        for path, text in _texts(section):
            lowered = text.lower()
            for key, spec in CLAIM_CLASSES.items():
                hit = _first_violation(key, spec, lowered, brief_lower, licensed[key])
                if hit:
                    found.append({"section": section_id, "path": path, "claim_class": key,
                                  "text": text[:160], "reason": hit})
    return found


def section_violations(sections) -> list[dict[str, str]]:
    """Sections the AI emitted that it may never author. Belt to the schema's braces.

    The schema already excludes these, so a hit means the model ignored the contract -- worth catching
    rather than trusting, because this is the failure whose cost is a legal representation.
    """
    out = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        kind = str(section.get("type") or "")
        if not may_generate_section(kind):
            out.append({"section": str(section.get("id") or kind), "path": "type",
                        "claim_class": "forbidden_section", "text": kind,
                        "reason": f"{kind} is resolver-owned: {floor_reason(kind)}"})
    return out


def assert_within_floor(value: dict[str, Any], brief: str = "") -> None:
    """The `validate` callback for `generate_structured`. Raises so the repair loop re-prompts.

    Raising rather than stripping is deliberate: silently deleting a section leaves a page with a gap
    nobody asked for, while a repair round tells the model what it did and usually gets a grounded
    sentence back.
    """
    sections = (value or {}).get("sections") or []
    problems = section_violations(sections) + claim_violations(sections, brief)
    if not problems:
        return
    lines = [f"- {p['section']}.{p['path']}: {p['reason']}" for p in problems[:8]]
    raise ValueError(
        "Remove or rewrite these -- state only what the brief gives you, and never invent policy, "
        "dosage, or results:\n" + "\n".join(lines))
