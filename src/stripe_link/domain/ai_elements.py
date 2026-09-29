"""Element contracts: what each element is FOR, and mechanical checks that it was used that way.

The V1 failure this exists to prevent: asked "what do you want people to know", the generator read
the answers as "desirable things" and made all six into bragging points -- prose in cards that want
quantities. The questionnaire's shape became the semantics.

Two halves, and only one of them is reliable.

CONTRACTS TEACH. `for_prompt()` renders each element's job, its do-not-use boundary, its confusable
neighbours and a worked bad example into the system prompt. That is persuasion, and a future model
may be persuaded differently.

CHECKS ENFORCE. `violations()` applies rules a machine can settle -- a bragging point's value must
carry a figure and stay short -- and every bad card in the measured failure fails one. This is what
still works when the model changes underneath us.

Both read `composition_rules.json`, so an element cannot be taught one thing and checked for another.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent.parent / "composition_rules.json"
_CACHE: dict[str, Any] | None = None

# A bragging point's value is a STAT, not a sentence. Both halves matter: "Premium Quality" has no
# figure, and "30g of premium milk protein" has one buried in prose where the card wanted "30g".
MAX_STAT_CHARS = 24
_FIGURE = re.compile(r"\d")


def _rules() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return _CACHE


def contract(element: str) -> dict[str, Any]:
    return (_rules().get("contracts") or {}).get(str(element or "").strip()) or {}


def contracted() -> list[str]:
    return sorted((_rules().get("contracts") or {}).keys())


def routes_for(element: str) -> list[str]:
    """The fact-kinds this element accepts.

    Junior Bay has no `feature` or `benefit` element. Rather than leave the model to guess where such
    a fact goes -- and it guessed bragging_points -- the contracts route them: features to
    numbered_list, benefits to content_block. Quantified social proof routes to bragging_points, which
    is where it always belonged; an ATTRIBUTED testimonial routes nowhere, because generating one is
    fabricating a review (§A.7).
    """
    return list(contract(element).get("routes") or [])


def route_table() -> dict[str, str]:
    """fact-kind -> element. The classification the model is asked to make explicit."""
    table: dict[str, str] = {}
    for element in contracted():
        for kind in routes_for(element):
            table.setdefault(kind, element)
    return table


def _items(section: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in (section.get("items") or []) if isinstance(i, dict)]


# A policy term is a COMMITMENT the tenant makes, not evidence about the product -- so it is never a
# bragging point however numeric it looks, and the page already carries a `refund_policy` element that says
# it properly. Found on a real generated page: "30 days / Refund window" as a stat card, beside the refund
# policy section saying the same thing (author, 2026-09-29). The floor did not catch it because the claim was
# perfectly GROUNDED; being true was never the question, being evidence was.
POLICY_TERMS = ("refund", "return", "warrant", "guarantee", "money back", "money-back", "exchange")


def _is_policy_term(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in POLICY_TERMS)


def violations(sections) -> list[dict[str, str]]:
    """Contract breaches a machine can settle. Raised into the repair loop, not silently stripped."""
    found: list[dict[str, str]] = []

    def fail(section, reason):
        found.append({"section": str(section.get("id") or section.get("type") or "?"),
                      "element": str(section.get("type") or ""), "reason": reason})

    for section in sections or []:
        if not isinstance(section, dict):
            continue
        element = str(section.get("type") or "")
        spec = contract(element)
        if not spec:
            continue

        if element == "bragging_points":
            for item in _items(section):
                if not isinstance(item, dict):
                    continue
                if _is_policy_term(item.get("label")) or _is_policy_term(item.get("value")):
                    fail(section, "bragging_points must not carry a policy term "
                                  f"({item.get('label') or item.get('value')!r}). A refund window, warranty "
                                  "or returns period is a promise, not evidence -- the refund_policy element "
                                  "says it, and repeating it here says it twice.")

        count = spec.get("count") or {}
        items = _items(section)
        if items:
            if count.get("min") and len(items) < int(count["min"]):
                fail(section, f"{element} needs at least {count['min']} items; it has {len(items)}.")
            if count.get("max") and len(items) > int(count["max"]):
                fail(section, f"{element} allows at most {count['max']} items; it has {len(items)}. "
                              f"Keep the strongest {count.get('ideal', count['max'])}.")

        if element == "bragging_points":
            for index, item in enumerate(items):
                value = str(item.get("value") or "").strip()
                if not value:
                    continue
                if not _FIGURE.search(value):
                    fail(section, f"items[{index}].value {value!r} carries no figure. A bragging point "
                                  f"is evidence, not an adjective -- move this to numbered_list "
                                  f"(a feature) or content_block (a benefit).")
                elif len(value) > MAX_STAT_CHARS:
                    fail(section, f"items[{index}].value {value!r} is a sentence, not a stat. The value "
                                  f"is the figure alone; what it counts goes in the label.")

        if element == "seo_title":
            text = str(section.get("text") or "").strip()
            if len(text) > 60:
                fail(section, f"seo_title is {len(text)} characters; a search result shows about 60.")

        if element == "quote":
            text = str(section.get("text") or "")
            # An attributed line is a testimonial, and a generated testimonial is a fabricated review.
            if re.search(r'["“”].*["“”]\s*[-–—]\s*\w', text) or \
               re.search(r'[-–—]\s*[A-Z][a-z]+\s+[A-Z]\.?\s*$', text.strip()):
                fail(section, "a quote must not be attributed to a person -- an attributed quote is a "
                              "testimonial, and generating one fabricates a review.")
    return found


def assert_contracts(value: dict[str, Any]) -> None:
    """The `validate` callback shape, so this composes with the §A.7 floor's own check."""
    problems = violations((value or {}).get("sections") or [])
    if not problems:
        return
    lines = [f"- {p['section']} ({p['element']}): {p['reason']}" for p in problems[:8]]
    raise ValueError("These sections do not match what the element is for:\n" + "\n".join(lines))


def for_prompt(elements) -> str:
    """The contracts, rendered for the system prompt.

    Ordered job-first and boundary-second on purpose: the model already knows what a headline looks
    like. What it does not know is where one element stops and the next begins, which is the whole of
    the V1 failure. Bad examples are included because an example where the WRONG answer is tempting
    teaches a boundary that a correct example cannot.
    """
    blocks: list[str] = []
    for element in elements or []:
        spec = contract(element)
        if not spec:
            continue
        lines = [f"### {element}", f"WHAT IT IS FOR: {spec.get('purpose','')}",
                 f"USE WHEN: {spec.get('use_when','')}",
                 f"DO NOT USE WHEN: {spec.get('do_not_use_when','')}"]
        fields = spec.get("fields") or {}
        if fields:
            lines.append("FIELDS: " + "; ".join(f"{k} = {v}" for k, v in fields.items()))
        count = spec.get("count") or {}
        if count:
            lines.append(f"HOW MANY: {count.get('min')}-{count.get('max')}, "
                         f"ideally {count.get('ideal')}.")
        for example in (spec.get("good") or [])[:3]:
            lines.append("RIGHT: " + json.dumps(example))
        for example in (spec.get("bad") or [])[:3]:
            why = example.pop("why", "") if isinstance(example, dict) else ""
            lines.append("WRONG: " + json.dumps(example) + (f"  <- {why}" if why else ""))
        for other, note in (spec.get("confusable_with") or {}).items():
            lines.append(f"NOT {other}: {note}")
        for rule in spec.get("rules") or []:
            lines.append(f"RULE: {rule}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
