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


def _function_bindings(node):
    """Every name this function binds, including inside nested functions and comprehensions."""
    bound = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            bound.add(child.id)
        elif isinstance(child, ast.arg):
            bound.add(child.arg)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name.split(".")[0]) for a in child.names}
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(child.name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            bound.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            bound |= set(child.names)
    return bound


def _module_bindings(tree):
    bound = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__all__"}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name.split(".")[0]) for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for target in ast.walk(node):
                if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                    bound.add(target.id)
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
                    bound.add(inner.id)
                elif isinstance(inner, (ast.Import, ast.ImportFrom)):
                    bound |= {(a.asname or a.name.split(".")[0]) for a in inner.names}
    return bound


class NoFunctionReadsAnotherFunctionsLocalTests(unittest.TestCase):
    """The gap the module-wide check above cannot close, and which has now cost two outages.

    That check asks whether a name is bound ANYWHERE in the module, which is the right
    over-approximation for "never imported at all" and blind to the commoner mistake: a name that exists,
    in a different function.

        persist_checkout_session_completed  ->  user_profiles_repo   (caught by the suite)
        quote_rates                         ->  body                 (reached production, 2026-10-05,
                                                                      and took the Orders page down)

    So this asks the narrower question per top-level function: is every name it READS bound by that
    function, by its module, or by builtins? Nested functions count as part of their parent, because a
    closure legitimately reads the enclosing scope.
    """

    def test_every_function_can_resolve_what_it_reads(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            module = _module_bindings(tree)
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                bound = _function_bindings(node) | module
                for child in ast.walk(node):
                    if (isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                            and child.id not in bound):
                        offenders.append(
                            f"{path.relative_to(SRC.parent)}:{child.lineno}: "
                            f"{node.name}() reads `{child.id}`, which it never binds")
        self.assertEqual(offenders, [], "names bound only in a DIFFERENT function:\n  "
                                        + "\n  ".join(offenders))

    def test_it_catches_the_shape_that_reached_production(self):
        """`quote_rates` read `body`, a name every neighbouring handler binds and it did not."""
        source = "def a(event):\n    body = 1\n    return body\n\ndef b(event):\n    return body\n"
        tree = ast.parse(source)
        module = _module_bindings(tree)
        caught = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                bound = _function_bindings(node) | module
                caught += [c.id for c in ast.walk(node)
                           if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Load)
                           and c.id not in bound]
        self.assertEqual(caught, ["body"])
