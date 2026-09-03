"""Section order is the composer's decision, and both runtimes must reach the same one.

Order used to have no owner. Visibility did — compose_page decides, the renderer obeys — but the sequence
was whatever the last writer happened to leave in the sections array, and the builder read it straight back
out again as "the tenant's order". That made every page a fixed point: the researched baseline could never
apply to anything, and a newly added section landed wherever the array put it.

Now compose_page orders as well as filters, `page.section_order` records only the tenant's own arrangement,
and its absence means "use the baseline for this goal".

An algorithm cannot be shared across Python and JS, so as with the slug rules the two run the SAME fixtures
and must produce identical output — and both must match expectations hand-written from composition_rules.json
rather than recorded from either implementation.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.composition import (  # noqa: E402
    AUTHORED_PAGE_TYPES, compose_page, order_section_keys, order_sections, section_order_key,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "section_order_cases.json").read_text())
JS_MODULE = ROOT / "dashboard" / "src" / "composables" / "pageComposer.js"
RULES_JSON = ROOT / "src" / "stripe_link" / "composition_rules.json"


def sections_of(case):
    return [{"type": t, "id": i} for t, i in case["sections"]]


class PythonSectionOrderTests(unittest.TestCase):
    def test_order_sections(self):
        for case in FIXTURES["order_sections"]:
            with self.subTest(why=case["why"]):
                got = [s["id"] for s in order_sections(sections_of(case), case["tenant_order"])]
                self.assertEqual(got, case["out"])

    def test_order_section_keys(self):
        for case in FIXTURES["order_section_keys"]:
            with self.subTest(why=case["why"]):
                self.assertEqual(order_section_keys(case["keys"], case["tenant_order"]), case["out"])

    def test_repeatable_types_key_by_id_others_by_type(self):
        self.assertEqual(section_order_key({"type": "content_block", "id": "cb1"}), "cb1")
        self.assertEqual(section_order_key({"type": "author_bio", "id": "ab"}), "author_bio")


class ComposePageOwnsOrderTests(unittest.TestCase):
    """The behaviour the fix exists to produce, exercised through compose_page itself."""

    PAGE = {
        "sections": [
            {"type": "checkout_cta", "id": "cta"},
            {"type": "content_block", "id": "cb"},
            {"type": "author_bio", "id": "ab"},
        ],
    }

    def test_unarranged_page_gets_the_baseline(self):
        got = [s["id"] for s in compose_page({}, self.PAGE)]
        self.assertEqual(got, ["ab", "cb", "cta"], "baseline puts author_bio before content_block, cta last")

    def test_tenant_order_is_obeyed_when_present(self):
        # Keyed the way sections are keyed: content_block is repeatable so it keys by id, the rest by type.
        page = {**self.PAGE, "section_order": ["checkout_cta", "cb", "author_bio"]}
        self.assertEqual([s["id"] for s in compose_page({}, page)], ["cta", "cb", "ab"])

    def test_authored_pages_keep_their_authored_sequence(self):
        # Thank-you / funnel pages are written in code by runtime/upsell_pages.py, not composed from a goal.
        # celebration is `free` and headline is `pinned_top`, so a baseline pass would sink the celebration.
        page = {"sections": [
            {"type": "celebration", "id": "celebration"},
            {"type": "headline", "id": "headline"},
            {"type": "subheadline", "id": "subheadline"},
        ]}
        for page_type in AUTHORED_PAGE_TYPES:
            with self.subTest(page_type=page_type):
                got = [s["id"] for s in compose_page({}, page, page_type)]
                self.assertEqual(got, ["celebration", "headline", "subheadline"])
        # ...and the exemption is load-bearing: composed as a landing page, it really would be reordered.
        composed = [s["id"] for s in compose_page({}, page, "landing")]
        self.assertNotEqual(composed, ["celebration", "headline", "subheadline"])

    def test_head_channel_sections_are_never_dropped(self):
        # structured_data is placement:none, and ordering must not treat that as "not a section" — the JS
        # twin did, which silently stripped the head-channel JSON-LD from every page it saved. Visibility
        # is the separate axis, so this composes under the goal that switches the capability on.
        page = {"goal": "search_seo", "sections": [
            {"type": "structured_data", "id": "sd"}, {"type": "hero", "id": "hero"}]}
        self.assertIn("sd", [s["id"] for s in compose_page({"offer_type": "product"}, page)])


class JsMirrorMatchesPythonTests(unittest.TestCase):
    """Run the SAME fixtures through pageComposer.js and require identical output."""

    def test_js_mirror_agrees(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        source = JS_MODULE.read_text(encoding="utf-8")
        # The module imports composition_rules.json, which bare node will not load without an import
        # attribute. Swap that one line for a filesystem read; everything under test is untouched.
        shimmed = source.replace(
            'import rules from "../../../src/stripe_link/composition_rules.json";',
            'import { readFileSync } from "node:fs";\n'
            f"const rules = JSON.parse(readFileSync({json.dumps(str(RULES_JSON))}, 'utf8'));",
            1,
        )
        self.assertNotIn("composition_rules.json\";", shimmed, "the JSON import moved; update this shim")
        with tempfile.TemporaryDirectory() as tmp:
            module = pathlib.Path(tmp) / "pageComposer.mjs"
            module.write_text(shimmed, encoding="utf-8")
            script = f"""
            import {{ orderSections, orderSectionKeys, sectionOrderKey }} from {json.dumps(str(module))};
            const f = {json.dumps(FIXTURES)};
            console.log(JSON.stringify({{
              order_sections: f.order_sections.map((c) =>
                orderSections(c.sections.map(([type, id]) => ({{ type, id }})), c.tenant_order).map((s) => s.id)),
              order_section_keys: f.order_section_keys.map((c) => orderSectionKeys(c.keys, c.tenant_order)),
              keys: [sectionOrderKey({{type: "content_block", id: "cb1"}}), sectionOrderKey({{type: "author_bio", id: "ab"}})],
            }}));
            """
            proc = subprocess.run(
                [node, "--input-type=module", "-e", script],
                capture_output=True, text=True, cwd=str(ROOT), timeout=60,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        js = json.loads(proc.stdout)

        # identical to Python...
        self.assertEqual(js["order_sections"],
                         [[s["id"] for s in order_sections(sections_of(c), c["tenant_order"])]
                          for c in FIXTURES["order_sections"]])
        self.assertEqual(js["order_section_keys"],
                         [order_section_keys(c["keys"], c["tenant_order"]) for c in FIXTURES["order_section_keys"]])
        self.assertEqual(js["keys"], ["cb1", "author_bio"])
        # ...and both match the fixtures' declared expectations, not merely each other.
        self.assertEqual(js["order_sections"], [c["out"] for c in FIXTURES["order_sections"]])
        self.assertEqual(js["order_section_keys"], [c["out"] for c in FIXTURES["order_section_keys"]])


if __name__ == "__main__":
    unittest.main()
