"""Targeted coupons: one personal code per recipient (plans/COUPONS_COMPLETION.md C5).

The property under test throughout is that a grant is bound to ONE customer and lives or dies with its
campaign -- everything else about it follows from that.
"""

import io
import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from handlers.checkout import CouponUnavailable, resolve_targeted_grant
from handlers.coupons import grants_csv, handler, redeem_url_for
from stripe_link.domain.coupon_grants import (
    grant_code,
    grant_document,
    grant_prefix,
    is_grant_code,
    normalize_recipients,
)
from stripe_link.domain.documents import DocumentValidationError, validate_coupon_grant_document
from tests.fakes import FakeDocumentRepository

ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeStripeKeys:
    def get(self, tenant_id, mode="test"):
        return {"connect_account_id": "acct_test"}


def grant_opener(*, existing_customer=False, fail_on=""):
    """Stripe, as far as the grant path needs it: a customer search, a customer create, a promo code create."""
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout=None):
        url = request.full_url
        body = (request.data or b"").decode()
        calls.append((url, body))
        if fail_on and fail_on in url:
            raise HTTPError(url, 400, "Bad Request", {},
                            io.BytesIO(json.dumps({"error": {"message": "No such coupon."}}).encode()))
        if "promotion_codes" in url:
            return _Response(json.dumps({"id": f"promo_{len(calls)}"}).encode())
        if request.get_method() == "GET":
            data = [{"id": "cus_known"}] if existing_customer else []
            return _Response(json.dumps({"data": data}).encode())
        return _Response(json.dumps({"id": f"cus_new_{len(calls)}"}).encode())

    opener.calls = calls
    return opener


class GrantCodeTests(unittest.TestCase):
    def test_code_carries_the_campaign_prefix_and_an_unguessable_suffix(self):
        code = grant_code("SAVE10")

        self.assertTrue(code.startswith("SAVE10-"))
        self.assertEqual(grant_prefix("SAVE10"), "SAVE10")
        self.assertNotEqual(code, grant_code("SAVE10"))

    def test_prefix_strips_what_stripe_would_refuse(self):
        self.assertEqual(grant_prefix("Win Back 25%!"), "WINBACK25")
        self.assertEqual(grant_prefix("   "), "SAVE")

    def test_suffix_avoids_characters_a_recipient_would_mistype(self):
        suffixes = "".join(grant_code("X").split("-")[1] for _ in range(50))

        for ambiguous in "O0I1L":
            self.assertNotIn(ambiguous, suffixes)

    def test_recipients_are_deduplicated_so_no_inbox_gets_two_codes(self):
        recipients = normalize_recipients(
            ["A@Example.com", "a@example.com", "", "not-an-email", {"email": "b@x.com", "name": "Bo"}]
        )

        self.assertEqual([row["email"] for row in recipients], ["a@example.com", "b@x.com"])
        self.assertEqual(recipients[1]["name"], "Bo")

    def test_is_grant_code_rejects_what_cannot_be_a_code(self):
        self.assertTrue(is_grant_code("SAVE10-AB3D9X"))
        self.assertFalse(is_grant_code(""))
        self.assertFalse(is_grant_code("save 10"))

    def test_grant_id_must_equal_the_code(self):
        document = grant_document(
            tenant_id="t1", coupon_id="c1", code="SAVE10-AAA111", email="a@x.com",
            stripe_promo_code_id="promo_1", stripe_customer_id="cus_1", stripe_mode="test", now=1,
        )
        validate_coupon_grant_document(document)

        document["grant_id"] = "SOMETHING-ELSE"
        with self.assertRaises(DocumentValidationError):
            validate_coupon_grant_document(document)


class IssueGrantsTests(unittest.TestCase):
    def setUp(self):
        self.coupons = FakeDocumentRepository("coupon_id")
        self.grants = FakeDocumentRepository("grant_id")
        self.coupon = load_fixture("coupon-demo.json")
        self.coupon["stripe_coupon_id"] = "co_live_1"
        self.coupon["stripe_promo_code_id"] = "promo_shared"
        self.coupon["restrictions"] = {**(self.coupon.get("restrictions") or {})}
        self.coupon["restrictions"].pop("expires_at", None)
        self.coupons.put(self.coupon)
        self.tenant_id = self.coupon["tenant_id"]
        self.coupon_id = self.coupon["coupon_id"]

    def _issue(self, body, opener=None):
        event = {
            "httpMethod": "POST",
            "resource": "/coupons/{coupon_id}/grants",
            "pathParameters": {"coupon_id": self.coupon_id},
            "body": json.dumps({"tenant_id": self.tenant_id, **body}),
        }
        with patch("handlers.coupons.checkout_credentials", return_value=("sk_test_x", "acct_test")):
            return handler(event, None, repository=self.coupons, stripe_repo=FakeStripeKeys(),
                           secret_cipher=object(), opener=opener or grant_opener(),
                           grants_repo=self.grants)

    def _list(self, params=None):
        event = {
            "httpMethod": "GET",
            "resource": "/coupons/{coupon_id}/grants",
            "pathParameters": {"coupon_id": self.coupon_id},
            "queryStringParameters": {"tenant_id": self.tenant_id, **(params or {})},
        }
        return handler(event, None, repository=self.coupons, grants_repo=self.grants)

    def test_one_code_per_recipient_each_scoped_to_its_own_customer(self):
        opener = grant_opener()
        response = self._issue({"recipients": ["a@x.com", "b@x.com"]}, opener=opener)

        self.assertEqual(response["statusCode"], 201)
        grants = json.loads(response["body"])["grants"]
        self.assertEqual(len(grants), 2)
        self.assertEqual({grant["email"] for grant in grants}, {"a@x.com", "b@x.com"})
        self.assertEqual(len({grant["code"] for grant in grants}), 2)
        # Every promotion code names a customer -- that is what makes it non-transferable.
        promo_calls = [body for url, body in opener.calls if "promotion_codes" in url]
        self.assertEqual(len(promo_calls), 2)
        for body in promo_calls:
            self.assertIn("customer=cus_", body)
            self.assertIn("coupon=co_live_1", body)

    def test_an_existing_stripe_customer_is_reused_rather_than_duplicated(self):
        opener = grant_opener(existing_customer=True)
        self._issue({"recipients": ["a@x.com"]}, opener=opener)

        creates = [url for url, _ in opener.calls if url.endswith("/customers") and "email=" not in url]
        self.assertEqual(creates, [])

    def test_reissuing_to_the_same_audience_does_not_send_a_second_code(self):
        self._issue({"recipients": ["a@x.com"]})
        response = self._issue({"recipients": ["a@x.com", "b@x.com"]})

        body = json.loads(response["body"])
        self.assertEqual([grant["email"] for grant in body["grants"]], ["b@x.com"])
        self.assertEqual([grant["email"] for grant in body["skipped"]], ["a@x.com"])
        self.assertEqual(len(self.grants.list_for_tenant(self.tenant_id)), 2)

    def test_one_bad_recipient_does_not_cost_the_whole_audience(self):
        calls = {"n": 0}
        base = grant_opener()

        def flaky(request, timeout=None):
            if "promotion_codes" in request.full_url:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise HTTPError(request.full_url, 400, "Bad", {},
                                    io.BytesIO(json.dumps({"error": {"message": "nope"}}).encode()))
            return base(request, timeout=timeout)

        response = self._issue({"recipients": ["a@x.com", "b@x.com"]}, opener=flaky)

        body = json.loads(response["body"])
        self.assertEqual(len(body["grants"]), 1)
        self.assertEqual([failure["email"] for failure in body["failures"]], ["a@x.com"])

    def test_an_audience_over_the_batch_limit_comes_back_as_remaining(self):
        recipients = [f"user{index}@x.com" for index in range(30)]
        response = self._issue({"recipients": recipients})

        body = json.loads(response["body"])
        self.assertEqual(len(body["grants"]), 25)
        self.assertEqual(len(body["remaining"]), 5)
        self.assertEqual(body["remaining"][0]["email"], "user25@x.com")

    def test_the_batch_counts_stripe_calls_not_list_positions(self):
        # The first 25 already hold codes; the rest must still be issued in THIS call.
        self._issue({"recipients": [f"user{index}@x.com" for index in range(25)]})

        response = self._issue({"recipients": [f"user{index}@x.com" for index in range(30)]})

        body = json.loads(response["body"])
        self.assertEqual(len(body["skipped"]), 25)
        self.assertEqual(len(body["grants"]), 5)
        self.assertEqual(body["remaining"], [])

    def test_a_typed_use_limit_is_refused_rather_than_crashing(self):
        response = self._issue({"recipients": ["a@x.com"], "max_redemptions": "many"})

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_grants")

    def test_a_dead_campaign_issues_nothing(self):
        dead = deepcopy(self.coupon)
        dead["status"] = "inactive"
        self.coupons.put(dead)

        response = self._issue({"recipients": ["a@x.com"]})

        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "coupon_unusable")

    def test_the_redeem_link_carries_the_recipients_own_code(self):
        response = self._issue({"recipients": ["a@x.com"], "landing_url": "https://shop.example/sale"})

        grant = json.loads(response["body"])["grants"][0]
        self.assertEqual(grant["redeem_url"], f"https://shop.example/sale?coupon={grant['code']}")
        self.assertEqual(redeem_url_for("https://x.test/p?a=1", "K-1"), "https://x.test/p?a=1&coupon=K-1")

    def test_listing_answers_csv_when_asked(self):
        self._issue({"recipients": ["b@x.com", "a@x.com"], "landing_url": "https://shop.example/sale"})

        response = self._list({"format": "csv"})

        self.assertEqual(response["headers"]["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["headers"]["Content-Disposition"])
        rows = response["body"].strip().splitlines()
        self.assertTrue(rows[0].startswith("email,name,code,redeem_url"))
        # Sorted by email, so a tenant's export is stable between calls.
        self.assertTrue(rows[1].startswith("a@x.com"))
        self.assertTrue(rows[2].startswith("b@x.com"))

    def test_csv_reports_whether_a_recipient_used_theirs(self):
        text = grants_csv([
            {"email": "a@x.com", "code": "K-1", "status": "active", "redemption_count": 0},
            {"email": "b@x.com", "code": "K-2", "status": "active", "redemption_count": 1},
        ])

        self.assertIn("a@x.com,,K-1,,active,no,", text)
        self.assertIn("b@x.com,,K-2,,active,yes,", text)


class ResolveGrantAtCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.coupons = FakeDocumentRepository("coupon_id")
        self.grants = FakeDocumentRepository("grant_id")
        self.coupon = load_fixture("coupon-demo.json")
        self.coupon["restrictions"] = {}
        self.coupon["applies_to_offer_ids"] = []
        self.coupons.put(self.coupon)
        self.tenant_id = self.coupon["tenant_id"]
        self.grant = grant_document(
            tenant_id=self.tenant_id, coupon_id=self.coupon["coupon_id"], code="SAVE10-AB3D9X",
            email="a@x.com", stripe_promo_code_id="promo_personal", stripe_customer_id="cus_known",
            stripe_mode="test", now=1,
        )
        self.grants.put(self.grant)

    def _resolve(self, code, offer_id=""):
        return resolve_targeted_grant(code, self.tenant_id, "test", self.grants, self.coupons, offer_id=offer_id)

    def test_a_grant_resolves_to_its_promotion_code_and_its_customer(self):
        self.assertEqual(self._resolve("SAVE10-AB3D9X"), ("promo_personal", "cus_known"))

    def test_lookup_is_case_insensitive_because_the_code_arrives_from_a_url(self):
        self.assertEqual(self._resolve("save10-ab3d9x")[0], "promo_personal")

    def test_a_code_that_is_not_a_grant_falls_through_untouched(self):
        self.assertEqual(self._resolve("SAVE10"), ("", ""))

    def test_a_revoked_grant_is_refused_rather_than_charged_full_price(self):
        revoked = dict(self.grant, status="inactive")
        self.grants.put(revoked)

        with self.assertRaises(CouponUnavailable):
            self._resolve("SAVE10-AB3D9X")

    def test_a_grant_dies_with_the_campaign_that_issued_it(self):
        self.coupons.put(dict(self.coupon, status="inactive"))

        with self.assertRaises(CouponUnavailable):
            self._resolve("SAVE10-AB3D9X")

    def test_a_grant_obeys_the_campaigns_offer_scope(self):
        self.coupons.put(dict(self.coupon, applies_to_offer_ids=["offer_other"]))

        with self.assertRaises(CouponUnavailable):
            self._resolve("SAVE10-AB3D9X", offer_id="offer_this")


class RedemptionTests(unittest.TestCase):
    """Who USED theirs -- the reason a tenant runs a targeted campaign at all.

    Redemption is a durable ledger row, not a counter (plans/COUPONS_COMPLETION.md, Option B slice 1).
    """

    def setUp(self):
        self.grants = FakeDocumentRepository("grant_id")
        self.coupons = FakeDocumentRepository("coupon_id")
        self.redemptions = FakeDocumentRepository("redemption_id")
        self.coupon = load_fixture("coupon-demo.json")
        self.coupon["tenant_id"] = "t1"
        self.coupon["coupon_id"] = "c1"
        self.coupon["redemption_count"] = 0
        self.coupons.put(self.coupon)
        self.grant = grant_document(
            tenant_id="t1", coupon_id="c1", code="SAVE10-AB3D9X", email="a@x.com",
            stripe_promo_code_id="promo_personal", stripe_customer_id="cus_known",
            stripe_mode="test", now=1,
        )
        self.grants.put(self.grant)

    def _session(self, session_id="cs_test_1"):
        return {
            "id": session_id,
            "amount_subtotal": 10000,
            "total_details": {"amount_discount": 1000},
            "currency": "usd",
            "payment_intent": "pi_1",
            "customer_details": {"email": "a@x.com"},
        }

    def _record(self, code, session=None):
        from handlers.stripe_webhook import record_coupon_redemption

        return record_coupon_redemption(
            code, tenant_id="t1", mode="test", session=session or self._session(),
            coupons_repo=self.coupons, grants_repo=self.grants, redemptions_repo=self.redemptions,
            now_fn=lambda: 1000,
        )

    def test_a_paid_session_writes_a_durable_redemption(self):
        self.assertTrue(self._record("SAVE10-AB3D9X"))

        rows = self.redemptions.list_for_tenant("t1")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["redemption_id"], "redemption_cs_test_1")
        self.assertEqual(row["coupon_id"], "c1")
        self.assertEqual(row["grant_id"], "SAVE10-AB3D9X")
        self.assertEqual(row["discount_amount"], 1000)
        self.assertEqual(row["qualifying_amount"], 10000)
        self.assertEqual(row["payment_intent_id"], "pi_1")
        self.assertEqual(row["redeemed_at"], 1000)

    def test_it_bumps_both_the_coupon_and_the_recipients_own_counter(self):
        self._record("SAVE10-AB3D9X")

        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 1)
        self.assertEqual(self.grants.get("t1", "SAVE10-AB3D9X")["redemption_count"], 1)

    def test_a_shared_code_counts_against_the_coupon_with_no_grant(self):
        self.assertTrue(self._record("SAVE10"))

        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 1)
        self.assertNotIn("grant_id", self.redemptions.list_for_tenant("t1")[0])

    def test_a_replayed_webhook_does_not_count_twice(self):
        # Stripe retries until it gets a 2xx and can deliver the same event twice unprompted.
        self.assertTrue(self._record("SAVE10-AB3D9X"))
        self.assertFalse(self._record("SAVE10-AB3D9X"))

        self.assertEqual(len(self.redemptions.list_for_tenant("t1")), 1)
        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 1)

    def test_a_second_genuine_sale_does_count(self):
        self._record("SAVE10", session=self._session("cs_test_1"))
        self._record("SAVE10", session=self._session("cs_test_2"))

        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 2)
        self.assertEqual(len(self.redemptions.list_for_tenant("t1")), 2)

    def test_a_session_with_no_id_is_refused_rather_than_counted_unsafely(self):
        # No session id means no idempotency key. Counting twice closes a tenant's cap early and turns
        # away buyers they meant to serve, which is worse than not counting at all.
        self.assertFalse(self._record("SAVE10", session={"amount_subtotal": 100}))
        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 0)

    def test_an_unknown_code_changes_nothing(self):
        self.assertFalse(self._record("NOSUCH-ZZZZZZ"))
        self.assertEqual(self.redemptions.list_for_tenant("t1"), [])
        self.assertEqual(self.coupons.get("t1", "c1")["redemption_count"], 0)

    def test_the_cap_now_actually_fires(self):
        # The whole point: coupon_is_usable reads redemption_count, which until now nothing wrote.
        from handlers.coupons import coupon_is_usable

        capped = dict(self.coupon, restrictions={**self.coupon["restrictions"], "max_redemptions": 1})
        self.coupons.put(capped)
        self.assertTrue(coupon_is_usable(self.coupons.get("t1", "c1"), 500))

        self._record("SAVE10")

        self.assertFalse(coupon_is_usable(self.coupons.get("t1", "c1"), 500))

    def test_the_session_carries_the_code_so_the_webhook_can_find_it(self):
        from handlers.checkout import build_checkout_payload

        grants = FakeDocumentRepository("grant_id")
        grants.put(self.grant)
        coupons = FakeDocumentRepository("coupon_id")
        coupon = load_fixture("coupon-demo.json")
        coupon["tenant_id"] = "t1"
        coupon["coupon_id"] = "c1"
        coupon["restrictions"] = {}
        coupon["applies_to_offer_ids"] = []
        coupons.put(coupon)

        payload = build_checkout_payload(
            tenant_id="t1",
            offer={"offer_id": "offer_1", "checkout": {}},
            products_by_id={},
            resolved={"items": [], "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c",
            coupon_code="save10-ab3d9x", mode="test",
            coupons_repo=coupons, grants_repo=grants,
        )

        self.assertEqual(payload["discounts[0][promotion_code]"], "promo_personal")
        self.assertEqual(payload["metadata[coupon_code]"], "SAVE10-AB3D9X")
        # The code is locked to this customer at Stripe, so the session has to name them.
        self.assertEqual(payload["customer"], "cus_known")


if __name__ == "__main__":
    unittest.main()
