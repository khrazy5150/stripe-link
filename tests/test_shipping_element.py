"""The Shipping Element: the page describes the choice, the engine decides the cost.

plans/SHIPPING_ELEMENT.md phase 5, the page component. The element is a RUNTIME commerce component -- it ships
as an empty shell and fills itself from `GET /shipping-quote` when the page loads.

The load-bearing tests here are the ones asserting what is NOT in the artifact. A rate depends on destination,
live carrier pricing, package composition and the date; a published page is an S3 file; so anything baked in
starts rotting immediately. Even the COUNTRY list is fetched, because a tenant who adds a zone would otherwise
not see it until they republished.
"""
import json
import pathlib
import unittest

from stripe_link.domain.ai_floor import generatable_sections
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime.html import render_shipping_selector, render_shipping_selector_script

ROOT = pathlib.Path(__file__).resolve().parents[1]
OFFER = {"tenant_id": "t1", "offer_id": "o1", "items": [{"product_id": "p1"}]}
PHYSICAL = {"p1": {"product_type": "physical", "fulfillment": {"requires_shipping": True}}}
DIGITAL = {"p1": {"product_type": "digital", "fulfillment": {"requires_shipping": False}}}
API = "https://api.test/dev"


def page(section):
    return {"schema_version": "2026-05-29", "document_type": "page", "tenant_id": "t", "page_id": "p",
            "offer_id": "o", "name": "Page", "status": "draft", "template": "universal_bundle",
            "route": {"slug": "s"}, "sections": [section]}


class NothingIsBakedIntoTheArtifact(unittest.TestCase):
    def setUp(self):
        self.html = render_shipping_selector({"id": "shipping"}, OFFER, PHYSICAL, API)

    def test_it_carries_no_prices(self):
        self.assertNotIn("$", self.html)
        for digit in ("699", "1299", "amount"):
            self.assertNotIn(digit, self.html)

    def test_it_carries_no_country_list(self):
        """A tenant who adds a zone must not have to republish to offer it."""
        # The TAG, not the substring: "option" also appears in aria-label="Shipping options".
        self.assertNotIn("<option", self.html)
        for code in ("US", "CA", "GB"):
            self.assertNotIn(f">{code}<", self.html)

    def test_it_carries_what_the_fetch_needs_and_nothing_more(self):
        for attribute in ("data-shipping-api-base", "data-shipping-tenant", "data-shipping-offer"):
            self.assertIn(attribute, self.html)

    def test_it_starts_HIDDEN_so_an_empty_selector_never_flashes(self):
        self.assertIn("hidden>", self.html)


class WhenItRendersAtAll(unittest.TestCase):
    def test_a_digital_offer_gets_no_element(self):
        self.assertEqual(render_shipping_selector({"id": "s"}, OFFER, DIGITAL, API), "")

    def test_no_api_base_means_no_element(self):
        """A dropdown that can never populate is worse than no dropdown."""
        self.assertEqual(render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, None), "")

    def test_disabled_means_no_element(self):
        self.assertEqual(render_shipping_selector({"id": "s", "enabled": False}, OFFER, PHYSICAL, API), "")

    def test_the_tenants_own_wording_is_used(self):
        html = render_shipping_selector({"id": "s", "heading": "Delivery", "prompt": "Ship where?"},
                                        OFFER, PHYSICAL, API)
        self.assertIn("<h2>Delivery</h2>", html)
        self.assertIn("Ship where?", html)


class TheScriptSendsAServiceNotAnAmount(unittest.TestCase):
    """The author's rule: *"You don't want someone manipulating the browser and submitting a $2.00 shipping
    option that was never actually returned by your shipping service."*"""

    def setUp(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        self.js = render_shipping_selector_script()

    def test_the_radio_value_is_the_service_token(self):
        self.assertIn("input.value = option.service_token", self.js)
        self.assertNotIn("input.value = option.amount", self.js)

    def test_the_chosen_country_reaches_checkout(self):
        self.assertIn("window.__jbShipTo", self.js)

    def test_an_unknown_is_never_shown_as_free_shipping(self):
        """`needs` means "not answerable yet". Rendering it as free would make a promise the tenant did not."""
        self.assertNotIn("Free shipping", self.js)
        self.assertIn("calculated at checkout", self.js)

    def test_no_zones_keeps_the_element_hidden(self):
        self.assertIn("data.needs === 'zones'", self.js)

    def test_a_tier_change_asks_again(self):
        """A different tier is a different parcel, so it is a different price."""
        self.assertIn("sl-price-option", self.js)

    def test_a_failed_fetch_is_silent(self):
        """A shipping selector that cannot reach the API must not block a sale."""
        self.assertIn(".catch(", self.js)


class TheScriptIsNotShippedToPagesThatCannotUseIt(unittest.TestCase):
    """~4KB of JS. The first version emitted it unconditionally, so every page carried a selector driver --
    including digital ones with no element to drive. Caught after deploying, by measuring it."""

    def test_no_element_means_no_script(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        self.assertEqual(render_shipping_selector_script(), "")

    def test_rendering_the_element_turns_the_script_on(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        self.assertTrue(render_shipping_selector_script())

    def test_a_digital_offer_leaves_it_off(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        render_shipping_selector({"id": "s"}, OFFER, DIGITAL, API)
        self.assertEqual(render_shipping_selector_script(), "")


class TheCtaCarriesTheDestination(unittest.TestCase):
    SOURCE = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")

    def test_ship_to_country_is_added_to_the_checkout_params(self):
        self.assertIn("params.set('ship_to_country', window.__jbShipTo)", self.SOURCE)


class TheSectionMayNotStoreASnapshot(unittest.TestCase):
    def test_wording_is_allowed(self):
        validate_page_document(page({"id": "s", "type": "shipping", "heading": "Delivery",
                                    "prompt": "Where to?"}))

    def test_rates_countries_and_amounts_are_refused(self):
        for field, value in (("rates", [{"a": 1}]), ("countries", ["US"]), ("amount", 500),
                             ("options", [{"label": "Ground"}])):
            with self.assertRaises(DocumentValidationError, msg=field):
                validate_page_document(page({"id": "s", "type": "shipping", field: value}))


class TheAiMayNotAuthorIt(unittest.TestCase):
    def test_it_is_floored(self):
        """Destinations and rates are computed from the tenant's zones. A price a model invented would be a
        commercial promise nobody made."""
        self.assertNotIn("shipping", generatable_sections(["shipping", "faq", "hero"]))


class TheComposerKnowsIt(unittest.TestCase):
    RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))

    def test_it_is_a_declared_element(self):
        self.assertIn("shipping", self.RULES["elements"])
        self.assertEqual(self.RULES["elements"]["shipping"]["heading_role"], "h2")

    def test_it_is_governed_so_it_can_be_turned_on_and_off(self):
        self.assertIn("shipping", self.RULES["governed_sections"])

    def test_it_sits_before_the_buy_button(self):
        """A buyer chooses a destination BEFORE pressing buy, not after."""
        order = self.RULES["default_order"]
        self.assertLess(order.index("shipping"), order.index("checkout_cta"))

    def test_it_is_OPT_IN_rather_than_on_by_default(self):
        """Adding it to the offer-type defaults would put a destination selector above the buy button on every
        existing physical page at its next publish. Only tenants who ship multi-country need one."""
        for offer_type, config in self.RULES["offer_types"].items():
            self.assertNotIn("shipping", config.get("sections", []), offer_type)


class TheBUILDERSaysWhyNothingRendered(unittest.TestCase):
    """Reported 2026-10-01: ticking "Shipping options" showed no element and said nothing.

    The element was behaving correctly -- the tenant had no zones, so there was nothing to offer and it hid
    itself. The PAGE is right to stay silent, because a buyer must never read "no zones configured". The
    builder was wrong to be: a tenant ticked a box, saw nothing happen, and had no way to find out why. Same
    silence this app keeps being bitten by.
    """

    SCREEN = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def test_the_builder_asks_the_PAGES_own_question(self):
        """Checking the config itself would be a second implementation, and the two would eventually disagree
        about which page shows a selector."""
        self.assertIn('apiRequest("/shipping-quote"', self.SCREEN)

    def test_it_names_the_two_reasons_an_enabled_element_renders_nothing(self):
        self.assertIn("no shipping zones yet", self.SCREEN)
        self.assertIn("nothing in this offer ships", self.SCREEN)

    def test_it_offers_the_way_to_fix_it(self):
        self.assertIn("Open Shipping settings", self.SCREEN)

    def test_the_warning_is_gated_on_the_section_being_ON(self):
        warning = self.SCREEN.split("const shippingSectionWarning", 1)[1].split("\nconst ", 1)[0]
        self.assertIn('if (!sectionVisible("shipping")) return ""', warning)

    def test_a_failed_check_does_not_block_editing(self):
        """The warning is a nudge. Failing to fetch it must not get in the way."""
        body = self.SCREEN.split("async function checkShippingElement", 1)[1].split("\nconst ", 1)[0]
        self.assertIn("catch", body)


if __name__ == "__main__":
    unittest.main()
