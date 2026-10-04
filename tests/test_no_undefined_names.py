"""Every name a module reads must be one it can actually resolve.

An upsell wrote its order and then silently failed to write its LEDGER entry, for eight days, because
`handlers/upsell.py` called `os.environ` without importing `os`:

    [upsell] ledger entry not recorded: NameError: name 'os' is not defined

Two things hid it. The line sits behind `ledger_repo or (... if os.environ.get(...) ...)`, and every test
passes `ledger_repo` explicitly -- so the branch holding the defect was the one branch tests never took.
And the writer is deliberately best-effort, because a bookkeeping append must not undo a sale that has
already moved money, so `except Exception` turned a missing import into a log line nobody was reading.

That combination -- a rarely-taken branch inside a deliberately-silent handler -- is not rare in this
codebase, and it is exactly what a NameError needs to survive. Python raises these at call time rather
than import time, so neither the test suite nor the deploy can be relied on to surface them; walking the
AST can. The same scan immediately found a second live one (`ai_generation_events_repository` used in
`handlers/ai_generate.py` and never imported, behind the identical `repo or factory()` shape).
"""
import ast
import builtins
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _bound_names(tree):
    """Every name the module could plausibly bind, over-approximated on purpose.

    Collected from the WHOLE tree rather than per-scope: a name bound in any function counts as bound
    everywhere. That cannot find a name used before assignment, which is deliberate -- the point is to
    catch names with no binding at all, with no false positives to train anyone to ignore the result.
    """
    bound = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__all__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound |= {(alias.asname or alias.name.split(".")[0]) for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            bound |= {(alias.asname or alias.name) for alias in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound |= set(node.names)
    return bound


class NoUndefinedNamesTests(unittest.TestCase):
    def test_no_module_reads_a_name_it_cannot_resolve(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            bound = _bound_names(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                        and node.id not in bound):
                    offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}: {node.id}")
        self.assertEqual(offenders, [], "names used but never imported or bound:\n  "
                                        + "\n  ".join(offenders))

    def test_the_two_it_was_written_for_stay_imported(self):
        # Named explicitly, so deleting either import fails with the reason rather than a bare diff.
        self.assertIn("import os", (SRC / "handlers" / "upsell.py").read_text().split("\n\n", 1)[0])
        self.assertIn("ai_generation_events_repository",
                      (SRC / "handlers" / "ai_generate.py").read_text().split("def ", 1)[0])
