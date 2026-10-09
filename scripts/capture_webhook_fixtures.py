"""Turn stored production webhook payloads into scrubbed test fixtures.

**Why these and not hand-written ones.** Every hand-written Stripe fixture in this repo encodes what we
BELIEVED the payload looked like, and four separate defects came from that belief being out of date on
`2026-05-27.preview`: `invoice.subscription` removed, `subscription_details` moved under `parent`,
`line.price` replaced by `line.pricing.price_details`, and `charge.refunds` absent from the payload
entirely. Each was found by a real buyer's money going somewhere wrong, because the suite was green
against a world that no longer existed.

`jb-webhook-events-{env}` already keeps the real thing. This lifts those payloads into fixtures so the
tests argue with Stripe's actual output instead of our memory of it.

**What is preserved, because it is the point:** every key's PRESENCE and ABSENCE, every type, every
nesting depth, every amount. A fixture that quietly grew a `refunds` key would be worthless.

**What is replaced:** anything identifying. Values are swapped by KEY NAME rather than by path -- there
are 512 distinct paths and a path list would rot. Identifiers are mapped consistently, so a charge that
referenced a payment intent still references the same (fake) one and cross-reference assertions hold.

Usage:
    python3 scripts/capture_webhook_fixtures.py --env dev [--out tests/fixtures/stripe_events]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

# Key names whose VALUE identifies a person or their card. Matched case-insensitively on the leaf key.
SENSITIVE_KEYS = {
    "email", "customer_email", "receipt_email", "name", "customer_name", "individual_name",
    "business_name", "account_name", "display_name", "nickname", "phone", "customer_phone",
    "line1", "line2", "city", "state", "postal_code", "from_postal_code", "to_postal_code",
    "last4", "receipt_url", "receipt_number", "statement_descriptor", "calculated_statement_descriptor",
    "statement_descriptor_suffix", "description", "customer_reference", "fingerprint", "network_transaction_id",
}
# `country` stays: it changes tax and shipping behaviour, and is not identifying on its own.

# Stripe id prefixes, remapped consistently so references between objects survive.
_ID_PREFIXES = "acct|cus|pi|ch|re|in|sub|cs|evt|price|prod|txn|pm|fee|si|il|seti|card|ba|tok"
ID_RE = re.compile(rf"^({_ID_PREFIXES})_[A-Za-z0-9]+$")
# An id EMBEDDED in a longer string -- Stripe's hosted invoice and PDF links carry the account id plus a
# base64 token that decodes back to it, so matching only whole-string ids left the real account in the
# fixtures. Caught by grepping the output for a known id rather than by trusting the regex.
EMBEDDED_ID_RE = re.compile(rf"\b({_ID_PREFIXES})_[A-Za-z0-9]{{8,}}")


def _fake_id(value: str) -> str:
    prefix = value.split("_", 1)[0]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def scrub(node, *, key: str = ""):
    """Recursively replace identifying values, preserving shape, type and key presence."""
    if isinstance(node, dict):
        return {k: scrub(v, key=k) for k, v in node.items()}
    if isinstance(node, list):
        return [scrub(v, key=key) for v in node]
    if isinstance(node, str):
        if ID_RE.match(node):
            return _fake_id(node)
        if node.startswith("http") and EMBEDDED_ID_RE.search(node):
            return "https://example.test/redacted"
        if EMBEDDED_ID_RE.search(node):
            return EMBEDDED_ID_RE.sub(lambda m: _fake_id(m.group(0)), node)
        if key.lower() in SENSITIVE_KEYS and node:
            # Keep the SHAPE of the string -- a parser that cares about an "@" or a digit count still sees one.
            if "@" in node:
                return "buyer@example.test"
            if node.isdigit():
                return "0" * len(node)
            if node.startswith("http"):
                return "https://example.test/redacted"
            return "REDACTED"
        return node
    return node


def _flat(value):
    """DynamoDB attribute value -> plain Python."""
    (kind, raw), = value.items()
    if kind == "M":
        return {k: _flat(v) for k, v in raw.items()}
    if kind == "L":
        return [_flat(v) for v in raw]
    if kind == "N":
        return int(raw) if "." not in raw else float(raw)
    if kind == "BOOL":
        return raw
    if kind == "NULL":
        return None
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="dev")
    parser.add_argument("--out", default="tests/fixtures/stripe_events")
    parser.add_argument("--project-prefix", default="jb")
    args = parser.parse_args()

    table = f"{args.project_prefix}-webhook-events-{args.env}"
    raw = subprocess.run(
        ["aws", "dynamodb", "scan", "--table-name", table, "--output", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = [{k: _flat(v) for k, v in item.items()} for item in json.loads(raw)["Items"]]

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # One fixture per (event_type, distinct shape). Several deliveries of the same type teach nothing extra,
    # so keep the first of each type plus any whose top-level key set differs -- a changed shape is exactly
    # what these exist to catch.
    seen_shapes: dict[str, set] = {}
    written = []
    for row in sorted(rows, key=lambda r: r.get("processed_at") or 0):
        event_type = str(row.get("event_type") or "unknown")
        payload = row.get("payload") or {}
        obj = ((payload.get("data") or {}).get("object")) or {}
        shape = frozenset(obj.keys())
        if shape in seen_shapes.setdefault(event_type, set()):
            continue
        seen_shapes[event_type].add(shape)
        index = len(seen_shapes[event_type])
        name = f"{event_type.replace('.', '_')}{'' if index == 1 else f'_{index}'}.json"
        (out_dir / name).write_text(json.dumps(scrub(payload), indent=2, sort_keys=True) + "\n")
        written.append((name, event_type, len(obj)))

    for name, event_type, fields in written:
        print(f"   {name:44s} {event_type:34s} {fields} fields")
    print(f"\n   {len(written)} fixtures -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
