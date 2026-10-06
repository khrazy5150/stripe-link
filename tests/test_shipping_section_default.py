"""The shipping element is ON by default for anything that ships.

A page with no shipping element cannot collect a postcode. The quote then returns
`{"ships": true, "options": [], "needs": "postal_code"}`, Stripe is given no shipping option, and the
buyer pays nothing to post -- silently, permanently, and with nothing anywhere saying so. A real order on
2026-10-06 shipped a Large box costing $7.83 having collected $0.00 at checkout, purely because its
landing page had been built without the element.

Default, not forced: the author asked for it ticked by default "like the trust badges", with the tenant
free to untick it.
"""
import json
import unittest
from pathlib import Path

from stripe_link.domain.composition import (
    compose_page,
    default_visible,
    is_section_visible,
    offer_ships_physical,
)


ROOT = Path(__file__).resolve().parents[1]


def page(*types, overrides=None):
    return {"sections": [{"id": t, "type": t} for t in types],
            "composition": {"overrides": overrides or {}}}


OFFER = {"offer_type": "single", "product_intent": "transaction"}


def composed(offer, p, ships_physical):
    return [str(s.get("type")) for s in compose_page(offer, p, "landing", ships_physical=ships_physical)]


class ShippingDefaultsOnWhenItShipsTests(unittest.TestCase):
    def test_a_shipping_offer_gets_the_element_without_anyone_adding_it(self):
        """Derived, so a page published before this existed heals on its next publish."""
        self.assertIn("shipping", composed(OFFER, page("hero", "checkout_cta"), True))

    def test_a_digital_offer_does_not(self):
        """`single` and `bundle` cover downloads too, and a shipping card on a download is nonsense."""
        self.assertNotIn("shipping", composed(OFFER, page("hero", "checkout_cta"), False))

    def test_the_tenant_can_untick_it(self):
        """A default is a default. An override outranks it."""
        p = page("hero", "checkout_cta", overrides={"shipping": {"enabled": False}})
        self.assertNotIn("shipping", composed(OFFER, p, True))

    def test_a_page_that_already_has_one_does_not_get_a_second(self):
        self.assertEqual(composed(OFFER, page("hero", "shipping", "checkout_cta"), True).count("shipping"), 1)

    def test_it_lands_before_the_checkout_button(self):
        """Ordering comes from the shared baseline, which already placed it there."""
        order = composed(OFFER, page("hero", "checkout_cta"), True)
        self.assertLess(order.index("shipping"), order.index("checkout_cta"))

    def test_the_offers_own_flag_can_say_so_when_the_caller_cannot(self):
        """`compose_page` gets the OFFER and never its products, which is why `lead_capture_action` and
        `pricing_model` are already denormalised onto it. Publish runs from a stream holding only the
        page, so the flag has to survive there too."""
        self.assertTrue(offer_ships_physical({**OFFER, "ships_physical": True}))
        self.assertIn("shipping", composed({**OFFER, "ships_physical": True}, page("hero"), False))

    def test_default_visible_is_the_single_rule(self):
        self.assertTrue(default_visible("single", "shipping", "", True))
        self.assertFalse(default_visible("single", "shipping", "", False))

    def test_an_exclusion_still_outranks_everything(self):
        """A lead page sells nothing; a shipping card on one is incoherent rather than merely unwanted."""
        for offer_type in ("lead_capture", "lead_social"):
            with self.subTest(offer_type=offer_type):
                self.assertFalse(
                    is_section_visible(offer_type, "shipping", {"shipping": {"enabled": True}}, "", True)
                    and "shipping" in (json.loads(
                        (ROOT / "src" / "stripe_link" / "composition_rules.json").read_text()
                    ).get("offer_types", {}).get(offer_type, {}).get("excludes") or []))


class TheTwoRenderersAgreeTests(unittest.TestCase):
    """Preview and published composing differently is the drift this layer exists to kill."""

    VUE = (ROOT / "dashboard" / "src" / "composables" / "pageComposer.js").read_text(encoding="utf-8")

    def test_the_vue_composer_keys_shipping_on_the_same_thing(self):
        self.assertIn('SHIPS_PHYSICAL_SECTION = "shipping"', self.VUE)
        self.assertIn("return Boolean(shipsPhysical)", self.VUE)

    def test_the_vue_composer_threads_it_through_visibility(self):
        block = self.VUE.split("export function isSectionVisible", 1)[1].split("\n}", 1)[0]
        self.assertIn("shipsPhysical", block)


if __name__ == "__main__":
    unittest.main()


class OneRuleOneCallSiteTests(unittest.TestCase):
    """Unticking has to actually untick.

    Composition grew a third axis (ships_physical, after offer_type and goal). Threading it through five
    separate call sites in the builder missed two — `isSectionEnabled` and `toggleSection` — and the second
    of those broke unticking in the worst available way: it compared the new value against a default
    computed WITHOUT the axis, concluded that unticking matched the default, and DELETED the override
    rather than writing it. The real composer then applied the real default, which is ON, so the element
    came straight back (2026-10-06).

    The component now answers the question in one place. These guard that.
    """

    VUE = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def test_the_builder_asks_the_question_in_exactly_one_place(self):
        """A fourth axis should cost one edit, not five."""
        self.assertEqual(self.VUE.count("defaultVisible("), 1,
                         "call sectionRecommended(), never defaultVisible() directly")

    def test_that_one_place_passes_every_axis(self):
        block = self.VUE.split("function sectionRecommended", 1)[1].split("\n}", 1)[0]
        for axis in ("builderOfferType", "builderGoal", "builderHasPhysicalItems"):
            with self.subTest(axis=axis):
                self.assertIn(axis, block)

    def test_untick_and_recommended_read_the_same_default(self):
        """`toggleSection` decides between writing an override and dropping it by comparing against the
        default. If that comparison disagrees with the composer, unticking silently does nothing."""
        for name in ("function isSectionEnabled", "async function toggleSection"):
            with self.subTest(fn=name):
                block = self.VUE.split(name, 1)[1].split("\n}", 1)[0]
                self.assertIn("sectionRecommended(key)", block)

    def test_the_axis_is_declared_before_anything_reads_it(self):
        """`watch(() => [sectionVisible("shipping"), ...])` runs its getter immediately to collect
        dependencies. A `const` declared after that line is a temporal dead zone, not a stale value — the
        whole builder throws on setup."""
        declared = self.VUE.index("const builderHasPhysicalItems")
        # Matched on the WHOLE statement: the comment above the declaration quotes the watcher, and a
        # looser needle finds the comment instead of the code it is warning about.
        for reader in ("function sectionVisible", "function sectionRecommended",
                       'watch(() => [sectionVisible("shipping"), builderOffer.value?.offer_id]'):
            with self.subTest(reader=reader):
                self.assertLess(declared, self.VUE.index(reader))
