"""CORS preflight comes from the API's global `Cors:` block, not from 62 hand-written OPTIONS methods.

Found 2026-09-25 when a deploy failed with "Number of resources, 501, is greater than maximum allowed,
500". The template carried an explicit `Method: OPTIONS` Api event for every path -- each one a
CloudFormation resource -- while `AWS::Serverless::Api` already had a `Cors:` block, which makes SAM
generate the preflight itself.

Verified against the live dev API before and after removing all 62: ten sampled paths answered OPTIONS 200
with `Access-Control-Allow-Origin: *` and the full header list, both times.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")

# The headers the dashboard actually sends. A preflight that omits one of these fails the real request,
# not the preflight, which is a confusing way to find out.
REQUIRED_HEADERS = ("Content-Type", "Authorization", "X-Tenant-Id", "X-Client-Id",
                    "X-Environment", "X-Stripe-Mode")


class GlobalCorsTests(unittest.TestCase):
    def test_the_api_declares_cors_globally(self):
        self.assertIn("Cors:", TEMPLATE, "without this, removing the OPTIONS methods breaks every preflight")

    def test_every_header_the_dashboard_sends_is_allowed(self):
        block = TEMPLATE.split("Cors:", 1)[1][:600]
        allow = re.search(r"AllowHeaders:\s*\"'([^']+)'\"", block)
        self.assertIsNotNone(allow, "AllowHeaders is not declared")
        allowed = {h.strip() for h in allow.group(1).split(",")}
        for header in REQUIRED_HEADERS:
            self.assertIn(header, allowed, f"{header} is sent by the dashboard but not allowed")

    def test_the_methods_the_api_uses_are_allowed(self):
        block = TEMPLATE.split("Cors:", 1)[1][:600]
        methods = re.search(r"AllowMethods:\s*\"'([^']+)'\"", block)
        self.assertIsNotNone(methods)
        allowed = {m.strip() for m in methods.group(1).split(",")}
        for verb in ("GET", "POST", "PUT", "OPTIONS"):
            self.assertIn(verb, allowed)


class NoHandWrittenPreflightTests(unittest.TestCase):
    def test_no_route_declares_its_own_OPTIONS_method(self):
        """Each was a CloudFormation resource bought for nothing, and 62 of them took the stack to the
        500-resource ceiling. Adding one back is how the next deploy fails."""
        offenders = [n for n, line in enumerate(TEMPLATE.splitlines(), 1)
                     if line.strip() == "Method: OPTIONS"]
        self.assertEqual(offenders, [],
                         f"explicit OPTIONS at lines {offenders} — the global Cors block already covers it")

    def test_the_stack_has_headroom_again(self):
        """Roughly two CloudFormation resources per Api event. This is a smoke check on the count, not an
        exact model of what SAM emits -- it exists so a large addition is noticed before a deploy fails."""
        api_events = len(re.findall(r"Type: Api\b", TEMPLATE))
        self.assertLess(api_events, 240,
                        f"{api_events} Api events; the ceiling is 500 CloudFormation resources total")


class HandlersStillAnswerOptionsTests(unittest.TestCase):
    """The handlers keep their `if method == "OPTIONS"` branch.

    Not dead code: SAM's generated preflight is a MOCK integration and never reaches a Lambda, but the
    branch costs nothing and is the difference between a 500 and an empty 200 if a route is ever invoked
    with OPTIONS another way.
    """

    def test_a_sample_of_handlers_still_short_circuit_options(self):
        handlers = ROOT / "src" / "handlers"
        for name in ("orders.py", "shipping.py", "products.py"):
            source = (handlers / name).read_text(encoding="utf-8")
            self.assertIn('"OPTIONS"', source, f"{name} no longer handles OPTIONS at all")


if __name__ == "__main__":
    unittest.main()
