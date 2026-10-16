"""Only a real buyer may write a review.

plans/REVIEWS.md "Review integrity", step 1 — and it is step 1 for a reason. The power to curate is what
makes `AggregateRating` a claim about a set the tenant chose, so it has to go; but removing it is only safe
once WRITING is restricted. Doing it the other way round would turn an anonymous hole into an open
publishing vector on a merchant's own domain.

The hole: `GET /review?tenant_id=…&product_id=…` rendered for anyone, `submit_review` accepted a tokenless
POST, and `_consume_invite` said so outright — *"an open/tokenless submission is fine, just not verified."*
Both ids sit in the public HTML of every published page, and there is no rate limit. Moderation was the
only thing in the way, and moderation is what this work removes.
"""
import json
import pathlib
import sys
import unittest
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from handlers.reviews_public import handler  # noqa: E402

PRODUCT = {"tenant_id": "t1", "product_id": "prod_a", "name": "Creatine Gummies"}
INVITE = {"invite_id": "invite_1", "token": "tok", "status": "active", "order_id": "order_1",
          "target": {"type": "product", "id": "prod_a"}}


class FakeProducts:
    def get(self, tenant_id, product_id):
        return PRODUCT if (tenant_id, product_id) == ("t1", "prod_a") else None


class FakeReviews:
    def __init__(self):
        self.saved = []

    def put(self, doc):
        self.saved.append(dict(doc))
        return dict(doc)


class FakeInvites:
    def __init__(self, invite=INVITE):
        self.invite = dict(invite) if invite else None
        self.saved = []

    def get(self, tenant_id, invite_id):
        return dict(self.invite) if self.invite and self.invite["invite_id"] == invite_id else None

    def put(self, doc):
        self.saved.append(dict(doc))
        self.invite = dict(doc)
        return dict(doc)


class Base(unittest.TestCase):
    def setUp(self):
        self.reviews = FakeReviews()
        self.invites = FakeInvites()

    def get(self, **params):
        return handler({"httpMethod": "GET",
                        "queryStringParameters": {"tenant_id": "t1", "product_id": "prod_a", **params}},
                       None, reviews_repo=self.reviews, products_repo=FakeProducts(),
                       sites_repo=None, invites_repo=self.invites)

    def post(self, **values):
        body = {"tenant_id": "t1", "product_id": "prod_a", "rating": "5", "author": "Jane",
                "body": "Loved it.", "company_website": "", **values}
        return handler({"httpMethod": "POST",
                        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                        "body": urlencode(body), "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}},
                       None, reviews_repo=self.reviews, products_repo=FakeProducts(),
                       sites_repo=None, invites_repo=self.invites)


class TheFormIsNotOpenToAnyoneTests(Base):
    def test_no_invite_does_not_even_render_the_form(self):
        """Refused at the GET, not only at the POST: a form that collects a review and then refuses it
        wastes a real person's effort, and one that renders for anyone is an invitation to try."""
        response = self.get()
        self.assertEqual(response["statusCode"], 403)
        self.assertNotIn("<form", response["body"])

    def test_no_invite_cannot_submit(self):
        self.assertEqual(self.post()["statusCode"], 403)
        self.assertEqual(self.reviews.saved, [], "an unauthorised POST must write nothing")

    def test_a_wrong_token_is_refused(self):
        self.assertEqual(self.get(invite="invite_1", token="guessed")["statusCode"], 403)
        self.assertEqual(self.post(invite="invite_1", token="guessed")["statusCode"], 403)

    def test_an_unknown_invite_is_refused(self):
        self.assertEqual(self.get(invite="invite_nope", token="tok")["statusCode"], 403)

    def test_an_invite_for_another_product_is_refused(self):
        """Bound to the product as well as the order: an invite for one purchase must not review another."""
        self.invites.invite["target"] = {"type": "product", "id": "prod_other"}
        self.assertEqual(self.get(invite="invite_1", token="tok")["statusCode"], 403)

    def test_every_refusal_reads_the_same(self):
        """A missing token, a wrong one and an invite for another product answer identically, so the page
        cannot be used to work out which of the three it was."""
        bodies = {
            self.get()["body"],
            self.get(invite="invite_1", token="guessed")["body"],
            self.get(invite="invite_nope", token="tok")["body"],
        }
        self.assertEqual(len(bodies), 1)

    def test_it_says_where_a_real_link_comes_from(self):
        self.assertIn("link we email after a purchase", self.get()["body"])


class AValidInviteStillWorksTests(Base):
    def test_the_form_renders(self):
        response = self.get(invite="invite_1", token="tok")
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Creatine Gummies", response["body"])

    def test_the_review_is_stored_and_verified(self):
        response = self.post(invite="invite_1", token="tok")
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(self.reviews.saved[0]["verified_purchase"])
        self.assertEqual(self.reviews.saved[0]["order_id"], "order_1")


class TheGetMustNotSpendTheTokenTests(Base):
    def test_opening_the_email_twice_still_works(self):
        """`_consume_invite` cancels the invite so the follow-ups stop. If the GET did that, opening the
        email and then coming back to it would burn the link before anything was written."""
        self.assertEqual(self.get(invite="invite_1", token="tok")["statusCode"], 200)
        self.assertEqual(self.invites.saved, [], "a GET must write nothing")
        self.assertEqual(self.get(invite="invite_1", token="tok")["statusCode"], 200)

    def test_the_post_still_spends_it(self):
        self.post(invite="invite_1", token="tok")
        self.assertEqual(self.invites.saved[-1]["status"], "completed")


class TheHoneypotStillAnswersFirstTests(Base):
    def test_a_flagged_post_is_thanked_and_dropped_without_a_lookup(self):
        """A bot must not learn whether its credentials were any good."""
        response = self.post(company_website="http://spam", invite="invite_nope", token="x")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.reviews.saved, [])


class TheDesignIsRecordedTests(unittest.TestCase):
    def test_the_plan_states_the_order(self):
        """Token first, approval second. The reverse turns the hole into an open publishing vector, and a
        future reader needs to know that before reordering the work."""
        plan = (pathlib.Path(__file__).resolve().parents[1] / "plans" / "REVIEWS.md").read_text()
        self.assertIn("Only a real buyer may write a review", plan)
        self.assertIn("Submission **requires the invite token**", plan)


if __name__ == "__main__":
    unittest.main()
