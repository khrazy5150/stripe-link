"""Parity between the Python slug rules and their JS mirror.

The recurring defect class in this codebase is "two things that must agree, with nothing forcing them to"
— the offer label vs its slug, the preview vs the published page, a marquee keyframe defined twice.
`composition_rules.json` solves it for composition by making both runtimes read ONE file. An algorithm
cannot be shared that way, so the next best thing is a shared FIXTURE set both suites execute.

If node is unavailable the JS half is skipped rather than failing — but the Python half still runs, so the
fixtures always assert something.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.slugs import sanitize_slug, slug_tokens, unique_slug  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "slug_cases.json").read_text())
JS_MODULE = ROOT / "dashboard" / "src" / "composables" / "slugs.js"


class PythonSlugRulesTests(unittest.TestCase):
    def test_sanitize(self):
        for case in FIXTURES["sanitize"]:
            with self.subTest(value=case["in"]):
                self.assertEqual(sanitize_slug(case["in"]), case["out"])

    def test_unique(self):
        for case in FIXTURES["unique"]:
            with self.subTest(desired=case["desired"], taken=case["taken"]):
                self.assertEqual(unique_slug(case["desired"], set(case["taken"])), case["out"])

    def test_tokens(self):
        for case in FIXTURES["tokens"]:
            with self.subTest(value=case["in"]):
                self.assertEqual(slug_tokens(case["in"], case["limit"]), case["out"])


class JsMirrorMatchesPythonTests(unittest.TestCase):
    """Run the SAME fixtures through the JS module and require identical output."""

    def test_js_mirror_agrees(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = f"""
        import {{ sanitizeSlug, slugTokens, uniqueSlug }} from {json.dumps(str(JS_MODULE))};
        const f = {json.dumps(FIXTURES)};
        console.log(JSON.stringify({{
          sanitize: f.sanitize.map((c) => sanitizeSlug(c.in)),
          unique: f.unique.map((c) => uniqueSlug(c.desired, c.taken)),
          tokens: f.tokens.map((c) => slugTokens(c.in, c.limit)),
        }}));
        """
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        js = json.loads(proc.stdout)

        self.assertEqual(js["sanitize"], [sanitize_slug(c["in"]) for c in FIXTURES["sanitize"]])
        self.assertEqual(js["unique"], [unique_slug(c["desired"], set(c["taken"])) for c in FIXTURES["unique"]])
        self.assertEqual(js["tokens"], [slug_tokens(c["in"], c["limit"]) for c in FIXTURES["tokens"]])
        # and both must match the fixtures' declared expectations, not merely each other
        self.assertEqual(js["sanitize"], [c["out"] for c in FIXTURES["sanitize"]])
        self.assertEqual(js["unique"], [c["out"] for c in FIXTURES["unique"]])


if __name__ == "__main__":
    unittest.main()
