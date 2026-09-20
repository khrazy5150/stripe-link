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
