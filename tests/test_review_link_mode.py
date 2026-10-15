"""The emailed review link could not find the product it was about.

Reported 2026-10-14: "Leave a review" answered "This review link is no longer valid. The product could not
be found." The product was there -- `PRODUCT#live#local_vwwhS4DSabx`, found by scan while investigating.

Third instance of one cause in one day, after the download link and the thank-you page's fetch: products
and orders are stored per Stripe mode, the mode comes from the REQUEST, and the link carried none -- so it
resolved to the fail-safe "test" and looked in the wrong books.

Unlike those two there is no session id here to read it out of, so the link has to SAY. Two things follow
from that: the invite supplies its own mode when the link is built, and the form carries it back through a
urlencoded POST, which `resolve_stripe_mode` cannot read at all. Invites already in inboxes predate the
parameter entirely, so a product missing from the asked-for books is looked for in the other.
"""
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from handlers.reviews_public import handler
from stripe_link.domain.review_invites import review_link

LIVE_PRODUCT = {"tenant_id": "t1", "product_id": "prod_a", "name": "Digital Marketing 101"}


class FakeReviews:
    def __init__(self):
        self.saved = []

    def put(self, doc):
        self.saved.append(dict(doc))
        return dict(doc)


class ModedProducts:
    """Products keyed by mode, as the real table is (`PRODUCT#<mode>#<id>`)."""

    def __init__(self, by_mode):
        self.by_mode = by_mode
        self.asked = []

    def for_mode(self, mode):
        outer = self

        class View:
            def get(self, tenant_id, product_id):
                outer.asked.append(mode)
                return outer.by_mode.get(mode, {}).get((tenant_id, product_id))

        return View()


class FakeInvites:
    def __init__(self, invite=None):
        self.invite = invite
        self.saved = []

    def get(self, tenant_id, invite_id):
        return self.invite if self.invite and self.invite["invite_id"] == invite_id else None

    def put(self, doc):
        self.saved.append(dict(doc))
        return dict(doc)


class LinkTests(unittest.TestCase):
    def test_the_link_says_which_books_it_means(self):
        invite = {"tenant_id": "t1", "invite_id": "invite_1", "token": "tok",
                  "target": {"id": "prod_a"}, "stripe_mode": "live"}
        params = parse_qs(urlsplit(review_link("https://api.example", invite)).query)
        self.assertEqual(params["mode"], ["live"])
        self.assertEqual(params["product_id"], ["prod_a"])

    def test_a_test_invite_says_test(self):
        invite = {"tenant_id": "t1", "invite_id": "invite_1", "token": "tok",
                  "target": {"id": "prod_a"}, "stripe_mode": "test"}
        self.assertEqual(parse_qs(urlsplit(review_link("https://api.example", invite)).query)["mode"], ["test"])

    def test_an_invite_that_does_not_say_is_treated_as_test(self):
        """Fail-safe in the same direction as everything else: an unknown mode never points at live."""
        invite = {"tenant_id": "t1", "invite_id": "invite_1", "token": "tok", "target": {"id": "prod_a"}}
        self.assertEqual(parse_qs(urlsplit(review_link("https://api.example", invite)).query)["mode"], ["test"])


class FormTests(unittest.TestCase):
    def setUp(self):
        self.reviews = FakeReviews()
        self.products = ModedProducts({"live": {("t1", "prod_a"): LIVE_PRODUCT}})

    def get(self, params):
        return handler({"httpMethod": "GET", "queryStringParameters": params}, None,
                       reviews_repo=self.reviews, products_repo=self.products.for_mode("live"), sites_repo=None)

    def test_a_live_link_renders_the_live_product(self):
        response = self.get({"tenant_id": "t1", "product_id": "prod_a", "mode": "live"})
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Digital Marketing 101", response["body"])

    def test_the_form_carries_the_mode_back(self):
        """A urlencoded POST is neither JSON body, query string nor header, so `resolve_stripe_mode` reads
        nothing from it. Without this hidden field a form that rendered from the live books submitted
        itself into the test ones -- and 404'd after the buyer had typed their review."""
        body = self.get({"tenant_id": "t1", "product_id": "prod_a", "mode": "live"})["body"]
        self.assertIn("name=mode value='live'", body)


class HealingTests(unittest.TestCase):
    """Invites sent before the link carried a mode at all."""

    def setUp(self):
        self.reviews = FakeReviews()
        self.products = ModedProducts({"live": {("t1", "prod_a"): LIVE_PRODUCT}})

    def call(self, event):
        return handler(event, None, reviews_repo=self.reviews,
                       products_repo=None, sites_repo=None, invites_repo=FakeInvites())

    def get(self, params):
        import handlers.reviews_public as module
        original = module.products_repository
        module.products_repository = lambda mode=None: self.products.for_mode(mode)
        try:
            return self.call({"httpMethod": "GET", "queryStringParameters": params})
        finally:
            module.products_repository = original

    def test_an_old_link_with_no_mode_still_finds_a_live_product(self):
        response = self.get({"tenant_id": "t1", "product_id": "prod_a"})
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Digital Marketing 101", response["body"])

    def test_it_asks_the_requested_books_first(self):
        self.get({"tenant_id": "t1", "product_id": "prod_a"})
        self.assertEqual(self.products.asked, ["test", "live"])

    def test_a_healed_form_posts_back_to_the_books_it_was_found_in(self):
        """Otherwise the GET heals and the POST breaks again, one screen later."""
        body = self.get({"tenant_id": "t1", "product_id": "prod_a"})["body"]
        self.assertIn("name=mode value='live'", body)

    def test_a_product_in_neither_mode_is_still_a_404(self):
        response = self.get({"tenant_id": "t1", "product_id": "nope"})
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(self.products.asked, ["test", "live"])


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.reviews = FakeReviews()
        self.invite = {"invite_id": "invite_1", "token": "tok", "status": "active", "order_id": "order_1",
                       "target": {"type": "product", "id": "prod_a"}}
        self.invites = FakeInvites(self.invite)
        self.products = ModedProducts({"live": {("t1", "prod_a"): LIVE_PRODUCT}})

    def post(self, values):
        return handler({"httpMethod": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                        "body": urlencode(values), "requestContext": {"identity": {"sourceIp": "1.2.3.4"}}},
                       None, reviews_repo=self.reviews, products_repo=self.products.for_mode("live"),
                       sites_repo=None, invites_repo=self.invites)

    def base(self, **extra):
        return {"tenant_id": "t1", "product_id": "prod_a", "mode": "live", "rating": "5",
                "author": "Keith", "body": "Worth it.", "company_website": "", **extra}

    def test_a_live_submission_is_stored(self):
        response = self.post(self.base())
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.reviews.saved[0]["target"], {"type": "product", "id": "prod_a"})

    def test_the_invite_still_marks_it_a_verified_purchase(self):
        """The invite is read from the mode the PRODUCT was found in. Reading it from the wrong one lost
        the verified badge AND left the remaining nag emails scheduled."""
        self.post(self.base(invite="invite_1", token="tok"))
        self.assertTrue(self.reviews.saved[0]["verified_purchase"])
        self.assertEqual(self.invites.saved[0]["status"], "completed")

    def test_the_honeypot_answers_before_anything_is_looked_up(self):
        """A bot must not be able to tell a real product from an invented one by what comes back."""
        response = self.post(self.base(product_id="nope", company_website="http://spam"))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.reviews.saved, [])
        self.assertEqual(self.products.asked, [])


if __name__ == "__main__":
    unittest.main()
