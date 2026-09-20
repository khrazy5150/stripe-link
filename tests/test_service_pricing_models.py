"""What pricing models a service may carry, enforced by the code rather than by a dropdown.

Written 2026-09-20 when a recurring service price was REFUSED, because everything underneath would have
mis-charged for it:

    service price says:   pricing_model=recurring, monthly
    resolved line says:   recurring = None          <- resolve_service_offer_item omitted recurring_terms
    Stripe session mode:  payment                   <- so the customer was charged ONCE

Recurring is now SUPPORTED (plans/RECURRING_SERVICES.md §4b): the resolver applies the terms, checkout flips
to subscription mode and sends the interval, and each paid cycle grants booking credits. These tests moved
with it -- what they still guard is that the narrowing is only ever widened alongside the machinery, and that
`customer_chooses`, which has no implementation, stays out.
"""
import unittest

from stripe_link.domain.documents import (
    SERVICE_PRICING_MODELS, DocumentValidationError, validate_service,
)
from stripe_link.domain.pricing import PricingError, resolve_offer

BASE = {
    "schema_version": "1", "document_type": "service", "tenant_id": "t", "service_id": "svc_1",
    "name": "Lawn care", "duration_minutes": 60, "price": {"currency": "usd", "unit_amount": 12000},
}


def _with_price(model=None, legacy=False):
    price = {"price_id": "p1", "currency": "usd", "unit_amount": 12000}
    if model:
        price["pricing_model"] = model
    if legacy:
        return {**BASE, "price": {"currency": "usd", "unit_amount": 12000, **({"pricing_model": model} if model else {})}}
    return {**BASE, "prices": [price]}


class ValidatorTests(unittest.TestCase):
    def test_a_service_may_be_one_time_or_recurring_and_nothing_else(self):
        """`customer_chooses` stays out: a pay-what-you-want booked service has no implementation, and a
        price with no amount resolving through the booking flow is the mis-charge in another costume."""
        self.assertEqual(SERVICE_PRICING_MODELS, {"one_time", "recurring"})

    def test_a_one_time_price_is_accepted(self):
        validate_service(_with_price("one_time"))
        validate_service(_with_price())          # absent means one_time

    def test_recurring_needs_an_interval(self):
        """The same rule the product path enforces, through the same helper.

        A recurring price with no interval is the original bug: it syncs as a one-time price and charges
        once. Defaulting to "month" would be that bug wearing a hat -- it picks a billing frequency on the
        tenant's behalf and charges their customers on it.
        """
        with self.assertRaises(DocumentValidationError) as caught:
            validate_service(_with_price("recurring"))
        self.assertIn("recurring.interval", str(caught.exception))

    def test_recurring_with_an_interval_is_accepted(self):
        doc = _with_price("recurring")
        doc["prices"][0]["recurring"] = {"interval": "month", "interval_count": 1}
        validate_service(doc)

    def test_the_legacy_single_price_is_checked_too(self):
        """Both shapes, or the guard is bypassed by the older one every service still carries."""
        with self.assertRaises(DocumentValidationError):
            validate_service(_with_price("recurring", legacy=True))   # no interval

    def test_customer_chooses_is_refused_too(self):
        # Also Phase 4, and a tip-jar pricing model has no meaning on a booked service.
        with self.assertRaises(DocumentValidationError):
            validate_service(_with_price("customer_chooses"))


class ResolverGuardTests(unittest.TestCase):
    """Belt and braces: a document that never passed the validator must still not mis-charge."""

    SERVICE = {
        "service_id": "svc_1", "name": "Monthly lawn care", "active": True,
        "fulfillment_mode": "no_booking", "default_price_id": "p1",
        "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": 12000,
                    "pricing_model": "recurring", "recurring": {"interval": "month"}}],
    }
    OFFER = {
        "offer_id": "o1", "tenant_id": "t1", "status": "active", "checkout": {},
        "items": [{"service_id": "svc_1", "price_id": "p1", "quantity": 1}],
    }

    def test_a_recurring_service_line_now_carries_its_terms(self):
        """The line the mis-charge came from. `recurring` reaching the resolved item is what makes checkout
        choose subscription mode."""
        resolved = resolve_offer(self.OFFER, {}, {}, services_by_id={"svc_1": self.SERVICE})
        self.assertEqual(resolved["items"][0]["recurring"], {"interval": "month", "interval_count": 1})

    def test_an_unimplemented_model_still_fails_loudly(self):
        """Refusing a checkout is bad. Charging someone the wrong way is worse, and silent.

        Only a hand-edited or imported document reaches this -- validate_service refuses to store one.
        """
        service = {**self.SERVICE,
                   "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": 12000,
                               "pricing_model": "customer_chooses"}]}
        with self.assertRaises(PricingError) as caught:
            resolve_offer(self.OFFER, {}, {}, services_by_id={"svc_1": service})
        self.assertIn("not supported", str(caught.exception))

    def test_a_one_time_service_still_resolves(self):
        service = {**self.SERVICE, "prices": [{"price_id": "p1", "currency": "usd", "unit_amount": 12000}]}
        resolved = resolve_offer(self.OFFER, {}, {}, services_by_id={"svc_1": service})
        self.assertEqual(resolved["items"][0]["unit_amount"], 12000)


class DropdownMatchesValidatorTests(unittest.TestCase):
    """The dropdown and the validator are two things that must agree.

    Nothing forced them to before -- which is how a UI-only restriction came to be the sole protection
    against a mis-charge. This is the thing that forces it.
    """

    def test_the_ui_offers_nothing_the_validator_would_reject(self):
        import pathlib
        import re

        store = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "stores"
                 / "services.js").read_text(encoding="utf-8")
        line = [l for l in store.splitlines() if "SERVICE_PRICING_MODELS" in l][0]
        offered = set(re.findall(r'\["(\w+)",', line))
        self.assertTrue(offered, "could not read the offered pricing models")
        self.assertTrue(
            offered <= SERVICE_PRICING_MODELS,
            f"the services form offers {offered - SERVICE_PRICING_MODELS}, which validate_service refuses",
        )


if __name__ == "__main__":
    unittest.main()
