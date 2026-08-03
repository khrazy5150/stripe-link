import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from stripe_link.runtime.html import build_checkout_url
from stripe_link.runtime.publishing import checkout_base_url_for_page


def _q(url):
    return parse_qs(urlparse(url).query)


class CheckoutUrlModeTests(unittest.TestCase):
    """P4 (plans/STRIPE_MODE_DECOUPLING.md): the Buy URL carries the offer's Stripe mode as ?mode=, and the
    checkout host is the same for both modes (no dev/prod split)."""

    def _build(self, stripe_mode):
        return build_checkout_url(
            "https://prod.juniorbay.com/checkout",
            page={"tenant_id": "t1", "page_id": "p1"},
            offer={"offer_id": "o1", "stripe_mode": stripe_mode},
            product_id="prod1", price_id="price1", quantity="1",
        )

    def test_live_offer_bakes_mode_live(self):
        self.assertEqual(_q(self._build("live")).get("mode"), ["live"])

    def test_test_offer_bakes_mode_test(self):
        self.assertEqual(_q(self._build("test")).get("mode"), ["test"])

    def test_missing_mode_defaults_to_test(self):
        self.assertEqual(_q(self._build("")).get("mode"), ["test"])

    def test_checkout_base_is_host_agnostic(self):
        # Same host regardless of the offer's mode — the mode travels on the query, not the host.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PUBLIC_CHECKOUT_BASE_URL", None)
            os.environ.pop("CHECKOUT_BASE_URL", None)
            live = checkout_base_url_for_page({}, {"stripe_mode": "live"}, "prod")
            test = checkout_base_url_for_page({}, {"stripe_mode": "test"}, "dev")
        self.assertEqual(live, test)
        self.assertNotIn("dev.juniorbay.com", live)

    def test_configured_checkout_base_url_env_wins(self):
        with patch.dict(os.environ, {"PUBLIC_CHECKOUT_BASE_URL": "https://pay.example.com/checkout"}, clear=False):
            self.assertEqual(
                checkout_base_url_for_page({}, {"stripe_mode": "test"}, "dev"),
                "https://pay.example.com/checkout",
            )


if __name__ == "__main__":
    unittest.main()
