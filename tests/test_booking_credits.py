"""Booking credits: what a recurring service subscription grants.

plans/RECURRING_SERVICES.md §4b. A recurring service is not a standing appointment -- the customer buys
entitlement ("four cuts a month") and books each visit through the booking flow that already exists. Credits
are what connect the subscription to the bookings.

Named `booking_credits`, NOT `entitlements`: `domain/entitlements.py` already exists and means something
else entirely -- the PLAN capabilities a tenant's subscription to US unlocks. This is what a tenant's
customer bought from THEM. I learned that by overwriting the wrong file.
"""
import unittest

from stripe_link.domain.booking_credits import (
    DEFAULT_BOOKINGS_PER_CYCLE, MAX_BOOKINGS_PER_CYCLE, EntitlementError,
    bookings_per_cycle, build_entitlement, entitlement_id_for, refill, restore, spend,
)

SERVICE = {"service_id": "svc_1", "name": "Haircut", "bookings_per_cycle": 4}


def _granted(**over):
    return build_entitlement(tenant_id="t1", service=SERVICE, subscription_id="sub_1", now=100, **over)


class GrantTests(unittest.TestCase):
    def test_a_cycle_grants_what_the_service_says(self):
        self.assertEqual(_granted()["credits_remaining"], 4)

    def test_a_service_that_says_nothing_grants_one(self):
        """A subscription granting NO bookings is a product subscription wearing a service's name."""
        entitlement = build_entitlement(tenant_id="t1", service={"service_id": "s", "name": "x"},
                                        subscription_id="sub", now=1)
        self.assertEqual(entitlement["credits_remaining"], DEFAULT_BOOKINGS_PER_CYCLE)

    def test_an_absurd_grant_is_refused(self):
        # A typo -- 100 for 10 -- would quietly promise a year of daily visits.
        with self.assertRaises(EntitlementError):
            bookings_per_cycle({"bookings_per_cycle": MAX_BOOKINGS_PER_CYCLE + 1})
        with self.assertRaises(EntitlementError):
            bookings_per_cycle({"bookings_per_cycle": 0})

    def test_the_id_is_derived_not_random(self):
        """The webhook that GRANTS a cycle and the one that REFILLS it arrive as separate Stripe events
        with nothing but these two ids in common. A random id would orphan the row on the first renewal."""
        self.assertEqual(entitlement_id_for("sub_1", "svc_1"), "ent_sub_1_svc_1")
        self.assertEqual(_granted()["entitlement_id"], entitlement_id_for("sub_1", "svc_1"))


class SpendTests(unittest.TestCase):
    def test_each_booking_takes_one(self):
        self.assertEqual(spend(_granted())["credits_remaining"], 3)

    def test_it_refuses_rather_than_going_negative(self):
        entitlement = _granted()
        for _ in range(4):
            entitlement = spend(entitlement)
        with self.assertRaises(EntitlementError) as caught:
            spend(entitlement)
        # The message is shown to a customer, so it says when they can book again.
        self.assertIn("renews", str(caught.exception))

    def test_an_inactive_plan_cannot_be_spent(self):
        with self.assertRaises(EntitlementError):
            spend({**_granted(), "status": "canceled"})


class CancellationTests(unittest.TestCase):
    def test_cancelling_a_booking_gives_the_credit_back(self):
        """Otherwise cancelling costs a visit, which reads as a penalty for doing the considerate thing."""
        entitlement = spend(_granted())
        self.assertEqual(restore(entitlement)["credits_remaining"], 4)

    def test_but_never_more_than_the_cycle_granted(self):
        # A cancellation must not leave someone holding more than they bought.
        self.assertEqual(restore(_granted())["credits_remaining"], 4)


class RenewalTests(unittest.TestCase):
    def test_a_paid_cycle_resets_the_balance(self):
        spent = spend(spend(_granted()))
        self.assertEqual(refill(spent, service=SERVICE, now=200)["credits_remaining"], 4)

    def test_unused_visits_do_NOT_roll_over(self):
        """Rollover turns a balance into an account with a history, and the plan puts it out of scope:
        expiring is simpler and is what such plans do. A tenant wanting rollover wants a different product."""
        untouched = _granted()
        self.assertEqual(refill(untouched, service=SERVICE, now=200)["credits_remaining"], 4)

    def test_a_changed_grant_takes_effect_next_cycle(self):
        # Re-read from the service, so "four cuts" becoming "six cuts" happens rather than never happening.
        bigger = {**SERVICE, "bookings_per_cycle": 6}
        self.assertEqual(refill(_granted(), service=bigger, now=200)["credits_remaining"], 6)


class ServiceValidationTests(unittest.TestCase):
    def test_the_service_validator_uses_the_same_rule(self):
        """One definition of a legal grant, shared by the form, the webhook and the validator."""
        from stripe_link.domain.documents import DocumentValidationError, validate_service

        base = {"schema_version": "1", "document_type": "service", "tenant_id": "t", "service_id": "s",
                "name": "Cuts", "duration_minutes": 45, "price": {"currency": "usd", "unit_amount": 1}}
        validate_service({**base, "bookings_per_cycle": 4})
        with self.assertRaises(DocumentValidationError):
            validate_service({**base, "bookings_per_cycle": 999})


if __name__ == "__main__":
    unittest.main()


class PurchaseGrantsCreditsTests(unittest.TestCase):
    """A recurring service line must not create an appointment.

    plans/RECURRING_SERVICES.md §4b: it sells ENTITLEMENT, not a slot. Creating one appointment at purchase
    would pick a time nobody chose, and would create exactly one for a subscription meant to produce many.
    """

    LINES = [
        {"service_id": "a", "fulfillment_mode": "scheduled"},
        {"service_id": "b", "fulfillment_mode": "no_booking"},
        {"service_id": "c", "fulfillment_mode": "scheduled", "recurring": True, "bookings_per_cycle": 4},
    ]

    def test_the_recurring_line_is_excluded_from_the_appointment_fan_out(self):
        from stripe_link.domain.booking import group_purchased_service_lines

        groups, no_booking = group_purchased_service_lines(self.LINES, "single_visit")
        self.assertEqual([[l["service_id"] for l in g] for g in groups], [["a"]])
        self.assertEqual([l["service_id"] for l in no_booking], ["b"])

    def test_and_is_picked_out_for_granting_instead(self):
        from stripe_link.domain.booking import recurring_purchased_lines

        self.assertEqual([l["service_id"] for l in recurring_purchased_lines(self.LINES)], ["c"])

    def test_the_checkout_metadata_carries_what_the_webhook_needs(self):
        """The webhook sees a Stripe session, not the offer -- it cannot re-derive either of these."""
        import json

        from handlers.checkout import build_checkout_payload
        from stripe_link.domain.pricing import resolve_offer

        service = {"service_id": "svc_1", "name": "Haircut", "active": True, "duration_minutes": 45,
                   "fulfillment_mode": "scheduled", "default_price_id": "p1", "bookings_per_cycle": 4,
                   "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": 12000,
                               "pricing_model": "recurring",
                               "recurring": {"interval": "month", "interval_count": 1}}]}
        offer = {"offer_id": "o1", "tenant_id": "t1", "status": "active", "checkout": {},
                 "items": [{"service_id": "svc_1", "price_id": "p1", "quantity": 1}]}
        resolved = resolve_offer(offer, {}, {}, services_by_id={"svc_1": service})
        payload = build_checkout_payload(offer=offer, resolved=resolved, products_by_id={}, tenant_id="t1",
                                         success_url="https://e/ok", cancel_url="https://e/no")
        line = json.loads(payload["metadata[service_lines]"])[0]
        self.assertTrue(line["recurring"])
        self.assertEqual(line["bookings_per_cycle"], 4)
        # ...and the session must actually be a subscription, with its interval, or Stripe rejects it.
        self.assertEqual(payload["mode"], "subscription")
        self.assertEqual(payload["line_items[0][price_data][recurring][interval]"], "month")


class ResolvedItemSerialisationTests(unittest.TestCase):
    def test_every_field_of_the_resolved_item_reaches_the_dict(self):
        """`resolve_offer` serialises ResolvedOfferItem through an explicit field list.

        Add a field to the dataclass, forget the list, and it silently vanishes between the resolver and
        checkout -- which is exactly what happened to `bookings_per_cycle` on its first attempt.
        """
        import dataclasses

        from stripe_link.domain.pricing import ResolvedOfferItem, resolve_offer

        service = {"service_id": "s", "name": "x", "active": True, "duration_minutes": 30,
                   "default_price_id": "p", "prices": [{"price_id": "p", "currency": "usd", "unit_amount": 1}]}
        offer = {"offer_id": "o", "tenant_id": "t", "status": "active", "checkout": {},
                 "items": [{"service_id": "s", "price_id": "p", "quantity": 1}]}
        serialised = set(resolve_offer(offer, {}, {}, services_by_id={"s": service})["items"][0])
        declared = {f.name for f in dataclasses.fields(ResolvedOfferItem)}
        self.assertEqual(declared - serialised, set())


class PlanBookingTests(unittest.TestCase):
    """Spending a credit at the moment the customer books."""

    def setUp(self):
        from handlers.booking import _spend_plan_credit

        self.spend_credit = _spend_plan_credit
        self.entitlement = build_entitlement(tenant_id="t1", service=SERVICE, subscription_id="sub_1",
                                             customer={"email": "buyer@example.com"}, now=100)

    class Repo:
        def __init__(self, doc=None):
            self.doc, self.written = doc, []

        def get(self, _tenant, _id):
            return self.doc

        def put(self, doc):
            self.written.append(doc)
            self.doc = doc
            return doc

    def _spend(self, **over):
        args = {"tenant_id": "t1", "entitlement_id": self.entitlement["entitlement_id"],
                "service_id": "svc_1", "customer": {"email": "buyer@example.com"}, "now": 200}
        args.update(over)
        return self.spend_credit(self.Repo(self.entitlement), **args)

    def test_an_ordinary_booking_is_untouched(self):
        # No entitlement claimed: not a plan booking, and nothing is looked up.
        self.assertEqual(self._spend(entitlement_id=""), {})

    def test_a_valid_plan_spends_one(self):
        result = self._spend()
        self.assertTrue(result["spent"])
        self.assertEqual(result["credits_remaining"], 3)

    def test_a_plan_for_a_DIFFERENT_service_is_refused(self):
        self.assertIn("does not cover", self._spend(service_id="svc_other")["error"])

    def test_someone_else_cannot_spend_your_visits(self):
        """The id is derived from a Stripe subscription id, so it is hard to guess -- but hard to guess is
        not authorised. The booking email must match the one the plan was bought with."""
        self.assertIn("different customer", self._spend(customer={"email": "thief@example.com"})["error"])

    def test_an_exhausted_plan_is_refused_rather_than_going_negative(self):
        self.entitlement = {**self.entitlement, "credits_remaining": 0}
        self.assertIn("used all", self._spend()["error"])

    def test_the_credit_is_taken_AFTER_the_slot_is_held(self):
        """Taking a credit for a slot we then fail to claim would charge someone a visit they did not get."""
        import inspect

        from handlers import booking

        source = inspect.getsource(booking.reserve_route)
        self.assertLess(source.index("slot_locks_repo.claim("), source.index("_spend_plan_credit("))


class FormTests(unittest.TestCase):
    """The tenant-facing half: a service can be made recurring, and asked how much a cycle buys."""

    import pathlib as _pathlib

    DASH = _pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
    STORE = (DASH / "stores" / "services.js").read_text(encoding="utf-8")
    WIZARD = (DASH / "components" / "services" / "ServiceWizard.vue").read_text(encoding="utf-8")
    EDITOR = (DASH / "components" / "Services.vue").read_text(encoding="utf-8")

    def test_the_form_offers_recurring(self):
        """PricingCard renders the model radio only when there is more than one model, so this single line
        is what reveals both the radio and the billing-interval block products already had."""
        self.assertIn('["recurring", "Recurring"]', self.STORE)

    def test_it_does_not_offer_what_the_validator_refuses(self):
        from stripe_link.domain.documents import SERVICE_PRICING_MODELS
        import re

        line = [l for l in self.STORE.splitlines() if "export const SERVICE_PRICING_MODELS" in l][0]
        self.assertTrue(set(re.findall(r'\["(\w+)",', line)) <= SERVICE_PRICING_MODELS)

    def test_bookings_per_cycle_is_asked_in_both_surfaces(self):
        for name, src in (("wizard", self.WIZARD), ("editor", self.EDITOR)):
            self.assertIn("form.bookings_per_cycle", src, name)
            self.assertIn('v-if="hasRecurringPrice"', src, name)

    def test_it_is_only_asked_when_a_price_recurs(self):
        """On a one-time service the number means nothing -- and a field that means nothing still gets
        answered, then stored, then believed by whoever reads the document next."""
        for name, src in (("wizard", self.WIZARD), ("editor", self.EDITOR)):
            block = src.split("const hasRecurringPrice", 1)[1].split(";", 1)[0]
            self.assertIn('pricing_model === "recurring"', block, name)

    def test_it_is_only_STORED_when_a_price_recurs(self):
        build = self.STORE.split("bookings_per_cycle: prices.some", 1)[1].split(",\n", 1)[0]
        self.assertIn("undefined", build)

    def test_the_saved_shape_passes_the_validator(self):
        """The whole round trip: what the form builds is what validate_service accepts."""
        from stripe_link.domain.documents import validate_service

        validate_service({
            "schema_version": "2026-05-29", "document_type": "service", "tenant_id": "t",
            "service_id": "svc_1", "name": "Haircut club", "duration_minutes": 45,
            "bookings_per_cycle": 4, "price": {"currency": "usd", "unit_amount": 12000},
            "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": 12000,
                        "pricing_model": "recurring", "recurring": {"interval": "month", "interval_count": 1}}],
            "default_price_id": "p1", "booking_flow": "pay_then_book", "active": True,
        })
