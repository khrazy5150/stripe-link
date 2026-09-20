"""Recurring prices: the chain from the form to the Stripe subscription.

Found 2026-09-15. "Recurring" was a radio and nothing else: no interval was asked for, none was written, the
Stripe price was created as a ONE-TIME price, and the buyer was charged once — with nothing anywhere saying
so. A plausible wrong answer, which is the worst failure shape there is, and the second time this codebase
has shipped one (the tip jar was the first; plans/PAY_WHAT_YOU_WANT.md §1).

These tests walk the whole chain deliberately, because every link in it was individually reasonable and the
gap only existed BETWEEN them.
"""
import json
import pathlib
import unittest
from decimal import Decimal

from stripe_link.domain.documents import (
    DocumentValidationError,
    MAX_TRIAL_DAYS,
    RECURRING_INTERVALS,
    validate_product_document,
)
from stripe_link.domain.pricing import recurring_terms, resolve_offer
from stripe_link.domain.stripe_products import build_price_params, price_differs

ROOT = pathlib.Path(__file__).resolve().parents[1]
CARD = (ROOT / "dashboard" / "src" / "components" / "shared" / "PricingCard.vue").read_text(encoding="utf-8")
PRICE_FORM = (ROOT / "dashboard" / "src" / "utils" / "priceForm.js").read_text(encoding="utf-8")
PRICING_STORE = (ROOT / "dashboard" / "src" / "stores" / "pricing.js").read_text(encoding="utf-8")
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")


def _price(**overrides):
    price = {
        "price_id": "price_1", "currency": "usd", "quantity": 1, "unit_amount": 1700,
        "pricing_model": "recurring", "recurring": {"interval": "month", "interval_count": 1},
    }
    price.update(overrides)
    return price


def _product(price):
    return {
        "schema_version": "1", "document_type": "product", "tenant_id": "t", "product_id": "p",
        "name": "Membership", "product_category": "membership", "canonical": True, "status": "active",
        "tags": [], "default_price_id": price["price_id"], "prices": [price],
        "fulfillment": {"requires_shipping": False, "ship_from": None, "weight_lb": None,
                        "dimensions": {"length_in": None, "width_in": None, "height_in": None}},
        "sync": {"status": "pending", "last_synced_at": None, "error": None},
    }


class TheGuardTests(unittest.TestCase):
    """The rule that makes the original bug impossible to reproduce."""

    def test_a_recurring_price_without_an_interval_is_refused(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_document(_product(_price(recurring=None)))
        # The message names the CONSEQUENCE, because "missing field" would not tell anyone why it matters.
        self.assertIn("one-time charge", str(caught.exception))

    def test_an_empty_recurring_object_counts_as_none(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(recurring={})))

    def test_the_interval_is_not_defaulted(self):
        """Defaulting to "month" would be the same bug wearing a hat.

        It would silently pick a billing frequency on the tenant's behalf and charge their customers on it.
        Refusing is the only answer that cannot be wrong.
        """
        self.assertNotIn('recurring.setdefault("interval"',
                         (ROOT / "src" / "stripe_link" / "domain" / "documents.py").read_text(encoding="utf-8"))

    def test_a_one_time_price_is_unaffected(self):
        validate_product_document(_product(_price(pricing_model="one_time", recurring=None)))

    def test_the_four_stripe_intervals_are_accepted(self):
        for interval in RECURRING_INTERVALS:
            validate_product_document(_product(_price(recurring={"interval": interval, "interval_count": 1})))

    def test_an_invented_interval_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(recurring={"interval": "fortnight"})))

    def test_stripes_own_ceiling_is_respected(self):
        # Stripe will not bill less often than once a year, so "every 2 years" is refused here rather than
        # discovered at sync time as an opaque API error.
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(recurring={"interval": "year", "interval_count": 2})))
        validate_product_document(_product(_price(recurring={"interval": "month", "interval_count": 12})))

    def test_a_price_read_back_from_dynamodb_still_validates(self):
        """DynamoDB hands numbers back as Decimal, and the publish path re-validates what it reads.

        The form wrote interval_count as 1 and it validated; the publisher read Decimal("1") for the same
        field and refused it, so a page with a recurring price never rendered and never got its short-code
        route -- it just answered 404. Fixtures use int and pass either way, which is why nothing caught it.
        """
        product = _product(_price(recurring={"interval": "month", "interval_count": Decimal("1")}))
        validate_product_document(product)
        self.assertEqual(product["prices"][0]["recurring"]["interval_count"], 1)
        self.assertIsInstance(product["prices"][0]["recurring"]["interval_count"], int)

    def test_a_decimal_that_is_not_whole_is_still_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(recurring={"interval": "month", "interval_count": Decimal("1.5")})))

    def test_interval_count_defaults_to_one(self):
        product = _product(_price(recurring={"interval": "month"}))
        validate_product_document(product)
        self.assertEqual(product["prices"][0]["recurring"]["interval_count"], 1)


class TrialTests(unittest.TestCase):
    def test_a_trial_is_bounded(self):
        validate_product_document(_product(_price(trial_period_days=MAX_TRIAL_DAYS)))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(trial_period_days=MAX_TRIAL_DAYS + 1)))
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(_price(trial_period_days=0, trial_price=500)))

    def test_a_trial_fee_without_a_trial_is_just_a_surcharge(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_product_document(_product(_price(trial_price=700)))
        self.assertIn("surcharge", str(caught.exception))

    def test_a_paid_trial_is_allowed(self):
        validate_product_document(_product(_price(trial_period_days=14, trial_price=700)))


class StripeSyncTests(unittest.TestCase):
    def test_the_interval_reaches_stripe(self):
        params = build_price_params(_price(recurring={"interval": "week", "interval_count": 2}), "prod_x")
        self.assertEqual(params["recurring"], {"interval": "week", "interval_count": 2})

    def test_a_trial_is_never_sent_to_the_stripe_price(self):
        # Stripe applies trials at the SUBSCRIPTION level; a Price has no trial. Sending one would be an API
        # error, and baking it in would freeze it at sync time instead of reading it per checkout.
        params = build_price_params(_price(trial_period_days=14, trial_price=700), "prod_x")
        self.assertNotIn("trial_period_days", params)
        self.assertNotIn("trial_price", params)

    def test_changing_the_interval_replaces_the_stripe_price(self):
        # Stripe prices are immutable, so an interval change has to create a new one — otherwise the tenant
        # edits "monthly" to "yearly" and every subscriber keeps being billed monthly.
        local = _price(recurring={"interval": "year", "interval_count": 1})
        stripe_price = {"unit_amount": 1700, "currency": "usd",
                        "recurring": {"interval": "month", "interval_count": 1}}
        self.assertTrue(price_differs(local, stripe_price))


class ResolvedLineTests(unittest.TestCase):
    """The link that was missing entirely: the resolved LINE has to say it repeats."""

    def test_the_terms_travel_with_the_line(self):
        terms = recurring_terms(_price(recurring={"interval": "month", "interval_count": 3},
                                       trial_period_days=7, trial_price=500))
        self.assertEqual(terms["recurring"], {"interval": "month", "interval_count": 3})
        self.assertEqual(terms["trial_period_days"], 7)
        self.assertEqual(terms["trial_price"], 500)

    def test_a_one_time_price_carries_no_terms(self):
        self.assertEqual(recurring_terms(_price(pricing_model="one_time")), {})

    def test_a_stale_recurring_block_cannot_resubscribe_anybody(self):
        # Switched back to one-time in the builder, but the old object was left on the document. Gating on
        # pricing_model rather than on the object's presence is what stops that becoming a subscription.
        self.assertEqual(recurring_terms(_price(pricing_model="one_time",
                                                recurring={"interval": "month"})), {})

    def test_the_resolved_offer_exposes_it(self):
        price = _price(recurring={"interval": "month", "interval_count": 1}, trial_period_days=7)
        product = _product(price)
        offer = {
            "offer_id": "o1", "tenant_id": "t", "status": "active", "context": "standard",
            "items": [{"product_id": "p", "price_id": "price_1", "quantity": 1}],
        }
        resolved = resolve_offer(offer, {"p": product})
        line = resolved["items"][0]
        self.assertEqual(line["recurring"], {"interval": "month", "interval_count": 1})
        self.assertEqual(line["trial_period_days"], 7)


class BuilderTests(unittest.TestCase):
    def test_the_form_asks_for_an_interval_and_does_not_guess_one(self):
        block = PRICE_FORM.split("export function defaultPriceForm", 1)[1].split("\n}", 1)[0]
        self.assertIn('billing_interval: ""', block)
        self.assertIn("interval_count: 1", block)

    def test_the_form_reads_the_nested_shape_back(self):
        # Reading it through the tip's month/year field would turn a weekly subscription into a monthly one.
        block = PRICE_FORM.split("export function priceFormFromDocument", 1)[1].split("\n}", 1)[0]
        self.assertIn("price.recurring?.interval", block)
        self.assertIn("price.recurring?.interval_count", block)

    def test_the_document_writer_emits_the_nested_object(self):
        self.assertIn("price.recurring = {", PRICING_STORE)
        self.assertIn("interval: priceForm.billing_interval", PRICING_STORE)

    def test_the_card_asks_for_all_four_intervals_and_a_count(self):
        self.assertIn("BILLING_INTERVALS", CARD)
        self.assertIn("price.interval_count", CARD)
        self.assertIn("price.trial_enabled", CARD)
        self.assertIn("price.trial_days", CARD)
        for interval in RECURRING_INTERVALS:
            self.assertIn(f'["{interval}"', PRICE_FORM, interval)

    def test_the_tenant_is_warned_on_the_screen_that_holds_the_field(self):
        self.assertIn("price-recurring-warning", CARD)
        self.assertIn("not a subscription", CARD)

    def test_saving_and_advancing_are_both_blocked_without_one(self):
        self.assertIn('price.pricing_model === "recurring" && !price.billing_interval', PRODUCTS)
        self.assertIn("Choose a billing interval for your recurring price.", PRODUCTS)
        advance = PRODUCTS.split("const wizardCanAdvance = computed(", 1)[1].split("\n});", 1)[0]
        self.assertIn('wizardStepKey.value === "pricing"', advance)


class CheckoutSessionTests(unittest.TestCase):
    """The end of the chain: a repeating line has to produce a SUBSCRIPTION."""

    def _payload(self, line, *, synced=False, offer_mode="payment"):
        from handlers.checkout import build_checkout_payload
        price = {"price_id": "pr1", "unit_amount": 1700, "currency": "usd",
                 "pricing_model": "recurring", "recurring": {"interval": "month", "interval_count": 1}}
        if synced:
            price["stripe_price_id"] = "price_stripe_1"
        item = {"product_id": "p1", "price_id": "pr1", "quantity": 1, "unit_amount": 1700,
                "currency": "usd", "product_name": "Membership", **line}
        return build_checkout_payload(
            tenant_id="t1",
            offer={"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": offer_mode}},
            products_by_id={"p1": {"product_id": "p1", "name": "Membership", "prices": [price]}},
            resolved={"items": [item], "subtotal": 1700, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c",
        )

    def test_a_repeating_line_switches_the_session_to_subscription(self):
        # The offer says "payment"; the LINE says it repeats. Before this, the line said nothing and the
        # buyer was charged once.
        payload = self._payload({"recurring": {"interval": "month", "interval_count": 1}})
        self.assertEqual(payload["mode"], "subscription")

    def test_the_interval_reaches_an_inline_priced_line(self):
        payload = self._payload({"recurring": {"interval": "week", "interval_count": 2}})
        self.assertEqual(payload["line_items[0][price_data][recurring][interval]"], "week")
        self.assertEqual(payload["line_items[0][price_data][recurring][interval_count]"], "2")

    def test_a_synced_stripe_price_still_subscribes(self):
        # With a stripe_price_id there is no inline price_data to carry the interval, so the mode decision
        # can only come from the resolved line. This is the case the old `"[recurring]" in payload` style of
        # check would have missed.
        payload = self._payload({"recurring": {"interval": "month", "interval_count": 1}}, synced=True)
        self.assertEqual(payload["mode"], "subscription")
        self.assertEqual(payload["line_items[0][price]"], "price_stripe_1")

    def test_a_one_time_line_is_untouched(self):
        payload = self._payload({})
        self.assertEqual(payload["mode"], "payment")
        self.assertNotIn("subscription_data[trial_period_days]", payload)

    def test_a_free_trial_rides_on_the_subscription(self):
        payload = self._payload({"recurring": {"interval": "month", "interval_count": 1},
                                 "trial_period_days": 14})
        self.assertEqual(payload["subscription_data[trial_period_days]"], "14")
        # Free: no extra line.
        self.assertNotIn("line_items[1][price_data][unit_amount]", payload)

    def test_a_paid_trial_is_charged_as_its_own_line(self):
        # Stripe's trial is free by definition, so the fee cannot live inside it.
        payload = self._payload({"recurring": {"interval": "month", "interval_count": 1},
                                 "trial_period_days": 7, "trial_price": 700})
        self.assertEqual(payload["subscription_data[trial_period_days]"], "7")
        self.assertEqual(payload["line_items[1][price_data][unit_amount]"], "700")
        self.assertEqual(payload["line_items[1][quantity]"], "1")
        self.assertIn("trial", payload["line_items[1][price_data][product_data][name]"].lower())

    def test_the_trial_line_never_overwrites_a_real_one(self):
        # It is indexed at the item COUNT, and every resolved item consumes its own index above — services
        # included. Getting this wrong would silently replace what the buyer came for.
        payload = self._payload({"recurring": {"interval": "month", "interval_count": 1},
                                 "trial_period_days": 7, "trial_price": 700})
        self.assertEqual(payload["line_items[0][price_data][unit_amount]"], "1700")

    def test_bnpl_is_never_offered_on_a_subscription(self):
        from handlers.checkout import build_checkout_payload
        price = {"price_id": "pr1", "unit_amount": 1700, "currency": "usd",
                 "pricing_model": "recurring", "recurring": {"interval": "month", "interval_count": 1},
                 "stripe_price_id": "price_stripe_1"}
        payload = build_checkout_payload(
            tenant_id="t1", offer={"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"}},
            products_by_id={"p1": {"product_id": "p1", "name": "Membership", "prices": [price]}},
            resolved={"items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1, "unit_amount": 1700,
                                 "currency": "usd", "recurring": {"interval": "month", "interval_count": 1}}],
                      "subtotal": 1700, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c",
            bnpl_payment_method_types=["klarna"],
        )
        self.assertEqual(payload["mode"], "subscription")
        self.assertNotIn("payment_method_types[0]", payload)



class PublishedPageTests(unittest.TestCase):
    """The buyer-facing half. A subscription rendered as a bare number is the same bug seen from the other
    side: the tenant meant a subscription, the page showed a price, and the buyer found out on the second
    charge."""

    def test_the_card_says_how_often_it_charges(self):
        from stripe_link.runtime.html import recurring_suffix
        self.assertEqual(recurring_suffix(_price(recurring={"interval": "month", "interval_count": 1})), "/month")
        self.assertEqual(recurring_suffix(_price(recurring={"interval": "year", "interval_count": 1})), "/year")

    def test_a_multiple_interval_is_spelled_out(self):
        # "/3 month" reads as "per one"; the number is the whole point of setting it.
        from stripe_link.runtime.html import recurring_suffix
        self.assertEqual(recurring_suffix(_price(recurring={"interval": "week", "interval_count": 3})),
                         " every 3 weeks")

    def test_nothing_is_added_to_a_one_time_price(self):
        from stripe_link.runtime.html import recurring_suffix
        self.assertEqual(recurring_suffix(_price(pricing_model="one_time")), "")

    def test_a_tip_is_left_to_its_own_frequency_control(self):
        # A repeating tip's frequency is chosen by the SUPPORTER at checkout, not fixed on the price, and
        # render_tip_frequency already says so in its own words.
        from stripe_link.runtime.html import recurring_suffix
        self.assertEqual(recurring_suffix({"pricing_model": "customer_chooses",
                                           "recurring_interval": "month"}), "")

    def test_a_screen_reader_is_told_it_repeats_too(self):
        """The radio's aria-label is the whole card for a screen-reader user.

        It read "<name>, $32.91" while the sighted card read "$32.91/day", so the one user who cannot see the
        suffix was the one not told they were subscribing.
        """
        import re
        src = pathlib.Path(__file__).resolve().parents[1] / "src/stripe_link/runtime/html.py"
        labels = re.findall(r'aria-label=\\"\{label\}, \{escape\(format_money\(amount, currency\)\)\}([^\\]*)', src.read_text())
        self.assertEqual(len(labels), 2, "expected the product and service price-card radios")
        for tail in labels:
            self.assertIn("recurring_suffix", tail)

    def test_the_suffix_is_styled_quieter_than_the_amount(self):
        from stripe_link.runtime import html as html_module
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-price-every{", css)



if __name__ == "__main__":
    unittest.main()


class SelectablePriceLabelTests(unittest.TestCase):
    """Two cards both titled "1 Item" hide the only difference that matters.

    Offering a one-time price alongside a subscription is the main reason to turn on "Buyer chooses", and the
    seeded label for every option was the quantity -- so the buyer saw "1 Item $39.00" next to "1 Item
    $32.91/day" and had to read the suffix to find the difference the cards existed to present.
    """

    OFFERS = pathlib.Path(__file__).resolve().parents[1] / "dashboard/src/components/Offers.vue"

    def test_a_repeating_option_is_named_by_its_frequency(self):
        block = self.OFFERS.read_text(encoding="utf-8").split("function selectablePriceDefaultLabel", 1)[1][:900]
        self.assertIn("Every ${recurring.interval}", block)
        self.assertIn("Every ${count} ${recurring.interval}s", block)

    def test_a_one_time_option_still_reads_as_a_quantity(self):
        block = self.OFFERS.read_text(encoding="utf-8").split("function selectablePriceDefaultLabel", 1)[1][:900]
        self.assertIn('"Item" : "Items"', block)
