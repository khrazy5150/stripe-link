"""The page brief: the contract the AI generation pipeline meets at (pure -- no I/O).

plans/AI_PAGE_BRIEF.md, reviewed 2026-09-27. Four things read this document, which is why it is
settled before any of them is built: the wizard writes it, the §A.7 floor grounds against it, the
Product and Offer are derived from it, and the Phase-2 URL adapter fills it.

The organising rule comes from slice 2: **every question we do not ask is a fact the AI is not
allowed to assert.** `domain/ai_floor.py` rejects claims the brief does not license, so a thin brief
does not make a shorter page -- it makes a cautious one. That is why `unlocked` and `withheld` exist:
a tenant should see what their answers buy BEFORE generating, not infer it from a disappointing page.

The brief is a CORE plus a KIND block (author, 2026-09-27: "number of steps doesn't matter as much as
smart steps"). `kind` is asked once, in plain language, and carries the fulfilment question with it --
which is why a download never sees a shipping field.
"""

from __future__ import annotations

from typing import Any

from stripe_link.domain.ai_floor import CLAIM_CLASSES

SCHEMA_VERSION = "2026-09-27"
DOCUMENT_TYPE = "page_brief"

PHYSICAL, DIGITAL, SERVICE = "physical", "digital", "service"
KINDS = (PHYSICAL, DIGITAL, SERVICE)
SOURCES = ("wizard", "url", "api", "existing_product")
TONES = ("direct", "warm", "playful", "technical", "premium")
LOCATION_MODES = ("in_person", "remote")
BOOKING_MODES = ("scheduled", "no_booking")

# Which brief field licenses which class of claim in `ai_floor.CLAIM_CLASSES`. This mapping IS the
# review step: everything empty on the left is a sentence the page will not contain.
LICENCES: dict[str, str] = {
    "guarantee": "guarantee",
    "terms": "cancellation",
    "certifications": "certification",
    "evidence": "efficacy",
    "physical.shipping": "shipping",
    "physical.usage": "dosage",
    "service.what_happens": "dosage",   # the service analogue: what actually happens in a session
}

# Steps, per kind. Derived rather than fixed, and read by the rail, the labels and the bounds alike --
# LandingPages.vue's rail is the scar that says what happens when three calculations each decide how
# long a conditional wizard is.
_COMMON_HEAD = ("identity", "price", "audience", "facts")
_COMMON_TAIL = ("promises", "voice", "exact", "review")
_KIND_STEP = {PHYSICAL: "shipping_use", DIGITAL: "delivery", SERVICE: "session"}

STEP_LABELS = {
    "identity": "What you're selling", "price": "Price", "audience": "Who it's for",
    "facts": "What people should know", "shipping_use": "Shipping & use",
    "delivery": "What they receive", "session": "The session", "promises": "Promises you make",
    "voice": "Voice", "exact": "Anything exact", "review": "Review",
}

# Required per step. `session` is the only kind block that can block, because a service page unable to
# say how long it takes or whether it is remote is not worth generating.
REQUIRED_STEPS = {"identity", "price", "audience", "facts", "session"}


class BriefError(ValueError):
    """The brief cannot be used. The message is shown to the tenant."""


def steps_for(kind: str) -> list[str]:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        return ["identity"]          # cannot know the shape until the kind is answered
    return list(_COMMON_HEAD) + [_KIND_STEP[kind]] + list(_COMMON_TAIL)


def step_labels(kind: str) -> list[str]:
    return [STEP_LABELS[s] for s in steps_for(kind)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _listed(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [_text(v) for v in value if _text(v)]
    return []


def kind_block(brief: dict[str, Any] | None) -> dict[str, Any]:
    """The one kind block that applies. Never more than one -- the wizard only ever shows one."""
    kind = _text((brief or {}).get("kind")).lower()
    block = (brief or {}).get(kind)
    return block if isinstance(block, dict) else {}


def field(brief: dict[str, Any] | None, path: str) -> Any:
    """Read `guarantee` or `physical.shipping` uniformly, so LICENCES can be one flat map."""
    if "." not in path:
        return (brief or {}).get(path)
    head, tail = path.split(".", 1)
    block = (brief or {}).get(head)
    return block.get(tail) if isinstance(block, dict) else None


def _answered(brief: dict[str, Any] | None, path: str) -> bool:
    value = field(brief, path)
    return bool(_listed(value)) if isinstance(value, (list, str)) and path.endswith("certifications") \
        else bool(_text(value)) if not isinstance(value, list) else bool(_listed(value))


def validate(brief: dict[str, Any] | None) -> None:
    """Enough to generate from, and no more. Optional fields stay optional -- that is the point."""
    if not isinstance(brief, dict):
        raise BriefError("A brief is required.")
    kind = _text(brief.get("kind")).lower()
    if kind not in KINDS:
        raise BriefError("Tell us what kind of thing this is: physical, digital, or a service.")
    if not _text(brief.get("name")):
        raise BriefError("Give it a name.")
    if not _text(brief.get("what_it_is")):
        raise BriefError("Say what it is, in a sentence.")
    if not _text(brief.get("audience")):
        raise BriefError("Say who it's for.")
    if not _listed(brief.get("facts")):
        raise BriefError("Add at least one thing people should know about it.")

    price = brief.get("price")
    if not isinstance(price, dict):
        raise BriefError("A price is required.")
    amount = price.get("unit_amount")
    if not isinstance(amount, int) or amount <= 0:
        raise BriefError("The price must be an amount in the smallest currency unit, above zero.")
    if len(_text(price.get("currency"))) != 3:
        raise BriefError("The price needs a three-letter currency.")
    if _text(price.get("pricing_model")) == "recurring" and not _text(price.get("recurring_interval")):
        raise BriefError("A recurring price needs an interval.")

    tone = _text(brief.get("tone"))
    if tone and tone not in TONES:
        raise BriefError(f"Tone must be one of: {', '.join(TONES)}.")
    source = _text(brief.get("source"))
    if source and source not in SOURCES:
        raise BriefError(f"Unknown brief source '{source}'.")

    if kind == SERVICE:
        block = kind_block(brief)
        duration = block.get("duration_minutes")
        if not isinstance(duration, int) or duration <= 0:
            raise BriefError("How long does the service take?")
        if _text(block.get("location_mode")) not in LOCATION_MODES:
            raise BriefError("Is it in person or remote?")
        booking = _text(block.get("booking"))
        if booking and booking not in BOOKING_MODES:
            raise BriefError(f"Booking must be one of: {', '.join(BOOKING_MODES)}.")


def unlocked(brief: dict[str, Any] | None) -> list[str]:
    """Claim classes this brief licenses."""
    return sorted({cls for path, cls in LICENCES.items() if _answered(brief, path)})


def withheld(brief: dict[str, Any] | None) -> list[dict[str, str]]:
    """What the page will NOT be able to say, and which answer would change that.

    The review step, and the reason a tenant understands a thin page instead of blaming the AI. Only
    classes relevant to this kind: a download has nothing to ship, so silence about shipping is not a
    gap worth reporting.
    """
    kind = _text((brief or {}).get("kind")).lower()
    out = []
    for path, cls in sorted(LICENCES.items(), key=lambda kv: kv[1]):
        head = path.split(".")[0]
        if head in KINDS and head != kind:
            continue
        if _answered(brief, path):
            continue
        out.append({"claim_class": cls, "field": path,
                    "label": CLAIM_CLASSES[cls]["label"],
                    "prompt": _WITHHELD_PROMPTS[path]})
    return out


_WITHHELD_PROMPTS = {
    "guarantee": "Add your guarantee and we can write about it.",
    "terms": "Tell us your cancellation terms and we can answer \"can I cancel anytime?\"",
    "certifications": "List certifications you actually hold and we can name them.",
    "evidence": "Add evidence you can stand behind and we can describe results.",
    "physical.shipping": "Tell us your shipping and we can mention delivery.",
    "physical.usage": "Add directions and we can explain how to use it.",
    "service.what_happens": "Describe the session and we can explain what happens.",
}


def grounding_text(brief: dict[str, Any] | None) -> str:
    """Everything the brief asserts, as one blob for `ai_floor` to ground claims against.

    Flattened rather than passed structurally because the floor does substring and number matching --
    it asks "does the brief say this", not "which field said it".
    """
    brief = brief or {}
    parts = [_text(brief.get("name")), _text(brief.get("what_it_is")), _text(brief.get("audience"))]
    parts += _listed(brief.get("facts"))
    for key in ("guarantee", "terms", "evidence"):
        parts.append(_text(brief.get(key)))
    parts += _listed(brief.get("certifications"))
    for value in kind_block(brief).values():
        parts.append(_text(value) if not isinstance(value, list) else " ".join(_listed(value)))
    price = brief.get("price") or {}
    if isinstance(price, dict) and price.get("unit_amount"):
        amount = int(price["unit_amount"]) / 100
        parts.append(f"{amount:.2f} {_text(price.get('currency')).upper()}")
        if _text(price.get("pricing_model")) == "recurring":
            parts.append(f"per {_text(price.get('recurring_interval'))}")
    parts += _listed(brief.get("must_say"))
    return "\n".join(p for p in parts if p)
