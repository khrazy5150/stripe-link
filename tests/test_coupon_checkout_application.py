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

from handlers.checkout import CouponUnavailable, resolve_campaign_promotion_code


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

    # The LAST occurrence: the first is the resolver re-raising its own exception, not the handler's arm.
    ARM = CHECKOUT.rsplit("except CouponUnavailable:", 1)[1][:900]

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
