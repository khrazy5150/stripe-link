"""Every sub-resource a handler branches on must be a path API Gateway actually routes.

This is the "two things that must agree, with nothing forcing them to" shape, in its most
expensive form: the handler code is correct, the tests pass, the deploy succeeds, and the feature
is simply unreachable because API Gateway returns 403/404 before the Lambda is ever invoked. There
is no error anywhere to find -- the request does not reach the code you would think to debug.

It cost a real bug on 2026-09-09: `POST /sites/{site_id}/social/check` was implemented, unit
tested, deployed and verified present in the deployed package, and still did nothing, because no
Api event declared the path.

The check is deliberately one-directional. A registered path with no handler branch is usually
fine (the handler dispatches on method, or handles the bare resource); a handler branch with no
registered path is always dead code.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "template.yaml"
HANDLERS = ROOT / "src" / "handlers"


def registered_paths() -> set[str]:
    return set(re.findall(r"^\s*Path:\s*(\S+)\s*$", TEMPLATE.read_text(encoding="utf-8"), re.M))


# Matches resource.endswith("/x") and resource.endswith(("/x", "/y")) -- and stops at the closing
# paren of THAT call, so it cannot run on into a neighbouring path.rstrip("/") and mistake its
# argument for a route. (It did exactly that on the first draft.)
_ENDSWITH = re.compile(r'resource\.endswith\(\s*\(?\s*((?:"[^"]*"\s*,?\s*)+)\)?\s*\)')


def branch_suffixes(source: str) -> set[str]:
    """Every literal passed to resource.endswith(...), including the tuple form."""
    found: set[str] = set()
    for call in _ENDSWITH.findall(source):
        found.update(re.findall(r'"([^"]+)"', call))
    # A bare "/" is not a sub-resource; it is a suffix of every path and says nothing.
    return {s for s in found if s.startswith("/") and len(s) > 1}


class RouterPathsAreRoutedTests(unittest.TestCase):
    def test_every_branch_has_a_route(self):
        paths = registered_paths()
        missing = []
        for handler in sorted(HANDLERS.glob("*.py")):
            source = handler.read_text(encoding="utf-8")
            for suffix in sorted(branch_suffixes(source)):
                if not any(p.endswith(suffix) for p in paths):
                    missing.append(f"{handler.name} branches on '{suffix}' but no Api event declares it")
        self.assertEqual(
            missing, [],
            "unreachable route(s) — the handler would never be invoked for these:\n  "
            + "\n  ".join(missing),
        )

    def test_the_check_can_actually_fail(self):
        # A guard that cannot fail is not a guard. Prove the matcher would catch a missing route.
        self.assertEqual(branch_suffixes('if resource.endswith("/social/check"):'), {"/social/check"})
        self.assertFalse(any(p.endswith("/nonexistent/route") for p in registered_paths()))


if __name__ == "__main__":
    unittest.main()
