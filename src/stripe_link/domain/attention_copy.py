"""Finished post copy from an Attention brief (plans/ATTENTION_PRIMITIVE.md A1, author decision 2026-11-02).

**Why generation lives in `stripe-link` and not in `../sam/attention`.** The tenant's AI key is stored as
ciphertext and decrypted only here -- "the ciphertext never leaves the backend" (`ai_provider.redacted`).
Letting a second stack generate would mean granting a second stack decrypt on every tenant's provider key,
and duplicating the usage counter. This is the same reasoning already written above `_enrich_offer`: this
function is the one that holds the BYOK config, the provider adapter and the counter, so hanging generation
elsewhere means widening another function's grants to re-reach what this one has.

**The division of labour.** Attention decides WHAT a post is about: the pillar, its goal, the instruction,
the anchor the post may not drift from, the channel's native format and the hook openings. That is §3's
"five-pillar prompt templates", and it stays there. This module only composes those given fields into a
prompt and names the shape of the answer. Nothing here knows what a pillar is, how many there are, or how
a hook is built -- add a pillar in Attention and this file does not change.

**The brief arrives via a browser, so it is INPUT, not instruction.** It is composed into the prompt field
by field, with every field length-capped (`_clean`), so a crafted brief can say more only within its own
budget -- it cannot append a new instruction of unbounded length, and it cannot introduce a field this
module does not name. `build_prompt` is the only place a brief becomes text.
"""
from __future__ import annotations

from typing import Any

# Per-field caps. Generous for real content (an anchor is a sentence, an instruction a line or two) and
# small enough that the assembled prompt cannot be used as a channel for something else.
MAX_FIELD = 400
MAX_HOOKS = 6
MAX_SLIDES = 10

# Every field this module will read off a brief. A brief carrying anything else is not an error -- Attention
# may add fields for its own UI -- but the extra never reaches the prompt, because the prompt is built from
# this list rather than from whatever arrived.
BRIEF_FIELDS = ("pillar", "goal", "brief", "anchor", "subject", "channel", "format", "format_label")

SYSTEM = (
    "You write social posts for a small business. You write plainly, in the voice of the person who runs "
    "it, never in marketing language. You do not invent facts, prices, guarantees, statistics, reviews or "
    "medical, legal or financial claims. If you do not know something, you leave it out."
)

# The one rule that makes this not sludge: the post is bounded by the anchor, which is the offer's own
# material. Stated to the model as a constraint, and checked afterwards by the caller's validator.
ANCHOR_RULE = ("Everything you write must be about this one idea, in the seller's own terms. You may "
               "rephrase it. You may not change the subject, add a second idea, or contradict it.")


def _clean(value: Any, *, cap: int = MAX_FIELD) -> str:
    """One field of a brief, as text: whitespace collapsed, newlines removed, length capped.

    Newlines go because the prompt is a line-per-field block and an embedded newline would let one field
    look like two -- which is the shape of every prompt-injection-by-field-value.
    """
    text = " ".join(str(value if value is not None else "").split())
    return text[:cap].strip()


def _hooks(brief: Any) -> list[str]:
    raw = (brief or {}).get("hooks") if isinstance(brief, dict) else None
    if not isinstance(raw, (list, tuple)):
        return []
    cleaned = [_clean(hook) for hook in raw]
    return [hook for hook in cleaned if hook][:MAX_HOOKS]


def _shape(brief: dict[str, Any]) -> str:
    """The channel's native size, in the units that channel uses. Absent rather than invented: a carousel
    has no duration and a video has no slide count, and Attention omits whichever does not apply."""
    seconds = brief.get("seconds")
    slides = brief.get("slides")
    if isinstance(seconds, (list, tuple)) and len(seconds) == 2:
        return f"Length: {int(seconds[0])}-{int(seconds[1])} seconds of spoken script."
    if isinstance(slides, (list, tuple)) and len(slides) == 2:
        return f"Length: {int(slides[0])}-{int(slides[1])} slides, one short line or two per slide."
    return ""


def wants_slides(brief: Any) -> bool:
    slides = (brief or {}).get("slides") if isinstance(brief, dict) else None
    return isinstance(slides, (list, tuple)) and len(slides) == 2


def usable(brief: Any) -> bool:
    """Whether there is enough here to generate anything.

    **The ANCHOR is the one required field**, because it is the bound. A brief without one would produce a
    post about nothing in particular, which is the free-form "write me marketing" prompt this whole design
    exists to refuse -- so it is declined rather than attempted, and the tenant keeps their generation.
    """
    return bool(isinstance(brief, dict) and _clean(brief.get("anchor")))


def build_prompt(brief: Any) -> str:
    """The prompt, composed field by field from a brief. "" when there is no anchor to bound it.

    Deliberately boring assembly. Every line is `label: value` with the value cleaned and capped, so what
    the model reads is a bounded description of a post and not a document the caller controls.
    """
    if not usable(brief):
        return ""
    fields = {name: _clean(brief.get(name)) for name in BRIEF_FIELDS}
    lines = [f"Write one {fields['format_label'] or 'social post'} for a small business."]
    if fields["subject"]:
        lines.append(f"What is being sold: {fields['subject']}")
    lines.append(f"The one idea this post is about: {fields['anchor']}")
    lines.append(ANCHOR_RULE)
    if fields["goal"]:
        lines.append(f"What this post is for: {fields['goal']}")
    if fields["brief"]:
        lines.append(f"How to approach it: {fields['brief']}")
    shape = _shape(brief if isinstance(brief, dict) else {})
    if shape:
        lines.append(shape)
    hooks = _hooks(brief)
    if hooks:
        # OFFERED, not imposed. The hooks are patterns built from the offer's own material; a model told to
        # reproduce one verbatim writes a stilted post around it, and one told to ignore them loses the
        # grounding. So: start from one, in your own words.
        lines.append("Open with one of these, adapted into your own words rather than copied:")
        lines.extend(f"- {hook}" for hook in hooks)
    if wants_slides(brief):
        lines.append("Put the post in `slides`, one entry per slide, and leave `body` empty.")
    else:
        lines.append("Put the post in `body` and leave `slides` empty.")
    return "\n".join(lines)


def request_schema() -> dict[str, Any]:
    """The answer's shape.

    **No `maxItems`, anywhere.** Bedrock REJECTS a schema carrying it, and the failure is silent in the
    worst way -- every generation degrades and nothing says why (learned 2026-11-01, `semantic_enrich`).
    Length limits are enforced in `parse` instead, where they are ours to apply.
    """
    return {
        "type": "object",
        "properties": {
            "hook": {"type": "string", "description": "The opening line, in the seller's own words."},
            "body": {"type": "string",
                     "description": "The post, or the spoken script. Empty for a slide format."},
            "slides": {"type": "array", "items": {"type": "string"},
                       "description": "One entry per slide. Empty for a non-slide format."},
        },
        "required": ["hook", "body", "slides"],
        "additionalProperties": False,
    }


def parse(answer: Any, brief: Any) -> dict[str, Any]:
    """The model's answer, cleaned into what the dashboard renders. `{}` when it said nothing usable.

    `{}` matters: the caller RELEASES the tenant's generation on it. Somebody who pressed the button and
    got nothing back must not have paid for it, which is the rule `enrich` already follows.
    """
    if not isinstance(answer, dict):
        return {}
    hook = _clean(answer.get("hook"))
    # The body is NOT newline-collapsed the way a field is -- paragraphs are the content here. Capped
    # generously and otherwise left as the model wrote it.
    body = str(answer.get("body") or "").strip()[:4000]
    raw_slides = answer.get("slides")
    slides = ([_clean(s) for s in raw_slides][:MAX_SLIDES]
              if isinstance(raw_slides, (list, tuple)) else [])
    slides = [s for s in slides if s]
    if wants_slides(brief):
        # A slide format with no slides produced nothing, whatever else came back: the body would then be
        # a paragraph where the tenant expected a carousel.
        if not slides:
            return {}
        body = ""
    elif not body:
        return {}
    if not hook:
        # A missing hook is recoverable rather than fatal: the first slide, or the first sentence, is the
        # opening whether or not the model labelled it. Throwing away a good post over a missing label
        # would cost the tenant a generation for nothing.
        hook = slides[0] if slides else body.split("\n", 1)[0][:MAX_FIELD]
    out: dict[str, Any] = {"hook": hook, "body": body, "slides": slides}
    if isinstance(brief, dict):
        # Echoed back so the dashboard can match copy to the brief it asked about without holding state.
        out["pillar"] = _clean(brief.get("pillar"))
        out["channel"] = _clean(brief.get("channel"))
        out["anchor"] = _clean(brief.get("anchor"))
    return out
