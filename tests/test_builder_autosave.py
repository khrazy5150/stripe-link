"""Every builder action that changes SAVED page state must save it.

The failure this prevents has no error and no visual tell: the edit applies to `builder`, the panel and
preview update, and nothing is written. It looks identical to a saved change until the tenant navigates
away and loses it — and it is INTERMITTENT, because any later action that does auto-save writes the whole
document and picks up the pending change. "It worked last time" is true, which is what makes it expensive
to diagnose.

Reported 2026-09-09 on section removal. Auditing that found two more (section enable/disable and
drag-reorder) which had been shipping the same way.

The check is deliberately narrow: a function that WRITES one of the persisted composition fields must also
call autoSavePage. It is not a general "all builder writes must save" rule, because loading a page writes
`builder` too and must not save.
"""
import pathlib
import re
import unittest

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

# WRITES to fields that end up in the saved page document (see buildBuilderPageDocument). Reads must not
# match: isSectionEnabled reads overrides[key] and has nothing to save, and a first draft that matched it
# reported a false offender.
PERSISTED_WRITES = (
    re.compile(r"builder\.section_order\s*="),
    re.compile(r"builder\.composition\.overrides\[[^\]]+\]\s*="),
    re.compile(r"delete builder\.composition\.overrides\["),
    re.compile(r"builder\.elements\.splice\("),
)


def top_level_functions() -> dict[str, str]:
    """Function name -> body, for functions declared at column 0 in the <script> block."""
    bodies: dict[str, str] = {}
    lines = BUILDER.split("\n")
    for index, line in enumerate(lines):
        match = re.match(r"^(?:async )?function (\w+)\(", line)
        if not match:
            continue
        depth = 0
        collected = []
        for current in lines[index:]:
            collected.append(current)
            depth += current.count("{") - current.count("}")
            if depth <= 0 and len(collected) > 1:
                break
        bodies[match.group(1)] = "\n".join(collected)
    return bodies


class BuilderAutoSaveTests(unittest.TestCase):
    def test_the_audit_finds_functions_to_check(self):
        # Guards the guard: a parser change that matched nothing would make the assertion below vacuous.
        bodies = top_level_functions()
        writers = [name for name, body in bodies.items() if any(w.search(body) for w in PERSISTED_WRITES)]
        self.assertGreaterEqual(len(writers), 3, writers)

    def test_every_writer_of_persisted_state_saves_it(self):
        offenders = []
        for name, body in top_level_functions().items():
            if not any(write.search(body) for write in PERSISTED_WRITES):
                continue
            if "autoSavePage" not in body:
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "these change saved page state without saving it, so the edit looks applied and is lost on "
            "navigating away: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
