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

    def test_the_code_is_appended_and_url_encoded(self):
        # The base url now goes through checkout_context first, which appends its own params -- so assert
        # the CODE survives the trip rather than pinning the whole string.
        href = coupon_checkout_href("https://x/c", "SAVE 10", {}, _offer(), _offer())
        self.assertIn("coupon=SAVE%2010", href)
        self.assertTrue(href.startswith("https://x/c?"))

    def test_the_link_carries_the_TENANT_so_checkout_can_identify_it(self):
        # Appending "?coupon=" to the bare base url produced a link with no tenant, offer or price, and
        # checkout answered "clientID or tenant_id is required" (found 2026-09-22). The CTA's own builder
        # is the only thing that knows what a checkout link needs.
        page = {"page_id": "page_1", "tenant_id": "tenant_demo"}
        offer = {"offer_id": "offer_1", "tenant_id": "tenant_demo",
                 "items": [{"product_id": "p1", "price_id": "price_1", "quantity": 1}]}
        href = coupon_checkout_href("https://x/c", "SAVE10", page, offer, offer)
        self.assertIn("clientID=tenant_demo", href)
        self.assertIn("offer=offer_1", href)
        self.assertIn("page_id=page_1", href)
        self.assertIn("coupon=SAVE10", href)

    def test_the_rendered_ticket_links_the_same_way(self):
        page = {"page_id": "page_1", "tenant_id": "tenant_demo"}
        offer = {"offer_id": "offer_1", "tenant_id": "tenant_demo",
                 "items": [{"product_id": "p1", "price_id": "price_1", "quantity": 1}]}
        html = render_coupon(_section(), offer, {}, CHECKOUT, page=page, resolved_offer=offer)
        self.assertIn("clientID=tenant_demo", html)

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


class InlineCouponFormCompletenessTests(unittest.TestCase):
    """The builder's inline form must supply every field a coupon cannot be validated without.

    Found in QA 2026-09-22: the form omitted `duration`, so `buildCouponDocument` produced
    `discount.duration: undefined` and the API refused with "discount.duration must be a non-empty string".
    The builder guards above are source-greps and could not see it — they check the wiring EXISTS, not that
    the payload is complete.

    The list is explicit rather than inferred. A first attempt derived "required" from the shape of the JS
    and got it wrong (`Boolean(form.first_time_only)` reads like an unguarded call), and a test that is
    clever and wrong is worse than one that is plain and right. These four are the fields
    `validate_coupon_document` rejects a coupon for lacking and that only the form can supply — everything
    else it reads either has a fallback in `buildCouponDocument` or is generated there.
    """

    import pathlib as _pathlib
    import re as _re
    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    BUILDER = (ROOT / "dashboard/src/components/LandingPages.vue").read_text(encoding="utf-8")

    REQUIRED = ("code", "discount_type", "value", "duration")

    def _inline_form_fields(self):
        block = self.BUILDER.split("const newCoupon = reactive(", 1)[1].split("});", 1)[0]
        return set(self._re.findall(r"(\w+):", block))

    def test_the_form_supplies_every_required_field(self):
        supplied = self._inline_form_fields()
        missing = [field for field in self.REQUIRED if field not in supplied]
        self.assertEqual(missing, [], f"the inline coupon form is missing: {missing}")

    def test_duration_specifically(self):
        # The one that actually broke, named so a regression says what it is rather than "a field".
        self.assertIn("duration", self._inline_form_fields())

    def test_the_tenant_chooses_the_duration_rather_than_inheriting_a_guess(self):
        # "every renewal" vs "once" is a materially different promise on a subscription.
        self.assertIn('v-model="newCoupon.duration"', self.BUILDER)


class DarkPresetTests(unittest.TestCase):
    """The ticket paints its own white ground, so it must not inherit the PAGE's ink.

    Found 2026-09-22: on a dark preset `--sl-text` is near-white, and the ticket rendered white-on-white --
    the value, code and headline vanished while the accent-coloured lines stayed, so it looked half-drawn
    rather than broken.
    """

    import pathlib as _pathlib
    CSS = (_pathlib.Path(__file__).resolve().parents[1]
           / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")

    def test_the_ink_does_not_fall_back_to_the_page_text_colour(self):
        self.assertNotIn("--sl-coupon-text,var(--sl-text)", self.CSS)

    def test_it_falls_back_to_a_dark_ink_that_suits_the_default_ground(self):
        self.assertIn("color:var(--sl-coupon-text,#16181d)", self.CSS)

    def test_the_ground_and_the_ink_are_both_defaulted(self):
        # A token with no default is the other half of the same bug: whichever side is missing, the pair
        # stops being self-consistent.
        self.assertIn("var(--sl-coupon-bg,#fff)", self.CSS)


class AppliedOnThePageTests(unittest.TestCase):
    """Applying a coupon must not restate the price (author, 2026-09-22).

    The card already carries a strike-through and a "Save X%" badge; a second recalculation invites "is
    this before or after my code?". It is also the only version that stays true under restrictions the
    browser cannot evaluate — Stripe's first_time_transaction is decided from the email typed AT checkout.
    So the ticket confirms, and the discount lands at checkout the way a supermarket's electronic coupon
    does.
    """

    import pathlib as _pathlib
    HTML = (_pathlib.Path(__file__).resolve().parents[1]
            / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")

    def test_the_ticket_advertises_its_code_to_the_page(self):
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn('data-coupon-code="MASSAGE20"', html)

    def test_the_applied_panel_ships_in_the_markup_but_hidden(self):
        # In the HTML rather than built in JS, so a crawler and a no-JS visitor see honest copy.
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("sl-coupon-applied", html)
        self.assertIn("hidden", html)

    def test_the_label_names_the_gesture(self):
        # The ticket applies in place rather than navigating, so the label has to say the whole coupon is
        # the control -- "Redeem this offer" reads like a description of what it is.
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("Click to redeem this offer", html)

    def test_a_tenants_own_label_still_wins(self):
        html = render_coupon(_section(cta_label="Grab it"), _offer(), {}, CHECKOUT)
        self.assertIn("Grab it", html)
        self.assertNotIn("Click to redeem", html)

    def test_an_expired_ticket_does_not_invite_a_click(self):
        html = render_coupon(_section(expires_at=PAST), _offer(), {}, CHECKOUT)
        self.assertIn("This offer has ended", html)
        self.assertNotIn("Click to redeem", html)

    def test_the_panel_is_actually_hidden_until_it_is_applied(self):
        # `hidden` is only display:none in the UA stylesheet, so giving the panel a display of its own
        # outranks the attribute and it showed before anyone clicked. Any element with a display must
        # restate [hidden], or the attribute silently stops working.
        self.assertIn(".sl-coupon-applied[hidden]{display:none}", self.HTML)

    def test_applying_twice_changes_nothing(self):
        # Idempotent by construction: one code, set to the same value, one class, one reveal.
        block = self.HTML.split("const applyCoupon", 1)[1][:700]
        self.assertIn("classList.add('is-applied')", block)
        self.assertNotIn("classList.toggle", block)

    def test_it_says_applied_and_where_the_discount_lands(self):
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("Coupon Applied", html)
        self.assertIn("Your discount will appear at checkout", html)

    def test_the_confirmation_is_green(self):
        self.assertIn("background:#e7f7ed;color:#136c34", self.HTML)

    def test_the_mark_is_an_inline_svg_not_a_fetched_asset(self):
        # An inline SVG cannot fail to load and needs no CDN.
        self.assertIn("COUPON_APPLIED_MARK", self.HTML)
        self.assertIn("<svg class=\"sl-coupon-applied-mark\"", self.HTML)

    def test_the_ticket_is_still_a_working_link_without_javascript(self):
        # Progressive enhancement: the script intercepts the click; without it the ticket still checks out.
        html = render_coupon(_section(), _offer(), {}, CHECKOUT)
        self.assertIn("<a ", html)
        self.assertIn("coupon=MASSAGE20", html)

    def test_the_code_rides_with_whichever_card_the_buyer_picked(self):
        # The bug this replaces: a link baked at publish from the offer's FIRST item sent every buyer on a
        # tiered offer to tier one, whatever they had selected.
        self.assertIn("if (window.__jbCoupon) params.set('coupon', window.__jbCoupon);", self.HTML)

    def test_applying_refreshes_the_cta_so_the_new_href_is_used(self):
        self.assertIn("window.__jbCoupon = coupon.dataset.couponCode", self.HTML)
        block = self.HTML.split("const applyCoupon", 1)[1][:700]
        self.assertIn("updateCta(", block)

    def test_the_price_is_never_recalculated_on_the_page(self):
        # The decision, asserted: nothing in the apply path touches an amount.
        block = self.HTML.split("const applyCoupon", 1)[1][:700]
        for forbidden in ("saleAmount", "regularAmount", "percent_off", "amount_off"):
            self.assertNotIn(forbidden, block, "applying a coupon must not restate the price")
