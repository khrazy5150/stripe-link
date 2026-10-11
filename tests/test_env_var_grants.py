"""Every function must be DECLARED every environment variable it can reach.

`plans/TRANSFORM_BUDGET.md` Phase 1. This test exists before the change it guards, which is the point:
the 84 variables in `Globals` are 36% of the template and the reason the stack sits at CloudFormation's
1,000,000-byte transform ceiling, and Phase 2 moves them per-function. **A missing env var is a RUNTIME
failure, not a deploy failure** — a function that loses `PUBLIC_CHECKOUT_BASE_URL` deploys perfectly and
breaks the first buyer who reaches it. That is the same class of defect as everything found on
2026-10-07/08, so the guard goes in first and the conversion follows it.

Today every assertion here passes trivially, because `Globals` gives every function everything. That is
not a reason to wait: the day a variable moves, this is what notices the function that still needed it.

**Why this over-approximates, deliberately.** `test_table_grants.py` answers a similar question to
demand an IAM grant, and gates two of its three signals on a module having one entry point. Under-
reporting there means a missing grant goes unnoticed. Here it means Phase 2 deletes a variable something
genuinely reads, so the bias is inverted: every function in a module inherits everything the module
reaches, imports are followed transitively, and `ast` is used so the deferred-import style this codebase
uses everywhere is seen. The cost of over-approximating is a few bytes; the cost of the alternative is an
outage.
"""
import pathlib
import unittest

import envreach

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EveryFunctionGetsWhatItReaches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        cls.reachable = envreach.reach()
        cls.declared = envreach.global_env_names(cls.template)
        cls.functions = envreach.template_functions(cls.template)

    def test_no_function_is_short_a_variable_it_can_reach(self):
        """THE guard. Everything else in this file exists to stop it passing vacuously."""
        missing = []
        for function, module in sorted(self.functions.items()):
            available = self.declared | envreach.function_env_names(self.template, function)
            for name in sorted(envreach.required(module, self.reachable, self.declared) - available):
                missing.append(f"{function} ({module}) reads {name} but the template never declares it")
        self.assertEqual([], missing, "\n".join(missing))

    def test_the_analysis_found_the_functions(self):
        self.assertGreaterEqual(len(self.functions), 70, "template parse is broken")
        self.assertIn("CheckoutFunction", self.functions)
        self.assertEqual(self.functions["CheckoutFunction"], "handlers.checkout")

    def test_the_globals_parse_found_the_variables(self):
        self.assertGreaterEqual(len(self.declared), 80, "Globals parse is broken")
        for name in ("ORDERS_TABLE", "PAGES_BUCKET", "PUBLIC_CHECKOUT_BASE_URL"):
            self.assertIn(name, self.declared)


class TheAnalysisIsNotTriviallyEmpty(unittest.TestCase):
    """An env-var analysis that returns nothing would make the guard above pass for every change.

    Each assertion here names a reach that is known to be real and that the analysis got WRONG at some
    point while being written, so a regression lands as a failure rather than as a quiet success.
    """

    @classmethod
    def setUpClass(cls):
        cls.reachable = envreach.reach()

    def test_a_handler_reaches_what_it_names_directly(self):
        self.assertIn("ORDERS_TABLE", self.reachable["handlers.orders"])

    def test_a_handler_reaches_a_table_through_a_factory_it_calls(self):
        """`handlers/refunds.py` reads every product's refund_policy by calling products_repository()
        and never names the env var — the hole that shipped twice in the IAM version of this test."""
        self.assertIn("PRODUCTS_TABLE", self.reachable["handlers.refunds"])

    def test_a_handler_reaches_a_table_through_an_imported_domain_module(self):
        """`ai_generate` never names PLATFORM_PLANS_TABLE and never calls its factory; it imports
        domain/platform_billing, which does both."""
        self.assertIn("PLATFORM_PLANS_TABLE", self.reachable["handlers.ai_generate"])

    def test_reach_is_transitive_through_a_second_hop(self):
        """fee reconciliation runs inside the webhook handler and imports it for fetch_actual_fees, so it
        inherits the webhook's tables. A one-hop walk would miss this."""
        webhook = self.reachable["handlers.stripe_webhook"]
        self.assertIn("LEDGER_TABLE", webhook)
        self.assertIn("REFUNDS_TABLE", webhook)

    def test_importing_the_factory_MODULE_is_not_calling_its_factories(self):
        """The error `plans/TRANSFORM_BUDGET.md` recorded against an earlier estimate, and the one that
        made the first run of this analysis useless: `repositories/documents.py` reads 39 table variables,
        one inside each factory, and 72 modules import it. Attributing all 39 to every importer put the
        median at 53 of 84 and would have made Phase 2 pointless."""
        self.assertNotIn("LEADS_TABLE", self.reachable["handlers.health"],
                         "health imports common, not the leads table")
        self.assertLessEqual(len(self.reachable["handlers.health"]), 6,
                             f"health should reach almost nothing: {sorted(self.reachable['handlers.health'])}")

    def test_a_trivial_handler_really_is_trivial(self):
        """The floor matters more than any single handler: it is paid 74 times."""
        self.assertLessEqual(len(self.reachable["handlers.page_view"]), 5)


class TheFloorIsNotSetByOneDiagnosticEndpoint(unittest.TestCase):
    """`runtime_manifest` named every table, bucket and distribution in the stack and lived in
    `stripe_link/common.py` — which every handler imports. One function, never called by any of them,
    put 28 variables on the floor of all 74 Lambdas and made `jb-health` look like it needed 35.

    Moving it to its own module took the median reach from 37 to 8 and the projected saving from ~195KB
    to ~312KB. It is guarded here because putting it back would be invisible and expensive.
    """

    def test_common_does_not_name_the_whole_stack(self):
        source = (ROOT / "src" / "stripe_link" / "common.py").read_text(encoding="utf-8")
        named = [line for line in source.splitlines() if "_TABLE" in line or "_BUCKET" in line]
        self.assertLessEqual(len(named), 4,
                             "common.py is imported by every handler; naming tables here is paid 74 times:\n"
                             + "\n".join(named[:10]))

    def test_the_manifest_still_works_from_its_own_module(self):
        from stripe_link.runtime_manifest import runtime_manifest
        body = runtime_manifest()
        self.assertEqual(body["service"], "stripe-link")
        for key in ("tables", "buckets", "distributions", "resource_prefix_ok"):
            self.assertIn(key, body)

    def test_only_the_manifest_handler_reaches_those_variables(self):
        reachable = envreach.reach()
        self.assertIn("THEMES_TABLE", reachable["handlers.manifest"])
        for handler in ("handlers.health", "handlers.page_view", "handlers.upload"):
            self.assertNotIn("THEMES_TABLE", reachable[handler], handler)


class WhatPhase2WouldSave(unittest.TestCase):
    """Not an assertion about the plan's estimate — a floor under it, so a refactor that silently makes
    the conversion pointless is visible."""

    def test_the_saving_is_still_worth_doing(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        reachable = envreach.reach()
        declared = envreach.global_env_names(template)
        functions = envreach.template_functions(template)
        needed = sum(len(envreach.required(module, reachable, declared))
                     for module in functions.values())
        now = len(functions) * len(declared)
        self.assertLess(needed, now * 0.35,
                        f"needed {needed} of {now} slots; Phase 2 stops being worth the risk above ~35%")


class IndirectReadsAreSeen(unittest.TestCase):
    """The reads that do NOT name their variable at the call site.

    These are the silent-outage class: an analysis that only understands `environ.get("X")` would strip
    them, the template would deploy, and the failure would arrive with the first request that took the
    branch. All three shapes below are real and in this codebase.
    """

    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        cls.reachable = envreach.reach()
        cls.declared = envreach.global_env_names(cls.template)

    def test_a_name_taken_from_a_module_level_list(self):
        """`for env_name in _PK_TABLES: os.environ.get(env_name, "")` — the dev-only wipe tool. Strip
        these and it silently deletes nothing, reporting success."""
        reached = self.reachable["handlers.admin_delete_test_data"]
        for name in ("ORDERS_TABLE", "PAGES_TABLE", "PRODUCTS_TABLE"):
            self.assertIn(name, reached, name)

    def test_a_literal_passed_through_a_local_function(self):
        """`_ips("CLOUDFLARE_APEX_IPV4")` in handlers/sites.py."""
        self.assertIn("CLOUDFLARE_APEX_IPV4", self.reachable["handlers.sites"])

    def test_an_fstring_prefix_expands_against_the_declared_names(self):
        """`os.environ.get(f"STRIPE_SECRET_KEY_{mode.upper()}")`. Those particular names are not template
        variables -- they come from Secrets Manager -- so this asserts the MECHANISM on a prefix that is
        declared, rather than asserting a vacuous empty set."""
        expanded = envreach.required("x", {"x": {"STRIPE_CLIENT_ID_*"}}, self.declared)
        self.assertEqual(expanded, {"STRIPE_CLIENT_ID_LIVE", "STRIPE_CLIENT_ID_TEST"})

    def test_the_connect_handlers_keep_every_client_id_variant(self):
        """Read as three separate literals, and all three are needed: test, live, and the legacy
        unsuffixed fallback. Losing the fallback breaks Connect for anyone on the older config."""
        need = envreach.required("handlers.stripe_connect", self.reachable, self.declared)
        for name in ("STRIPE_CLIENT_ID", "STRIPE_CLIENT_ID_LIVE", "STRIPE_CLIENT_ID_TEST"):
            self.assertIn(name, need, name)

    def test_over_collecting_cannot_leak_an_undeclared_name(self):
        """Bare SCREAMING_SNAKE literals are collected wholesale, which is safe only because `required`
        intersects with what the template declares. If that intersection went away, the guard would start
        demanding variables that do not exist."""
        need = envreach.required("handlers.orders", self.reachable, self.declared)
        self.assertTrue(need <= self.declared)


if __name__ == "__main__":
    unittest.main()
