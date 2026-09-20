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
