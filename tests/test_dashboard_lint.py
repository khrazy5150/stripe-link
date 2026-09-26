"""The dashboard has a linter, and the rule that cost nine days gates the build.

`Products.vue` called `productStore.fetchFull(row)` while declaring `const store = useProductsStore()`.
Editing ANY product failed with "productStore is not defined". Shipped 2026-09-01, reported 2026-09-10 --
nine days, because nothing could catch it: Vite does not resolve identifiers inside a function body, so
the build succeeded, and no test exercises the dashboard's JavaScript.

`no-undef` is the rule that exists for exactly that, and it had never run against this codebase.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"

# First run found 88. The 41 `no-unused-vars` were all genuinely dead and are gone -- ~100 lines across 13
# files. What remains is ONE pattern: 46 `vue/no-mutating-props`, children writing to a prop object their
# parent owns. That is a coherent design choice (form-field components editing a passed object), not 46
# independent mistakes, and unpicking it means adopting `defineModel` across the product, offer and
# landing editors -- a refactor with real regression risk on the most complex screens in the app.
#
# Pinned so it cannot grow. Lower it when the refactor happens; raising it should be deliberate.
WARNING_CEILING = 46


def _npx(*args, cwd=DASHBOARD):
    return subprocess.run([shutil.which("npx") or "npx", *args],
                          capture_output=True, text=True, cwd=str(cwd), timeout=300)


class ConfigTests(unittest.TestCase):
    CONFIG = (DASHBOARD / "eslint.config.js").read_text(encoding="utf-8")
    PACKAGE = json.loads((DASHBOARD / "package.json").read_text(encoding="utf-8"))

    def test_the_config_exists_at_all(self):
        self.assertTrue((DASHBOARD / "eslint.config.js").exists())

    def test_no_undef_is_an_ERROR_not_a_warning(self):
        """A warning would not have saved the nine days -- nobody reads a warning in a passing build."""
        self.assertIn('"no-undef": "error"', self.CONFIG)

    def test_the_BUILD_runs_it(self):
        """The entry's requirement: a broken identifier fails the build rather than the browser."""
        self.assertIn("eslint", self.PACKAGE["scripts"]["build"])

    def test_there_is_a_lint_script_to_run_on_its_own(self):
        self.assertIn("lint", self.PACKAGE["scripts"])

    def test_eslint_is_a_DEV_dependency_not_a_shipped_one(self):
        self.assertIn("eslint", self.PACKAGE.get("devDependencies", {}))
        self.assertNotIn("eslint", self.PACKAGE.get("dependencies", {}))

    def test_style_rules_are_not_turned_on(self):
        """Formatting findings on an existing codebase train everyone to ignore the output, and the
        output is the whole point. This config catches errors, not taste."""
        for noisy in ("indent", "quotes", "semi", "comma-dangle"):
            self.assertNotIn(f'"{noisy}"', self.CONFIG, f"{noisy} is a style rule, not an error")


class ItActuallyRunsTests(unittest.TestCase):
    """Asserting on the config file proves nothing about whether eslint can parse this codebase."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("npx") or not (DASHBOARD / "node_modules" / "eslint").exists():
            raise unittest.SkipTest("eslint is not installed")
        cls.result = _npx("eslint", ".", "-f", "json")
        try:
            cls.report = json.loads(cls.result.stdout or "[]")
        except json.JSONDecodeError:
            raise unittest.SkipTest(f"eslint produced no JSON: {cls.result.stderr[:200]}")

    def _by_rule(self, severity):
        return [m for f in self.report for m in f["messages"] if m.get("severity") == severity]

    def test_the_codebase_has_NO_undefined_identifiers(self):
        offenders = [f"{f['filePath'].rsplit('/', 1)[-1]}:{m['line']} {m['message']}"
                     for f in self.report for m in f["messages"] if m.get("ruleId") == "no-undef"]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_nothing_fails_to_PARSE(self):
        fatal = [f["filePath"] for f in self.report for m in f["messages"] if m.get("fatal")]
        self.assertEqual(fatal, [])

    def test_there_are_no_errors_at_all_so_the_build_is_not_already_broken(self):
        errors = [f"{f['filePath'].rsplit('/', 1)[-1]}:{m['line']} {m.get('ruleId')}"
                  for f in self.report for m in f["messages"] if m.get("severity") == 2]
        self.assertEqual(errors, [], "\n".join(errors))

    def test_no_unused_names_remain(self):
        """All 41 were dead code and were removed. A new one is a rename half-done or an orphaned import,
        and it should be noticed while it is one rather than forty."""
        offenders = [f"{f['filePath'].rsplit('/', 1)[-1]}:{m['line']} {m['message']}"
                     for f in self.report for m in f["messages"] if m.get("ruleId") == "no-unused-vars"]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_known_warnings_do_not_quietly_grow(self):
        count = len(self._by_rule(1))
        self.assertLessEqual(
            count, WARNING_CEILING,
            f"{count} warnings, ceiling {WARNING_CEILING}. Fix them or raise the ceiling deliberately.")


if __name__ == "__main__":
    unittest.main()
