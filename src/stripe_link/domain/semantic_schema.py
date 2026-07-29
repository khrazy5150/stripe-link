"""The OfferSemanticModel schema, as code, plus a tiny dependency-free validator (plans/OFFER_SEMANTIC_P4.md,
P4.0 drift close-out).

`OFFER_SEMANTIC_MODEL_SCHEMA` is the SINGLE SOURCE OF TRUTH the runtime validator (`validate_semantic_model`)
enforces AND the one `schemas/OfferSemanticModel.schema.json` mirrors (a test keeps the two identical minus the
human-readable annotations). Before, a hand-written validator and the JSON Schema file could silently disagree;
now the validator *is* the schema, so the only thing to keep in step is the documented file — mechanically, via
that equality test. The repo keeps third-party deps out (src/requirements.txt is empty), so `check_schema` is a
small in-repo interpreter of the JSON-Schema subset this contract uses — never a `jsonschema` dependency.
"""
from typing import Any

_ENTITY = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "name"],
    "properties": {
        "type": {"type": "string", "enum": ["product", "service", "bundle", "listicle", "membership", "lead_generation"]},
        "name": {"type": "string"},
    },
}

OFFER_SEMANTIC_MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts", "interpretation"],
    "properties": {
        "facts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["entities", "taxonomy", "intent", "commerce", "attributes"],
            "properties": {
                "entities": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["primary", "secondary"],
                    "properties": {
                        "primary": {"$ref": "#/$defs/entity"},
                        "secondary": {"type": "array", "items": {"$ref": "#/$defs/entity"}},
                    },
                },
                "brand": {
                    "oneOf": [
                        {"type": "null"},
                        {"type": "object", "additionalProperties": False, "required": ["name"],
                         "properties": {"name": {"type": "string"}}},
                    ]
                },
                "taxonomy": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["hierarchy"],
                    "properties": {"hierarchy": {"type": "array", "items": {"type": "string"}}},
                },
                "intent": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["commercial"],
                    "properties": {
                        "commercial": {"type": "string"},
                        "audience": {"type": "string"},
                        "fulfillment": {"type": "string"},
                        "acquisition": {"type": "string"},
                        "urgency": {"type": "string"},
                    },
                },
                "commerce": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["pricing_model", "purchase_model", "funnel"],
                    "properties": {
                        "pricing_model": {"type": "string"},
                        "purchase_model": {"type": "string"},
                        "funnel": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["landing", "order_bump", "upsells", "downsells"],
                            "properties": {
                                "landing": {"type": "boolean"},
                                "order_bump": {"type": "boolean"},
                                "upsells": {"type": "integer", "minimum": 0},
                                "downsells": {"type": "integer", "minimum": 0},
                            },
                        },
                    },
                },
                "attributes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "value"],
                        "properties": {"name": {"type": "string"}, "value": {}},
                    },
                },
            },
        },
        "interpretation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["key_concepts", "confidence", "source", "version"],
            "properties": {
                "key_concepts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["value", "weight"],
                        "properties": {"value": {"type": "string"}, "weight": {"type": "number"}},
                    },
                },
                "confidence": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1}},
                "source": {"type": "string", "enum": ["deterministic", "ai"]},
                "version": {"type": "integer", "minimum": 1},
                "generated_at": {"type": "integer", "minimum": 0},
            },
        },
    },
    "$defs": {"entity": _ENTITY},
}

# JSON-Schema keywords that are documentation, not validation — the JSON file carries them, the code doesn't.
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "title", "description"})


def _type_ok(instance: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return True


def _resolve_ref(root: dict, ref: str) -> dict:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = (node or {}).get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def check_schema(instance: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """Validate `instance` against the JSON-Schema-subset `schema`; return a list of human-readable error
    strings (empty = valid). Supports the keywords this contract uses: type, required, properties,
    additionalProperties (false | schema), enum, items, oneOf, $ref (into $defs), minimum/maximum. An empty
    schema ({}) accepts anything (used for attribute values)."""
    root = root if root is not None else schema
    if "$ref" in schema:
        schema = _resolve_ref(root, schema["$ref"])
    errors: list[str] = []
    if "oneOf" in schema:
        if not any(not check_schema(instance, sub, root, path) for sub in schema["oneOf"]):
            errors.append(f"{path}: matches none of the allowed shapes")
        return errors
    expected = schema.get("type")
    if expected and not _type_ok(instance, expected):
        return [f"{path}: expected {expected}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']}")
    if expected == "object" and isinstance(instance, dict):
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}.{key}: required")
        for key, value in instance.items():
            if key in properties:
                errors += check_schema(value, properties[key], root, f"{path}.{key}")
            elif additional is False:
                errors.append(f"{path}.{key}: not an allowed property")
            elif isinstance(additional, dict):
                errors += check_schema(value, additional, root, f"{path}.{key}")
    if expected == "array" and isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors += check_schema(item, item_schema, root, f"{path}[{index}]")
    if expected in ("number", "integer") and _type_ok(instance, expected):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
    return errors
