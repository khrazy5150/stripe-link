"""The GENERATION schema -- what the model is allowed to emit (pure -- no I/O).

Derived from the section catalog, and deliberately stricter than `Page.schema.json`. Measured
2026-09-27: that document's `sections[]` is `additionalProperties: true` requiring only `id` and
`type`, so `{"id": "x", "type": "anything"}` validates perfectly and renders nothing. A schema that
accepts unrenderable output is not a contract, so the validation schema cannot be the generation one.

Shapes come from what `runtime/html.py` actually reads, not from what a section could theoretically
hold -- a field the renderer ignores is a field the model wasted tokens on.

Strict structured output constrains the shape of the schema itself, which is why this is built rather
than hand-written: `minItems` above 1 is rejected outright (so cardinality is stated in the prompt),
`oneOf` is not accepted (so the union is `anyOf`), and every object must close `additionalProperties`
and list every property in `required`.
"""

from __future__ import annotations

from typing import Any

from stripe_link.domain.ai_elements import for_prompt, routes_for
from stripe_link.domain.ai_floor import may_generate_section

_TEXT = {"type": "string"}


# The model must say WHERE each section came from and WHY that element fits -- it forces the
# classification to happen before the content, which is the whole correction to V1. That generator
# went brief -> element directly, so the questionnaire's shape became the semantics and "things you
# want people to know" collapsed into "desirable things -> bragging points".
#
# It is a PARALLEL ARRAY rather than three fields on every branch, and that is not a style choice:
# per-branch fields multiply by the number of elements, and Bedrock rejected the result outright --
# "the compiled grammar is too large". Eleven branches x three properties is 33 extra slots in the
# grammar; one extra object shape is four. Same discipline, a fraction of the complexity.
CLASSIFICATION_ITEM = {
    "section_id": {"type": "string"},
    "source_fact": {"type": "string"},
    "fact_kind": {"type": "string"},
    "reason": {"type": "string"},
}


def _obj(props: dict[str, Any], required=None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": sorted(required if required is not None else props.keys()),
            "properties": props}


# What the renderer reads, per section type. Anything absent here cannot be generated even if the
# catalog knows it -- an un-modelled section would reach the page as an empty shell.
SECTION_SHAPES: dict[str, dict[str, Any]] = {
    "headline": {"text": _TEXT},
    "subheadline": {"text": _TEXT},
    "seo_title": {"text": _TEXT},
    "hero": {"tagline": _TEXT},
    "quote": {"text": _TEXT},
    "content_block": {"heading": _TEXT, "body": _TEXT},
    "author_bio": {"heading": _TEXT, "body": _TEXT},
    "page_ribbon": {"text": _TEXT},
    "bragging_points": {"heading": _TEXT,
                        "items": {"type": "array", "items": _obj({"label": _TEXT, "value": _TEXT})}},
    # STRINGS, not {label, value} objects. `render_numbered_list` is the authority and it renders one
    # authored LINE per item -- `str(item or "").strip()` into a single <p>. The object shape here made the
    # model emit objects the renderer could not use; the builder then coerced them on load with String(i),
    # which is where the literal "[object Object]" on a real generated page came from (author, 2026-09-29).
    "numbered_list": {"heading": _TEXT,
                      "items": {"type": "array", "items": _TEXT}},
    "faq": {"heading": _TEXT,
            "items": {"type": "array", "items": _obj({"question": _TEXT, "answer": _TEXT})}},
}


def generatable_with_shape(section_types) -> list[str]:
    """The intersection of "allowed" and "we know what it looks like", in the caller's order."""
    return [s for s in (section_types or []) if s in SECTION_SHAPES and may_generate_section(s)]


def page_sections_schema(section_types) -> dict[str, Any]:
    """A strict schema for `{"sections": [...]}` over exactly these section types.

    `type` is a single-value enum per branch rather than one shared string field: it makes the union
    discriminable, so a model choosing the `faq` branch cannot then emit a `headline`'s fields.
    """
    allowed = generatable_with_shape(section_types)
    if not allowed:
        raise ValueError("No generatable sections: every candidate was floored or has no known shape.")
    branches = [
        _obj({"id": _TEXT, "type": {"type": "string", "enum": [name]}, **SECTION_SHAPES[name]})
        for name in allowed
    ]
    return _obj({
        "sections": {"type": "array", "items": {"anyOf": branches}},
        "classification": {"type": "array", "items": _obj(CLASSIFICATION_ITEM)},
    }, required=["sections", "classification"])


def describe_vocabulary(section_types) -> str:
    """The element contracts, as prompt text.

    This used to be a list of field names, which told the model what each element LOOKED like and
    nothing about what it was FOR -- and a model that only knows shapes will put a sentence in a card
    built for a number. The contracts lead with the job and the do-not-use boundary instead.

    Cardinality is stated here rather than in the schema because strict structured output rejects
    `minItems` above 1: the constraint is real, it just cannot live where it belongs.
    """
    allowed = generatable_with_shape(section_types)
    routing = []
    for name in allowed:
        for kind in routes_for(name):
            routing.append(f"- a {kind.replace('_', ' ')} goes in {name}")
    return (
        "ELEMENTS YOU MAY USE. Use each at most once, in this order, and include at least four.\n\n"
        + for_prompt(allowed)
        + "\n\n### Where each kind of fact goes\n"
        + "Junior Bay has no `feature` or `benefit` element. Route them:\n"
        + "\n".join(routing)
        + "\n\nAn attributed customer quote has NO element here and must not be written at all."
    )
