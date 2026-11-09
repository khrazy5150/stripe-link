"""Every route the dashboard calls must exist in the API, with the verb it uses.

WHY THIS EXISTS. The Create Invoice modal sent `POST /invoices` for months. The API exposes GET and PUT
on that collection and no POST, so API Gateway matched no route and answered 403
`MissingAuthenticationToken` -- a response that carries NO CORS header. The browser therefore blocked it
and `fetch` rejected with the bare TypeError "Failed to fetch".

Three things conspired to hide it:

  * the CORS preflight PASSES, because the OPTIONS mock advertises POST in `access-control-allow-methods`
    whether or not a POST method exists -- so the failure only appears on the real request;
  * "Missing Authentication Token" is API Gateway's wording for "no such route", which reads as an auth
    problem and sends you to the wrong place entirely;
  * the handler itself accepts `{"POST", "PUT"}`, so every server-side test passed. Nothing in Python
    could see the gap, because the gap was between the client and the template.

The bug lives in neither layer, which is why only a test that reads BOTH can catch it.
"""
import re
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.yaml"
DASHBOARD = ROOT / "dashboard" / "src"


def api_routes():
    """(path, METHOD) for every `Type: Api` event in the template."""
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    routes = set()
    for i, line in enumerate(lines):
        match = re.match(r"\s*Path:\s*(\S+)\s*$", line)
        if not match:
            continue
        for ahead in lines[i + 1:i + 4]:
            verb = re.match(r"\s*Method:\s*(\S+)\s*$", ahead)
            if verb:
                routes.add((match.group(1), verb.group(1).upper()))
                break
    return routes


def _segments(path):
    return [s for s in path.split("?")[0].strip("/").split("/") if s]


def _matches(client, route):
    """One client segment against one route segment. A `*` (an interpolated `${...}`) matches any single
    literal, and a route's own `{param}` matches anything -- but a wildcard is ONE segment, never a tail,
    so /a/* cannot quietly satisfy /a/b/c."""
    if len(client) != len(route):
        return False
    return all(c == "*" or r.startswith("{") or c == r for c, r in zip(client, route))


def dashboard_calls():
    pattern = re.compile(r"""apiRequest\(\s*(["'`])([^"'`]+)\1\s*(?:,\s*\{(.*?)\})?""", re.S)
    for path_obj in sorted(DASHBOARD.rglob("*.js")) + sorted(DASHBOARD.rglob("*.vue")):
        source = path_obj.read_text(encoding="utf-8")
        for match in pattern.finditer(source):
            raw, options = match.group(2), match.group(3) or ""
            if not raw.startswith("/"):
                continue
            verb = re.search(r"method:\s*[\"'`](\w+)", options)
            segments = ["*" if ("${" in s or s.startswith("{")) else s for s in _segments(raw)]
            yield (path_obj.relative_to(ROOT), source[:match.start()].count("\n") + 1, raw,
                   (verb.group(1) if verb else "GET").upper(), segments)


class EveryDashboardCallHasARouteTests(unittest.TestCase):
    def test_the_template_parses(self):
        """A parser that silently finds nothing would make this whole file vacuously green."""
        routes = api_routes()
        self.assertGreater(len(routes), 150, "template parse returned implausibly few routes")
        self.assertIn(("/invoices", "GET"), routes)

    def test_every_call_matches_a_route_with_its_verb(self):
        routes = api_routes()
        unmatched = []
        for file, line, raw, verb, segments in dashboard_calls():
            # A path whose FIRST segment is interpolated is a generic helper (composables/indexedList)
            # and names no single route; there is nothing here to check it against.
            if segments and segments[0] == "*":
                continue
            if not any((v == verb or v == "ANY") and _matches(segments, _segments(p)) for p, v in routes):
                unmatched.append(f"{verb} {raw}  ({file}:{line})")
        self.assertEqual(unmatched, [], "dashboard calls with no matching API route:\n  " +
                         "\n  ".join(unmatched))

    def test_the_check_can_actually_fail(self):
        """The regression itself. Without this, a matcher that returns True for everything passes the
        test above and the next wrong verb ships exactly as this one did."""
        routes = api_routes()

        def exposed(verb):
            return any((v == verb or v == "ANY") and _matches(["invoices"], _segments(p))
                       for p, v in routes)

        self.assertTrue(exposed("PUT"), "PUT /invoices is the save route")
        self.assertTrue(exposed("GET"))
        self.assertFalse(exposed("POST"), "no POST on the /invoices collection -- that was the bug")

    def test_a_wildcard_does_not_swallow_a_longer_path(self):
        self.assertTrue(_matches(["shipping", "*"], ["shipping", "pickups"]))
        self.assertFalse(_matches(["shipping", "*"], ["shipping", "a", "b"]))
        self.assertFalse(_matches(["invoices"], ["invoices", "{invoice_id}"]))


if __name__ == "__main__":
    unittest.main()
