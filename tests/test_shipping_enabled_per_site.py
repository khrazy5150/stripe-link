"""One business ships, its sibling is digital-only (plans/SHIPPING_PER_SITE.md §S5).

The phase that changes what a BUYER sees, which is why the plan put it last. The shipping element is the
only thing on a page that collects a postal code, so getting this wrong in the wrong direction is the
2026-10-06 failure again: an order shipped a Large box for $7.83 having collected $0.

**The flag is `enabled_opt_out`, not `enabled`, and that is a correction to the plan.** The buyer-facing
gate has always read the opt-out, because the Enable-shipping checkbox was declared, rendered, saved and
gating nothing until 2026-10-11 — so every config in existence carries `enabled: false` by accident. Making
that field per-Site would copy a legacy accident into a fresh layer and give a tenant two overlapping ways
to say one thing.

And the flag merges by a different rule from the containers: `False` is a DECISION — "this shop ships even
though the account has shipping off" — so absent and false are different answers. Reading `False` as
"inherit" is the midnight-cutoff bug wearing a boolean.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
from stripe_link.domain.shipping import (
    SITE_OVERRIDABLE,
    SITE_OVERRIDABLE_FLAGS,
    config_for_site,
    shipping_opted_out,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def config(opted_out=False, **over):
    doc = {"schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
           "provider": {"name": "shippo", "api_key_ref": "ref"}, "boxes": [], "zones": []}
    if opted_out:
        doc["enabled_opt_out"] = True
    doc.update(over)
    return doc


def resolved(account_off, site_override):
    return config_for_site({**config(opted_out=account_off), "sites": {"site_x": site_override}}, "site_x")


class TheFlagIsAThreeStateAnswerTests(unittest.TestCase):
    def test_a_site_can_opt_OUT_of_an_account_that_ships(self):
        self.assertTrue(shipping_opted_out(resolved(False, {"enabled_opt_out": True})))

    def test_a_site_can_opt_IN_to_an_account_that_does_not(self):
        """The reason `False` has to be a statement. Without it a tenant who turned shipping off
        account-wide could never let one shop keep shipping."""
        self.assertFalse(shipping_opted_out(resolved(True, {"enabled_opt_out": False})))

    def test_saying_NOTHING_inherits_either_way(self):
        self.assertFalse(shipping_opted_out(resolved(False, {})))
        self.assertTrue(shipping_opted_out(resolved(True, {})))

    def test_a_NON_BOOLEAN_is_not_a_statement(self):
        """A string from a hand-rolled client must not be read as truthy and silently turn shipping off."""
        self.assertFalse(shipping_opted_out(resolved(False, {"enabled_opt_out": "yes"})))
        self.assertTrue(shipping_opted_out(resolved(True, {"enabled_opt_out": "no"})))

    def test_ENABLED_is_deliberately_not_overridable(self):
        """It is legacy-poisoned: every config predating 2026-10-11 carries `enabled: false` by accident,
        and the gate reads the opt-out precisely because of that."""
        self.assertNotIn("enabled", SITE_OVERRIDABLE)
        self.assertNotIn("enabled", SITE_OVERRIDABLE_FLAGS)
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(config(sites={"site_x": {"enabled": True}}))

    def test_the_validator_accepts_BOTH_booleans_and_refuses_anything_else(self):
        for value in (True, False):
            with self.subTest(value=value):
                validate_shipping_config(config(sites={"site_x": {"enabled_opt_out": value}}))
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(config(sites={"site_x": {"enabled_opt_out": "yes"}}))

    def test_the_write_path_KEEPS_a_false(self):
        """The truthiness filter that drops an empty address would also drop `False`, which is the bug this
        pins: the flags are filtered by `isinstance(..., bool)` instead."""
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        block = source.split("def save_site_override(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("isinstance(raw.get(flag), bool)", block)


class TheBUYERPathsAskPerSiteTests(unittest.TestCase):
    """Where it has to bite: what a page publishes with, what the builder previews, and what checkout
    charges. All three already hold the page, so all three can answer which business this is."""

    def test_PUBLISH_resolves_the_pages_site(self):
        source = (ROOT / "src/stripe_link/runtime/publishing.py").read_text(encoding="utf-8")
        self.assertIn('config_for_site(shipping_config_repository.get(tenant_id) or {},', source)
        self.assertIn('str((page or {}).get("site_id") or "")', source)

    def test_the_BUILDER_PREVIEW_resolves_it_too(self):
        """Mirrors what publish decides, or the builder shows a page the visitor will not get."""
        source = (ROOT / "src/handlers/page_render.py").read_text(encoding="utf-8")
        self.assertIn("config_for_site(shipping_config_repository().get(tenant_id) or {}, site_id)", source)
        self.assertIn('str(page.get("site_id") or "")', source)

    def test_CHECKOUT_resolves_it_for_the_session_and_the_rate_island(self):
        source = (ROOT / "src/handlers/checkout.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("_site_scoped(_tenant_shipping_config(tenant_id), tenant_id, page_id, mode)"), 2)

    def test_the_site_read_is_LAZY(self):
        """The rate island is public and documented as "a cached config read plus arithmetic, with NO
        carrier call". A page read per quote would be a new cost on every tenant, so it is paid only by an
        account that actually has an override."""
        source = (ROOT / "src/handlers/checkout.py").read_text(encoding="utf-8")
        block = source.split("def _site_scoped(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('if not isinstance((config or {}).get("sites"), dict) or not config["sites"]:', block)
        self.assertLess(block.index("return config"), block.index("site_id_of_page"),
                        "the early return must come before anything is read")

    def test_an_unreadable_page_means_NO_OVERRIDE_not_a_failed_sale(self):
        block = (ROOT / "src/handlers/checkout.py").read_text(encoding="utf-8") \
            .split("def _site_scoped(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("except Exception as exc:", block)
        self.assertIn("return config", block)


class TheCheapSiteLookupTests(unittest.TestCase):
    class Pages:
        def __init__(self, page=None, explode=False):
            self.page = page
            self.explode = explode
            self.reads = 0

        def get(self, _tenant, _page_id):
            self.reads += 1
            if self.explode:
                raise RuntimeError("throttled")
            return self.page

    def test_it_returns_the_edge_in_ONE_read(self):
        from stripe_link.domain.sites import site_id_of_page

        pages = self.Pages({"page_id": "p1", "site_id": "site_qui"})
        self.assertEqual(site_id_of_page(pages, "t1", "p1"), "site_qui")
        self.assertEqual(pages.reads, 1)

    def test_a_page_with_no_edge_is_an_empty_string(self):
        from stripe_link.domain.sites import site_id_of_page

        self.assertEqual(site_id_of_page(self.Pages({"page_id": "p1"}), "t1", "p1"), "")

    def test_it_never_raises(self):
        from stripe_link.domain.sites import site_id_of_page

        self.assertEqual(site_id_of_page(self.Pages(explode=True), "t1", "p1"), "")
        self.assertEqual(site_id_of_page(None, "t1", "p1"), "")
        self.assertEqual(site_id_of_page(self.Pages(), "", ""), "")


class WhatStaysACCOUNTLEVELTests(unittest.TestCase):
    """Said out loud, because an unscoped reader looks identical to a forgotten one."""

    def test_the_ORDERS_SCREEN_stays_account_level(self):
        """One list across every business; a readiness summary scoped to one Site answers a question
        nobody asked there."""
        source = (ROOT / "src/handlers/orders.py").read_text(encoding="utf-8")
        self.assertIn("ACCOUNT-LEVEL on purpose (plans/SHIPPING_PER_SITE.md §S5)", source)
        self.assertNotIn("config_for_site", source)

    def test_the_UPSELL_stays_account_level_because_it_has_no_page(self):
        """An upsell's order records `attribution.page_id = ""` deliberately — charged off-session after
        checkout, belonging to no page — so there is no Site to resolve."""
        source = (ROOT / "src/handlers/upsell.py").read_text(encoding="utf-8")
        self.assertIn('records `attribution.page_id = ""` deliberately', source)
        self.assertNotIn("config_for_site", source)


class TheScreenOffersThreeStatesTests(unittest.TestCase):
    SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_control_appears_only_for_a_SELECTED_site(self):
        block = self.SCREEN.split("Shipping on this site", 1)[0][-400:]
        self.assertIn('v-if="shipFromScope"', block)

    def test_all_THREE_states_are_offered(self):
        """Collapsing "inherit" into "on" would make the account's own switch unreachable from here."""
        self.assertIn("Follow the account setting", self.SCREEN)
        self.assertIn("digital only", self.SCREEN)
        self.assertIn('<option value="on">', self.SCREEN)

    def test_it_reports_what_the_ACCOUNT_setting_resolves_to(self):
        self.assertIn("accountShippingLabel", self.SCREEN)
        self.assertIn("rawDoc.value?.enabled_opt_out", self.SCREEN)

    def test_FOLLOW_sends_the_key_ABSENT(self):
        """Sending `false` for "follow the account" would store a decision the tenant did not make."""
        block = self.SCREEN.split("function siteShippingFlag()", 1)[1][:500]
        self.assertIn("return {};", block)
        self.assertIn("enabled_opt_out: false", block)
        self.assertIn("enabled_opt_out: true", block)

    def test_an_unsaved_choice_does_not_follow_the_tenant_to_ANOTHER_site(self):
        block = self.SCREEN.split("watch(shipFromScope", 1)[1][:400]
        self.assertIn("pendingSiteShipping.value = null", block)


if __name__ == "__main__":
    unittest.main()
