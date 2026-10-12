"""The sales-tax switch: status-gated, fail-open, and never a compliance claim.

`plans/TAX_STATUS_AND_THRESHOLDS.md`. That plan says *"A control labelled 'Enable Stripe Tax' would imply
the platform can make that statement … so the control does not exist."* The control built here is a
different one: it governs **our** behaviour (do we ask Stripe to calculate) and is only offered once
Stripe **already** reports the account active. These tests pin that distinction, because it is the whole
reason the control is allowed to exist.

Verified against Stripe's docs 2026-10-12: `GET /v1/tax/settings` works for Standard accounts via the
`Stripe-Account` header; `status` is `active`/`pending`; `automatic_tax[enabled]=true` FAILS on a pending
account; and with no registration for the buyer's location the calculation returns zero tax, not an error.
"""
import unittest

from stripe_link.domain import tax_status as ts


def settings(status="active", behaviour="exclusive", missing=()):
    out = {"object": "tax.settings", "status": status,
           "defaults": {"tax_code": None, "tax_behavior": behaviour}}
    out["status_details"] = ({"active": {}} if status == "active"
                             else {"pending": {"missing_fields": list(missing)}})
    return out


class TheSwitchIsOnlyOfferedWhenStripeSaysSo(unittest.TestCase):
    def test_active_with_a_default_behaviour_may_enable(self):
        config, _ = ts.apply_settings({}, settings(), 1)
        self.assertTrue(ts.may_enable(config))

    def test_pending_may_not_enable(self):
        config, _ = ts.apply_settings({}, settings("pending", missing=["head_office"]), 1)
        self.assertFalse(ts.may_enable(config))

    def test_unreadable_settings_may_not_enable(self):
        """`unknown` is "we could not ask", and it must never unlock a control."""
        config, _ = ts.apply_settings({}, None, 1)
        self.assertEqual(config["status"], ts.UNKNOWN)
        self.assertFalse(ts.may_enable(config))

    def test_active_without_a_default_tax_behaviour_may_not_enable(self):
        """THIS integration never sets `tax_behavior` on a Price -- only shipping rates carry one -- so
        the account default is what lets Stripe price a line at all. Without this check a tenant could
        switch tax on, have every session fall down the fail-open ladder, and collect nothing while the
        screen said "Calculating": a silent failure dressed as success."""
        config, _ = ts.apply_settings({}, settings(behaviour=None), 1)
        self.assertFalse(ts.may_enable(config))
        self.assertFalse(ts.calculates(dict(config, enabled=True)))

    def test_inferred_by_currency_counts_as_set(self):
        """It is a real answer, not an absence."""
        config, _ = ts.apply_settings({}, settings(behaviour="inferred_by_currency"), 1)
        self.assertTrue(ts.may_enable(config))


class CalculatingNeedsBothIntentAndStatus(unittest.TestCase):
    def test_both_present(self):
        config, _ = ts.apply_settings({"enabled": True}, settings(), 1)
        self.assertTrue(ts.calculates(config))

    def test_intent_without_active_status_does_not_calculate(self):
        """The failure this prevents: `automatic_tax` errors outright on a pending account, so acting on a
        stale intent would turn a tenant's lapsed tax settings into REFUSED CHECKOUTS."""
        config, _ = ts.apply_settings({"enabled": True}, settings("pending", missing=["head_office"]), 1)
        self.assertTrue(config["enabled"], "the tenant's choice is remembered, not cleared")
        self.assertFalse(ts.calculates(config))

    def test_active_status_without_intent_does_not_calculate(self):
        config, _ = ts.apply_settings({"enabled": False}, settings(), 1)
        self.assertFalse(ts.calculates(config))


class AStatusChangeNeverClearsTheTenantsChoice(unittest.TestCase):
    """A tenant who switched tax on and then fell out of `active` must not appear to have been switched
    off by us. `calculates` stops sending `automatic_tax` on its own, so nothing unsafe happens while
    their intent waits for them to fix their Stripe settings."""

    def test_falling_out_of_active_keeps_enabled(self):
        config, _ = ts.apply_settings({"enabled": True}, settings(), 1)
        lapsed, changed = ts.apply_settings(config, settings("pending", missing=["head_office"]), 2)
        self.assertTrue(changed)
        self.assertTrue(lapsed["enabled"])
        self.assertFalse(ts.calculates(lapsed))

    def test_coming_back_to_active_resumes_without_the_tenant_acting(self):
        config, _ = ts.apply_settings({"enabled": True}, settings("pending", missing=["head_office"]), 1)
        back, _ = ts.apply_settings(config, settings(), 2)
        self.assertTrue(ts.calculates(back))

    def test_an_unchanged_status_reports_no_change(self):
        """The webhook writes only on a real change; Stripe re-sends and also fires on unrelated edits."""
        config, _ = ts.apply_settings({"enabled": True}, settings(), 1)
        _again, changed = ts.apply_settings(config, settings(), 2)
        self.assertFalse(changed)


class TheWordsNeverClaimALiability(unittest.TestCase):
    """The plan's boundary: *"We never determine, declare, or imply anything about their liability."*"""

    FORBIDDEN = ("nexus", "you owe", "must register", "required to register", "compliant",
                 "liable", "taxable in")

    def all_copy(self):
        out = []
        for payload in (settings(), settings(behaviour=None),
                        settings("pending", missing=["head_office"]), None):
            config, _ = ts.apply_settings({}, payload, 1)
            for enabled in (True, False):
                described = ts.describe(dict(config, enabled=enabled))
                out += [described["headline"], described["detail"], described["label"]]
        out += list(ts.describe({}, connected=False).values())
        return [str(s).lower() for s in out]

    def test_no_phrase_claims_a_tax_obligation(self):
        for text in self.all_copy():
            for phrase in self.FORBIDDEN:
                self.assertNotIn(phrase, text, f"copy claims a liability: {text!r}")

    def test_the_guard_can_fail(self):
        """A test that forbids strings is worthless if it never sees any."""
        copy = self.all_copy()
        self.assertGreater(len(copy), 10)
        self.assertTrue(any("sales tax" in t for t in copy))

    def test_the_unknown_state_only_says_what_is_happening(self):
        described = ts.describe({})
        self.assertEqual(described["headline"], "No sales tax is being collected on your orders.")
        self.assertIn("monitor for free", described["detail"])

    def test_pending_names_what_stripe_is_missing(self):
        config, _ = ts.apply_settings({}, settings("pending", missing=["head_office"]), 1)
        self.assertIn("head office address", ts.describe(config)["detail"])

    def test_pending_does_not_claim_the_tenant_abandoned_a_setup(self):
        """`tax.settings` always exists and is `pending` by DEFAULT for an account that never touched
        Stripe Tax, so `pending` is the starting state rather than evidence of an attempt. This plan's own
        premise -- "the tenant started and did not finish" -- was wrong, and the first tenant to see the
        screen had never opened Stripe Tax at all."""
        described = ts.describe(ts.apply_settings({}, settings("pending", missing=["head_office"]), 1)[0])
        self.assertEqual(described["label"], "Not set up")
        for phrase in ("unfinished", "not finished", "did not finish", "still needs"):
            self.assertNotIn(phrase, (described["headline"] + " " + described["detail"]).lower(),
                             "implies the tenant began something they may never have begun")

    def test_the_two_off_states_do_not_wear_the_same_label(self):
        """"Not set up" (Stripe has no setup) and "Not collecting" (we could not find out) are different
        facts with different actions. "Disabled" was rejected for both: the switch sits directly below
        this badge, so it would put two kinds of "off" under one word."""
        pending = ts.describe(ts.apply_settings({}, settings("pending", missing=["head_office"]), 1)[0])
        unknown = ts.describe(ts.apply_settings({}, None, 1)[0])
        self.assertNotEqual(pending["label"], unknown["label"])
        self.assertNotIn("disabled", (pending["label"] + unknown["label"]).lower())

    def test_a_calculating_tenant_is_told_why_some_orders_show_no_tax(self):
        """Stripe returns ZERO tax where there is no registration for the buyer's location. Unexplained,
        that reads as a bug; this is not a claim about where they owe anything."""
        config, _ = ts.apply_settings({"enabled": True}, settings(), 1)
        self.assertIn("where you are registered", ts.describe(config)["detail"])

    def test_an_unconnected_account_is_not_told_about_tax_at_all(self):
        described = ts.describe({"status": "active"}, connected=False)
        self.assertFalse(described["may_enable"])
        self.assertIn("Connect Stripe", described["headline"])


class CheckoutSendsAutomaticTaxOnlyWhenGated(unittest.TestCase):
    def payload(self, tax_config):
        from handlers.checkout import build_checkout_payload
        return build_checkout_payload(
            tenant_id="t1", offer={"offer_id": "o1"}, products_by_id={},
            resolved={"items": [], "currency": "usd", "amount_total": 1000},
            success_url="https://x/s", cancel_url="https://x/c",
            collect_tax=ts.calculates(tax_config), mode="test")

    def test_it_is_sent_when_enabled_and_active(self):
        config, _ = ts.apply_settings({"enabled": True}, settings(), 1)
        self.assertEqual(self.payload(config).get("automatic_tax[enabled]"), "true")

    def test_it_is_absent_when_pending(self):
        config, _ = ts.apply_settings({"enabled": True}, settings("pending", missing=["head_office"]), 1)
        self.assertNotIn("automatic_tax[enabled]", self.payload(config))

    def test_it_is_absent_when_the_tenant_has_not_switched_it_on(self):
        config, _ = ts.apply_settings({"enabled": False}, settings(), 1)
        self.assertNotIn("automatic_tax[enabled]", self.payload(config))

    def test_it_is_absent_for_a_tenant_with_no_tax_config_at_all(self):
        """Every tenant today. The default must be silence, not a parameter that can refuse a sale."""
        self.assertNotIn("automatic_tax[enabled]", self.payload(None))


class AFailedTaxCalculationNeverCostsTheSale(unittest.TestCase):
    """The plan's rule, verbatim: *"fail open — an uncollected tax is recoverable and the tenant can be
    told; a refused checkout is revenue that never arrives."*"""

    def test_the_retry_ladder_drops_automatic_tax(self):
        from handlers.checkout import create_checkout_session_with_fallback
        attempts = []

        def opener_fails_on_tax(payload, **_kwargs):
            attempts.append(dict(payload))
            if "automatic_tax[enabled]" in payload:
                raise RuntimeError("tax settings are not active on this account")
            return {"id": "cs_ok", "url": "https://pay"}

        import handlers.checkout as co
        original = co.create_stripe_checkout_session
        co.create_stripe_checkout_session = lambda payload, **kw: opener_fails_on_tax(payload)
        try:
            got = create_checkout_session_with_fallback(
                {"mode": "payment", "automatic_tax[enabled]": "true"}, api_key="sk_test")
        finally:
            co.create_stripe_checkout_session = original
        self.assertEqual(got["id"], "cs_ok")
        self.assertIn("automatic_tax[enabled]", attempts[0], "the first attempt asks for tax")
        self.assertNotIn("automatic_tax[enabled]", attempts[-1], "the sale completes without it")

    def test_a_session_that_never_asked_for_tax_is_unaffected(self):
        from handlers.checkout import create_checkout_session_with_fallback
        import handlers.checkout as co
        original = co.create_stripe_checkout_session
        co.create_stripe_checkout_session = lambda payload, **kw: {"id": "cs_1"}
        try:
            got = create_checkout_session_with_fallback({"mode": "payment"}, api_key="sk_test")
        finally:
            co.create_stripe_checkout_session = original
        self.assertEqual(got["id"], "cs_1")


if __name__ == "__main__":
    unittest.main()
