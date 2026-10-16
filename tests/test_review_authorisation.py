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
    """Stores by id as well as appending, because withdrawal is a read-modify-write: without `get` the
    handler's own except branch would swallow the AttributeError and report "nothing to remove"."""

    def __init__(self):
        self.saved = []
        self.rows = {}

    def put(self, doc):
        self.saved.append(dict(doc))
        self.rows[doc["review_id"]] = dict(doc)
        return dict(doc)

    def get(self, tenant_id, review_id):
        return dict(self.rows[review_id]) if review_id in self.rows else None


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


class TheAuthorMayWithdrawTests(Base):
    """The removal path that needs no human — not the tenant's, not the platform's.

    It ships WITH the approval step being removed, not after it: taking away the tenant's delete while no
    other path existed would have left a review nobody could take down, and the erasure right with nowhere
    to go (plans/REVIEWS.md "Review integrity").
    """

    def write(self):
        self.post(invite="invite_1", token="tok")
        return self.reviews.saved[-1]["review_id"]

    def test_the_invite_points_at_the_review_it_wrote(self):
        """Which is what lets the author find their own words later, with no second token and no account."""
        review_id = self.write()
        self.assertEqual(self.invites.invite["review_id"], review_id)

    def test_a_get_only_asks(self):
        """An email client that prefetches links would otherwise remove a review nobody meant to touch."""
        self.write()
        response = self.get(invite="invite_1", token="tok", action="withdraw")
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("<form method=post>", response["body"])
        self.assertIn("Remove your review?", response["body"])
        self.assertEqual(self.reviews.saved[-1]["status"], "approved", "a GET must change nothing")

    def test_a_post_removes_it(self):
        self.write()
        response = self.post(invite="invite_1", token="tok", action="withdraw")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.reviews.saved[-1]["status"], "rejected")
        self.assertEqual(self.reviews.saved[-1]["removed_reason"], "reviewer withdrawal")

    def test_it_is_removed_by_status_not_deleted(self):
        """The invite still points at it, and a row that vanished would make "did this ever exist"
        unanswerable for whoever fields the question later."""
        review_id = self.write()
        self.post(invite="invite_1", token="tok", action="withdraw")
        self.assertEqual(self.reviews.saved[-1]["review_id"], review_id)

    def test_withdrawal_needs_the_same_credentials_as_writing(self):
        self.write()
        self.assertEqual(self.post(action="withdraw")["statusCode"], 403)
        self.assertEqual(self.post(invite="invite_1", token="guessed", action="withdraw")["statusCode"], 403)

    def test_an_invite_that_never_wrote_one_has_nothing_to_remove(self):
        response = self.post(invite="invite_1", token="tok", action="withdraw")
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Nothing to remove", response["body"])


class TheHarmFilterHoldsWithoutJudgingTests(Base):
    """A HARM filter, never a QUALITY filter. If it could be tuned to catch unhappy customers it would
    rebuild tenant moderation with the platform holding the dial."""

    def test_a_clean_review_publishes_immediately(self):
        self.post(invite="invite_1", token="tok", body="Genuinely useful, no notes.")
        self.assertEqual(self.reviews.saved[-1]["status"], "approved")

    def test_a_one_star_review_publishes_just_the_same(self):
        self.post(invite="invite_1", token="tok", rating="1", body="It did not work for me at all.")
        self.assertEqual(self.reviews.saved[-1]["status"], "approved")

    def test_contact_details_and_links_are_held(self):
        for body in ("call me on +1 555 010 1234", "mail me at x@y.com", "try cheaper-course.com"):
            with self.subTest(body=body):
                self.setUp()
                self.post(invite="invite_1", token="tok", body=body)
                self.assertEqual(self.reviews.saved[-1]["status"], "pending")
                self.assertTrue(self.reviews.saved[-1]["held_for"])

    def test_the_reviewer_is_told_plainly(self):
        """Not dressed up as success: they wrote something that cannot go straight up, and a cheerful
        "it's live" would be a lie they could check."""
        response = self.post(invite="invite_1", token="tok", body="ring me on 555 010 1234")
        self.assertIn("checking this one", response["body"])

    def test_the_rating_is_not_an_input(self):
        from stripe_link.domain.review_harm import harm_reasons

        for rating in (1, 3, 5):
            with self.subTest(rating=rating):
                self.assertEqual(harm_reasons({"rating": rating, "body": "Fine."}), [])
                self.assertEqual(harm_reasons({"rating": rating, "body": "Call 555 010 1234"}), ["phone"])
