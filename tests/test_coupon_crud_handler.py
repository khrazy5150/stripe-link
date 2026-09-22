import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from handlers.coupons import handler
from tests.fakes import FakeDocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class FakeStripeKeys:
    """A tenant with Connect configured, so coupon creation can reach Stripe."""

    def get(self, tenant_id, mode="test"):
        return {"connect_account_id": "acct_test"}


def stripe_opener(responses=None, fail_on=None):
    """Stands in for urlopen. Returns Stripe-shaped objects so the handler can be exercised without a key."""
    import io, json as _json
    from urllib.error import HTTPError
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout=None):
        url = request.full_url
        calls.append(url)
        if fail_on and fail_on in url:
            raise HTTPError(url, 400, "Bad Request", {},
                            io.BytesIO(_json.dumps({"error": {"message": "Coupon code already exists."}}).encode()))
        body = {"id": "promo_live_1"} if "promotion_codes" in url else {"id": "co_live_1"}
        if responses:
            body = {**body, **responses}
        return _Response(_json.dumps(body).encode())

    opener.calls = calls
    return opener


class CouponCrudHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("coupon_id")
        self.coupon = load_fixture("coupon-demo.json")
        self.stripe_keys = FakeStripeKeys()
        self.opener = stripe_opener()

    def _create(self, coupon=None, opener=None):
        # checkout_credentials resolves a Connect tenant to the PLATFORM secret key, which no test has.
        # Patching it keeps these tests about the coupon handler rather than about secret resolution.
        with patch("handlers.coupons.checkout_credentials", return_value=("sk_test_x", "acct_test")):
            return handler({"httpMethod": "POST", "body": json.dumps(coupon or self.coupon)}, None,
                           repository=self.repository, stripe_repo=self.stripe_keys,
                           secret_cipher=object(), opener=opener or self.opener)

    def test_create_coupon_persists_document(self):
        response = self._create()

        self.assertEqual(response["statusCode"], 201)
        body = json.loads(response["body"])
        self.assertEqual(body["coupon"]["coupon_id"], "coupon_demo_save10")
        self.assertEqual(body["coupon"]["code"], "SAVE10")

    def test_list_usable_coupons_excludes_expired_and_redeemed(self):
        active = deepcopy(self.coupon)
        expired = deepcopy(self.coupon)
        expired["coupon_id"] = "coupon_expired"
        expired["code"] = "OLD10"
        expired["restrictions"]["expires_at"] = 100
        redeemed = deepcopy(self.coupon)
        redeemed["coupon_id"] = "coupon_redeemed"
        redeemed["code"] = "USED10"
        redeemed["restrictions"]["max_redemptions"] = 1
        redeemed["redemption_count"] = 1
        self.repository.put(active)
        self.repository.put(expired)
        self.repository.put(redeemed)

        with patch("handlers.coupons.time.time", return_value=200):
            response = handler({
                "httpMethod": "GET",
                "queryStringParameters": {"tenant_id": "tenant_demo", "status": "usable"},
            }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 200)
        coupon_ids = [coupon["coupon_id"] for coupon in json.loads(response["body"])["coupons"]]
        self.assertEqual(coupon_ids, ["coupon_demo_save10"])

    def test_create_coupon_rejects_invalid_code(self):
        self.coupon["code"] = "save 10"

        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.coupon),
        }, None, repository=self.repository)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_coupon")


if __name__ == "__main__":
    unittest.main()


class StripeBackedCreationTests(CouponCrudHandlerTests):
    """A coupon is created AT STRIPE before it is stored (plans/COUPONS_COMPLETION.md C1).

    The schema always said "Coupons are persisted only after Stripe sync succeeds"; until now nothing
    synced anything and `sync.status` was a literal string the client wrote.
    """

    def test_both_stripe_objects_are_created(self):
        self._create()
        self.assertTrue(any("v1/coupons" in url for url in self.opener.calls))
        self.assertTrue(any("v1/promotion_codes" in url for url in self.opener.calls))

    def test_the_stored_ids_are_the_ones_STRIPE_returned(self):
        response = self._create()
        stored = json.loads(response["body"])["coupon"]
        self.assertEqual(stored["stripe_coupon_id"], "co_live_1")
        self.assertEqual(stored["stripe_promo_code_id"], "promo_live_1")

    def test_the_clients_proposed_ids_are_overwritten(self):
        # The browser synthesises placeholders; trusting them is what made sync.status a fiction.
        coupon = deepcopy(self.coupon)
        coupon["stripe_coupon_id"] = "coupon_local_made_up"
        coupon["stripe_promo_code_id"] = "promo_local_made_up"
        stored = json.loads(self._create(coupon)["body"])["coupon"]
        self.assertNotIn("made_up", stored["stripe_coupon_id"])
        self.assertNotIn("made_up", stored["stripe_promo_code_id"])

    def test_nothing_is_stored_when_stripe_refuses(self):
        # A document whose Stripe objects do not exist is a promise the platform cannot keep.
        response = self._create(opener=stripe_opener(fail_on="v1/coupons"))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "stripe_coupon_failed")
        self.assertEqual(self.repository.documents, {})

    def test_stripes_own_message_reaches_the_tenant(self):
        # "Coupon code already exists" is actionable; "Stripe rejected the request" is not.
        response = self._create(opener=stripe_opener(fail_on="v1/promotion_codes"))
        self.assertIn("already exists", json.loads(response["body"])["message"])

    def test_a_malformed_coupon_never_reaches_stripe(self):
        coupon = deepcopy(self.coupon)
        coupon["code"] = "lower case!"
        opener = stripe_opener()
        response = self._create(coupon, opener=opener)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(opener.calls, [], "a coupon we would refuse must not be created at Stripe first")

    def test_creation_is_idempotent_per_coupon(self):
        # A retried save must not leave the tenant with two coupons for one intent.
        from stripe_link.stripe_coupons import create_coupon_in_stripe
        seen = []

        def opener(request, timeout=None):
            seen.append(request.get_header("Idempotency-key"))
            import io, json as _json
            class R(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R(_json.dumps({"id": "x"}).encode())

        create_coupon_in_stripe(coupon_id="coupon_9", code="X", name="", discount={"type": "percent", "value": 10},
                                restrictions={}, api_key="sk", opener=opener)
        self.assertEqual(seen, ["coupon_9:coupon", "coupon_9:promo"])


class ImmutabilityTests(CouponCrudHandlerTests):
    """A coupon is immutable until it expires -- the platform's rule, and Stripe's own constraint."""

    def _stored(self):
        created = json.loads(self._create()["body"])["coupon"]
        return deepcopy(created)

    def _update(self, document, opener=None):
        with patch("handlers.coupons.checkout_credentials", return_value=("sk_test_x", "acct_test")):
            return handler({"httpMethod": "PUT", "pathParameters": {"coupon_id": document["coupon_id"]},
                            "body": json.dumps(document)}, None,
                           repository=self.repository, stripe_repo=self.stripe_keys,
                           secret_cipher=object(), opener=opener or stripe_opener())

    def test_the_value_cannot_be_changed(self):
        document = self._stored()
        document["discount"]["value"] = 99
        response = self._update(document)
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["error"], "coupon_immutable")

    def test_the_code_cannot_be_changed(self):
        document = self._stored()
        document["code"] = "SOMETHINGELSE"
        self.assertEqual(self._update(document)["statusCode"], 409)

    def test_renaming_is_allowed(self):
        document = self._stored()
        document["name"] = "Spring promo"
        self.assertEqual(self._update(document)["statusCode"], 200)

    def test_disabling_deactivates_the_code_at_stripe(self):
        # A record saying "inactive" while the code still works at Stripe is the dangerous disagreement.
        document = self._stored()
        document["status"] = "inactive"
        opener = stripe_opener()
        self.assertEqual(self._update(document, opener=opener)["statusCode"], 200)
        self.assertTrue(any("promotion_codes/promo_live_1" in url for url in opener.calls))

    def test_nothing_is_stored_when_stripe_refuses_the_disable(self):
        document = self._stored()
        document["status"] = "inactive"
        response = self._update(document, opener=stripe_opener(fail_on="promotion_codes"))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(self.repository.get(document["tenant_id"], document["coupon_id"])["status"], "active")
