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


class CouponCrudHandlerTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("coupon_id")
        self.coupon = load_fixture("coupon-demo.json")

    def test_create_coupon_persists_document(self):
        response = handler({
            "httpMethod": "POST",
            "body": json.dumps(self.coupon),
        }, None, repository=self.repository)

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
