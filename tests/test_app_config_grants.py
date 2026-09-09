"""Every function that READS app_config must also be GRANTED app_config.

APP_CONFIG_TABLE is set in template.yaml's `Globals`, so all functions get the env var and believe they can
read the document. The IAM grant is per-function. When the two disagree, `platform_config._app_config_doc`
catches the AccessDenied on purpose -- a config read must never break a render -- and returns {}. The failure
is therefore SILENT: `default_favicon_url()` becomes "", `render_favicon_tags` correctly emits nothing rather
than a broken href, and published pages simply have no favicon. Nothing logs, nothing 500s.

That is how the favicon went missing from every published page. This test removes the drift by deriving the
list of readers from the imports rather than restating it, so a new handler that reaches platform_config
fails here until it is granted.
"""
import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = "stripe_link.platform_config"


def _module_paths() -> dict[str, pathlib.Path]:
    mods = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).with_suffix("")
        name = ".".join(rel.parts)
        mods[name.removesuffix(".__init__")] = path
    return mods


def _imports(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken file fails its own tests
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def handlers_reading_app_config() -> set[str]:
    """Handler modules that reach platform_config, directly or through any import chain."""
    mods = _module_paths()
    edges = {name: _imports(path) for name, path in mods.items()}

    def reaches(name: str, seen: set[str]) -> bool:
        if name in seen:
            return False
        seen.add(name)
        for dep in edges.get(name, ()):
            if dep == TARGET or dep.startswith(f"{TARGET}."):
                return True
            if dep in mods and reaches(dep, seen):
                return True
        return False

    return {
        name.split(".")[-1]
        for name in mods
        if name.startswith("handlers.") and reaches(name, set())
    }


class AppConfigGrantTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.blocks = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", self.template, re.M))

    def test_the_env_var_is_global_which_is_why_the_grant_must_be_checked(self):
        # If this ever stops being global the premise changes and the test below is measuring the wrong risk.
        globals_block = re.search(r"^Globals:\n((?:  .*\n|\n)*)", self.template, re.M)
        self.assertIsNotNone(globals_block)
        self.assertIn("APP_CONFIG_TABLE", globals_block.group(1))

    def test_every_handler_that_reads_app_config_is_granted_it(self):
        readers = handlers_reading_app_config()
        self.assertTrue(readers, "import graph found no readers — the walk is broken, not the template")

        by_handler = {}
        for name, body in self.blocks.items():
            match = re.search(r"Handler:\s*handlers\.(\w+)\.", body)
            if match:
                by_handler.setdefault(match.group(1), []).append(name)

        for module in sorted(readers):
            for function in by_handler.get(module, []):
                with self.subTest(function=function, handler=module):
                    self.assertIn(
                        "AppConfigTable", self.blocks[function],
                        f"{function} reads app_config but has no grant for it; the read will fail "
                        "silently and platform values (favicon, legal identity) will vanish",
                    )


if __name__ == "__main__":
    unittest.main()
