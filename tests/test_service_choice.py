"""Customer-chooses for services (plans/SERVICE_CHOICE.md).

Products carry an Item Mode; services carried nothing, so a tenant offering 60 / 90 / 120 minute massages
had no way to present them as alternatives. And the shape that looks like it should work did the worst
possible thing: an offer holding three services resolved to three LINES and charged the buyer $390 for a
$130 massage.

That is not a bug to delete -- several services in one offer has always meant a BUNDLE, coordinated by
service_booking_mode ("massage + facial in one visit"). Both meanings have to coexist, so the meaning is
declared: `service_selection`, absent => bundle, which is what every existing offer means.

duration_minutes lives on the SERVICE and is required, so 60/90/120 are three SERVICES, not three prices of
one -- which is why the product mechanism (selectable_prices on one item) does not reach this case.
"""
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_offer_document
from stripe_link.domain.opportunities import service_selection
from stripe_link.domain.pricing import chosen_service_item, resolve_offer
from stripe_link.runtime.html import render_offer_price_selector

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _service(sid, minutes, amount):
    return {"service_id": sid, "name": f"{minutes} minute massage", "duration_minutes": minutes,
            "fulfillment_mode": "scheduled", "booking_flow": "pay_then_book",
            "prices": [{"price_id": f"p_{sid}", "unit_amount": amount, "currency": "usd",
                        "pricing_model": "one_time"}]}


SERVICES = {s["service_id"]: s for s in (_service("svc60", 60, 9000),
                                         _service("svc90", 90, 13000),
                                         _service("svc120", 120, 17000))}


def _offer(**extra):
    return {"offer_id": "o1", "status": "active", "stripe_mode": "test", "checkout": {"mode": "payment"},
            "items": [{"service_id": sid, "price_id": f"p_{sid}", "quantity": 1,
                       "booking_flow": "pay_then_book"} for sid in SERVICES],
            **extra}


class DefaultIsBundleTests(unittest.TestCase):
    def test_an_offer_written_before_this_field_still_bundles(self):
        self.assertEqual(service_selection({}), "bundle")
        resolved = resolve_offer(_offer(), {}, {}, services_by_id=SERVICES)
        self.assertEqual([i["service_id"] for i in resolved["items"]], ["svc60", "svc90", "svc120"])
        self.assertEqual(resolved["subtotal"], 39000)

    def test_choice_is_never_inferred_from_the_items(self):
        # Two services in one visit is a real offer. Guessing would silently change what a published page
        # charges, so only the explicit field turns it on.
        self.assertEqual(service_selection({"items": [{"service_id": "a"}, {"service_id": "b"}]}), "bundle")


class ChoiceChargesOneTests(unittest.TestCase):
    def test_the_buyers_pick_is_the_only_line(self):
        resolved = resolve_offer(_offer(service_selection="choice"), {}, {},
                                 services_by_id=SERVICES, selected_service_id="svc90")
        self.assertEqual([i["service_id"] for i in resolved["items"]], ["svc90"])
        self.assertEqual(resolved["subtotal"], 13000)

    def test_no_pick_falls_back_to_the_offers_default(self):
        resolved = resolve_offer(_offer(service_selection="choice", default_service_id="svc120"), {}, {},
                                 services_by_id=SERVICES)
        self.assertEqual([i["service_id"] for i in resolved["items"]], ["svc120"])

    def test_no_pick_and_no_default_still_charges_something_offered(self):
        # A CTA clicked before the JS ran, or a link shared without a selection, must still charge the
        # option the page shows checked -- never nothing, and never all of them.
        resolved = resolve_offer(_offer(service_selection="choice"), {}, {}, services_by_id=SERVICES)
        self.assertEqual([i["service_id"] for i in resolved["items"]], ["svc60"])

    def test_an_unknown_selection_does_not_charge_everything(self):
        resolved = resolve_offer(_offer(service_selection="choice", default_service_id="svc90"), {}, {},
                                 services_by_id=SERVICES, selected_service_id="svc_deleted")
        self.assertEqual([i["service_id"] for i in resolved["items"]], ["svc90"])

    def test_the_page_and_the_checkout_agree_on_the_default(self):
        """The card rendered `checked` must be the line resolve_offer charges with no selection.

        Two independent answers to "which one is default" is how a page comes to show one price and charge
        another.
        """
        offer = _offer(service_selection="choice", default_service_id="svc120")
        html = render_offer_price_selector(offer, {}, SERVICES)
        checked = re.findall(r'<article[^>]*data-service-id="([^"]+)"[^>]*data-default="true"', html)
        resolved = resolve_offer(offer, {}, {}, services_by_id=SERVICES)
        self.assertEqual(checked, [i["service_id"] for i in resolved["items"]])


class ChoiceRendersOneGroupTests(unittest.TestCase):
    def test_every_card_shares_one_radio_group_and_one_is_checked(self):
        html = render_offer_price_selector(_offer(service_selection="choice", default_service_id="svc90"), {}, SERVICES)
        groups = set(re.findall(r'<input type="radio" name="([^"]+)"', html))
        self.assertEqual(groups, {"sl-service-choice"}, "alternatives must be ONE group or both can be picked")
        self.assertEqual(len(re.findall(r"<input type=\"radio\"[^>]*\schecked", html)), 1)

    def test_a_bundle_is_left_exactly_as_it_rendered_before(self):
        html = render_offer_price_selector(_offer(), {}, SERVICES)
        groups = set(re.findall(r'<input type="radio" name="([^"]+)"', html))
        self.assertEqual(groups, {"sl-price-svc60", "sl-price-svc90", "sl-price-svc120"})
        self.assertEqual(len(re.findall(r"<input type=\"radio\"[^>]*\schecked", html)), 3)


class ChosenItemOrderTests(unittest.TestCase):
    def test_the_buyer_beats_the_default(self):
        items = [{"service_id": "a"}, {"service_id": "b"}]
        self.assertEqual(chosen_service_item(items, "b", "a")["service_id"], "b")

    def test_products_are_not_service_items(self):
        self.assertIsNone(chosen_service_item([{"product_id": "p1"}]))


class DocumentTests(unittest.TestCase):
    def test_an_invented_selection_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_offer_document({"service_selection": "whatever"})


class WiringTests(unittest.TestCase):
    """The layers that only fail in a browser or at Stripe."""

    HTML = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
    CHECKOUT = (ROOT / "src/handlers/checkout.py").read_text(encoding="utf-8")
    OFFERS = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")

    def test_the_cta_sends_which_service_was_picked(self):
        # Service cards carry data-service-id with an EMPTY data-product-id, so without this param the
        # checkout cannot tell the alternatives apart.
        self.assertIn("const serviceId = card?.dataset.serviceId", self.HTML)
        self.assertIn("params.set('service_id', serviceId)", self.HTML)

    def test_checkout_reads_it_and_passes_it_to_resolution(self):
        self.assertIn('service_id = str(params.get("service_id")', self.CHECKOUT)
        self.assertIn("selected_service_id=service_id", self.CHECKOUT)

    def test_the_form_only_writes_the_field_when_it_means_something(self):
        block = self.OFFERS.split("service_selection: (serviceRows", 1)[1][:200]
        self.assertIn('=== "choice") ? "choice" : undefined', block)

    def test_loading_an_old_offer_cannot_flip_it_to_choice(self):
        block = self.OFFERS.split("form.service_selection = offer.service_selection", 1)[1][:120]
        self.assertIn('=== "choice" ? "choice" : "bundle"', block)


if __name__ == "__main__":
    unittest.main()


class ServiceSelectablePricesTests(unittest.TestCase):
    """One service, several ways to buy it: a single session beside a plan.

    The offer form showed a Price DROPDOWN -- the tenant picked one and the buyer got no say -- and
    validate_offer_document refused the alternative outright: "Service offer items must use price_id, not
    selectable_prices". A service now takes the same either/or a product does.
    """

    SERVICE = {"service_id": "svc_m", "name": "120 minute massage", "duration_minutes": 120,
               "fulfillment_mode": "scheduled", "booking_flow": "pay_then_book",
               "prices": [{"price_id": "p_once", "unit_amount": 27476, "currency": "usd",
                           "pricing_model": "one_time"},
                          {"price_id": "p_plan", "unit_amount": 19792, "currency": "usd",
                           "pricing_model": "recurring",
                           "recurring": {"interval": "day", "interval_count": 1}}]}

    def _offer(self):
        return {"offer_id": "o1", "status": "active", "stripe_mode": "test", "checkout": {"mode": "payment"},
                "items": [{"service_id": "svc_m", "quantity": 1, "booking_flow": "pay_then_book",
                           "selectable_prices": [{"price_id": "p_once", "label": "Single session"},
                                                 {"price_id": "p_plan", "label": "Every day"}],
                           "default_price_id": "p_once"}]}

    def test_both_prices_get_a_card(self):
        html = render_offer_price_selector(self._offer(), {}, {"svc_m": self.SERVICE})
        self.assertEqual(re.findall(r'data-price-id="(p_[a-z]+)"', html), ["p_once", "p_plan"])
        self.assertEqual(re.findall(r'<strong title="([^"]+)"', html), ["Single session", "Every day"])

    def test_they_are_one_radio_group_with_one_checked(self):
        html = render_offer_price_selector(self._offer(), {}, {"svc_m": self.SERVICE})
        self.assertEqual(set(re.findall(r'<input type="radio" name="([^"]+)"', html)), {"sl-price-svc_m"})
        self.assertEqual(len(re.findall(r"<input type=\"radio\"[^>]*\schecked", html)), 1)

    def test_the_buyers_pick_is_what_is_charged(self):
        for picked, amount, repeats in (("p_once", 27476, False), ("p_plan", 19792, True)):
            with self.subTest(picked=picked):
                resolved = resolve_offer(self._offer(), {}, {"svc_m": picked},
                                         services_by_id={"svc_m": self.SERVICE})
                line = resolved["items"][0]
                self.assertEqual(line["price_id"], picked)
                self.assertEqual(line["unit_amount"], amount)
                self.assertEqual(bool(line.get("recurring")), repeats)

    def test_no_pick_charges_the_card_shown_checked(self):
        resolved = resolve_offer(self._offer(), {}, {}, services_by_id={"svc_m": self.SERVICE})
        self.assertEqual(resolved["items"][0]["price_id"], "p_once")

    def test_a_price_the_offer_does_not_sell_is_refused_not_swapped(self):
        # Quietly charging an amount the page never showed is worse than an error.
        from stripe_link.domain.pricing import PricingError
        with self.assertRaises(PricingError):
            resolve_offer(self._offer(), {}, {"svc_m": "p_secret"}, services_by_id={"svc_m": self.SERVICE})

    def test_the_document_accepts_the_shape(self):
        from stripe_link.domain.documents import _validate_offer_item
        _validate_offer_item({"product_intent": "transaction"}, self._offer()["items"][0])

    def test_both_shapes_at_once_is_still_refused(self):
        from stripe_link.domain.documents import _validate_offer_item
        item = {**self._offer()["items"][0], "price_id": "p_once"}
        with self.assertRaises(DocumentValidationError):
            _validate_offer_item({"product_intent": "transaction"}, item)

    def test_the_form_never_writes_both(self):
        offers = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")
        block = offers.split("service_id: row.service_id,", 1)[1][:600]
        self.assertIn("price_id: selectable.length ? undefined : row.price_id", block)


class CardTitleTests(unittest.TestCase):
    """A service card headed by its own price says the amount twice.

    The offer form seeded each option's label from servicePriceOptionLabel() -- the MONEY string, which is
    right in the tenant's dropdown and wrong as the buyer-facing title, because the card shows the amount
    again in the price row directly below. Published offers carry those labels, so the page has to cope
    rather than wait for every tenant to retype them.
    """

    SERVICE = {"service_id": "svc_m", "name": "120 Minute Massage", "duration_minutes": 120,
               "fulfillment_mode": "scheduled",
               "prices": [{"price_id": "p1", "unit_amount": 27476, "currency": "usd",
                           "pricing_model": "one_time"},
                          {"price_id": "p2", "unit_amount": 19792, "currency": "usd",
                           "pricing_model": "recurring",
                           "recurring": {"interval": "day", "interval_count": 1}}]}

    def _titles(self, item):
        offer = {"offer_id": "o1", "status": "active", "stripe_mode": "test",
                 "checkout": {"mode": "payment"}, "items": [item]}
        html = render_offer_price_selector(offer, {}, {"svc_m": self.SERVICE})
        return re.findall(r'<strong title="([^"]+)"', html)

    def _options(self, *labels):
        return {"service_id": "svc_m", "quantity": 1, "default_price_id": "p2",
                "selectable_prices": [{"price_id": pid, "label": label}
                                      for pid, label in zip(("p1", "p2"), labels)]}

    def test_a_money_title_is_replaced_by_how_often_it_charges(self):
        # The service name is the same on every card and is already the page's H1, so it cannot tell the
        # options apart -- the frequency is the difference between them.
        self.assertEqual(self._titles(self._options("$274.76", "$197.92")), ["One time", "Every day"])

    def test_the_amount_is_still_shown_once(self):
        offer = {"offer_id": "o1", "status": "active", "stripe_mode": "test",
                 "checkout": {"mode": "payment"}, "items": [self._options("$274.76", "$197.92")]}
        html = render_offer_price_selector(offer, {}, {"svc_m": self.SERVICE})
        self.assertEqual(re.findall(r"data-price-amount>([^<]+)<", html), ["$274.76", "$197.92"])

    def test_a_money_title_with_its_suffix_is_caught_too(self):
        self.assertEqual(self._titles(self._options("$274.76", "$197.92/day"))[1], "Every day")

    def test_a_real_label_is_left_alone(self):
        self.assertEqual(self._titles(self._options("Single session", "Daily plan")),
                         ["Single session", "Daily plan"])

    def test_a_single_card_keeps_the_service_name(self):
        # Nothing to tell apart, so "One time" would be a downgrade from the service's own name.
        self.assertEqual(self._titles({"service_id": "svc_m", "price_id": "p1", "quantity": 1}),
                         ["120 Minute Massage"])

    def test_the_form_seeds_words_not_money(self):
        offers = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")
        block = offers.split("selectable_prices: selectable.length", 1)[1][:600]
        self.assertIn("serviceOptionDefaultLabel(", block)
        self.assertNotIn("label: row.labels?.[priceId] || servicePriceOptionLabel(", block)

    def test_a_stored_money_label_does_not_survive_a_re_save(self):
        offers = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")
        self.assertIn("isMoneyLabel(option.label,", offers)


class IndexCarriesTheIntervalTests(unittest.TestCase):
    """`pricing_model` says THAT a price repeats; only `recurring` says how often.

    The list projections dropped `recurring`, so every dashboard screen reading them could show a bare
    amount and nothing else -- a $197.92/day subscription and a $197.92 one-off were indistinguishable in
    the offer form's own price picker, which is exactly the choice the picker exists to present.

    This is the failure mode product_index's own comment already names: the default is WRONG rather than
    absent. A missing field here does not look missing on screen, it looks like a different price.
    """

    RECURRING = {"price_id": "p2", "unit_amount": 19792, "currency": "usd", "pricing_model": "recurring",
                 "recurring": {"interval": "day", "interval_count": 1}}

    def test_a_service_row_keeps_the_interval(self):
        from stripe_link.domain.service_index import service_index_entry
        entry = service_index_entry({"service_id": "s1", "name": "Massage", "prices": [self.RECURRING]})
        self.assertEqual(entry["prices"][0]["recurring"], {"interval": "day", "interval_count": 1})

    def test_a_product_row_keeps_the_interval(self):
        from stripe_link.domain.product_index import product_index_entry
        entry = product_index_entry({"product_id": "pr1", "name": "Gummies", "prices": [self.RECURRING]})
        self.assertEqual(entry["prices"][0]["recurring"], {"interval": "day", "interval_count": 1})

    def test_a_one_time_price_carries_no_empty_interval(self):
        from stripe_link.domain.service_index import service_index_entry
        entry = service_index_entry({"service_id": "s1", "name": "Massage",
                                     "prices": [{"price_id": "p1", "unit_amount": 27476,
                                                 "currency": "usd", "pricing_model": "one_time"}]})
        self.assertNotIn("recurring", entry["prices"][0])

    def test_both_pickers_append_the_suffix_they_now_have_the_data_for(self):
        offers = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")
        for fn in ("priceOptionLabel", "servicePriceOptionLabel"):
            with self.subTest(fn=fn):
                block = offers.split(f"function {fn}(price)", 1)[1][:700]
                self.assertIn("recurringSuffix(price)", block)
