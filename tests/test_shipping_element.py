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
        # "amount" is checked as a bare substring on purpose: it is blunt, and the bluntness is the point --
        # a published page is a static S3 artifact, so ANY price-shaped thing in it starts rotting the
        # moment it is written. A class name that trips this gets renamed; the guard stays strict.
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

    def test_it_no_longer_promises_shipping_is_calculated_at_checkout(self):
        """It was not. `needs: carrier` produced empty `shipping_options`, Stripe charged nothing, and the
        buyer had been told on the page that a cost was coming (removed 2026-10-01, with live rating).

        The replacement says what is true -- we could not get a rate -- and the element offers a retry.
        """
        self.assertNotIn("calculated at checkout", self.js)
        self.assertIn("could not get shipping rates", self.js)
        self.assertIn("sl-shipping-retry", self.js)

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


class TheElementCollectsAnAddressNotJustACountry(unittest.TestCase):
    """plans/LIVE_SHIPPING_RATES.md phase 3. A carrier prices a journey between two postcodes; until the
    element grew a second field, every live zone answered `needs: carrier` and every buyer shipped free."""

    def setUp(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        self.html = render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        self.js = render_shipping_selector_script()

    def test_it_asks_for_a_postal_code(self):
        self.assertIn('class="sl-shipping-postal"', self.html)
        self.assertIn('autocomplete="postal-code"', self.html)

    def test_the_postcode_rides_to_the_quote_endpoint(self):
        self.assertIn("'&postal_code=' + encodeURIComponent(postal.value.trim())", self.js)

    def test_the_region_field_is_hidden_until_a_country_needs_one(self):
        # Most countries do not use a subdivision for rating. An always-visible field a buyer must guess
        # at is friction bought for nothing.
        self.assertIn('class="sl-shipping-field sl-shipping-region-field" hidden', self.html)
        self.assertIn("regionField.hidden = !needsRegion", self.js)

    def test_the_countries_that_need_a_region_are_named(self):
        for code in ("US", "CA", "AU", "BR", "IN", "MX"):
            self.assertIn(f"{code}:", self.js.split("REGION_REQUIRED", 1)[1][:200])

    def test_the_field_is_labelled_in_the_buyers_own_vocabulary(self):
        self.assertIn("ZIP code", self.js)
        self.assertIn("Postcode", self.js)
        self.assertIn("Province", self.js)

    def test_a_carrier_call_is_not_made_per_keystroke(self):
        self.assertIn("clearTimeout(timer)", self.js)
        self.assertIn("postal.value.trim().length >= 3", self.js)

    def test_a_slow_answer_never_overwrites_a_newer_one(self):
        # The buyer has typed since. Painting the stale answer would show a price for the wrong address.
        self.assertIn("var mine = ++seq", self.js)
        self.assertIn("mine === seq ? data : undefined", self.js)


class TheBuyerComparesBeforePaying(unittest.TestCase):
    def setUp(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        self.html = render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        self.js = render_shipping_selector_script()

    def test_each_option_shows_a_name_a_price_and_an_estimate(self):
        self.assertIn("sl-shipping-rate-label", self.js)
        self.assertIn("sl-shipping-rate-price", self.js)
        self.assertIn("sl-shipping-rate-estimate", self.js)

    def test_a_single_day_estimate_reads_naturally(self):
        self.assertIn("'Estimated ' + one + ' business day'", self.js)
        self.assertIn("'Estimated ' + lo + '-' + hi + ' business days'", self.js)

    def test_the_order_total_moves_with_the_chosen_service(self):
        self.assertIn("sl-shipping-total", self.html)
        self.assertIn("money(sub + shipping)", self.js)

    def test_choosing_a_service_updates_the_total(self):
        self.assertIn("input.addEventListener('change', function(){ choose(input.value, option.amount); })",
                      self.js)

    def test_every_state_the_buyer_can_be_in_is_handled(self):
        for state in ("loading", "error", "rates", "idle"):
            with self.subTest(state=state):
                self.assertIn(f"'{state}'", self.js)

    def test_a_failure_offers_a_retry_rather_than_a_dead_end(self):
        self.assertIn("retry.addEventListener('click', run)", self.js)
        self.assertIn("retry.hidden = state !== 'error'", self.js)

    def test_the_element_has_a_stylesheet_at_all(self):
        # It shipped as structure with no CSS whatsoever, so the mock's card was never going to appear.
        source = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        self.assertIn(".sl-shipping-rate{", source)
        self.assertIn(".sl-shipping-summary{", source)

    def test_the_selected_rate_is_not_marked_by_colour_alone(self):
        source = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        selected = source.split(".sl-shipping-rate:has(input:checked)", 1)[1][:120]
        self.assertIn("border-width:2px", selected)


class TheChoiceReachesCheckout(unittest.TestCase):
    """Until now the radios were decorative: `input.value` was set to the service token and the token never
    left the page. Only `ship_to_country` travelled."""

    def test_the_quote_and_the_service_both_ride_to_checkout(self):
        source = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        self.assertIn("params.set('shipping_quote', window.__jbShipQuote)", source)
        self.assertIn("params.set('shipping_service', window.__jbShipService)", source)

    def test_the_amount_never_rides_to_checkout(self):
        source = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        self.assertNotIn("params.set('shipping_amount'", source)
        self.assertNotIn("set('shipping_cost'", source)


class TheElementAgreesWithTheRestOfThePage(unittest.TestCase):
    """Cross-checks between the element and the renderer that writes what it reads.

    Both bugs here shipped green: every test string-matched the element's own source, so a selector that
    matched nothing on the real page, and a CSS rule that defeated its own `hidden` attribute, both looked
    correct in isolation. They were found by downloading the PUBLISHED page.
    """

    SOURCE = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")

    def _script(self):
        # The GENERATED script, not the module source -- a comment explaining the old selector would
        # otherwise satisfy a source-level assertion while the shipped JS still had the bug.
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        return render_shipping_selector_script()

    def test_the_cart_reads_the_class_the_price_cards_actually_carry(self):
        # The page marks a chosen card `.selected` -- the CTA and the price selector both say so. The
        # element looked for `[aria-checked="true"]` and `.is-selected`, neither of which is ever written,
        # so no product_id, price_id or quantity ever reached /shipping-quote and every quote came from
        # the offer's first item whatever tier the buyer picked.
        js = self._script()
        self.assertIn("document.querySelector('.sl-price-option.selected')", js)
        self.assertNotIn("aria-checked", js)
        self.assertNotIn("is-selected", js)

    def test_it_falls_back_to_the_first_card_like_the_rest_of_the_page(self):
        self.assertIn("cards[0]", self._script())

    def test_the_hidden_attribute_survives_the_elements_own_css(self):
        # A class selector that sets `display` beats the UA's `[hidden]{display:none}`, so the summary
        # block rendered as empty Subtotal / Shipping / Total rows whenever there was nothing to show.
        self.assertIn('.sl-shipping [hidden]{display:none!important}', self.SOURCE)

    def test_every_shipping_rule_that_sets_display_is_covered_by_that_guard(self):
        import re

        rules = re.findall(r'"    (\.sl-shipping[\w-]*(?:\[[^\]]+\])?)\{([^}]*)\}"', self.SOURCE)
        setting_display = [name for name, body in rules
                           if "display:" in body and "[hidden]" not in name]
        # Any of these can carry `hidden` at runtime; the scoped guard is what keeps the attribute working.
        self.assertTrue(setting_display, "expected shipping rules that set display")
        self.assertIn('.sl-shipping [hidden]{display:none!important}', self.SOURCE)


class TheChosenServiceReachesTheLink(unittest.TestCase):
    """Setting `window.__jbShipQuote` is not the same as the CTA using it.

    The CTA's href is built ONCE at page load and rebuilt only when a PRICE CARD changes. The quote is
    fetched asynchronously, so the link was always frozen before the globals existed, and nothing ever
    rebuilt it when a shipping service was picked. The buyer chose a service, saw a total, and checked out
    with no postage -- while every test asserting "the quote rides to checkout" passed, because the
    PARAMETER was in the builder and the builder was never re-run.
    """

    def setUp(self):
        import stripe_link.runtime.html as module

        module._RENDER_SHIPPING.clear()
        render_shipping_selector({"id": "s"}, OFFER, PHYSICAL, API)
        self.js = render_shipping_selector_script()

    def test_the_element_rewrites_the_links_shipping_params(self):
        self.assertIn("var syncCta = function()", self.js)
        for param in ("ship_to_country", "shipping_quote", "shipping_service"):
            with self.subTest(param=param):
                self.assertIn(f"put('{param}'", self.js)

    def test_choosing_a_service_updates_the_link_not_just_a_global(self):
        choose = self.js.split("var choose = function(token, amount){", 1)[1].split("};", 1)[0]
        self.assertIn("syncCta()", choose)

    def test_an_absent_value_is_removed_rather_than_left_stale(self):
        # A buyer who changes country to one with no rates must not check out on the previous quote.
        self.assertIn("url.searchParams.delete(key)", self.js)

    def test_the_link_is_fixed_in_the_capture_phase_before_the_cta_reads_it(self):
        # A buyer who picks a tier and immediately hits Buy beats the async re-quote. That race would be
        # rare, silent, and would only ever cost the tenant money. The CTA's own handler reads `cta.href`
        # at click time, so a capture-phase rewrite lands before it.
        listener = self.js.split("'.sl-cta, [data-checkout-base-url]'", 1)[1][:80]
        self.assertIn("syncCta()", listener)
        self.assertIn("}, true);", listener)

    def test_a_tier_change_resyncs_the_link(self):
        tier = self.js.split(".sl-price-option')) return;", 1)[1][:160]
        self.assertIn("syncCta()", tier)

    def test_it_never_writes_an_amount_onto_the_link(self):
        self.assertNotIn("shipping_amount", self.js)
