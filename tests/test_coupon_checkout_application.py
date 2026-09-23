"""A coupon carried in from a campaign page (plans/COUPONS_COMPLETION.md C3).

The decision this file exists to hold: when the page promised a discount and checkout cannot apply it,
checkout REFUSES. It does not quietly charge full price. Someone who tapped a ticket saying "$20 off"
and is charged the full amount without being told has been overcharged by surprise, which is worse than
being told the offer ended -- they can still buy at the regular price from the ordinary page.

A published artifact carries only the code and expiry copied at publish, so it cannot know a coupon was
disabled or used up afterwards. Checkout is the only place that can tell them.
"""
import time
import unittest

from handlers.checkout import (
    CouponUnavailable,
    coupon_covers_offer,
    resolve_campaign_promotion_code,
)


class Repo:
    def __init__(self, coupons):
        self.coupons = coupons

    def list_for_tenant(self, tenant_id):
        return list(self.coupons)


def _coupon(**over):
    coupon = {
        "coupon_id": "coupon_1", "code": "MASSAGE20", "status": "active",
        "stripe_promo_code_id": "promo_live_1",
        "restrictions": {"expires_at": None, "max_redemptions": None},
        "redemption_count": 0,
    }
    coupon.update(over)
    return coupon


class AppliedTests(unittest.TestCase):
    def test_a_usable_coupon_yields_the_real_stripe_id(self):
        repo = Repo([_coupon()])
        self.assertEqual(
            resolve_campaign_promotion_code("MASSAGE20", "t1", "test", repo), "promo_live_1")

    def test_the_code_is_matched_case_insensitively(self):
        repo = Repo([_coupon()])
        self.assertEqual(resolve_campaign_promotion_code("massage20", "t1", "test", repo), "promo_live_1")

    def test_no_coupon_asked_for_is_not_an_error(self):
        self.assertEqual(resolve_campaign_promotion_code("", "t1", "test", Repo([])), "")


class RefusedTests(unittest.TestCase):
    """Every one of these used to fall through to full price."""

    def _refuses(self, coupon=None, repo=None):
        with self.assertRaises(CouponUnavailable):
            resolve_campaign_promotion_code(
                "MASSAGE20", "t1", "test", repo if repo is not None else Repo([coupon] if coupon else []))

    def test_a_disabled_coupon(self):
        self._refuses(_coupon(status="inactive"))

    def test_an_expired_coupon(self):
        self._refuses(_coupon(restrictions={"expires_at": int(time.time()) - 60}))

    def test_a_fully_redeemed_coupon(self):
        self._refuses(_coupon(restrictions={"max_redemptions": 5}, redemption_count=5))

    def test_a_code_that_does_not_exist(self):
        self._refuses()

    def test_a_coupon_with_no_stripe_id_yet(self):
        # Records created before the module created anything at Stripe. Sending a placeholder id would make
        # Stripe reject the whole session, which is a worse failure than this one.
        self._refuses(_coupon(stripe_promo_code_id=""))

    def test_an_unreadable_coupons_table(self):
        class Exploding:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("coupons table is unavailable")
        self._refuses(repo=Exploding())

    def test_a_missing_tenant(self):
        with self.assertRaises(CouponUnavailable):
            resolve_campaign_promotion_code("MASSAGE20", "", "test", Repo([_coupon()]))


class HandlerResponseTests(unittest.TestCase):
    """The visitor is TOLD, on the surface they are actually on."""

    import pathlib as _pathlib
    CHECKOUT = (_pathlib.Path(__file__).resolve().parents[1]
                / "src/handlers/checkout.py").read_text(encoding="utf-8")

    # The arm that RENDERS something, found by what it does rather than by where it sits. This used to
    # take the last `except CouponUnavailable:` in the file, which silently stopped being the handler's
    # arm the moment another one was added below it (Option B's materializer, 2026-09-23).
    ARM = next(
        block for block in
        (segment[:900] for segment in CHECKOUT.split("except CouponUnavailable:")[1:])
        if "render_error_page" in block
    )

    def test_the_arm_lives_in_the_request_handler(self):
        self.assertIn("method ==", self.ARM)

    def test_a_browser_gets_the_branded_page_not_json(self):
        block = self.ARM
        self.assertIn("render_error_page", block)
        self.assertIn('method == "GET"', block)

    def test_it_says_the_offer_ended_and_what_to_do(self):
        block = self.ARM
        self.assertIn("no longer available", block)
        self.assertIn("regular price", block)

    def test_410_rather_than_an_error_code_that_reads_as_a_bug(self):
        # Gone: it existed and does not any more, which is exactly what happened.
        block = self.ARM
        self.assertIn("410", block)


class OfferEligibilityTests(unittest.TestCase):
    """`applies_to_offer_ids` was stored and validated from the day the module was written, and read by
    nothing — so a coupon scoped to one offer worked on every offer.

    This is ELIGIBILITY (may this code be used here), NOT which products in a cart get discounted. Stripe's
    applies_to.products is the mechanism for that, and it silently ignored both documented syntaxes when
    tested against a live connected account on 2026-09-22 — accepted, then `applies_to: null` on create and
    on retrieve. Product-level scoping is therefore left unbuilt rather than half-trusted.
    """

    def test_an_unscoped_coupon_covers_every_offer(self):
        # What every coupon created so far carries, so this is the path that must not change.
        self.assertTrue(coupon_covers_offer({"applies_to_offer_ids": []}, "offer_1"))
        self.assertTrue(coupon_covers_offer({}, "offer_1"))

    def test_a_scoped_coupon_covers_the_offer_it_names(self):
        self.assertTrue(coupon_covers_offer({"applies_to_offer_ids": ["offer_1", "offer_2"]}, "offer_2"))

    def test_a_scoped_coupon_does_not_cover_another_offer(self):
        self.assertFalse(coupon_covers_offer({"applies_to_offer_ids": ["offer_1"]}, "offer_9"))

    def test_checkout_refuses_rather_than_charging_full_price(self):
        repo = Repo([_coupon(applies_to_offer_ids=["offer_other"])])
        with self.assertRaises(CouponUnavailable):
            resolve_campaign_promotion_code("MASSAGE20", "t1", "test", repo, offer_id="offer_1")

    def test_it_applies_on_the_offer_it_was_scoped_to(self):
        repo = Repo([_coupon(applies_to_offer_ids=["offer_1"])])
        self.assertEqual(
            resolve_campaign_promotion_code("MASSAGE20", "t1", "test", repo, offer_id="offer_1"),
            "promo_live_1")
