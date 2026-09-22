"""The campaign coupon element (plans/COUPON_ELEMENT.md).

The tenant emails a ticket; the visitor taps it and lands on a page that shows the SAME ticket and takes
them to a checkout with the discount already on it. The whole ticket is the link, because someone who
tapped a coupon in an email expects to tap the same thing again.

Smart by the offer's own shape, not a setting: a transacting offer carries the code into checkout, and a
lead offer -- which by composition has no checkout at all -- links to the destination it names.
"""
import unittest

from unittest.mock import patch

from stripe_link.runtime.html import coupon_checkout_href, coupon_is_live, render_coupon

CHECKOUT = "https://dev.juniorbay.com/checkout?clientID=t1&offer=offer_1"
FUTURE = 4102444800   # 2100
PAST = 1262304000     # 2010


def _section(**over):
    section = {"id": "c1", "type": "coupon", "code": "MASSAGE20", "value_text": "$20 OFF",
               "headline": "Your first 60-minute massage", "terms": "New clients only.",
               "expires_at": FUTURE}
    section.update(over)
    return section


def _offer(**over):
    offer = {"offer_id": "offer_1", "items": [{"product_id": "p1"}]}
    offer.update(over)
    return offer


def _lead_offer():
    return _offer(product_intent="lead_gen", lead_capture_action="external_url")


class SmartBehaviourTests(unittest.TestCase):
    def test_a_transacting_offer_carries_the_code_into_checkout(self):
        html = render_coupon(_section(), _offer(), checkout_url=CHECKOUT)
        self.assertIn("coupon=MASSAGE20", html)
        self.assertIn("/checkout?", html)

    def test_a_lead_offer_links_to_its_destination_instead(self):
        # A lead_gen offer gets no checkout page at all, so sending it to one would be a dead link.
        html = render_coupon(_section(destination_url="https://spa.example.com/book"),
                             _lead_offer(), checkout_url=CHECKOUT)
        self.assertIn('href="https://spa.example.com/book"', html)
        self.assertNotIn("/checkout?", html)

    def test_the_whole_ticket_is_the_link(self):
        html = render_coupon(_section(), _offer(), checkout_url=CHECKOUT)
        self.assertTrue(html.strip().startswith("<a "), "the coupon itself must be the click target")

    def test_the_code_survives_a_url_that_already_has_a_query(self):
        self.assertEqual(coupon_checkout_href("https://x/c?a=1", "SAVE 10"), "https://x/c?a=1&coupon=SAVE%2010")
        self.assertEqual(coupon_checkout_href("https://x/c", "S10"), "https://x/c?coupon=S10")

    def test_no_checkout_url_yields_no_link_rather_than_a_broken_one(self):
        html = render_coupon(_section(), _offer(), checkout_url="")
        self.assertNotIn("<a ", html)
        self.assertIn("MASSAGE20", html)


class ExpiryTests(unittest.TestCase):
    def test_an_expired_coupon_still_renders(self):
        # An email outlives its deadline; a page with a hole in it reads as broken.
        html = render_coupon(_section(expires_at=PAST), _offer(), checkout_url=CHECKOUT)
        self.assertIn("MASSAGE20", html)
        self.assertIn("sl-coupon-expired", html)

    def test_an_expired_coupon_does_not_link_to_checkout(self):
        # Checkout must not be where the visitor discovers the offer ended.
        html = render_coupon(_section(expires_at=PAST), _offer(), checkout_url=CHECKOUT)
        self.assertNotIn("<a ", html)
        self.assertIn("Expired", html)

    def test_no_expiry_means_it_does_not_expire(self):
        self.assertTrue(coupon_is_live(_section(expires_at=None)))
        self.assertTrue(coupon_is_live(_section(expires_at="")))

    def test_an_unreadable_expiry_is_treated_as_live(self):
        # Refusing a discount because a field is malformed punishes the buyer for our bug.
        self.assertTrue(coupon_is_live(_section(expires_at="not-a-date")))


class ContentTests(unittest.TestCase):
    def test_a_coupon_with_no_code_renders_nothing(self):
        # There is nothing to redeem, and an empty ticket is worse than no ticket.
        self.assertEqual(render_coupon(_section(code=""), _offer(), checkout_url=CHECKOUT), "")

    def test_the_value_and_code_are_both_shown(self):
        html = render_coupon(_section(), _offer(), checkout_url=CHECKOUT)
        self.assertIn("$20 OFF", html)
        self.assertIn("MASSAGE20", html)

    def test_tenant_copy_is_escaped(self):
        html = render_coupon(_section(terms='<script>alert(1)</script>'), _offer(), checkout_url=CHECKOUT)
        self.assertNotIn("<script>", html)

    def test_the_expiry_date_is_shown_in_words(self):
        html = render_coupon(_section(), _offer(), checkout_url=CHECKOUT)
        self.assertIn("Expires", html)


class LayoutTests(unittest.TestCase):
    """The ticket reads like a paper coupon: picture, whose it is, then the value in the biggest type."""

    def test_the_business_is_named(self):
        # A coupon that names no business is a voucher for nowhere -- the first thing a recipient checks.
        with patch("stripe_link.runtime.html.resolve_business_name", return_value="Luxe Spa"):
            html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("Luxe Spa", html)
        self.assertIn("sl-coupon-brand", html)

    def test_the_section_may_override_the_business_name(self):
        with patch("stripe_link.runtime.html.resolve_business_name", return_value="Luxe Spa"):
            html = render_coupon(_section(business_name="Luxe Spa — Downtown"), _offer(), {}, CHECKOUT)
        self.assertIn("Luxe Spa — Downtown", html)

    def test_the_image_falls_back_to_the_offers_own_product_picture(self):
        products = {"p1": {"product_id": "p1", "images": ["https://cdn.example/massage.jpg"]}}
        html = render_coupon(_section(), _offer(), products, CHECKOUT)
        self.assertIn("https://cdn.example/massage.jpg", html)
        self.assertIn("sl-coupon-media", html)

    def test_an_authored_image_wins_over_the_product_picture(self):
        products = {"p1": {"product_id": "p1", "images": ["https://cdn.example/massage.jpg"]}}
        html = render_coupon(_section(image_url="https://cdn.example/campaign.jpg"), _offer(), products, CHECKOUT)
        self.assertIn("campaign.jpg", html)
        self.assertNotIn("massage.jpg", html)

    def test_no_picture_falls_back_to_the_platform_mark(self):
        # An empty panel looks unfinished. The mark is the LAST resort, contained rather than cropped,
        # because a square logo filled into a tall panel loses its edges.
        with patch("stripe_link.runtime.html.default_favicon_url", return_value="https://cdn/icon/favicon.png"):
            html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("https://cdn/icon/favicon.png", html)
        self.assertIn("sl-coupon-media-logo", html)
        self.assertNotIn("sl-coupon-noimage", html)

    def test_the_platform_mark_is_decorative_so_it_gets_empty_alt(self):
        # It says nothing the text does not; a screen reader should not announce it before the offer.
        with patch("stripe_link.runtime.html.default_favicon_url", return_value="https://cdn/icon/favicon.png"):
            html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn('alt=""', html)

    def test_a_real_picture_always_beats_the_platform_mark(self):
        products = {"p1": {"product_id": "p1", "images": ["https://cdn.example/massage.jpg"]}}
        with patch("stripe_link.runtime.html.default_favicon_url", return_value="https://cdn/icon/favicon.png"):
            html = render_coupon(_section(), _offer(), products, CHECKOUT)
        self.assertIn("massage.jpg", html)
        self.assertNotIn("favicon.png", html)
        self.assertNotIn("sl-coupon-media-logo", html)

    def test_single_column_only_when_the_platform_mark_is_unconfigured(self):
        # default_favicon_url() returns "" when the asset CDN is not configured -- then there is genuinely
        # nothing to show, and an empty panel would be worse than none.
        with patch("stripe_link.runtime.html.default_favicon_url", return_value=""):
            html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("sl-coupon-noimage", html)
        self.assertNotIn("sl-coupon-media", html)

    def test_the_value_is_present_and_the_code_is_beside_its_label(self):
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("sl-coupon-value", html)
        self.assertIn("sl-coupon-code-row", html)

    def test_nothing_inside_the_ticket_is_underlined_as_a_link(self):
        # The whole ticket is the anchor, so its children must inherit -- not render as blue link text.
        source = __import__("pathlib").Path(__file__).resolve().parents[1] / "src/stripe_link/runtime/html.py"
        css = source.read_text(encoding="utf-8")
        self.assertIn(".sl-coupon,.sl-coupon *{text-decoration:none}", css)


class BuilderEditorTests(unittest.TestCase):
    """Two ways to attach a coupon, mirroring how a Site can come from its own screen OR this builder.

    Source-level, like the other builder guards in this suite: the registration test already proves the
    element round-trips, and this proves the tenant has a way to fill it in at all.
    """

    import pathlib as _pathlib
    BUILDER = (_pathlib.Path(__file__).resolve().parents[1]
               / "dashboard/src/components/LandingPages.vue").read_text(encoding="utf-8")

    def test_an_existing_coupon_can_be_picked(self):
        self.assertIn("couponsStore.usableCoupons", self.BUILDER)

    def test_a_coupon_can_be_created_without_leaving_the_builder(self):
        self.assertIn("createInlineCoupon", self.BUILDER)
        self.assertIn('value="__new__"', self.BUILDER)

    def test_creating_one_goes_through_the_SAME_path_as_the_coupons_screen(self):
        # Not a second way to write a coupon document: one shape, one validator, one place to change.
        self.assertIn("couponsStore.saveCoupon", self.BUILDER)

    def test_the_values_are_copied_onto_the_section(self):
        # Referencing the coupon would let an edit change what a published page already promised.
        block = self.BUILDER.split("function fillCouponElement", 1)[1][:600]
        for field in ("element.code", "element.expires_at", "element.value_text"):
            self.assertIn(field, block, field)

    def test_a_tenants_own_wording_is_not_overwritten(self):
        block = self.BUILDER.split("function fillCouponElement", 1)[1][:600]
        self.assertIn("if (!element.value_text)", block)

    def test_the_destination_field_appears_only_for_a_lead_offer(self):
        # A transacting offer goes to checkout; asking for a URL there would invite a wrong answer.
        self.assertIn("couponNeedsDestination", self.BUILDER)
        self.assertIn("offerIntent(selectedOffer.value)", self.BUILDER)

    def test_coupons_load_lazily(self):
        self.assertIn("ensureCouponsLoaded", self.BUILDER)
