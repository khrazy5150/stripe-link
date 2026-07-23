import unittest
from urllib.parse import urlencode

from handlers.review_invites import handler as sweep_handler
from handlers.reviews_public import handler as public_handler
from handlers.stripe_webhook import plan_order_review_invite
from stripe_link.domain.review_invites import due_steps, mark_step_sent, plan_invite


def _invite(now=0, **over):
    inv = plan_invite(tenant_id="t1", invite_id="invite_o1", order_id="o1",
                      product={"product_id": "prod_a", "name": "Widget", "product_type": "digital"},
                      customer={"email": "buyer@example.com", "name": "Jane"}, now=now)
    inv.update(over)
    return inv


class InviteModelTests(unittest.TestCase):
    def test_digital_and_physical_offsets(self):
        digital = plan_invite(tenant_id="t", invite_id="i", order_id="o", product={"product_id": "p", "product_type": "digital"}, customer={"email": "a@b.c"}, now=0)
        physical = plan_invite(tenant_id="t", invite_id="i", order_id="o", product={"product_id": "p", "product_type": "physical"}, customer={"email": "a@b.c"}, now=0)
        self.assertEqual([s["day"] for s in digital["steps"]], [1, 3, 7, 10])
        self.assertEqual(digital["steps"][0]["send_at"], 86_400)          # day 1, no ship offset
        self.assertEqual(physical["steps"][0]["send_at"], (5 + 1) * 86_400)  # + 5-day ship estimate

    def test_due_steps_only_when_active_and_arrived_and_unsent(self):
        inv = _invite(now=0)
        self.assertEqual([s["day"] for s in due_steps(inv, now=3 * 86_400)], [1, 3])  # day 1 & 3 arrived
        mark_step_sent(inv, 1, now=3 * 86_400)
        self.assertEqual([s["day"] for s in due_steps(inv, now=3 * 86_400)], [3])      # 1 now sent
        inv["status"] = "completed"
        self.assertEqual(due_steps(inv, now=99 * 86_400), [])                          # canceled/completed => none

    def test_mark_all_steps_completes_invite(self):
        inv = _invite(now=0)
        for d in (1, 3, 7, 10):
            mark_step_sent(inv, d, now=99 * 86_400)
        self.assertEqual(inv["status"], "completed")


class DestinationTests(unittest.TestCase):
    def test_default_by_entity_type(self):
        from stripe_link.domain.reviews import resolve_review_destination
        self.assertEqual(resolve_review_destination({"entity_type": "OnlineStore"}), "junior_bay")
        self.assertEqual(resolve_review_destination({"entity_type": "LocalBusiness", "place_id": "ChIJ"}), "google")

    def test_google_needs_place_id_else_falls_back(self):
        from stripe_link.domain.reviews import resolve_review_destination
        self.assertEqual(resolve_review_destination({"entity_type": "LocalBusiness"}), "junior_bay")
        self.assertEqual(resolve_review_destination({"review_destination": "google"}), "junior_bay")  # no place_id
        self.assertEqual(resolve_review_destination({"review_destination": "google", "place_id": "ChIJ"}), "google")

    def test_explicit_override_wins(self):
        from stripe_link.domain.reviews import resolve_review_destination
        self.assertEqual(resolve_review_destination({"entity_type": "OnlineStore", "review_destination": "google", "place_id": "ChIJ"}), "google")
        self.assertEqual(resolve_review_destination({"entity_type": "LocalBusiness", "review_destination": "junior_bay"}), "junior_bay")

    def test_email_routes_to_the_chosen_destination(self):
        from stripe_link.domain.review_invites import invite_email
        inv = _invite(now=0)
        google = invite_email(inv, base_url="https://x", organization={"name": "Spa", "entity_type": "HealthAndBeautyBusiness", "place_id": "ChIJ"})
        self.assertIn("writereview?placeid=ChIJ", google["html"])
        self.assertIn("Review us on Google", google["html"])
        jb = invite_email(inv, base_url="https://x", organization={"name": "Mart", "entity_type": "OnlineStore"})
        self.assertIn("/review?tenant_id", jb["html"])


class FakeInvites:
    def __init__(self, invites=None):
        self.docs = {(i["tenant_id"], i["invite_id"]): dict(i) for i in (invites or [])}

    def scan_type(self):
        return [dict(v) for v in self.docs.values()]

    def get(self, tenant_id, invite_id):
        d = self.docs.get((tenant_id, invite_id))
        return dict(d) if d else None

    def put(self, doc):
        self.docs[(doc["tenant_id"], doc["invite_id"])] = dict(doc)
        return dict(doc)


class SweepTests(unittest.TestCase):
    def test_sends_due_steps_and_marks_sent(self):
        invites = FakeInvites([_invite(now=0)])
        sent = []
        result = sweep_handler({}, None, invites_repo=invites, sites_repo=None,
                               mailer_send=lambda **kw: sent.append(kw) or {"MessageId": "m"},
                               now_fn=lambda: 4 * 86_400)  # day 1 & 3 due
        self.assertEqual(result["sent"], 2)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["to"], "buyer@example.com")
        saved = invites.get("t1", "invite_o1")
        self.assertIsNotNone(saved["steps"][0]["sent_at"])  # day 1 marked
        self.assertIsNone(saved["steps"][2]["sent_at"])      # day 7 not yet

    def test_completed_invite_is_skipped(self):
        invites = FakeInvites([_invite(now=0, status="completed")])
        result = sweep_handler({}, None, invites_repo=invites, sites_repo=None,
                               mailer_send=lambda **kw: 1 / 0, now_fn=lambda: 99 * 86_400)
        self.assertEqual(result["sent"], 0)


class FakeProducts:
    def get(self, tenant_id, product_id):
        return {"tenant_id": tenant_id, "product_id": product_id, "name": "Widget", "product_type": "digital"}


class WebhookTriggerTests(unittest.TestCase):
    def _order(self, **over):
        order = {"order_id": "order_x", "status": "paid",
                 "customer": {"email": "buyer@example.com", "name": "Jane"},
                 "product": {"product_id": "prod_a", "name": "Widget"}}
        order.update(over)
        return order

    def test_paid_order_plans_an_invite(self):
        invites = FakeInvites()
        self.assertTrue(plan_order_review_invite(self._order(), "t1", FakeProducts(), invites, now=0))
        self.assertIsNotNone(invites.get("t1", "invite_order_x"))

    def test_idempotent_no_double_plan(self):
        invites = FakeInvites()
        plan_order_review_invite(self._order(), "t1", FakeProducts(), invites, now=0)
        self.assertFalse(plan_order_review_invite(self._order(), "t1", FakeProducts(), invites, now=100))

    def test_unpaid_or_no_email_skipped(self):
        invites = FakeInvites()
        self.assertFalse(plan_order_review_invite(self._order(status="pending"), "t1", FakeProducts(), invites, now=0))
        self.assertFalse(plan_order_review_invite(self._order(customer={"email": ""}), "t1", FakeProducts(), invites, now=0))
        self.assertEqual(invites.docs, {})


class FakeReviews:
    def __init__(self):
        self.saved = []

    def put(self, doc):
        self.saved.append(dict(doc)); return dict(doc)


class FakeProductsExists:
    def get(self, tenant_id, product_id):
        return {"tenant_id": tenant_id, "product_id": product_id, "name": "Widget"} if product_id == "prod_a" else None


class VerifiedSubmissionTests(unittest.TestCase):
    def _post(self, values, invites):
        return public_handler({"httpMethod": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                               "body": urlencode(values), "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}}, None,
                              reviews_repo=self.reviews, products_repo=FakeProductsExists(), sites_repo=None, invites_repo=invites)

    def setUp(self):
        self.reviews = FakeReviews()

    def test_valid_token_marks_verified_and_cancels_invite(self):
        invites = FakeInvites([_invite(now=0)])
        token = invites.get("t1", "invite_o1")["token"]
        resp = self._post({"tenant_id": "t1", "product_id": "prod_a", "invite": "invite_o1", "token": token,
                           "rating": "5", "author": "Jane", "body": "Great.", "company_website": ""}, invites)
        self.assertEqual(resp["statusCode"], 200)
        review = self.reviews.saved[0]
        self.assertTrue(review["verified_purchase"])
        self.assertEqual(review["order_id"], "o1")
        self.assertEqual(invites.get("t1", "invite_o1")["status"], "completed")  # canceled — no more emails

    def test_bad_token_is_not_verified(self):
        invites = FakeInvites([_invite(now=0)])
        resp = self._post({"tenant_id": "t1", "product_id": "prod_a", "invite": "invite_o1", "token": "wrong",
                           "rating": "4", "author": "Jane", "body": "ok", "company_website": ""}, invites)
        self.assertEqual(resp["statusCode"], 200)
        self.assertNotIn("verified_purchase", self.reviews.saved[0])
        self.assertEqual(invites.get("t1", "invite_o1")["status"], "active")  # untouched


if __name__ == "__main__":
    unittest.main()
