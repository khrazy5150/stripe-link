"""Which environment variables can each Lambda actually reach?

`plans/TRANSFORM_BUDGET.md` Phase 1. The template puts 84 environment variables in `Globals`, so all 74
functions carry all 84 — 4,887 bytes each, 362,538 in total, **36% of the entire template** and the
single reason the stack sits at CloudFormation's 1,000,000-byte transform ceiling. Phase 2 moves them
per-function; this module is the guard that has to exist first, because **a missing env var is a RUNTIME
failure, not a deploy failure.** A function that loses `PUBLIC_CHECKOUT_BASE_URL` deploys perfectly and
breaks the first buyer who reaches it.

**It over-approximates on purpose, and that is the whole difference from `test_table_grants.py`.**

That test asks "does this handler reach this table?" to demand an IAM grant, and it gates two of its
three signals on the module having a single entry point — because in a module with several, a factory call
somewhere says nothing about which function reaches it. Under-reporting there means a missing grant goes
unnoticed; annoying, and the test still catches most.

Here the bias has to point the other way. Under-reporting means Phase 2 deletes a variable a function
genuinely reads, and nothing fails until a request arrives. So:

* every function in a module inherits everything the MODULE reaches, entry points be damned;
* imports are followed TRANSITIVELY — a handler that imports `domain/a` which imports `domain/b` reaches
  what `b` reads, and `handlers/fee_reconciliation` importing `handlers/stripe_webhook` really does
  inherit its 22 tables;
* parsed with `ast`, not regex, so `from x import y` inside a function body (which this codebase does
  constantly, for cold-start cost) is seen exactly like a top-level import.

The cost of over-approximating is a few bytes of env var that a function did not strictly need. The cost
of under-approximating is an outage. There is no version of this worth being clever about.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# `os.environ.get("X")`, `os.environ["X"]`, `environ.get("X")` — the literal shape.
_ENV_CALL = re.compile(r'(?:os\.)?environ(?:\.get)?\(?\[?\s*["\'](\w+)["\']')

# NOT EVERY READ NAMES ITS VARIABLE AT THE CALL SITE, and the ones that do not are exactly the reads
# whose absence would be a silent outage. Three real shapes in this codebase:
#
#   handlers/admin_delete_test_data.py   for env_name in _PK_TABLES: os.environ.get(env_name, "")
#   handlers/sites.py                    _ips("CLOUDFLARE_APEX_IPV4")   # literal through a local fn
#   stripe_link/stripe_platform_secrets  os.environ.get(f"STRIPE_SECRET_KEY_{mode.upper()}")
#
# So any bare SCREAMING_SNAKE string literal in a file counts as a candidate name, and an f-string read
# contributes its literal PREFIX, which then matches every declared variable beginning with it. Both
# over-collect wildly -- and harmlessly, because `required()` intersects the result with the names the
# template actually declares. Over-collecting costs a few bytes of env var; missing one of these costs an
# outage in a dev-only wipe tool or, worse, in Stripe credential resolution.
_BARE_NAME = re.compile(r'["\']([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)["\']')
_ENV_FSTRING_PREFIX = re.compile(r'(?:os\.)?environ(?:\.get)?\(?\[?\s*f["\']([A-Z][A-Z0-9_]*_)\{')


def _module_name(path: pathlib.Path) -> str:
    """`src/stripe_link/domain/cogs.py` -> `stripe_link.domain.cogs`."""
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def _source_modules() -> dict[str, pathlib.Path]:
    return {_module_name(p): p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts}


REPOSITORIES = SRC / "stripe_link" / "repositories"


def _env_reads(node: ast.AST) -> set[str]:
    """Env var names read anywhere inside this AST node, literal or indirect."""
    if node is None:
        return set()
    return _names_in(ast.unparse(node))


def _names_in(source: str) -> set[str]:
    """Every env var name this source could read: literal calls, bare names, f-string prefixes."""
    found = set(_ENV_CALL.findall(source))
    found |= set(_BARE_NAME.findall(source))
    found |= {f"{prefix}*" for prefix in _ENV_FSTRING_PREFIX.findall(source)}
    return found


def factory_envs() -> dict[str, set[str]]:
    """repository factory name -> the env vars ITS OWN BODY reads.

    **This is what stops the analysis collapsing into "everything".** `repositories/documents.py` reads
    39 table env vars, one inside each of its 53 factory functions, and 72 modules import it. Treating an
    import of that module as reaching all 39 is the error `plans/TRANSFORM_BUDGET.md` recorded against an
    earlier estimate -- *"importing it is not calling them"* -- and it is what pushed the first run of
    this module to a median of 53 of 84.

    So a factory's variables are attributed to whoever CALLS it, never to whoever imports the module that
    defines it.
    """
    out: dict[str, set[str]] = {}
    for path in sorted(REPOSITORIES.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                envs = _env_reads(node)
                if envs:
                    out.setdefault(node.name, set()).update(envs)
            elif isinstance(node, ast.ClassDef):
                # A repository CLASS whose methods read env vars: attributed to the class name, which is
                # what a caller names when instantiating it.
                envs = _env_reads(node)
                if envs:
                    out.setdefault(node.name, set()).update(envs)
    return out


def direct_envs(path: pathlib.Path, *, factories: dict[str, set[str]] | None = None) -> set[str]:
    """Env vars this file reads ON ITS OWN BEHALF.

    For a repositories module that means module-level reads only: everything inside a factory belongs to
    the factory's callers (see `factory_envs`). For every other file it is simply every read in it.
    """
    source = path.read_text(encoding="utf-8")
    if factories is None or REPOSITORIES not in path.parents:
        return _names_in(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover
        return _names_in(source)
    inside_definitions: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inside_definitions |= _env_reads(node)
    return _names_in(source) - inside_definitions


def called_names(path: pathlib.Path) -> set[str]:
    """Every name this file CALLS, by bare name or as an attribute.

    `orders_repository(...)` and `documents.orders_repository(...)` are the same reach, and this codebase
    writes both.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            out.add(func.id)
        elif isinstance(func, ast.Attribute):
            out.add(func.attr)
    return out


def imported_modules(path: pathlib.Path, known: set[str]) -> set[str]:
    """The project modules this file imports, including imports inside function bodies.

    `ast` rather than a regex because the deferred-import style here is pervasive -- a handler's real
    dependencies are mostly written inside the functions that need them, to keep cold start down, and a
    top-level-only parse would miss nearly all of them.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a file that will not parse cannot ship anyway
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(_candidates(alias.name, known))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import; this codebase uses absolute ones
                continue
            base = node.module or ""
            found.update(_candidates(base, known))
            # `from stripe_link.domain import cogs` names the module in the alias, not the base.
            for alias in node.names:
                found.update(_candidates(f"{base}.{alias.name}", known))
    return found


def _candidates(name: str, known: set[str]) -> set[str]:
    """`name` itself when it is a module, plus its package `__init__` if there is one."""
    out = set()
    if name in known:
        out.add(name)
    package = f"{name}.__init__"
    if package in known:
        out.add(package)
    return out


def reach() -> dict[str, set[str]]:
    """module -> every env var it or anything it imports can read. Transitive closure.

    Two kinds of edge, and the second is what keeps the answer useful:

    * **imports** — a handler reaches whatever the modules it imports read;
    * **calls** — a module that CALLS a repository factory reaches that factory's variables, wherever the
      factory is defined. Without this the import edge alone would hand all 39 of `documents.py`'s table
      variables to all 72 of its importers.
    """
    modules = _source_modules()
    known = set(modules)
    factories = factory_envs()
    own: dict[str, set[str]] = {}
    for name, path in modules.items():
        envs = direct_envs(path, factories=factories)
        for called in called_names(path):
            envs |= factories.get(called, set())
        own[name] = envs
    edges = {name: imported_modules(path, known) for name, path in modules.items()}

    # Iterate to a fixed point. Cycles are real here (handlers import each other), so a recursive walk
    # would need its own visited set anyway; this is the same thing without the stack.
    result = {name: set(envs) for name, envs in own.items()}
    changed = True
    while changed:
        changed = False
        for name, deps in edges.items():
            before = len(result[name])
            for dep in deps:
                result[name] |= result.get(dep, set())
            if len(result[name]) != before:
                changed = True
    return result


def template_functions(template: str) -> dict[str, str]:
    """Lambda logical id -> the handler module it runs (`handlers.checkout`)."""
    blocks = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", template, re.M))
    out = {}
    for name, body in blocks.items():
        match = re.search(r"Handler:\s*(handlers\.\w+)\.", body)
        if match:
            out[name] = match.group(1)
    return out


def global_env_names(template: str) -> set[str]:
    """Every env var name declared in `Globals`."""
    block = re.search(r"^Globals:\n((?:  .*\n|\n)*)", template, re.M)
    if not block:
        return set()
    variables = re.search(r"^    Environment:\n      Variables:\n((?:        .*\n|\n)*)",
                          block.group(1), re.M)
    if not variables:
        return set()
    return set(re.findall(r"^        (\w+):", variables.group(1), re.M))


def declared_env_names(template: str) -> set[str]:
    """Every env var name the template declares ANYWHERE -- `Globals` plus every function block.

    `global_env_names` alone was the right question until Phase 2 moved the 42 table names onto the
    functions that reach them. After that it returns the 42 that stayed, and intersecting the reach
    analysis with it would quietly stop asking about every table in the stack.
    """
    names = set(global_env_names(template))
    for function in template_functions(template):
        names |= function_env_names(template, function)
    return names


def function_env_names(template: str, function: str) -> set[str]:
    """Env var names declared on ONE function.

    Stops at the first line that is not a variable, which matters more than it looks: the first version
    matched `^          (\\w+):` across the whole remainder of the block and happily collected `Type` and
    `Properties` out of the function's Events, because they sit at the same indentation. That
    over-collects into the set of variables the guard considers AVAILABLE -- so a function could be short
    a real variable and the guard would call it declared. A guard that fails open is worse than no guard.
    """
    block = re.search(r"^  " + function + r":\n((?:    .*\n|\n)*)", template, re.M)
    if not block:
        return set()
    start = re.search(r"^      Environment:\n        Variables:\n", block.group(1), re.M)
    if not start:
        return set()
    names = set()
    for line in block.group(1)[start.end():].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^          (\w+):", line)
        if not match:
            break  # indentation dropped out of the Variables block
        names.add(match.group(1))
    return names


def required(function_module: str, reachable: dict[str, set[str]], declared: set[str]) -> set[str]:
    """What this function needs, limited to names the template actually declares.

    A module reads plenty of env vars the template never sets (`AWS_REGION`, test shims, optional
    switches that default when absent). Those are not Phase 2's business: the question is only which of
    the DECLARED variables must keep being declared for this function.
    """
    reached = reachable.get(function_module, set())
    # Expand the f-string prefixes recorded as `PREFIX_*`. `STRIPE_SECRET_KEY_TEST` never appears as a
    # literal anywhere, so without this a function resolving Stripe credentials would be stripped of the
    # only variable that holds them.
    concrete = {name for name in reached if not name.endswith("*")}
    for wildcard in (name for name in reached if name.endswith("*")):
        prefix = wildcard[:-1]
        concrete |= {name for name in declared if name.startswith(prefix)}
    return concrete & declared
