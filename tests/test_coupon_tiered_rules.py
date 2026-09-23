"""Option B: rules Stripe has no vocabulary for (plans/COUPONS_COMPLETION.md).

A spend ladder — "spend $100 get 20%, spend $250 get 30%" — depends on the cart, not on any product, so no
durable Stripe Coupon can represent it. We evaluate it and hand Stripe the number as a coupon made for one
checkout. The tenant's coupon stays a durable, immutable rule either way; only the EVALUATOR moves.
"""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from handlers.checkout import (
    CouponUnavailable,
    build_checkout_payload,
    materialize_platform_discount,
    resolve_platform_coupon,
)
from handlers.coupons import coupon_edit_conflict, handler
from stripe_link.domain.coupon_rules import (
    evaluate,
    is_platform_evaluated,
    lines_from_resolved,
    matching_tier,
    qualifying_subtotal,
)
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_document
from tests.fakes import FakeDocumentRepository

ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def tiered_coupon(**over):
    coupon = load_fixture("coupon-demo.json")
    coupon["code"] = "SPEND20"
    coupon["applies_to_offer_ids"] = []
    coupon["restrictions"] = {}
    coupon["discount"] = {
        "type": "tiered", "duration": "once",
        "tiers": [{"min_subtotal": 10000, "percent": 20}, {"min_subtotal": 25000, "percent": 30}],
    }
    coupon.pop("stripe_coupon_id", None)
    coupon.pop("stripe_promo_code_id", None)
    coupon.update(over)
    return coupon


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.coupon = tiered_coupon()

    def _at(self, subtotal):
        return evaluate(self.coupon, [{"product_id": "p1", "amount": subtotal, "quantity": 1}])

    def test_below_every_tier_is_worth_nothing_and_is_not_an_error(self):
        result = self._at(4000)

        self.assertEqual(result["amount_off"], 0)
        self.assertIn("below the first tier", result["reason"])

    def test_exactly_on_a_threshold_qualifies(self):
        self.assertEqual(self._at(10000)["amount_off"], 2000)

    def test_the_BEST_tier_wins_not_the_first_match(self):
        # A buyer who reached 30% must not be given 20% because that tier was listed first.
        self.assertEqual(self._at(27500)["amount_off"], 8250)

    def test_tier_order_in_the_document_does_not_matter(self):
        self.coupon["discount"]["tiers"].reverse()

        self.assertEqual(self._at(27500)["amount_off"], 8250)

    def test_quantity_counts_toward_the_threshold(self):
        result = evaluate(self.coupon, [{"product_id": "p1", "amount": 5000, "quantity": 3}])

        self.assertEqual(result["qualifying_amount"], 15000)
        self.assertEqual(result["amount_off"], 3000)

    def test_a_scope_narrows_what_counts_toward_the_threshold(self):
        self.coupon["applies_to_product_ids"] = ["p1"]
        lines = [{"product_id": "p1", "amount": 9000, "quantity": 1},
                 {"product_id": "p2", "amount": 9000, "quantity": 1}]

        result = evaluate(self.coupon, lines)

        # $90 of qualifying product does not reach the $100 tier, even though the cart totals $180.
        self.assertEqual(result["qualifying_amount"], 9000)
        self.assertEqual(result["amount_off"], 0)

    def test_rounding_is_half_up_on_the_cent(self):
        self.coupon["discount"]["tiers"] = [{"min_subtotal": 1, "percent": 15}]

        self.assertEqual(evaluate(self.coupon, [{"amount": 3333, "quantity": 1}])["amount_off"], 500)

    def test_a_discount_can_never_exceed_what_it_discounts(self):
        # The validator refuses >100%, but a document read back from storage predates today's validator.
        self.coupon["discount"]["tiers"] = [{"min_subtotal": 1, "percent": 500}]

        self.assertEqual(evaluate(self.coupon, [{"amount": 1000, "quantity": 1}])["amount_off"], 1000)

    def test_only_tiered_rules_are_ours_to_evaluate(self):
        self.assertTrue(is_platform_evaluated(self.coupon))
        self.assertFalse(is_platform_evaluated(load_fixture("coupon-demo.json")))

    def test_no_tier_matched_returns_none_rather_than_a_default(self):
        self.assertIsNone(matching_tier(self.coupon["discount"], 500))

    def test_lines_come_off_a_resolved_offer(self):
        lines = lines_from_resolved({"items": [{"product_id": "p1", "unit_amount": 2500, "quantity": 2}]})

        self.assertEqual(qualifying_subtotal(lines), 5000)


class ValidatorTests(unittest.TestCase):
    def test_a_tiered_coupon_needs_no_stripe_ids(self):
        validate_coupon_document(tiered_coupon())

    def test_an_ordinary_coupon_still_does(self):
        plain = load_fixture("coupon-demo.json")
        plain.pop("stripe_coupon_id")

        with self.assertRaises(DocumentValidationError):
            validate_coupon_document(plain)

    def test_tiers_must_exist_and_be_sane(self):
        for tiers in ([], [{"min_subtotal": 1}], [{"min_subtotal": 1, "percent": 0}],
                      [{"min_subtotal": 1, "percent": 101}], [{"percent": 10}]):
            with self.assertRaises(DocumentValidationError):
                validate_coupon_document(tiered_coupon(
                    discount={"type": "tiered", "duration": "once", "tiers": tiers}))

    def test_two_tiers_at_one_threshold_have_no_defined_answer(self):
        with self.assertRaises(DocumentValidationError):
            validate_coupon_document(tiered_coupon(discount={
                "type": "tiered", "duration": "once",
                "tiers": [{"min_subtotal": 100, "percent": 10}, {"min_subtotal": 100, "percent": 20}]}))

    def test_a_tiered_discount_can_only_be_once(self):
        with self.assertRaises(DocumentValidationError):
            validate_coupon_document(tiered_coupon(discount={
                "type": "tiered", "duration": "forever",
                "tiers": [{"min_subtotal": 100, "percent": 10}]}))


class ImmutabilityTests(unittest.TestCase):
    def test_moving_a_threshold_is_a_broken_promise(self):
        was = {"code": "S", "discount": {"type": "tiered", "tiers": [{"min_subtotal": 10000, "percent": 20}]}}
        now = {"code": "S", "discount": {"type": "tiered", "tiers": [{"min_subtotal": 20000, "percent": 20}]}}

        self.assertEqual(coupon_edit_conflict(was, now), "discount.tiers")

    def test_reordering_the_same_ladder_is_not_a_change(self):
        ladder = [{"min_subtotal": 10000, "percent": 20}, {"min_subtotal": 25000, "percent": 30}]
        was = {"code": "S", "discount": {"type": "tiered", "tiers": ladder}}
        now = {"code": "S", "discount": {"type": "tiered", "tiers": list(reversed(ladder))}}

        self.assertEqual(coupon_edit_conflict(was, now), "")


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("coupon_id")

    def test_a_tiered_coupon_creates_NOTHING_at_stripe(self):
        calls = []

        def opener(request, timeout=None):
            calls.append(request.full_url)
            raise AssertionError("a platform-evaluated rule must not call Stripe at creation")

        response = handler({"httpMethod": "POST", "body": json.dumps(tiered_coupon())}, None,
                           repository=self.repository, opener=opener)

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(calls, [])
        saved = json.loads(response["body"])["coupon"]
        self.assertNotIn("stripe_coupon_id", saved)

    def test_it_does_not_demand_a_connected_stripe_account(self):
        # An ordinary coupon must refuse without Stripe, because its code has to EXIST there. A tiered one
        # has no object to create, so the same demand would be a wall for no reason.
        response = handler({"httpMethod": "POST", "body": json.dumps(tiered_coupon())}, None,
                           repository=self.repository)

        self.assertEqual(response["statusCode"], 201)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.coupons = FakeDocumentRepository("coupon_id")
        self.coupon = tiered_coupon()
        self.coupons.put(self.coupon)
        self.tenant_id = self.coupon["tenant_id"]
        self.made = []

        def materializer(*, amount_off, currency, code, tenant_id):
            self.made.append({"amount_off": amount_off, "currency": currency, "code": code})
            return f"co_disposable_{amount_off}"

        self.materializer = materializer

    def _payload(self, items, coupon_code="SPEND20", materializer=True):
        # Service-shaped lines: they price straight off the resolved item, so the payload builder needs no
        # product catalogue to render them. The evaluator reads the same unit_amount/quantity either way.
        lines = [{**item, "kind": "service", "service_id": f"svc_{index}", "currency": "usd",
                  "label": "Probe"} for index, item in enumerate(items)]
        return build_checkout_payload(
            tenant_id=self.tenant_id,
            offer={"offer_id": "offer_1", "checkout": {}},
            products_by_id={},
            resolved={"items": lines, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c",
            coupon_code=coupon_code, mode="test", coupons_repo=self.coupons,
            discount_materializer=self.materializer if materializer else None,
        )

    def test_a_qualifying_cart_gets_a_disposable_coupon(self):
        payload = self._payload([{"product_id": "p1", "unit_amount": 27500, "quantity": 1}])

        self.assertEqual(payload["discounts[0][coupon]"], "co_disposable_8250")
        self.assertNotIn("discounts[0][promotion_code]", payload)
        self.assertEqual(payload["metadata[coupon_code]"], "SPEND20")
        self.assertEqual(self.made[0]["amount_off"], 8250)

    def test_a_cart_below_every_tier_simply_gets_no_discount(self):
        # NOT a refusal: the tenant said "spend $100", and this buyer has not. Charging full price is
        # exactly what the coupon promised — unlike a withdrawn coupon, which does refuse.
        payload = self._payload([{"product_id": "p1", "unit_amount": 4000, "quantity": 1}])

        self.assertNotIn("discounts[0][coupon]", payload)
        self.assertNotIn("metadata[coupon_code]", payload)
        self.assertEqual(self.made, [])

    def test_a_withdrawn_tiered_coupon_still_refuses(self):
        self.coupons.put(dict(self.coupon, status="inactive"))

        with self.assertRaises(CouponUnavailable):
            self._payload([{"product_id": "p1", "unit_amount": 27500, "quantity": 1}])

    def test_a_qualifying_buyer_is_refused_rather_than_charged_full_price_when_stripe_fails(self):
        def broken(**kwargs):
            raise RuntimeError("stripe is down")

        with self.assertRaises(CouponUnavailable):
            materialize_platform_discount(self.coupon, {"items": [{"unit_amount": 27500, "quantity": 1}],
                                                        "currency": "usd"}, "SPEND20", "t1", broken)

    def test_no_materializer_and_a_qualifying_cart_is_also_a_refusal(self):
        with self.assertRaises(CouponUnavailable):
            self._payload([{"product_id": "p1", "unit_amount": 27500, "quantity": 1}], materializer=False)

    def test_an_ordinary_coupon_is_left_to_stripe(self):
        self.coupons.put(load_fixture("coupon-demo.json"))

        self.assertIsNone(resolve_platform_coupon("SAVE10", self.tenant_id, "test", self.coupons))

    def test_an_unknown_code_is_not_claimed_by_the_platform_path(self):
        self.assertIsNone(resolve_platform_coupon("NOPE", self.tenant_id, "test", self.coupons))


if __name__ == "__main__":
    unittest.main()
