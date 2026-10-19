"""A test-mode page must not touch the tenant's real analytics.

The page's pixel adapters send ViewContent, AddToCart, InitiateCheckout and Purchase to the tenant's own
GA4 property and Meta pixel. Fired from a test page those describe purchases that never happened — and
the Meta pixel is not merely a report: its optimiser LEARNS from conversion events, so a tenant testing
their own funnel trains the model their ad spend is optimised against. Deleting the data does not unteach
it. That makes this the most expensive leak in the mode sweep: the others corrupted a list or a rating.
"""
import unittest

from stripe_link.runtime.html import render_analytics_adapters, render_analytics_tags

ANALYTICS = {"google_tag_id": "G-ABC123", "pixel_id": "1234567890"}


class TheAdaptersThemselvesTests(unittest.TestCase):
    def test_they_send_purchase_events_when_configured(self):
        """What is at stake: this is a conversion signal, not a page counter."""
        out = render_analytics_adapters(ANALYTICS)
        self.assertIn("Purchase", out)
        self.assertIn("InitiateCheckout", out)

    def test_nothing_is_emitted_without_ids(self):
        self.assertEqual(render_analytics_adapters({}).strip(), "")
        self.assertEqual(render_analytics_tags({}).strip(), "")


class TheModeGateTests(unittest.TestCase):
    """`_page_is_live` decides whether the page's analytics are handed to the renderers at all."""

    def test_a_live_page_is_live(self):
        from stripe_link.runtime.html import _page_is_live
        self.assertTrue(_page_is_live({"stripe_mode": "live"}))

    def test_a_test_page_is_not(self):
        from stripe_link.runtime.html import _page_is_live
        self.assertFalse(_page_is_live({"stripe_mode": "test"}))

    def test_a_page_with_no_mode_counts_as_live(self):
        """Every page written before Stripe mode existed is a live one. Silently dropping a long-standing
        tenant's analytics would be a worse surprise than the thing this guards."""
        from stripe_link.runtime.html import _page_is_live
        self.assertTrue(_page_is_live({}))
        self.assertTrue(_page_is_live({"stripe_mode": ""}))

    def test_an_unexpected_value_counts_as_live(self):
        from stripe_link.runtime.html import _page_is_live
        self.assertTrue(_page_is_live({"stripe_mode": "sandbox"}))


if __name__ == "__main__":
    unittest.main()
