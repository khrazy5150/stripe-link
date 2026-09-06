"""The Junior Bay sign-off on mail a tenant sends to their customers.

Free tenants carry it; premium (tier `pro`) has paid it away. The decision lives in the mailer -- the one
place every send already passes through -- because a sign-off that eight callers have to remember is a
sign-off that the ninth feature ships without.
"""

import os
import unittest
from unittest.mock import patch

from stripe_link.domain.platform_signature import (
    SIGNATURE_CTA,
    shows_platform_signature,
    signature_html,
    signature_text,
)
from stripe_link.mailer import send_email


class FakeProfiles:
    def __init__(self, tier="basic", fail=False):
        self.tier, self.fail = tier, fail

    def get(self, *_args):
        if self.fail:
            raise RuntimeError("dynamo down")
        return {"tier_id": self.tier}


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m1"}


def send(**overrides):
    ses = FakeSes()
    kwargs = {"to": "a@b.co", "subject": "S", "html": "<p>Hi</p>", "text": "Hi", "client": ses}
    kwargs.update(overrides)
    with patch.dict(os.environ, {"EMAIL_FROM_ADDRESS": "support@juniorbay.net"}, clear=False):
        send_email(**kwargs)
    body = ses.sent[0]["Content"]["Simple"]["Body"]
    return body.get("Html", {}).get("Data", ""), body.get("Text", {}).get("Data", "")


class TierTests(unittest.TestCase):
    def test_the_free_tiers_carry_it(self):
        for tier in ("basic", "standard", "starter", "", None):
            with self.subTest(tier=tier):
                self.assertTrue(shows_platform_signature({"tier_id": tier}))

    def test_premium_has_paid_it_away(self):
        self.assertFalse(shows_platform_signature({"tier_id": "pro"}))

    def test_a_missing_profile_is_treated_as_free(self):
        # Failing toward SHOWING: an unreadable profile must not hand a free tenant the premium perk.
        for profile in ({}, None, "nonsense"):
            with self.subTest(profile=profile):
                self.assertTrue(shows_platform_signature(profile))


class MailerTests(unittest.TestCase):
    def test_a_free_tenants_mail_carries_it_in_both_bodies(self):
        html, text = send(tenant_id="t1", profiles_repo=FakeProfiles("basic"))
        self.assertIn(SIGNATURE_CTA, html)
        self.assertIn(SIGNATURE_CTA, text)
        self.assertTrue(html.startswith("<p>Hi</p>"), "the signature appends, it does not replace")

    def test_premium_mail_is_clean(self):
        html, text = send(tenant_id="t1", profiles_repo=FakeProfiles("pro"))
        self.assertNotIn(SIGNATURE_CTA, html)
        self.assertNotIn(SIGNATURE_CTA, text)

    def test_a_lookup_failure_still_sends(self):
        # A footer must never be the reason a customer does not get their receipt.
        html, _ = send(tenant_id="t1", profiles_repo=FakeProfiles(fail=True))
        self.assertIn(SIGNATURE_CTA, html, "unreadable tier falls back to the free behaviour")

    def test_an_explicit_opt_out_beats_the_tier(self):
        # Platform -> tenant mail: they already have the store the sign-off advertises.
        html, _ = send(tenant_id="t1", profiles_repo=FakeProfiles("basic"), signature=False)
        self.assertNotIn(SIGNATURE_CTA, html)

    def test_no_tenant_means_no_signature_and_no_lookup(self):
        html, _ = send()
        self.assertNotIn(SIGNATURE_CTA, html)


class ContentTests(unittest.TestCase):
    def test_the_copy_survives_blocked_images(self):
        """Most clients block remote images by default, so the LINE has to carry the message -- a logo
        with alt text would render as a broken-image label, which advertises nothing."""
        html = signature_html()
        self.assertIn("Want to start your own online store?", html)
        self.assertIn('alt=""', html)

    def test_the_logo_is_absolute_and_the_link_is_measurable(self):
        html = signature_html()
        self.assertIn("https://images.juniorbay.com/", html, "email cannot resolve a relative image")
        self.assertIn("utm_source=tenant_email", html)
        self.assertNotIn("&utm", html, "a bare & in an href is invalid HTML; it must be &amp;")
        self.assertIn("&amp;utm", html)

    def test_the_text_part_is_plain(self):
        self.assertNotIn("<", signature_text())


class CallSiteTests(unittest.TestCase):
    """Every sender must opt in with a tenant_id, or that tenant's mail silently loses the sign-off."""

    SENDERS = {
        "src/handlers/downloads.py": "tenant_id=tenant_id",
        "src/handlers/cart_recovery.py": "tenant_id=tenant_id",
        "src/handlers/invoices.py": "tenant_id=tenant_id",
        "src/handlers/review_invites.py": "tenant_id=tenant_id",
        "src/handlers/stripe_webhook.py": "tenant_id=tenant_id",
        "src/stripe_link/delegation.py": "tenant_id=tenant_id",
        # Junior Bay's OWN mail to a tenant, deliberately opted out rather than forgotten.
        "src/handlers/profile.py": "signature=False",
    }

    def test_every_sender_states_its_intent(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        for path, expected in self.SENDERS.items():
            with self.subTest(sender=path):
                self.assertIn(expected, (root / path).read_text(),
                              f"{path} sends mail without saying whether it carries the sign-off")


class GrantTests(unittest.TestCase):
    """The tier lookup happens inside the mailer, so it is INVISIBLE in a sender's own source -- no test
    that reads the handler can see it. Every function that mails with a tenant_id needs the grant, and the
    only way to notice a missing one used to be a 502 in production."""

    # Functions whose handler calls send_email with a tenant_id.
    SENDING_FUNCTIONS = [
        "LeadDownloadFunction", "CartRecoveryFunction", "ReviewInvitesFunction",
        "InvoicesFunction", "StripeWebhookFunction", "BookingFunction", "ServicesFunction",
    ]

    def test_every_sending_function_can_read_the_tier(self):
        import pathlib
        import re

        tmpl = (pathlib.Path(__file__).resolve().parents[1] / "template.yaml").read_text()
        blocks = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", tmpl, re.M))
        for name in self.SENDING_FUNCTIONS:
            with self.subTest(function=name):
                self.assertIn(name, blocks, "function missing from template.yaml")
                self.assertIn("TenantProfilesTable", blocks[name],
                              f"{name} mails with a tenant_id but cannot read the tenant's tier")


if __name__ == "__main__":
    unittest.main()
