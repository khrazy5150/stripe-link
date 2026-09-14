"""A tip jar on a live page: the cards a supporter picks from, and what the server then charges.

plans/PAY_WHAT_YOU_WANT.md §3. The model and the wizard landed first; until this, a `customer_chooses`
product reached the page with no `unit_amount` and rendered as an ordinary tier card worth $0.00 — the same
"plausible wrong answer" the model work set out to kill, pointing the other way.

Author, 2026-09-13: "Each preset tip should create a separate card that the customer can choose from
(similar to multiple-product pricing). If a 'customer chooses' tip is allowed, then the last box should
create a textbox where the customer can enter a value between 1 and 500. When they do, the app will
recalculate the final entry with the fee (if anything other than 'standard' was set)."
"""
import copy
import json
import pathlib
import unittest
from decimal import Decimal

from handlers.checkout import apply_tip_amount, build_checkout_payload
from stripe_link.domain import tips
from stripe_link.domain.documents import validate_product_document
from stripe_link.domain.composition import default_cta_label
from stripe_link.domain.pricing import resolve_offer
from stripe_link.domain.tips import stamp_tip_jar
from stripe_link.runtime.html import product_json_ld, render_page, thin_content_warnings

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")


def _fixture(name):
    return json.loads((ROOT / "schemas" / "examples" / name).read_text(encoding="utf-8"))


def _tip_price(**overrides):
    return {
        "price_id": "price_tip", "currency": "usd", "quantity": 1,
        "pricing_model": "customer_chooses", "presets": [500, 1000, 2500],
        # What the buyer pays for each, net_guaranteed: the tenant keeps the round number.
        "preset_charges": [545, 1063, 2618],
        "allow_custom": True, "fee_handling": "net_guaranteed",
        "min_amount": tips.MIN_AMOUNT, "max_amount": tips.MAX_AMOUNT,
        **overrides,
    }


def _product(**price_overrides):
    product = copy.deepcopy(_fixture("product-creatine-gummies.json"))
    product["name"] = "Support the Cause"
    product["product_type"] = "digital"
    product["product_category"] = "tip"
    product["prices"] = [_tip_price(**price_overrides)]
    product["default_price_id"] = "price_tip"
    return product


def _offer(product):
    offer = copy.deepcopy(_fixture("offer-creatine-standard.json"))
    offer["offer_type"] = None
    offer["items"] = [{"product_id": product["product_id"], "price_id": "price_tip", "quantity": 1}]
    return offer


def _selector(html):
    """Just the rendered price selector.

    Absence assertions have to look HERE, not at the document: the stylesheet and the island script name
    every tip class and data attribute on every page, so `assertNotIn("data-tip-frequency", html)` passes
    only by accident. Three tests in this file have now been written the wrong way round.
    """
    start = html.index('<section class="sl-price-selector')
    return html[start:html.index("</section>", start)]


def _render(**price_overrides):
    product = _product(**price_overrides)
    return render_page(
        _fixture("page-creatine-standard.json"), _offer(product),
        {product["product_id"]: product}, api_base_url="https://api-dev.example.com",
    )


class CardTests(unittest.TestCase):
    def test_every_preset_gets_its_own_card(self):
        # The CHARGE is on the button, not the tenant's keyed amount: under net_guaranteed the buyer covers
        # the fees, so a $5.00 tip is a $5.45 card charge, and the button must say the number the statement
        # will say.
        html = _render()
        for amount, label in ((545, "$5.45"), (1063, "$10.63"), (2618, "$26.18")):
            self.assertIn(f'data-tip-amount="{amount}"', html)
            self.assertIn(f"<strong>{label}</strong>", html)
        # The same card the tier selector draws, so selection, styling and the CTA all work already.
        self.assertEqual(html.count('class="sl-price-option sl-tip-option"'), 3)

    def test_the_smallest_preset_starts_selected(self):
        html = _render()
        first = html.split('data-tip-amount="545"', 1)[1].split("</article>", 1)[0]
        self.assertIn('value="tip-545" aria-label="Tip $5.45" checked', html)
        self.assertIn("<strong>$5.45</strong>", first)
        # And the CTA advertises it, server-side -- not $0.00 until the island runs.
        self.assertIn('data-cta-amount="545"', html)
        self.assertIn("Continue To Checkout - $5.45", html)

    def test_an_older_document_still_renders_its_buttons(self):
        # Written before presets carried a keyed/charged split: those presets WERE the charged amounts, so
        # they read back as their own charges rather than rendering nothing.
        product = _product()
        product["prices"][0].pop("preset_charges")
        html = render_page(
            _fixture("page-creatine-standard.json"), _offer(product),
            {product["product_id"]: product}, api_base_url="https://api-dev.example.com",
        )
        self.assertIn('data-tip-amount="500"', html)
        self.assertIn("<strong>$5.00</strong>", html)

    def test_the_last_card_is_a_box_when_a_custom_amount_is_allowed(self):
        html = _render()
        card = html.split("sl-tip-custom", 1)[1].split("</article>", 1)[0]
        self.assertIn("data-tip-input", card)
        # Bounded in the markup as well as on the server: the box itself refuses 0 or 501.
        self.assertIn('min="1"', card)
        self.assertIn('max="500"', card)
        self.assertIn("$1.00 to $500.00.", card)

    def test_no_box_when_the_tenant_did_not_offer_one(self):
        # Asserted on the CARD, not on the string: the island's script mentions `.sl-tip-custom` on every
        # page, so a document-wide search finds it whether or not a box was rendered.
        html = _selector(_render(allow_custom=False))
        self.assertNotIn("sl-tip-custom", html)
        self.assertNotIn("<input type=\"number\"", html)

    def test_a_tip_card_carries_no_price_id_to_charge_against(self):
        # There is no per-amount Stripe price; the buyer's choice travels as tip_amount and the server
        # decides the charge. The price_id still rides along to say WHICH price was chosen.
        html = _render()
        self.assertIn('data-tip-source="preset"', html)
        self.assertIn('data-price-id="price_tip"', html)
        self.assertNotIn("$0.00", html)


class MarkupTests(unittest.TestCase):
    def test_the_structured_data_states_a_range_not_a_free_product(self):
        # `selected["unit_amount"]` is 0 for a tip jar, and emitting it would tell Google the page sells
        # something free -- a fabricated claim, which is the one thing this markup may never carry.
        product = _product()
        markup = product_json_ld(
            _fixture("page-creatine-standard.json"), _offer(product),
            {product["product_id"]: product}, {},
        )
        self.assertNotIn('"price":"0.00"', markup)
        self.assertNotIn('"price": "0.00"', markup)
        self.assertIn("priceSpecification", markup)
        self.assertIn('"minPrice":"1.00"', markup)
        self.assertIn('"maxPrice":"500.00"', markup)


class IslandTests(unittest.TestCase):
    """What the page's own script does with the cards."""

    def test_the_checkout_link_carries_the_chosen_amount(self):
        self.assertIn("params.set('tip_amount', keyed)", HTML)
        self.assertIn("params.set('tip_source', card.dataset.tipSource)", HTML)

    def test_the_typed_amount_is_priced_by_the_server(self):
        # Not by a copy of the fee formula living in the page script: a second implementation of the fee
        # maths is how the number on the button and the number on the statement come to disagree.
        self.assertIn("/prices/calculate", HTML)
        self.assertIn("pricing_model: 'customer_chooses'", HTML)
        # Standard fees need no round trip at all -- the tip IS the charge.
        self.assertIn("if (feeHandling === 'standard'", HTML)

    def test_the_box_can_price_itself_without_a_checkout_url(self):
        # A PREVIEW renders with no checkout_url, so the CTA carries no api base and no tenant -- and the box
        # quoted the tip without its fees, which is wrong by exactly the fees. The card carries its own.
        html = _render()
        self.assertIn('data-tip-api="https://api-dev.example.com"', html)
        self.assertIn('data-tip-tenant="', html)

    def test_it_never_quotes_a_total_it_could_not_work_out(self):
        self.assertIn("plus the card and platform fees", HTML)
        # Standard fee handling is the one case where the tip IS the charge, so it answers without a call.
        self.assertIn("if (feeHandling === 'standard') {", HTML)

    def test_an_empty_box_cannot_be_checked_out(self):
        self.assertIn("cta.dataset.tipNeedsAmount = needsTip ? 'true' : 'false'", HTML)
        self.assertIn("if (cta.dataset.tipNeedsAmount === 'true') {", HTML)
        self.assertIn("cta.textContent = 'Enter an amount'", HTML)


class ChargeTests(unittest.TestCase):
    """What the SERVER charges, which is the only number that matters."""

    def _resolved(self, **price_overrides):
        product = _product(**price_overrides)
        products = {product["product_id"]: product}
        return resolve_offer(_offer(product), products), products

    def test_a_resolved_tip_line_defaults_to_the_checked_preset(self):
        resolved, _ = self._resolved()
        self.assertEqual(resolved["items"][0]["unit_amount"], 545)
        self.assertEqual(resolved["subtotal"], 545)

    def test_a_preset_is_charged_at_the_number_the_card_displayed(self):
        resolved, products = self._resolved()
        apply_tip_amount(resolved, products, amount="2618", source="preset", tenant_id="t1")
        self.assertEqual(resolved["items"][0]["unit_amount"], 2618)
        self.assertEqual(resolved["subtotal"], 2618)

    def test_the_tenants_keyed_amount_is_not_a_chargeable_number(self):
        # $25.00 is what the creator KEEPS on that button; the card was charged $26.18. Accepting the keyed
        # figure would quietly undercharge every net_guaranteed tip by the fees.
        resolved, products = self._resolved()
        with self.assertRaises(tips.TipAmountError):
            apply_tip_amount(resolved, products, amount="2500", source="preset", tenant_id="t1")

    def test_an_amount_the_page_never_offered_is_refused(self):
        # The page's number is an input, not the authority: a crafted request naming $0.01 must not charge.
        resolved, products = self._resolved()
        with self.assertRaises(tips.TipAmountError):
            apply_tip_amount(resolved, products, amount="1", source="preset", tenant_id="t1")

    def test_a_typed_amount_is_grossed_up_when_the_buyer_covers_the_fees(self):
        resolved, products = self._resolved()
        apply_tip_amount(resolved, products, amount="2000", source="custom", tenant_id="t1")
        # net_guaranteed: the creator keeps the $20, so the buyer is charged more than it.
        self.assertGreater(resolved["items"][0]["unit_amount"], 2000)

    def test_a_typed_amount_is_charged_as_typed_when_the_creator_absorbs_the_fees(self):
        resolved, products = self._resolved(fee_handling="standard")
        apply_tip_amount(resolved, products, amount="2000", source="custom", tenant_id="t1")
        self.assertEqual(resolved["items"][0]["unit_amount"], 2000)

    def test_a_typed_amount_outside_the_platform_range_is_refused(self):
        resolved, products = self._resolved()
        for amount in (tips.MIN_AMOUNT - 1, tips.MAX_AMOUNT + 1):
            with self.assertRaises(tips.TipAmountError):
                apply_tip_amount(resolved, products, amount=amount, source="custom", tenant_id="t1")

    def test_a_typed_amount_is_refused_when_the_jar_offers_no_box(self):
        resolved, products = self._resolved(allow_custom=False)
        with self.assertRaises(tips.TipAmountError):
            apply_tip_amount(resolved, products, amount="2000", source="custom", tenant_id="t1")

    def test_no_amount_falls_back_to_the_checked_preset(self):
        # A CTA clicked before the island ran still charges a real, offered amount rather than $0.00.
        resolved, products = self._resolved()
        apply_tip_amount(resolved, products, amount="", source="preset", tenant_id="t1")
        self.assertEqual(resolved["items"][0]["unit_amount"], 545)

    def test_a_jar_with_nothing_to_fall_back_to_says_so(self):
        resolved, products = self._resolved(presets=[], allow_custom=True)
        with self.assertRaises(tips.TipAmountError):
            apply_tip_amount(resolved, products, amount="", source="preset", tenant_id="t1")

    def test_a_synced_price_id_cannot_charge_the_wrong_number(self):
        # A tip is always priced inline; a stale stripe_price_id would quietly charge whatever it holds.
        resolved, products = self._resolved(stripe_price_id="price_stale")
        apply_tip_amount(resolved, products, amount="1063", source="preset", tenant_id="t1")
        self.assertIsNone(products["prod_creatine_gummies"]["prices"][0].get("stripe_price_id"))


class StoredDocumentTests(unittest.TestCase):
    """The document as the TABLE returns it, which is not the document the fixtures build.

    DynamoDB hands every number back as a `Decimal`. The first cut checked `isinstance(amount, int)` on the
    preset lists, which passes for a JSON fixture and fails for anything that has actually been saved: the
    publisher refused the product, no artifact was written, and the page served a 404 while the builder's
    own preview (rendering from the in-memory draft) looked perfect. Found in the publish log, not in tests.
    """

    def _stored(self):
        product = _product()
        price = product["prices"][0]
        price["presets"] = [Decimal(amount) for amount in price["presets"]]
        price["preset_charges"] = [Decimal(amount) for amount in price["preset_charges"]]
        price["quantity"] = Decimal(1)
        return product

    def test_a_saved_tip_jar_still_validates(self):
        validate_product_document(self._stored())

    def test_a_saved_tip_jar_still_renders_its_buttons(self):
        product = self._stored()
        html = render_page(
            _fixture("page-creatine-standard.json"), _offer(product),
            {product["product_id"]: product}, api_base_url="https://api-dev.example.com",
        )
        self.assertIn('data-tip-amount="545"', html)
        self.assertIn("<strong>$26.18</strong>", html)

    def test_the_amounts_read_back_as_whole_numbers(self):
        price = self._stored()["prices"][0]
        self.assertEqual(tips.preset_amounts(price), [500, 1000, 2500])
        self.assertEqual(tips.preset_charges(price), [545, 1063, 2618])
        self.assertEqual(tips.preset_pairs(price), [(500, 545), (1000, 1063), (2500, 2618)])

    def test_a_flag_is_not_an_amount(self):
        # bool is an int subclass, so a naive numeric check reads True as 1.
        self.assertIsNone(tips.whole_amount(True))
        self.assertIsNone(tips.whole_amount(Decimal("1.5")))
        self.assertIsNone(tips.whole_amount(Decimal("-1")))
        self.assertEqual(tips.whole_amount(Decimal("500")), 500)


class FrequencyTests(unittest.TestCase):
    """How often the tip repeats, said on the cards (author, 2026-09-13).

    A tip jar that offers a monthly option and a card that says nothing about it leaves the supporter to
    find out from their statement. The tenant picks ONE interval; this is the supporter choosing whether to
    use it, so a recurring jar still takes one-off tips.
    """

    def _recurring(self, **overrides):
        return _render(allow_recurring=True, recurring_interval="week", **overrides)

    def test_every_card_says_what_it_will_charge(self):
        html = _selector(_render())
        self.assertEqual(html.count('class="sl-tip-freq" data-tip-freq>one-time</span>'), 4)

    def test_a_recurring_jar_offers_the_choice_once(self):
        html = _selector(self._recurring())
        self.assertIn('data-tip-frequency data-tip-interval="week" data-tip-word="weekly"', html)
        self.assertIn(">One-time</button>", html)
        self.assertIn(">Weekly</button>", html)
        # Asked once, above the amounts -- pairing every preset with every interval would be eight cards to
        # say four things.
        self.assertEqual(html.count("data-tip-frequency-value="), 2)

    def test_a_one_time_jar_asks_nothing(self):
        self.assertNotIn("sl-tip-frequency", _selector(_render()))

    def test_the_cards_restate_the_choice(self):
        # Otherwise the toggle says "Weekly" while every card still reads "one-time".
        self.assertIn("label.textContent = value === 'recurring' ? tipFreqWord : 'one-time'", HTML)
        self.assertIn("params.set('tip_recurring', '1')", HTML)

    def test_the_control_exists_before_anything_reads_it(self):
        # checkoutHref and updateCta close over tipFreq and both run at startup; a `const` read before its
        # declaration is a TDZ error, which takes the whole island -- not just the tip jar -- down.
        self.assertLess(HTML.index("const tipFreq"), HTML.index("cta.href = checkoutHref"))


class RecurringCheckoutTests(unittest.TestCase):
    def _resolved(self, **price_overrides):
        product = _product(**price_overrides)
        products = {product["product_id"]: product}
        return resolve_offer(_offer(product), products), products

    def _payload(self, resolved, products):
        return build_checkout_payload(
            tenant_id="t1", offer=_offer(products["prod_creatine_gummies"]), products_by_id=products,
            resolved=resolved, success_url="https://x/ok", cancel_url="https://x/no",
        )

    def test_a_repeating_tip_becomes_a_subscription(self):
        resolved, products = self._resolved(allow_recurring=True, recurring_interval="week")
        apply_tip_amount(resolved, products, amount="1063", source="preset", recurring=True, tenant_id="t1")
        payload = self._payload(resolved, products)
        self.assertEqual(payload["mode"], "subscription")
        self.assertEqual(payload["line_items[0][price_data][recurring][interval]"], "week")
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], "1063")

    def test_a_one_off_tip_is_still_a_payment(self):
        resolved, products = self._resolved(allow_recurring=True)
        apply_tip_amount(resolved, products, amount="1063", source="preset", tenant_id="t1")
        payload = self._payload(resolved, products)
        self.assertEqual(payload["mode"], "payment")
        self.assertNotIn("line_items[0][price_data][recurring][interval]", payload)

    def test_a_jar_that_offers_no_repeat_refuses_one(self):
        # Charging it once instead would hand the supporter a different thing than the one they picked.
        resolved, products = self._resolved()
        with self.assertRaises(tips.TipAmountError):
            apply_tip_amount(resolved, products, amount="1063", source="preset", recurring=True, tenant_id="t1")


class PageShapeTests(unittest.TestCase):
    """A tip jar page is not a sales page, and the page it composes has to agree."""

    def test_no_trust_badges(self):
        # "Secure checkout · Money-back guarantee" has nothing to say where nothing ships.
        product = _product()
        page = _fixture("page-creatine-standard.json")
        page["sections"] = [{"id": "tb", "type": "trust_badges", "badges": [{"label": "Secure checkout"}]}] + page["sections"]
        html = render_page(page, _offer(product), {product["product_id"]: product}, api_base_url="https://x")
        self.assertNotIn('data-section-type="trust_badges"', html)

    def test_the_button_does_not_say_buy(self):
        # Nothing is being bought, and the verb is the last thing a supporter reads before their card is
        # charged. From the shared rules file, so the builder's default and the renderer's cannot drift.
        self.assertEqual(default_cta_label({"pricing_model": "customer_chooses"}), "Send tip")
        self.assertEqual(default_cta_label({}), "")
        product = _product()
        offer = _offer(product)
        offer.setdefault("presentation", {}).pop("cta_label", None)
        page = _fixture("page-creatine-standard.json")
        page["sections"] = [s for s in page["sections"] if s.get("type") != "checkout_cta"]
        page["sections"].append({"id": "cta", "type": "checkout_cta"})
        products = {product["product_id"]: product}
        html = render_page(page, stamp_tip_jar(offer, products), products, api_base_url="https://x")
        self.assertIn("Send tip - ", html)
        self.assertNotIn("Buy Now", html)

    def test_the_thin_content_nudge_is_skipped(self):
        # Every remedy it offers -- a specifications table, condition details, an FAQ -- is uncallable on a
        # page with no product. A notice has to name something the tenant can do AND should do.
        product = _product()
        offer = stamp_tip_jar(_offer(product), {product["product_id"]: product})
        html = render_page(_fixture("page-creatine-standard.json"), offer,
                           {product["product_id"]: product}, api_base_url="https://x")
        self.assertEqual(thin_content_warnings(html, offer), [])
        # An ordinary product keeps it: there, thin really is thin.
        plain = copy.deepcopy(_fixture("product-creatine-gummies.json"))
        plain["prices"] = [{"price_id": "p1", "currency": "usd", "quantity": 1, "unit_amount": 1000}]
        plain["default_price_id"] = "p1"
        plain["description"] = ""
        plain_offer = _offer(plain)
        plain_offer["items"] = [{"product_id": plain["product_id"], "price_id": "p1", "quantity": 1}]
        plain_html = render_page(_fixture("page-creatine-standard.json"), plain_offer,
                                 {plain["product_id"]: plain}, api_base_url="https://x")
        self.assertTrue(thin_content_warnings(plain_html, plain_offer))


if __name__ == "__main__":
    unittest.main()
