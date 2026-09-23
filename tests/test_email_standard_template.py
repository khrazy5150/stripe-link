"""The standard transactional email: one identity, one shell (plans/EMAIL_TEMPLATE.md).

Two defects drove this, both visible in a real inbox on 2026-09-23: a review invite that carried the
business name but no Reply-To, and a receipt from a bare `support@juniorbay.net` with no name and no
Reply-To either. Neither was a missing capability — `mailer.send_email` had taken `from_name` and
`reply_to` since it was written. The callers just did not pass them, and the two that resolved a name read
different fields.
"""

import unittest

from stripe_link import mailer
from stripe_link.domain.business_email import email_identity, reply_to_address
from stripe_link.domain.cart_recovery import recovery_email
from stripe_link.domain.email_layout import (
    FONT_STACK,
    MAX_WIDTH,
    button,
    paragraph,
    render_email,
    rows_table,
)
from stripe_link.domain.invoicing import invoice_email_content
from stripe_link.domain.receipts import receipt_content
from stripe_link.domain.review_invites import invite_email

BUSINESS = "Poliaxis Nutrition"
REPLY = "keith@example.com"


class FakeProfiles:
    def __init__(self, profile=None, raises=False):
        self.profile, self.raises = profile, raises
        self.calls = []

    def get(self, tenant_id, user_id):
        self.calls.append((tenant_id, user_id))
        if self.raises:
            raise RuntimeError("table on fire")
        return self.profile


class FakeClient:
    def __init__(self):
        self.request = None

    def send_email(self, **kwargs):
        self.request = kwargs
        return {"MessageId": "m1"}


class IdentityResolutionTests(unittest.TestCase):
    def test_a_verified_business_email_is_preferred(self):
        identity = email_identity({
            "business": {"name": BUSINESS, "email": "biz@x.com", "email_verified": True},
            "email": "signup@x.com"})

        self.assertEqual(identity, {"business_name": BUSINESS, "reply_to": "biz@x.com"})

    def test_an_unverified_business_email_falls_back_to_the_signup_address(self):
        # The measured reality: on 2026-09-23 not one tenant in dev or prod had ever verified a business
        # email, so gating on verification alone is what left every reply undeliverable.
        identity = email_identity({
            "business": {"name": BUSINESS, "email": "biz@x.com"}, "email": "signup@x.com"})

        self.assertEqual(identity["reply_to"], "signup@x.com")

    def test_the_name_falls_through_business_then_display_then_person(self):
        self.assertEqual(email_identity({"business": {"name": BUSINESS}})["business_name"], BUSINESS)
        self.assertEqual(email_identity({"display_name": "Keith's Shop"})["business_name"], "Keith's Shop")
        self.assertEqual(
            email_identity({"first_name": "Keith", "last_name": "D"})["business_name"], "Keith D")

    def test_a_tenant_with_nothing_at_all_yields_empty_rather_than_a_placeholder(self):
        self.assertEqual(email_identity({}), {"business_name": "", "reply_to": ""})

    def test_a_malformed_signup_address_is_not_used_as_a_reply_to(self):
        self.assertEqual(reply_to_address({"email": "not-an-email"}), "")


class MailerChokePointTests(unittest.TestCase):
    """Resolution lives at the ONE place every send already passes through, so the next emitter cannot
    forget it the way nine existing ones did."""

    def setUp(self):
        self.client = FakeClient()
        self.profiles = FakeProfiles({"business": {"name": BUSINESS}, "email": REPLY})

    def _send(self, **over):
        kwargs = dict(to="buyer@x.com", subject="s", html="<p>b</p>", signature=False,
                      user_profiles_repo=self.profiles, client=self.client)
        kwargs.update(over)
        mailer.send_email(**kwargs)
        return self.client.request

    def test_a_tenant_message_gets_the_tenant_identity_without_asking(self):
        request = self._send(tenant_id="t1")

        self.assertEqual(request["FromEmailAddress"], f"{BUSINESS} <support@juniorbay.net>")
        self.assertEqual(request["ReplyToAddresses"], [REPLY])

    def test_platform_mail_stays_the_platform(self):
        # A verification code must not appear to come from the shop the recipient happens to own.
        request = self._send()

        self.assertEqual(request["FromEmailAddress"], "support@juniorbay.net")
        self.assertNotIn("ReplyToAddresses", request)
        self.assertEqual(self.profiles.calls, [], "platform mail must not look up a tenant")

    def test_an_explicit_value_always_wins(self):
        request = self._send(tenant_id="t1", from_name="Explicit Co", reply_to="explicit@x.com")

        self.assertEqual(request["FromEmailAddress"], "Explicit Co <support@juniorbay.net>")
        self.assertEqual(request["ReplyToAddresses"], ["explicit@x.com"])

    def test_a_half_specified_send_is_still_completed(self):
        request = self._send(tenant_id="t1", from_name="Explicit Co")

        self.assertEqual(request["FromEmailAddress"], "Explicit Co <support@juniorbay.net>")
        self.assertEqual(request["ReplyToAddresses"], [REPLY])

    def test_an_unreadable_profile_costs_the_branding_not_the_message(self):
        self.profiles = FakeProfiles(raises=True)

        request = self._send(tenant_id="t1")

        self.assertEqual(request["FromEmailAddress"], "support@juniorbay.net")

    def test_a_name_with_a_comma_is_quoted_rather_than_read_as_two_addresses(self):
        self.profiles = FakeProfiles({"business": {"name": "Acme, Inc."}, "email": REPLY})

        request = self._send(tenant_id="t1")

        self.assertEqual(request["FromEmailAddress"], '"Acme, Inc." <support@juniorbay.net>')


class LayoutTests(unittest.TestCase):
    def test_the_business_is_named_in_the_message_not_only_the_envelope(self):
        html = render_email(business_name=BUSINESS, title="Hello", body=paragraph("Body"))

        self.assertIn(BUSINESS, html)

    def test_a_reply_to_produces_a_line_telling_the_reader_they_may_reply(self):
        # A Reply-To nobody is told about is a Reply-To nobody uses.
        self.assertIn("Just reply to this email", render_email(reply_to=REPLY, business_name=BUSINESS))
        self.assertNotIn("Just reply to this email", render_email(business_name=BUSINESS))

    def test_no_business_name_still_renders_rather_than_printing_an_empty_header(self):
        html = render_email(title="Hello", body=paragraph("Body"))

        self.assertIn("Hello", html)
        self.assertNotIn("<td style=\"padding:22px 28px 0", html)

    def test_tenant_copy_is_escaped(self):
        html = render_email(business_name='<script>alert(1)</script>', title='"><img>')

        self.assertNotIn("<script>", html)
        self.assertNotIn('"><img>', html)

    def test_a_button_without_a_url_renders_nothing(self):
        self.assertEqual(button("Pay", ""), "")
        self.assertIn("Pay", button("Pay", "https://x"))

    def test_a_totals_row_is_separated_from_the_lines(self):
        table = rows_table([("Item", "$1.00")], total=("Total", "$1.00"))

        self.assertEqual(table.count("border-top"), 2)   # one per total cell

    def test_an_empty_table_renders_nothing(self):
        self.assertEqual(rows_table([]), "")

    def test_the_preheader_is_hidden(self):
        html = render_email(preheader="Order #1 — $10.00", body="x")

        self.assertIn("Order #1", html)
        self.assertIn("display:none", html)


class EveryEmailUsesTheShellTests(unittest.TestCase):
    """The point of the exercise: two messages from one shop must look like one shop sent them."""

    ORDER = {"order_id": "ord_1", "currency": "usd", "amount_total": 49900,
             "customer": {"name": "Keith"}, "product": {"name": "Electric Scooter"}}

    def _all(self):
        return {
            "receipt": receipt_content(self.ORDER, business_name=BUSINESS, support_email=REPLY)["html"],
            "review": invite_email({"product_name": "Electric Scooter", "customer": {"name": "Keith"},
                                    "invite_id": "i1"}, base_url="https://x",
                                   organization={"name": BUSINESS}, reply_to=REPLY)["html"],
            "cart": recovery_email({"line_items": [{"name": "Scooter", "qty": 1, "unit_amount": 49900}],
                                    "item_count": 1, "currency": "usd", "total_amount": 49900},
                                   recovery_url="https://x/c", unsubscribe_url="https://x/u",
                                   organization={"name": BUSINESS}, reply_to=REPLY)["html"],
            "invoice": invoice_email_content({"line_items": [{"description": "C", "quantity": 1,
                                                              "unit_amount": 5000}], "currency": "usd"},
                                             "https://pay/x", business_name=BUSINESS,
                                             support_email=REPLY)["html"],
        }

    def test_one_font_one_width_one_shell(self):
        for label, html in self._all().items():
            with self.subTest(email=label):
                self.assertIn(FONT_STACK, html)
                self.assertIn(MAX_WIDTH, html)
                self.assertIn("border-radius:12px", html)

    def test_every_one_names_the_business_and_invites_a_reply(self):
        for label, html in self._all().items():
            with self.subTest(email=label):
                self.assertIn(BUSINESS, html)
                self.assertIn("Just reply to this email", html)

    def test_none_of_them_carries_its_own_font_stack_any_more(self):
        # The old divergence, asserted against so it cannot creep back: three different stacks across
        # four emails, none of them the same as another.
        for label, html in self._all().items():
            with self.subTest(email=label):
                self.assertNotIn("system-ui,Arial", html)
                self.assertNotIn("sans-serif;max-width:32rem", html)

    def test_the_receipt_names_the_shop_in_its_subject(self):
        self.assertEqual(
            receipt_content(self.ORDER, business_name=BUSINESS)["subject"],
            f"Your receipt from {BUSINESS}")

    def test_a_shop_with_no_name_still_gets_a_sensible_subject(self):
        self.assertEqual(receipt_content(self.ORDER)["subject"], "Your order receipt")

    def test_only_the_marketing_nudge_carries_an_unsubscribe(self):
        emails = self._all()
        self.assertIn("Unsubscribe", emails["cart"])
        for label in ("receipt", "review", "invoice"):
            with self.subTest(email=label):
                self.assertNotIn("Unsubscribe", emails[label])


if __name__ == "__main__":
    unittest.main()


class SenderIdentityGrantTests(unittest.TestCase):
    """Every function that can send TENANT mail must be able to read the owner's profile.

    This test exists because the failure is silent by design. `tenant_email_identity` swallows every
    exception — branding must never be the reason a receipt fails to send — so a missing IAM grant does
    not raise, it just quietly produces mail with no business name and no Reply-To. Which is the exact
    bug the whole template was written to fix.

    Found 2026-09-23: after the identity work, six of the seven mailing functions had no UserProfilesTable
    grant, and only the webhook would have branded anything.
    """

    import pathlib as _pathlib
    import re as _re

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")

    # Functions whose mail is PLATFORM-authored: they pass explicit from_name/reply_to and no tenant_id,
    # so they never look a tenant up and must not be granted a table they do not read.
    PLATFORM_SENDERS = {"SupportContactFunction", "UserProfileFunction"}

    def _function_blocks(self):
        pattern = (r"\n  ([A-Za-z0-9]+):\n    Type: AWS::Serverless::Function\n"
                   r"(.*?)(?=\n  [A-Za-z0-9]+:\n    Type:|\Z)")
        return self._re.findall(pattern, self.TEMPLATE, self._re.S)

    def _mailing_modules(self):
        handlers = self.ROOT / "src" / "handlers"
        modules = set()
        for path in handlers.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "send_email" in text or "stripe_link.delegation" in text:
                modules.add(path.stem)
        return modules

    def test_every_tenant_mailing_function_can_read_the_owner_profile(self):
        mailing = self._mailing_modules()
        missing = []
        for name, body in self._function_blocks():
            handler = self._re.search(r"Handler: handlers\.([A-Za-z0-9_]+)\.", body)
            if not handler or handler.group(1) not in mailing:
                continue
            if name in self.PLATFORM_SENDERS:
                continue
            if "UserProfilesTable" not in body:
                missing.append(f"{name} (handlers.{handler.group(1)}) sends tenant mail but cannot read "
                               "UserProfilesTable — its mail will silently have no sender identity")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_the_identity_lookup_really_is_silent_which_is_why_the_test_above_exists(self):
        class Exploding:
            def get(self, *_):
                raise RuntimeError("AccessDeniedException")

        self.assertEqual(mailer.tenant_email_identity("t1", Exploding()),
                         {"business_name": "", "reply_to": ""})
