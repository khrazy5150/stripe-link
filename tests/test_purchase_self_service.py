"""One button, one transaction, one request.

plans/PURCHASE_SELF_SERVICE.md v1. A customer who wants to stop paying, or wants their money back, had two
routes: find our email, or find the seller. This is the third, from a link at the bottom of the page next to
the refund policy — where someone goes when they want the money to stop.

The rules these tests exist to hold:

* **Never enumerate.** ONE transaction — the latest, or the nearest to a date given. A list behind an
  emailed link is both a privacy target and the screen that ends three subscriptions instead of the one the
  customer came for.
* **A lookup answers identically whether or not anything matched**, or the form is an oracle for "did that
  person buy from this creator" — a fact about someone who is not the one asking.
* **Cancel is a fact; refund is a REQUEST.** Stopping future charges costs the seller nothing, so it happens
  on the spot. A refund moves their money, so it goes in their queue and the copy must not imply otherwise.
"""
import json
import os
import pathlib
import unittest
from unittest.mock import patch

import handlers.purchase_manage as pm
from stripe_link.domain.documents import validate_refund_request
from stripe_link.domain.purchase_lookup import (
    available_actions,
    contact_key,
    order_contact_keys,
    purchase_token_doc,
    refund_request_doc,
    select_order,
)
from handlers.legal import handler as legal_handler
from stripe_link.domain.legal import manage_purchase_block
from stripe_link.runtime.html import render_page

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML_SOURCE = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")


def _order(**overrides):
    order = {
        "order_id": "o1", "tenant_id": "t1", "created_at": "1757000000", "amount_total": 1119,
        "currency": "usd", "payment_status": "paid", "stripe_mode": "live",
        "customer": {"email": "sam@example.com", "name": "Sam", "phone": "+12065550100"},
        "product": {"name": "Support the Cause"}, "metadata": {"tip_recurring": "month"},
        "subscription_id": "sub_1",
    }
    order.update(overrides)
    return order


class FakeOrders:
    def __init__(self, orders=None):
        self.orders = orders if orders is not None else [_order()]

    def list_for_tenant(self, tenant_id):
        return [order for order in self.orders if order.get("tenant_id") == tenant_id]

    def get(self, tenant_id, order_id):
        return next((o for o in self.orders if o.get("order_id") == order_id), None)


class FakeTokens:
    def __init__(self):
        self.rows = {}

    def put(self, document):
        self.rows[document["token"]] = document
        return document

    def find_by_id(self, token):
        return self.rows.get(token)


class FakeRefunds:
    def __init__(self):
        self.saved = []

    def put(self, document):
        self.saved.append(document)
        return document


class ContactMatchingTests(unittest.TestCase):
    def test_an_email_matches_however_it_was_typed(self):
        self.assertEqual(contact_key("  Sam@Example.COM "), "e:sam@example.com")

    def test_a_phone_matches_however_it_was_typed(self):
        # Checkout stored "+12065550100"; the customer types what is on their phone.
        self.assertEqual(contact_key("(206) 555-0100"), contact_key("+1 206-555-0100"))

    def test_nonsense_is_not_a_key(self):
        # An empty key must never match everything -- it returns nothing at all.
        self.assertEqual(contact_key("hello"), "")
        self.assertIsNone(select_order([_order()], contact_key("hello")))

    def test_an_order_written_before_the_field_existed_still_matches(self):
        # This is what lets v1 ship with no backfill: the email is on the row either way.
        old = _order()
        old.pop("contact_keys", None)
        self.assertIn("e:sam@example.com", order_contact_keys(old))
        stored = _order(contact_keys=["e:other@example.com"])
        self.assertEqual(order_contact_keys(stored), ["e:other@example.com"])


class SelectionTests(unittest.TestCase):
    ORDERS = [
        _order(order_id="old", created_at="1000", subscription_id=""),
        _order(order_id="new", created_at="5000"),
        _order(order_id="theirs", created_at="9000", customer={"email": "other@example.com"}),
    ]

    def test_the_latest_one_wins_by_default(self):
        # People ask about the charge they just saw on their statement.
        self.assertEqual(select_order(self.ORDERS, contact_key("sam@example.com"))["order_id"], "new")

    def test_a_date_narrows_instead_of_listing(self):
        chosen = select_order(self.ORDERS, contact_key("sam@example.com"), approximate_date=1200)
        self.assertEqual(chosen["order_id"], "old")

    def test_someone_elses_purchase_is_never_reachable(self):
        self.assertEqual(select_order(self.ORDERS, contact_key("sam@example.com"))["order_id"], "new")
        self.assertEqual(select_order(self.ORDERS, contact_key("other@example.com"))["order_id"], "theirs")


class ActionTests(unittest.TestCase):
    def test_a_subscription_can_be_stopped_and_refunded(self):
        self.assertEqual(available_actions(_order()), ["cancel", "refund"])

    def test_a_one_off_can_only_be_refunded(self):
        self.assertEqual(available_actions(_order(subscription_id="")), ["refund"])

    def test_an_already_refunded_order_offers_nothing_to_refund(self):
        self.assertEqual(available_actions(_order(subscription_id="", amount_refunded=1119)), [])


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tokens = FakeTokens()
        self.orders = FakeOrders()
        self.refunds = FakeRefunds()
        self.sent = []
        self._business = pm._business_name
        pm._business_name = lambda tenant_id: "Poliaxis"

    def tearDown(self):
        pm._business_name = self._business

    def _post(self, body, **kwargs):
        return pm.handler({"httpMethod": "POST", "body": body}, None,
                          orders_repo=self.orders, tokens_repo=self.tokens, refunds_repo=self.refunds,
                          mailer_send=lambda **mail: self.sent.append(mail), **kwargs)

    def test_the_form_asks_for_the_two_things_a_static_page_can_ask(self):
        response = pm.handler({"httpMethod": "GET", "queryStringParameters": {"tenant": "t1"}}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn('name="contact"', response["body"])
        self.assertIn('name="when"', response["body"])
        # Never a card number. A form reached from a link must not teach people to type one. Asserted on the
        # FORM, not the document: the page's own CSS has a `.card` class, which is the third time in this
        # repo a test has searched a whole document for a short string.
        form = response["body"].split("<form", 1)[1].split("</form>", 1)[0]
        self.assertNotIn("card", form.lower())
        self.assertEqual(sorted(field for field in ("contact", "when") if f'name="{field}"' in form),
                         ["contact", "when"])

    def test_a_hit_and_a_miss_are_indistinguishable(self):
        hit = self._post("action=lookup&tenant=t1&contact=sam%40example.com")
        miss = self._post("action=lookup&tenant=t1&contact=nobody%40example.com")
        self.assertEqual(hit["body"], miss["body"])
        self.assertEqual(hit["statusCode"], miss["statusCode"])
        # And only the hit sent anything.
        self.assertEqual(len(self.sent), 1)

    def test_the_link_goes_to_the_address_on_the_ORDER(self):
        # Not to whatever was typed: otherwise anyone could have a stranger's link sent to themselves.
        self._post("action=lookup&tenant=t1&contact=%2B1%20206-555-0100")
        self.assertEqual(self.sent[0]["to"], "sam@example.com")

    def test_the_transaction_page_states_what_it_found(self):
        self._post("action=lookup&tenant=t1&contact=sam%40example.com")
        token = next(iter(self.tokens.rows))
        page = pm.handler({"httpMethod": "GET", "queryStringParameters": {"t": token}}, None,
                          tokens_repo=self.tokens, orders_repo=self.orders)
        self.assertIn("USD 11.19", page["body"])
        self.assertIn("Support the Cause", page["body"])
        # Confirmation, not enumeration -- and a way out when it is the wrong one.
        self.assertIn("Not this one?", page["body"])
        self.assertEqual(page["body"].count('name="action"'), 2)

    def test_a_refund_is_REQUESTED_and_says_so(self):
        self._post("action=lookup&tenant=t1&contact=sam%40example.com")
        token = next(iter(self.tokens.rows))
        response = self._post(f"action=refund&t={token}&reason=changed+my+mind", notifications_repo=None)
        self.assertIn("Request sent", response["body"])
        self.assertIn("decision is theirs", response["body"])
        self.assertNotIn("refunded", response["body"].lower())
        saved = self.refunds.saved[0]
        self.assertEqual(saved["status"], "new")
        self.assertEqual(saved["reason"], "changed my mind")
        validate_refund_request(saved)

    def test_an_expired_token_is_a_page_not_a_stack_trace(self):
        response = pm.handler({"httpMethod": "GET", "queryStringParameters": {"t": "nope"}}, None,
                              tokens_repo=self.tokens, orders_repo=self.orders)
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("expired", response["body"].lower())

    def test_every_page_is_noindex(self):
        response = pm.handler({"httpMethod": "GET", "queryStringParameters": {"tenant": "t1"}}, None)
        self.assertIn("noindex", response["headers"]["X-Robots-Tag"])


class CancelTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._stripe, self._creds, self._business = (
            pm.stripe_request, pm.checkout_credentials, pm._business_name)
        pm.stripe_request = lambda method, path, **kwargs: (
            self.calls.append((method, path, kwargs.get("data"))) or {"id": "sub_1"})
        pm.checkout_credentials = lambda *args, **kwargs: ("sk_test", "acct_1")
        pm._business_name = lambda tenant_id: "Poliaxis"
        self.tokens = FakeTokens()
        self.tokens.put(purchase_token_doc("t1", "good", order_id="o1", email="sam@example.com", now=0))

    def tearDown(self):
        pm.stripe_request, pm.checkout_credentials, pm._business_name = (
            self._stripe, self._creds, self._business)

    class Keys:
        def get(self, tenant_id, mode="test"):
            return {"connect_account_id": "acct_1"}

    def test_cancelling_happens_on_the_spot(self):
        response = pm.handler({"httpMethod": "POST", "body": "action=cancel&t=good"}, None,
                              tokens_repo=self.tokens, orders_repo=FakeOrders(), stripe_repo=self.Keys())
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Payments stopped", response["body"])

    def test_it_cancels_at_the_period_end_not_immediately(self):
        # They paid for the period they are in; taking it away is a refund nobody asked for.
        pm.handler({"httpMethod": "POST", "body": "action=cancel&t=good"}, None,
                   tokens_repo=self.tokens, orders_repo=FakeOrders(), stripe_repo=self.Keys())
        method, path, data = self.calls[0]
        self.assertEqual((method, path), ("POST", "/subscriptions/sub_1"))
        self.assertEqual(data, {"cancel_at_period_end": True})

    def test_it_says_money_already_paid_is_not_coming_back(self):
        response = pm.handler({"httpMethod": "POST", "body": "action=cancel&t=good"}, None,
                              tokens_repo=self.tokens, orders_repo=FakeOrders(), stripe_repo=self.Keys())
        self.assertIn("not returned by this", response["body"])


class EntryPointTests(unittest.TestCase):
    """The way in is ON the refund policy page, not beside it.

    Someone opens Refund Policy because they want the money to stop; a second footer link would compete with
    the page they are already going to (author, 2026-09-14). The page is platform-global, so the tenant
    travels with the footer link.
    """

    def _footer(self, legal=None):
        product = json.loads((ROOT / "schemas" / "examples" / "product-creatine-gummies.json")
                             .read_text(encoding="utf-8"))
        offer = json.loads((ROOT / "schemas" / "examples" / "offer-creatine-standard.json")
                           .read_text(encoding="utf-8"))
        page = json.loads((ROOT / "schemas" / "examples" / "page-creatine-standard.json")
                          .read_text(encoding="utf-8"))
        page["sections"].append({"id": "legal", "type": "legal_footer", "copyright": "(c) Poliaxis"})
        if legal is not None:
            page["legal"] = legal
        html = render_page(page, offer, {product["product_id"]: product},
                           api_base_url="https://api.example.com")
        return html.split('class="sl-legal"', 1)[1].split("</footer>", 1)[0]

    def test_the_refund_link_carries_the_tenant(self):
        footer = self._footer(legal={})
        self.assertIn("/legal/refund?tenant=tenant_demo", footer)

    def test_there_is_no_second_footer_link(self):
        # One way in, on the page someone is already opening.
        self.assertNotIn("Manage a purchase", self._footer(legal={}))

    def test_terms_and_privacy_carry_nothing(self):
        footer = self._footer(legal={})
        self.assertIn("/legal/terms\"", footer)
        self.assertIn("/legal/privacy\"", footer)

    def test_a_tenants_own_refund_url_is_left_alone(self):
        # They own that page; we do not rewrite someone else's URL.
        footer = self._footer(legal={"refund_url": "https://example.com/refunds"})
        self.assertIn('href="https://example.com/refunds"', footer)
        self.assertNotIn("tenant=", footer)

    def test_the_block_only_renders_for_a_real_tenant(self):
        self.assertEqual(manage_purchase_block("", "https://api.example.com"), "")
        self.assertEqual(manage_purchase_block("../evil", "https://api.example.com"), "")
        block = manage_purchase_block("tenant_demo", "https://api.example.com")
        self.assertIn("/purchase/manage?tenant=tenant_demo", block)
        self.assertIn("Manage a purchase", block)

    def test_the_button_label_is_readable_on_the_button(self):
        """Purple text on a purple button, i.e. invisible.

        `.content a` sets the link colour for everything inside the article and outranks a single class, so
        `.manage-cta` lost. Second time in two days a rule of mine was written at equal-or-lower specificity
        than one that already existed -- the fix is the selector, not another rule further down.
        """
        from stripe_link.domain.legal import render_public_page

        html = render_public_page({"title": "Refund", "content": "<p>x</p>"}, {}, 2026,
                                  manage_block=manage_purchase_block("t1", "https://api.example.com"))
        css = html[html.index("<style>"):html.index("</style>")]
        self.assertIn(".content a.manage-cta", css)
        self.assertGreater(css.index(".content a.manage-cta"), css.index(".content a {"))
        button_rule = css.split(".content a.manage-cta", 1)[1].split("}", 1)[0]
        self.assertIn("color:#fff", button_rule)

    def test_the_refund_page_shows_it_and_other_pages_do_not(self):
        class Repo:
            def get(self, tenant_id, page_id):
                return None

            def list_for_tenant(self, tenant_id):
                return []

        with patch.dict(os.environ, {"PUBLIC_API_BASE_URL": "https://api.example.com"}, clear=False):
            refund = legal_handler({"httpMethod": "GET", "pathParameters": {"page_id": "refund"},
                                    "queryStringParameters": {"tenant": "tenant_demo"}}, None, repository=Repo())
            bare = legal_handler({"httpMethod": "GET", "pathParameters": {"page_id": "refund"}},
                                 None, repository=Repo())
            terms = legal_handler({"httpMethod": "GET", "pathParameters": {"page_id": "terms"},
                                   "queryStringParameters": {"tenant": "tenant_demo"}}, None, repository=Repo())
        self.assertIn("Manage a purchase", refund["body"])
        self.assertNotIn("Manage a purchase", bare["body"])
        self.assertNotIn("Manage a purchase", terms["body"])


if __name__ == "__main__":
    unittest.main()
