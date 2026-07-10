"""A landing page built from a SERVICE-based offer must render a price card (Stripe-critical) and a
hero, sourced from the service document — not silently drop the service item."""
import copy
import json
import unittest
from pathlib import Path

from stripe_link.runtime.html import render_offer_price_selector, render_page, require_offer_products

ROOT = Path(__file__).resolve().parents[1]


def _service():
    return {
        "schema_version": "2026-05-29", "document_type": "service", "tenant_id": "t1",
        "service_id": "svc_1", "name": "Tax Prep SVC", "description": "Simple tax preparation.",
        "fulfillment_mode": "no_booking",
        "price": {"currency": "usd", "unit_amount": 15000},
        "prices": [{"price_id": "svcprice_svc_1", "currency": "usd", "unit_amount": 15000, "context": "standard"}],
        "default_price_id": "svcprice_svc_1",
        "presentation": {"hero_image_url": "https://img.example.com/tax.jpg"},
    }


def _offer():
    return {
        "schema_version": "2026-05-29", "document_type": "offer", "tenant_id": "t1", "offer_id": "off_1",
        "name": "Tax Prep SVC", "product_intent": "transaction", "stripe_mode": "test", "status": "active",
        "items": [{"service_id": "svc_1", "price_id": "svcprice_svc_1", "quantity": 1}],
        "discount": {"mode": "none"}, "checkout": {"mode": "payment"},
    }


def _page():
    # A real, valid page shell; point it at the service offer.
    with (ROOT / "schemas" / "examples" / "page-creatine-standard.json").open() as handle:
        page = json.load(handle)
    page = copy.deepcopy(page)
    page["tenant_id"] = "t1"
    page["offer_id"] = "off_1"
    return page


class ServiceLandingPageTests(unittest.TestCase):
    def test_require_offer_products_skips_service_items(self):
        require_offer_products(_offer(), {})  # no products, only a service item — must not raise

    def test_price_selector_renders_service_card(self):
        html = render_offer_price_selector(_offer(), {}, {"svc_1": _service()})
        self.assertIn('data-service-id="svc_1"', html)
        self.assertIn('data-price-id="svcprice_svc_1"', html)
        self.assertIn("$150.00", html)  # 15000 cents
        self.assertIn("Tax Prep SVC", html)

    def test_render_page_service_offer_has_price_card_and_hero(self):
        html = render_page(_page(), _offer(), {}, services_by_id={"svc_1": _service()})
        self.assertIn('data-section-type="offer_price_selector"', html)
        self.assertIn('data-price-id="svcprice_svc_1"', html)
        self.assertIn("$150.00", html)
        self.assertIn("https://img.example.com/tax.jpg", html)  # hero from the service

    def test_render_page_service_offer_without_services_raises(self):
        # Guard: a service offer with no services_by_id must fail loudly (resolve_offer), not render blank.
        with self.assertRaises(Exception):
            render_page(_page(), _offer(), {})


if __name__ == "__main__":
    unittest.main()
