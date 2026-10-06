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
