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
from stripe_link.domain.leads import HONEYPOT_FIELD
from stripe_link.domain.legal import manage_purchase_block
from stripe_link.domain.request_throttle import TENANT_LIMIT, is_over_limit, next_count, throttle_doc, throttle_id
from stripe_link.runtime.html import render_page
from stripe_link.runtime.purchase_pages import render_lookup_sent

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


class ThrottleTests(unittest.TestCase):
    """The gate on a public endpoint that reads a whole order list and sends mail.

    Unthrottled, one HTTP request amplified into a full read of a tenant's orders (in BOTH modes) plus an
    outbound email — with the tenant id sitting in a public footer URL. Two counters: per (tenant, contact)
    so one address cannot be mailed repeatedly, and per tenant so enumerating DIFFERENT addresses is capped
    too, which the first counter cannot see.
    """

    class Throttles:
        def __init__(self):
            self.rows = {}

        def get(self, tenant_id, identifier):
            return self.rows.get((tenant_id, identifier))

        def put(self, document):
            self.rows[(document["tenant_id"], document["throttle_id"])] = document
            return document

    def setUp(self):
        self.orders = FakeOrders()
        self.tokens = FakeTokens()
        self.throttles = self.Throttles()
        self.sent = []
        self.reads = []
        self._business = pm._business_name
        pm._business_name = lambda tenant_id: "Poliaxis"
        orders = self.orders
        outer = self

        class CountingOrders:
            def list_for_tenant(self, tenant_id):
                outer.reads.append(tenant_id)
                return orders.list_for_tenant(tenant_id)

            def get(self, tenant_id, order_id):
                return orders.get(tenant_id, order_id)

        self.counting = CountingOrders()

    def tearDown(self):
        pm._business_name = self._business

    def _lookup(self, contact="sam@example.com", now=1000, extra=""):
        return pm.handler({"httpMethod": "POST",
                           "body": f"action=lookup&tenant=t1&contact={contact}{extra}"}, None,
                          orders_repo=self.counting, tokens_repo=self.tokens,
                          throttles_repo=self.throttles,
                          mailer_send=lambda **mail: self.sent.append(mail),
                          now_fn=lambda: now)

    def test_the_same_contact_is_mailed_once_per_window(self):
        first = self._lookup()
        second = self._lookup()
        self.assertEqual(len(self.sent), 1)
        # And the refusal is INDISTINGUISHABLE from the first answer, or the throttle itself leaks which
        # addresses matched.
        self.assertEqual(first["body"], second["body"])

    def test_a_blocked_request_does_no_work_at_all(self):
        self._lookup()
        reads_after_first = len(self.reads)
        self._lookup()
        self.assertEqual(len(self.reads), reads_after_first)

    def test_the_window_eventually_rolls(self):
        self._lookup(now=1000)
        self._lookup(now=1000 + 16 * 60)
        self.assertEqual(len(self.sent), 2)

    def test_enumerating_different_addresses_is_capped_too(self):
        # The per-contact gate cannot see this: every address is its own counter.
        for index in range(30):
            self._lookup(contact=f"person{index}%40example.com")
        self.assertLessEqual(len(self.reads), TENANT_LIMIT * 2)  # two modes per allowed request

    def test_the_honeypot_is_rendered_and_read(self):
        form = pm.handler({"httpMethod": "GET", "queryStringParameters": {"tenant": "t1"}}, None)
        self.assertIn(f'name="{HONEYPOT_FIELD}"', form["body"])
        # A bot that fills every field gets the same page and nothing else happens.
        response = self._lookup(extra=f"&{HONEYPOT_FIELD}=http%3A%2F%2Fspam")
        self.assertEqual(response["body"], render_lookup_sent())
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reads, [])

    def test_it_fails_OPEN_when_the_counter_is_unavailable(self):
        """A throttle table that is down must not take the cancel-my-subscription path with it.

        Being wrong this way costs some extra reads. Being wrong the other way costs a customer who cannot
        stop a recurring charge — and that is the failure this whole flow exists to prevent.
        """
        class Broken:
            def get(self, *args, **kwargs):
                raise RuntimeError("table gone")

            def put(self, *args, **kwargs):
                raise RuntimeError("table gone")

        response = pm.handler({"httpMethod": "POST", "body": "action=lookup&tenant=t1&contact=sam%40example.com"},
                              None, orders_repo=self.counting, tokens_repo=self.tokens,
                              throttles_repo=Broken(),
                              mailer_send=lambda **mail: self.sent.append(mail), now_fn=lambda: 1000)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(self.sent), 1)


class ThrottleCounterTests(unittest.TestCase):
    def test_a_counter_from_an_earlier_window_counts_for_nothing(self):
        old = throttle_doc("t1", "x", now=0, window_seconds=900, count=99)
        self.assertFalse(is_over_limit(old, now=100000, window_seconds=900, limit=1))
        self.assertEqual(next_count(old, now=100000, window_seconds=900), 1)

    def test_the_id_carries_no_readable_contact(self):
        # A primary key is the one value that ends up in logs and metrics without anyone deciding it should.
        identifier = throttle_id("contact", "t1", "e:sam@example.com")
        self.assertNotIn("sam", identifier)
        self.assertNotIn("@", identifier)
        self.assertEqual(identifier, throttle_id("contact", "t1", "e:sam@example.com"))


if __name__ == "__main__":
    unittest.main()


class MultiplePurchaseTests(unittest.TestCase):
    """One buyer, several purchases — the case that shipped broken.

    Found 2026-09-28 against real money: four daily subscriptions under one email, and the lookup
    returned the newest and stopped. The customer could cancel exactly one and had no route to the
    other three, which is precisely the situation that sends someone to their bank instead — the
    dispute this whole flow exists to prevent, caused by the flow itself.
    """

    CONTACT = "buyer@example.com"

    def orders(self):
        return [
            {"order_id": "o_sub_a", "customer": {"email": self.CONTACT}, "created_at": 300,
             "amount_total": 19792, "currency": "usd", "subscription_id": "sub_a",
             "product": {"name": "Premium Bundle"}},
            {"order_id": "o_sub_b", "customer": {"email": self.CONTACT}, "created_at": 200,
             "amount_total": 3291, "currency": "usd", "subscription_id": "sub_b",
             "line_items": [{"name": "1 × Creatine Gummies (at $32.91 / day)"}]},
            {"order_id": "o_once", "customer": {"email": self.CONTACT}, "created_at": 100,
             "amount_total": 1445, "currency": "usd", "product": {"name": "Shaker Bottle"}},
            {"order_id": "o_other", "customer": {"email": "someone@else.com"}, "created_at": 400,
             "amount_total": 999, "currency": "usd"},
        ]

    # ---- the matcher --------------------------------------------------------------------------
    def test_every_purchase_for_the_contact_is_returned(self):
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        found = select_orders(self.orders(), contact_key(self.CONTACT))
        self.assertEqual([o["order_id"] for o in found], ["o_sub_a", "o_sub_b", "o_once"])

    def test_another_contacts_purchase_is_never_included(self):
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        found = select_orders(self.orders(), contact_key(self.CONTACT))
        self.assertNotIn("o_other", [o["order_id"] for o in found])

    def test_a_date_reorders_rather_than_collapsing_the_list(self):
        # "it was around March" should narrow, not guess -- the old behaviour picked one and stopped.
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        found = select_orders(self.orders(), contact_key(self.CONTACT), approximate_date=100)
        self.assertEqual(found[0]["order_id"], "o_once")
        self.assertEqual(len(found), 3)

    def test_the_list_is_capped(self):
        from stripe_link.domain.purchase_lookup import MAX_LISTED, contact_key, select_orders
        many = [{"order_id": f"o{n}", "customer": {"email": self.CONTACT}, "created_at": n}
                for n in range(50)]
        self.assertEqual(len(select_orders(many, contact_key(self.CONTACT))), MAX_LISTED)

    def test_an_unknown_contact_gets_nothing(self):
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        self.assertEqual(select_orders(self.orders(), contact_key("nobody@example.com")), [])

    # ---- labelling ----------------------------------------------------------------------------
    def test_a_purchase_is_named_the_way_the_buyer_would_recognise_it(self):
        from stripe_link.domain.purchase_lookup import order_label
        self.assertEqual(order_label(self.orders()[0]), "Premium Bundle")

    def test_a_renewal_line_is_stripped_back_to_the_product_name(self):
        # Stripe writes "1 × Creatine Gummies (at $32.91 / day)"; the count and price are shown beside it.
        from stripe_link.domain.purchase_lookup import order_label
        self.assertEqual(order_label(self.orders()[1]), "Creatine Gummies")

    def test_an_unnameable_purchase_still_gets_a_label(self):
        from stripe_link.domain.purchase_lookup import order_label
        self.assertEqual(order_label({"order_id": "x"}), "Your purchase")

    def test_a_price_is_never_used_as_a_product_name(self):
        # "1 x $197.92 (at $197.92 / day)" strips to a bare price, and "$197.92 — USD 197.92" tells a
        # buyer nothing about WHICH purchase it is.
        from stripe_link.domain.purchase_lookup import order_label
        priced = {"order_id": "p", "subscription_id": "sub_p",
                  "line_items": [{"name": "1 × $197.92 (at $197.92 / day)"}]}
        self.assertEqual(order_label(priced), "Subscription")

    def test_renewals_of_one_subscription_appear_once(self):
        """A renewal writes an order each cycle, so four daily subscriptions produced eight rows --
        the same subscription listed twice, once per charge. A buyer cancelling the first would see
        the second still listed and conclude it had not worked."""
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        renewals = [
            {"order_id": "r2", "customer": {"email": self.CONTACT}, "created_at": 300,
             "subscription_id": "sub_a", "product": {"name": "Gummies"}},
            {"order_id": "r1", "customer": {"email": self.CONTACT}, "created_at": 200,
             "subscription_id": "sub_a", "product": {"name": "Gummies"}},
        ]
        found = select_orders(renewals, contact_key(self.CONTACT))
        self.assertEqual([o["order_id"] for o in found], ["r2"])   # the latest charge

    def test_two_separate_one_off_purchases_both_appear(self):
        # Buying the same thing twice IS two purchases, and each has its own refund window.
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        twice = [{"order_id": "a", "customer": {"email": self.CONTACT}, "created_at": 200,
                  "product": {"name": "Shaker"}},
                 {"order_id": "b", "customer": {"email": self.CONTACT}, "created_at": 100,
                  "product": {"name": "Shaker"}}]
        self.assertEqual(len(select_orders(twice, contact_key(self.CONTACT))), 2)

    def test_recurring_and_one_off_are_distinguishable(self):
        # "Cancel" means nothing on a one-off, and a buyer scanning a list needs to know which charge
        # is the one that keeps coming back.
        from stripe_link.domain.purchase_lookup import is_recurring
        self.assertTrue(is_recurring(self.orders()[0]))
        self.assertFalse(is_recurring(self.orders()[2]))

    # ---- the email ------------------------------------------------------------------------------
    def send(self, orders):
        import handlers.purchase_manage as pm
        captured = {}
        pm._send_link([(o, f"tok_{o['order_id']}") for o in orders], "t1", lambda **kw: captured.update(kw))
        return captured

    def test_the_email_lists_every_purchase_with_its_own_link(self):
        sent = self.send(self.orders()[:3])
        for order_id in ("o_sub_a", "o_sub_b", "o_once"):
            self.assertIn(f"tok_{order_id}", sent["text"])
            self.assertIn(f"tok_{order_id}", sent["html"])

    def test_each_link_is_a_separate_token(self):
        """One token per order, still. purchase_token_doc is scoped to a single order on purpose --
        "a leaked link can never sweep a history" -- so listing several must not hand one token
        several purchases."""
        sent = self.send(self.orders()[:3])
        tokens = {line.split("t=")[1] for line in sent["text"].splitlines() if "t=" in line}
        self.assertEqual(len(tokens), 3)

    def test_the_email_says_what_each_purchase_is_and_costs(self):
        sent = self.send(self.orders()[:3])
        self.assertIn("Premium Bundle", sent["text"])
        self.assertIn("197.92", sent["text"])
        self.assertIn("Creatine Gummies", sent["text"])

    def test_no_html_tags_reach_the_reader(self):
        # paragraph() escapes what it is given -- rightly, since these carry tenant-supplied product
        # names -- so HTML passed to it arrives as visible <strong> tags. Reported from a real inbox.
        sent = self.send(self.orders()[:3])
        for leak in ("&lt;strong&gt;", "&lt;p&gt;", "&lt;a "):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, sent["html"])
        self.assertNotIn("<strong>", sent["text"])

    def test_the_seller_is_named_the_same_way_the_header_names_them(self):
        # The header read "Poliaxis Nutrition" while the body said "the seller", in one message,
        # because they read different sources.
        import handlers.purchase_manage as pm
        original = pm.tenant_email_identity
        pm.tenant_email_identity = lambda t: {"business_name": "Poliaxis Nutrition", "reply_to": ""}
        try:
            sent = self.send(self.orders()[:3])
            self.assertIn("Poliaxis Nutrition", sent["subject"])
            self.assertIn("Poliaxis Nutrition", sent["text"])
            self.assertNotIn("the seller", sent["text"])
        finally:
            pm.tenant_email_identity = original

    def test_an_unnamed_subscription_does_not_say_subscription_twice(self):
        unnamed = [{"order_id": "u", "customer": {"email": self.CONTACT}, "created_at": 100,
                    "amount_total": 19792, "currency": "usd", "subscription_id": "sub_u",
                    "line_items": [{"name": "1 × $197.92 (at $197.92 / day)"}]}]
        sent = self.send(unnamed)
        self.assertNotIn("subscription subscription", sent["text"].lower())

    def test_the_email_marks_which_ones_recur(self):
        sent = self.send(self.orders()[:3])
        self.assertIn("subscription", sent["text"])
        self.assertIn("one-time", sent["text"])

    def test_the_date_disambiguates_two_of_the_same_product(self):
        same = [dict(self.orders()[1], order_id="o_a", created_at=1790627700),
                dict(self.orders()[1], order_id="o_b", created_at=1790541300)]
        sent = self.send(same)
        self.assertIn("28 Sep 2026", sent["text"])
        self.assertIn("27 Sep 2026", sent["text"])

    def test_one_purchase_still_reads_as_one_purchase(self):
        # The common case must not become a list of one with a "pick one" instruction.
        sent = self.send(self.orders()[:1])
        self.assertNotIn("Pick the one", sent["text"])
        self.assertTrue(sent["subject"].startswith("Your purchase"))

    def test_an_unnamed_seller_is_omitted_rather_than_called_the_seller(self):
        # "Your purchase from the seller" reads worse than "Your purchase", and the header would have
        # been blank anyway.
        sent = self.send(self.orders()[:1])
        self.assertNotIn("from ", sent["subject"])
        self.assertNotIn("the seller", sent["text"])

    def test_several_purchases_say_how_many(self):
        sent = self.send(self.orders()[:3])
        self.assertIn("3 purchases", sent["subject"])
        self.assertIn("Pick the one", sent["text"])

    def test_nothing_is_sent_without_an_address(self):
        sent = self.send([{"order_id": "x", "customer": {}, "created_at": 1}])
        self.assertEqual(sent, {})

    def test_an_empty_match_sends_nothing(self):
        sent = self.send([])
        self.assertEqual(sent, {})

    def test_an_unreadable_date_does_not_cost_the_email(self):
        sent = self.send([dict(self.orders()[0], created_at="not-a-date")])
        self.assertIn("Premium Bundle", sent["text"])


class CancellationEmailTests(unittest.TestCase):
    """Cancelling used to render a page and send nothing.

    The only record was a tab the customer could close. That is the shape that produces a chargeback
    -- not "I was charged after cancelling", which cancel_at_period_end already prevents, but "I think
    I cancelled, I have nothing saying so, and I cannot tell whether another payment is coming".
    Someone in that state calls their bank, which is the dispute this flow exists to avoid.
    """

    PERIOD_END = 1790714125     # 29 September 2026

    def setUp(self):
        self.sent = []
        self.calls = []
        self._stripe, self._creds, self._business, self._identity = (
            pm.stripe_request, pm.checkout_credentials, pm._business_name, pm.tenant_email_identity)
        pm.stripe_request = lambda method, path, **kwargs: (
            self.calls.append((method, path, kwargs.get("data")))
            or {"id": "sub_1", "cancel_at_period_end": True,
                "items": {"data": [{"current_period_end": self.PERIOD_END}]}})
        pm.checkout_credentials = lambda *a, **k: ("sk_test", "acct_1")
        pm._business_name = lambda tenant_id: "Poliaxis"
        pm.tenant_email_identity = lambda tenant_id: {"business_name": "Poliaxis",
                                                      "reply_to": "hi@poliaxis.com"}
        self.tokens = FakeTokens()
        self.tokens.put(purchase_token_doc("t1", "good", order_id="o1",
                                           email="sam@example.com", now=0))

    def tearDown(self):
        pm.stripe_request, pm.checkout_credentials, pm._business_name, pm.tenant_email_identity = (
            self._stripe, self._creds, self._business, self._identity)

    class Keys:
        def get(self, tenant_id, mode="test"):
            return {"connect_account_id": "acct_1"}

    def cancel(self, **over):
        kwargs = dict(tokens_repo=self.tokens, orders_repo=FakeOrders(), stripe_repo=self.Keys(),
                      mailer_send=lambda **kw: self.sent.append(kw))
        kwargs.update(over)
        return pm.handler({"httpMethod": "POST", "body": "action=cancel&t=good"}, None, **kwargs)

    def test_cancelling_confirms_in_writing(self):
        self.cancel()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "sam@example.com")

    def test_the_email_answers_the_actual_question(self):
        # "Am I going to be charged again?" is the only thing they want to know.
        self.cancel()
        self.assertIn("will not be charged again", self.sent[0]["text"])

    def test_the_email_says_when_access_ends(self):
        # A cancelled subscription stays ACTIVE until period end; without the date, a customer who
        # checks and finds it running reads "cancelled" as a failure.
        self.cancel()
        self.assertIn("29 September 2026", self.sent[0]["text"])

    def test_the_email_carries_the_refund_route(self):
        # Cancelling and wanting money back are usually the same conversation, and the refund link is
        # otherwise a page they have just navigated away from.
        self.cancel()
        self.assertIn("t=good", self.sent[0]["text"])

    def test_the_page_says_when_access_ends_and_that_we_emailed(self):
        body = self.cancel()["body"]
        self.assertIn("29 September 2026", body)
        self.assertIn("sam@example.com", body)

    def test_a_failed_email_never_reports_the_cancellation_as_failed(self):
        # The cancellation SUCCEEDED at Stripe. Telling the customer otherwise would have them cancel
        # again, or call their bank.
        def broken(**kwargs):
            raise RuntimeError("SES is having a day")
        response = self.cancel(mailer_send=broken)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Payments stopped", response["body"])
        self.assertNotIn("emailed a confirmation", response["body"])

    def test_an_unreadable_period_end_omits_the_date_rather_than_guessing(self):
        pm.stripe_request = lambda method, path, **kwargs: {"id": "sub_1"}
        response = self.cancel()
        self.assertIn("Payments stopped", response["body"])
        self.assertNotIn("You keep access until", response["body"])
        self.assertIn("will not be charged again", self.sent[0]["text"])

    def test_the_period_end_is_read_from_the_item_as_well_as_the_subscription(self):
        # The 2026-05-27 API version moved fields down onto the line item, and that move has already
        # cost this codebase once.
        self.assertEqual(pm._period_end({"items": {"data": [{"current_period_end": 99}]}}), 99)
        self.assertEqual(pm._period_end({"current_period_end": 42}), 42)
        self.assertEqual(pm._period_end({"cancel_at": 7}), 7)
        self.assertEqual(pm._period_end({}), 0)

    def test_nothing_is_emailed_without_an_address(self):
        class NoEmail(FakeOrders):
            def get(self, tenant_id, order_id):
                order = dict(super().get(tenant_id, order_id) or {})
                order["customer"] = {}
                return order
        response = self.cancel(orders_repo=NoEmail())
        self.assertEqual(self.sent, [])
        self.assertIn("Payments stopped", response["body"])


class AlreadyCancelledTests(unittest.TestCase):
    """A stopped subscription is not a choice.

    Offering "cancel" on something already cancelled invites a customer to do something that cannot
    happen -- and a second confirmation has them wondering whether the first one took, which is the
    doubt this flow exists to remove.
    """

    CONTACT = "buyer@example.com"

    def order(self, oid, sub=None, *, at=100, cancelled=None, name="Gummies"):
        from stripe_link.domain.purchase_lookup import CANCELLED_FIELD
        row = {"order_id": oid, "customer": {"email": self.CONTACT}, "created_at": at,
               "amount_total": 3291, "currency": "usd", "payment_status": "paid",
               "product": {"name": name}}
        if sub:
            row["subscription_id"] = sub
        if cancelled:
            row[CANCELLED_FIELD] = cancelled
        return row

    def offered(self, orders):
        from stripe_link.domain.purchase_lookup import contact_key, select_orders
        return [o["order_id"] for o in select_orders(orders, contact_key(self.CONTACT))]

    def test_a_cancelled_subscription_is_not_offered(self):
        self.assertEqual(
            self.offered([self.order("a", "sub_A", at=200, cancelled=1790700000),
                          self.order("b", "sub_B", at=300)]),
            ["b"])

    def test_the_whole_subscription_goes_even_when_the_stamp_is_on_an_older_renewal(self):
        # The stamp lands on the one order the link pointed at; a subscription has an order per cycle.
        # Matching by subscription id is what makes one cancellation cover every charge it produced.
        self.assertEqual(
            self.offered([self.order("new", "sub_A", at=300),
                          self.order("old", "sub_A", at=200, cancelled=1790700000),
                          self.order("other", "sub_B", at=250)]),
            ["other"])

    def test_a_one_off_purchase_is_never_swept_up(self):
        # It has no subscription, so it cannot be cancelled and was never at risk -- but its refund
        # window is still open and it must stay reachable.
        self.assertEqual(
            self.offered([self.order("sub", "sub_A", at=200, cancelled=1790700000),
                          self.order("once", None, at=100, name="Shaker")]),
            ["once"])

    def test_a_cancelled_subscription_still_appears_when_it_is_all_they_have(self):
        """Otherwise the customer gets no email at all -- and the reason they are looking is usually
        the refund, which is still open to them."""
        self.assertEqual(self.offered([self.order("only", "sub_A", cancelled=1790700000)]), ["only"])

    def test_but_it_never_offers_cancel_again(self):
        from stripe_link.domain.purchase_lookup import available_actions
        self.assertEqual(available_actions(self.order("x", "sub_A", cancelled=1790700000)), ["refund"])
        self.assertEqual(available_actions(self.order("y", "sub_B")), ["cancel", "refund"])

    def test_a_malformed_stamp_is_treated_as_not_cancelled(self):
        # Failing the other way would hide a live subscription from the only screen that can stop it.
        from stripe_link.domain.purchase_lookup import is_cancelled
        for value in (None, "", 0, "yesterday", -1, {}):
            with self.subTest(value=value):
                self.assertFalse(is_cancelled({"subscription_cancelled_at": value}))


class CancelRecordsItLocallyTests(unittest.TestCase):
    """Cancelling stamps the order, so a later lookup knows without asking Stripe.

    Asking would mean one API call per subscription inside an unauthenticated endpoint that is
    throttled precisely because it "amplifies one HTTP request into a full read of a tenant's order
    list plus an outbound email".
    """

    def setUp(self):
        self._stripe, self._creds, self._business, self._identity = (
            pm.stripe_request, pm.checkout_credentials, pm._business_name, pm.tenant_email_identity)
        pm.stripe_request = lambda method, path, **kwargs: {
            "id": "sub_1", "items": {"data": [{"current_period_end": 1790714125}]}}
        pm.checkout_credentials = lambda *a, **k: ("sk_test", "acct_1")
        pm._business_name = lambda t: "Poliaxis"
        pm.tenant_email_identity = lambda t: {"business_name": "Poliaxis", "reply_to": ""}
        self.tokens = FakeTokens()
        self.tokens.put(purchase_token_doc("t1", "good", order_id="o1", email="s@x.com", now=0))
        self.saved = []

    def tearDown(self):
        pm.stripe_request, pm.checkout_credentials, pm._business_name, pm.tenant_email_identity = (
            self._stripe, self._creds, self._business, self._identity)

    class Keys:
        def get(self, tenant_id, mode="test"):
            return {"connect_account_id": "acct_1"}

    def cancel(self, orders_repo):
        return pm.handler({"httpMethod": "POST", "body": "action=cancel&t=good"}, None,
                          tokens_repo=self.tokens, orders_repo=orders_repo, stripe_repo=self.Keys(),
                          mailer_send=lambda **kw: None, now_fn=lambda: 1790710000)

    def test_the_order_is_stamped_with_when_it_was_cancelled(self):
        saved = []
        class Repo(FakeOrders):
            def put(self, document):
                saved.append(document)
                return document
        self.cancel(Repo())
        self.assertTrue(saved)
        self.assertEqual(saved[0]["subscription_cancelled_at"], 1790710000)
        self.assertEqual(saved[0]["subscription_ends_at"], 1790714125)

    def test_a_failed_stamp_never_reports_the_cancellation_as_failed(self):
        # It ALREADY happened at Stripe. Saying otherwise has them cancel twice or call their bank.
        class Broken(FakeOrders):
            def put(self, document):
                raise RuntimeError("dynamo is having a day")
        response = self.cancel(Broken())
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Payments stopped", response["body"])
