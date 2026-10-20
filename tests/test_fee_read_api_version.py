"""The fee read must stay on a PRE-BASIL Stripe version.

Stripe's Basil release (2025-03-31) removed `charge` from the Invoice object, along with
`payment_intent` — whose absence is the entire reason the invoice route exists. `fetch_actual_fees_for_
invoice` reads `invoice.charge`, so the version pinned on that call is load-bearing.

Bumping it past Basil breaks nothing loudly. The expand returns nothing, `{}` comes back, the estimate
stands — which is a legitimate outcome on a settling delay — and the only visible symptom is the ledger
audit reporting a cent every five minutes forever. That is precisely the bug this route was written to
fix, so the pin is guarded rather than trusted.

If this ever needs to move, the replacement comes FIRST: /v1/invoice_payments, or expanding
`payments.data.payment.payment_intent` on the invoice.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Basil is the release that removed invoice.charge and invoice.payment_intent.
BASIL = "2025-03-31"


class TheFeeReadStaysPreBasilTests(unittest.TestCase):
    def _pinned(self):
        from handlers.stripe_webhook import FEE_READ_API_VERSION

        return FEE_READ_API_VERSION

    def test_the_pin_is_older_than_basil(self):
        pinned = self._pinned()
        self.assertLess(
            pinned[:10], BASIL,
            f"The invoice fee read is pinned to {pinned}, which is Basil or later. Basil removed "
            "invoice.charge, so this read now returns nothing — silently, leaving every renewal's fee "
            "as an estimate. Move to /v1/invoice_payments before changing this.")

    def test_the_request_actually_uses_that_constant(self):
        """A named constant nothing reads would pass this test and protect nothing."""
        import inspect

        from handlers import stripe_webhook

        source = inspect.getsource(stripe_webhook._fetch_fees)
        self.assertIn("FEE_READ_API_VERSION", source,
                      "the fee read no longer uses the constant this test guards")

    def test_the_invoice_route_reads_the_field_basil_removed(self):
        """States the dependency this guard exists for, so the link is not just a comment."""
        import inspect

        from handlers import stripe_webhook

        self.assertIn('invoice.get("charge")', inspect.getsource(stripe_webhook.fees_from_invoice))


if __name__ == "__main__":
    unittest.main()
