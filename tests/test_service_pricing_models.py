"""A service is one-time only, and the code says so rather than the dropdown.

Found 2026-09-20 while answering "why don't services offer recurring pricing?". The answer was a deliberate
deferral (Phase 4 of plans/SERVICES_IN_OFFERS.md) -- but the deferral was enforced ONLY by a pricing dropdown
with one option. Everything underneath accepted a recurring service price and then mis-charged for it:

    service price says:   pricing_model=recurring, monthly
    resolved line says:   recurring = None          <- resolve_service_offer_item omits recurring_terms
    Stripe session mode:  payment                   <- so the customer is charged ONCE

Refused rather than honoured, deliberately. Honouring it would ship half a feature: Stripe would bill monthly
while nothing created the appointments each cycle pays for. plans/RECURRING_SERVICES.md plans the real thing.
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
    def test_one_time_is_the_only_model_a_service_may_carry(self):
        self.assertEqual(SERVICE_PRICING_MODELS, {"one_time"})

    def test_a_one_time_price_is_accepted(self):
        validate_service(_with_price("one_time"))
        validate_service(_with_price())          # absent means one_time

    def test_recurring_is_refused_in_prices(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_service(_with_price("recurring"))
        # The message has to say what to do, not just that something is wrong.
        self.assertIn("one_time", str(caught.exception))
        self.assertIn("RECURRING_SERVICES", str(caught.exception))

    def test_and_in_the_legacy_single_price(self):
        """Both shapes, or the guard is bypassed by the older one every service still carries."""
        with self.assertRaises(DocumentValidationError):
            validate_service(_with_price("recurring", legacy=True))

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

    def test_a_recurring_service_line_fails_loudly(self):
        """Refusing the checkout is bad. Charging a subscriber once and never again is worse, and silent."""
        with self.assertRaises(PricingError) as caught:
            resolve_offer(self.OFFER, {}, {}, services_by_id={"svc_1": self.SERVICE})
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
