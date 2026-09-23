"""Every handler that names a table env var must be GRANTED that table.

The `*_TABLE` env vars live in template.yaml's `Globals`, so every function receives every table name and
therefore believes every table is available to it. The IAM grant is per-function. When the two disagree the
code still takes the branch -- `os.environ.get("BOOKING_CREDITS_TABLE")` is truthy, so the repository is
built and called -- and DynamoDB answers AccessDeniedException at the point of use, not at deploy.

This is the same shape as the missing app_config grant (see test_app_config_grants.py), but louder: these
reads are not wrapped in a swallow, so the handler 500s. It shipped twice. `jb-offers-api-dev` was already
throwing AccessDeniedException on `jb-services-dev` for every service-backed offer, and the booking-credit
grant and spend would both have failed on the first service subscription ever sold.

Detection is per-module, so an entry point that happens to share a module with a reader is over-reported.
PURE_ENTRY_POINTS carries those, and each one is re-checked below so an exemption cannot outlive its reason.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "src" / "handlers"

# Entry points whose module mentions a table env var that the entry point itself never reaches.
# function name -> (handler module, table env var, why)
PURE_ENTRY_POINTS = {
    "OfferResolveFunction": (
        "offers", "SERVICES_TABLE",
        "resolve_handler takes offer/products/services from the request body and reads no table",
    ),
}


class StripeCredentialGrantTests(unittest.TestCase):
    """A handler that resolves Stripe credentials needs BOTH grants, not just the keys table.

    Found on dev 2026-09-22: CouponsFunction had DynamoDBReadPolicy on StripeKeysTable and still failed
    with AccessDeniedException on GetSecretValue — because a CONNECT tenant's key is the platform secret in
    Secrets Manager, and a non-Connect tenant's is KMS-wrapped. The table grant alone covers neither. The
    browser saw only "Failed to fetch", because an unhandled 502 carries no CORS headers.
    """

    import pathlib as _pathlib
    import re as _re
    TEMPLATE = (_pathlib.Path(__file__).resolve().parents[1] / "template.yaml").read_text(encoding="utf-8")

    def _block(self, function):
        return self._re.search(
            r"^  " + function + r":\n((?:    .*\n|\n)*)", self.TEMPLATE, self._re.M).group(1)

    def test_every_caller_of_checkout_credentials_has_both_grants(self):
        root = self._pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
        callers = sorted(
            path.stem for path in root.glob("*.py")
            if "checkout_credentials" in path.read_text(encoding="utf-8"))
        self.assertTrue(callers, "the import walk found nothing — the check is broken, not the template")

        by_handler = {}
        for match in self._re.finditer(r"^  (\w+):\n((?:    .*\n|\n)*)", self.TEMPLATE, self._re.M):
            handler = self._re.search(r"Handler: handlers\.(\w+)\.", match.group(2))
            if handler:
                by_handler.setdefault(handler.group(1), []).append(match.group(1))

        for module in callers:
            for function in by_handler.get(module, []):
                with self.subTest(function=function, handler=module):
                    block = self._block(function)
                    self.assertIn("secretsmanager:GetSecretValue", block,
                                  f"{function} resolves Stripe credentials but cannot read the platform secret")
                    self.assertIn("kms:Decrypt", block,
                                  f"{function} resolves Stripe credentials but cannot unwrap a tenant key")


class TableGrantTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.blocks = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", self.template, re.M))
        globals_block = re.search(r"^Globals:\n((?:  .*\n|\n)*)", self.template, re.M)
        self.assertIsNotNone(globals_block, "template has no Globals section")
        self.env_to_table = dict(
            re.findall(r"^\s+(\w+_TABLE):\s*!Ref\s+(\w+)\s*$", globals_block.group(1), re.M)
        )
        self.functions_by_module = {}
        for name, body in self.blocks.items():
            match = re.search(r"Handler:\s*handlers\.(\w+)\.", body)
            if match:
                self.functions_by_module.setdefault(match.group(1), []).append(name)

    def test_the_env_vars_are_global_which_is_why_the_grant_must_be_checked(self):
        # If tables stop being global, every function no longer believes it can reach every table and this
        # test is measuring a risk that no longer exists.
        self.assertGreater(len(self.env_to_table), 1, "no global table env vars found — the parse is broken")

    def test_every_handler_that_names_a_table_is_granted_it(self):
        missing = []
        for path in sorted(HANDLERS.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for env, table in sorted(self.env_to_table.items()):
                if not re.search(rf"\b{env}\b", source):
                    continue
                for function in self.functions_by_module.get(path.stem, []):
                    if PURE_ENTRY_POINTS.get(function, (None, None))[:2] == (path.stem, env):
                        continue
                    if not re.search(rf"TableName: !Ref {table}\b", self.blocks[function]):
                        missing.append(f"{function} (handlers.{path.stem}) reads {env} but is not granted {table}")
        self.assertEqual([], missing, "\n".join(missing))

    def test_no_exemption_outlives_its_reason(self):
        for function, (module, env, why) in PURE_ENTRY_POINTS.items():
            with self.subTest(function=function):
                self.assertIn(function, self.blocks, f"{function} is gone; drop the exemption ({why})")
                source = (HANDLERS / f"{module}.py").read_text(encoding="utf-8")
                self.assertRegex(
                    source, rf"\b{env}\b",
                    f"handlers.{module} no longer names {env}; the {function} exemption is dead weight",
                )


if __name__ == "__main__":
    unittest.main()
