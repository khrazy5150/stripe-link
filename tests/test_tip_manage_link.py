"""A supporter can stop a recurring tip without an account.

plans/PAY_WHAT_YOU_WANT.md §5g, decided 2026-09-14. Patreon, Ko-fi and Buy Me a Coffee all require a
supporter account, and cancellation runs through it. We deliberately do not build one — the account is a
directory and a feed, cancellation is merely what it happens to make possible, and "what if they lose the
email?" does not favour it either, since account recovery IS email recovery.

But the surface is not optional. A recurring charge nobody can stop is a chargeback generator, and under
direct charges the dispute fee AND the ratio land on the TENANT's account. So: an opaque link in the
receipt, dereferenced server-side, handing the supporter to Stripe's own portal on the connected account
where the subscription actually lives.
"""
import os
import unittest
from unittest.mock import patch

import handlers.tip_manage as tip_manage
from handlers.stripe_webhook import mint_tip_manage_link, send_order_receipt
from stripe_link.domain.receipts import receipt_content
from stripe_link.domain.tips import keyed_amount, manage_token_doc


class FakeTokens:
    def __init__(self, record=None):
        self.written = []
        self.record = record

    def put(self, document):
        self.written.append(document)
        return document

    def find_by_id(self, token):
        return self.record if self.record and self.record.get("token", token) == token else None


ORDER = {
    "order_id": "order_cs_1",
    "amount_total": 1119,
    "currency": "usd",
    "customer": {"name": "Sam", "email": "sam@example.com", "stripe_customer_id": "cus_1"},
    "product": {"name": "Support the Cause"},
}


def _session(**overrides):
    session = {
        "id": "cs_1", "mode": "subscription", "livemode": True, "subscription": "sub_1",
        "metadata": {"tip": "1", "tip_recurring": "month", "tip_keyed_amount": "1000"},
    }
    session.update(overrides)
    return session


class TokenTests(unittest.TestCase):
    def test_the_url_carries_no_identity(self):
        # The token dereferences server-side, like a cart-recovery link: no customer id, no email in a URL
        # that will sit in an inbox for a year.
        doc = manage_token_doc("t1", "tok_abc", email="Sam@Example.com",
                               stripe_customer_id="cus_1", subscription_id="sub_1", mode="live", now=1000)
        self.assertEqual(doc["document_type"], "tip_token")
        self.assertEqual(doc["email"], "sam@example.com")
        self.assertEqual(doc["stripe_customer_id"], "cus_1")
        self.assertGreater(doc["expires_at"], doc["created_at"])

    def test_it_outlives_a_cart_nudge(self):
        # A supporter may cancel a monthly tip a year in. A 30-day token would have expired long before the
        # moment it exists for.
        doc = manage_token_doc("t1", "tok", email="a@b.co", stripe_customer_id="cus_1", now=0)
        self.assertGreater(doc["expires_at"], 365 * 24 * 60 * 60)


class MintingTests(unittest.TestCase):
    def _mint(self, session, repo=None, base="https://api.example.com"):
        with patch.dict(os.environ, {"PUBLIC_API_BASE_URL": base}, clear=False):
            return mint_tip_manage_link(session, ORDER, "t1", repo if repo is not None else FakeTokens(), 1000)

    def test_a_recurring_tip_gets_a_link(self):
        repo = FakeTokens()
        url = self._mint(_session(), repo)
        self.assertTrue(url.startswith("https://api.example.com/tips/manage?t="))
        self.assertEqual(repo.written[0]["stripe_customer_id"], "cus_1")
        self.assertEqual(repo.written[0]["subscription_id"], "sub_1")
        # The token is the credential, so it has to be unguessable rather than derived from the order.
        self.assertNotIn("cs_1", url)
        self.assertNotIn("cus_1", url)

    def test_a_one_off_tip_has_nothing_to_manage(self):
        repo = FakeTokens()
        self.assertEqual(self._mint(_session(mode="payment", metadata={"tip": "1"}), repo), "")
        self.assertEqual(repo.written, [])

    def test_an_ordinary_subscription_is_not_a_tip(self):
        repo = FakeTokens()
        self.assertEqual(self._mint(_session(metadata={}), repo), "")
        self.assertEqual(repo.written, [])

    def test_a_failure_costs_the_link_and_not_the_tip(self):
        # Best-effort like every side effect in that webhook: raising would make Stripe retry and duplicate
        # every write that already succeeded.
        class Broken:
            def put(self, document):
                raise RuntimeError("table gone")

        self.assertEqual(self._mint(_session(), Broken()), "")

    def test_no_api_base_means_no_half_built_link(self):
        self.assertEqual(self._mint(_session(), FakeTokens(), base=""), "")


class ReceiptTests(unittest.TestCase):
    def test_the_receipt_carries_the_link(self):
        content = receipt_content(ORDER, business_name="Poliaxis",
                                  manage_url="https://api.example.com/tips/manage?t=tok")
        self.assertIn("Manage or cancel this recurring tip", content["text"])
        self.assertIn("https://api.example.com/tips/manage?t=tok", content["text"])
        self.assertIn("tips/manage?t=tok", content["html"])

    def test_an_ordinary_receipt_says_nothing_about_managing(self):
        content = receipt_content(ORDER, business_name="Poliaxis")
        self.assertNotIn("Manage or cancel", content["text"])
        self.assertNotIn("Manage or cancel", content["html"])

    def test_the_webhook_passes_it_through(self):
        sent = {}

        def fake_send(**kwargs):
            sent.update(kwargs)

        result = send_order_receipt(
            ORDER, "t1", mailer_send=fake_send,
            context_loader=lambda tenant: {"business_name": "Poliaxis", "support_email": ""},
            manage_url="https://api.example.com/tips/manage?t=tok",
        )
        self.assertEqual(result["status"], "sent")
        self.assertIn("tips/manage?t=tok", sent["text"])


class EndpointTests(unittest.TestCase):
    RECORD = {"tenant_id": "t1", "stripe_customer_id": "cus_1", "stripe_mode": "live",
              "subscription_id": "sub_1"}

    def _handler(self, token, record=RECORD, stripe=None):
        calls = []

        def fake_stripe(method, path, *, api_key, stripe_account="", data=None, **kwargs):
            calls.append({"method": method, "path": path, "account": stripe_account, "data": data})
            return stripe if stripe is not None else {"url": "https://billing.stripe.com/p/s_1"}

        class Keys:
            def get(self, tenant_id, mode="test"):
                return {"connect_account_id": "acct_1"}

        with patch.object(tip_manage, "stripe_request", fake_stripe), \
                patch.object(tip_manage, "checkout_credentials", lambda *a, **k: ("sk_test", "acct_1")):
            response = tip_manage.handler(
                {"httpMethod": "GET", "queryStringParameters": {"t": token} if token else {}}, None,
                tokens_repo=FakeTokens({**record, "token": "good"} if record else None), stripe_repo=Keys(),
            )
        return response, calls

    def test_a_valid_link_lands_on_the_portal(self):
        response, calls = self._handler("good")
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["Location"], "https://billing.stripe.com/p/s_1")
        # On the CONNECTED account: direct charges mean the subscription lives there, not on the platform.
        self.assertEqual(calls[0]["path"], "/billing_portal/sessions")
        self.assertEqual(calls[0]["account"], "acct_1")
        self.assertEqual(calls[0]["data"]["customer"], "cus_1")

    def test_the_link_opens_the_cancel_flow_and_nothing_else(self):
        """The narrowing that makes "a leaked link is harmless" actually true.

        An account-wide portal shows invoice history and the card's last four and allows a payment-method
        change. Stripe hides the portal's navigation inside a flow, so this link does one thing: cancel the
        subscription it was minted for.
        """
        _, calls = self._handler("good")
        flow = calls[0]["data"]["flow_data"]
        self.assertEqual(flow["type"], "subscription_cancel")
        self.assertEqual(flow["subscription_cancel"]["subscription"], "sub_1")

    def test_a_record_with_no_subscription_still_opens_something(self):
        # Defensive: a token minted before the subscription id was stored would otherwise 500 on a missing
        # key. It degrades to the account portal rather than to nothing.
        _, calls = self._handler("good", record={"tenant_id": "t1", "stripe_customer_id": "cus_1",
                                                 "stripe_mode": "live"})
        self.assertNotIn("flow_data", calls[0]["data"])

    def test_an_unknown_token_is_a_page_not_a_stack_trace(self):
        response, calls = self._handler("nope")
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("no longer valid", response["body"])
        self.assertEqual(calls, [])

    def test_a_missing_token_says_the_same_thing(self):
        response, _ = self._handler("")
        self.assertEqual(response["statusCode"], 404)

    def test_stripe_being_down_does_not_leak_a_stack_trace(self):
        from stripe_link.stripe_client import StripeApiError

        def boom(*args, **kwargs):
            raise StripeApiError(503, "nope")

        class Keys:
            def get(self, tenant_id, mode="test"):
                return {"connect_account_id": "acct_1"}

        with patch.object(tip_manage, "stripe_request", boom), \
                patch.object(tip_manage, "checkout_credentials", lambda *a, **k: ("sk_test", "acct_1")):
            response = tip_manage.handler(
                {"httpMethod": "GET", "queryStringParameters": {"t": "good"}}, None,
                tokens_repo=FakeTokens({**self.RECORD, "token": "good"}), stripe_repo=Keys(),
            )
        self.assertEqual(response["statusCode"], 503)
        self.assertIn("try again", response["body"])

    def test_the_page_is_never_indexed(self):
        response, _ = self._handler("nope")
        self.assertIn("noindex", response["headers"]["X-Robots-Tag"])


class KeyedAmountTests(unittest.TestCase):
    """What the tenant keeps, frozen at checkout — the §5f prerequisite, captured here because the recurring
    work is what put a tip through checkout at all."""

    PRICE = {"presets": [300, 500, 1000], "preset_charges": [346, 576, 1119], "allow_custom": True}

    def test_a_preset_charge_maps_back_to_what_the_tenant_keeps(self):
        self.assertEqual(keyed_amount(self.PRICE, 1119), 1000)
        self.assertEqual(keyed_amount(self.PRICE, 346), 300)

    def test_a_typed_amount_is_already_the_keyed_one(self):
        # The supporter typed what they meant to GIVE; the fees were added on top of it.
        self.assertEqual(keyed_amount(self.PRICE, 2000, source="custom"), 2000)

    def test_an_unrecognised_charge_falls_back_to_itself(self):
        # Rather than raising inside a checkout that has already been priced.
        self.assertEqual(keyed_amount(self.PRICE, 777), 777)


if __name__ == "__main__":
    unittest.main()
