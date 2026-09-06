"""Verification of the tenant's business email — the reply-to on every tenant-authored send.

Junior Bay's SES account has production access, so it will mail anyone on a tenant's behalf. Nothing in AWS
checks whether that reply-to belongs to the tenant, which is why these rules exist at all.
"""

import unittest

from stripe_link.domain.business_email import (
    CODE_TTL_SECONDS, MAX_ATTEMPTS, check_code, is_disposable, looks_like_email,
    start_verification, verified_email,
)
from stripe_link.email_validation import check_email


class CodeTests(unittest.TestCase):
    def test_the_code_is_never_stored_in_the_clear(self):
        # A stored plaintext code is a credential in a database; reading it would be enough to take over a
        # tenant's sending identity.
        record = start_verification("a@b.co", tenant_id="t1", code="123456", now=1000)
        self.assertNotIn("123456", str(record))
        self.assertIn("code_hash", record)

    def test_it_expires_after_five_minutes(self):
        record = start_verification("a@b.co", tenant_id="t1", code="123456", now=1000)
        self.assertTrue(check_code(record, "123456", tenant_id="t1", now=1000 + CODE_TTL_SECONDS - 1)[0])
        self.assertFalse(check_code(record, "123456", tenant_id="t1", now=1000 + CODE_TTL_SECONDS)[0])

    def test_attempts_are_capped(self):
        # Six digits is a million possibilities; unlimited guesses is no protection at all.
        record = {**start_verification("a@b.co", tenant_id="t1", code="123456", now=1000),
                  "attempts": MAX_ATTEMPTS}
        ok, reason = check_code(record, "123456", tenant_id="t1", now=1000)
        self.assertFalse(ok)
        self.assertIn("Too many", reason)

    def test_a_code_is_bound_to_its_tenant(self):
        record = start_verification("a@b.co", tenant_id="t1", code="123456", now=1000)
        self.assertFalse(check_code(record, "123456", tenant_id="t2", now=1000)[0])

    def test_no_pending_record_is_not_an_accidental_pass(self):
        for pending in (None, {}, {"expires_at": 9999999999}):
            with self.subTest(pending=pending):
                self.assertFalse(check_code(pending, "123456", tenant_id="t1", now=1000)[0])


class GateTests(unittest.TestCase):
    def test_pending_is_not_verified(self):
        self.assertEqual(verified_email({"email": "a@b.co"}), "")
        self.assertEqual(verified_email({"email": "a@b.co", "email_verified": True}), "a@b.co")

    def test_a_verified_flag_with_no_address_is_not_a_sender(self):
        self.assertEqual(verified_email({"email": "", "email_verified": True}), "")


class ValidationTests(unittest.TestCase):
    def test_obvious_shapes_and_disposables(self):
        self.assertTrue(looks_like_email("a@b.co"))
        self.assertFalse(looks_like_email("not-an-email"))
        self.assertTrue(is_disposable("x@mailinator.com"))
        self.assertFalse(is_disposable("x@poliaxis.co"))

    def test_subdomains_of_a_listed_domain_are_caught(self):
        # Found in testing: MailSlurp hands out {uuid}@sandbox.zazamail.link, and Debounce rates that
        # domain "Safe to Send" while flagging mailslurp.com as Disposable. Listing the bare domain is no
        # use if the service only ever issues subdomains.
        self.assertTrue(is_disposable("8b73cb60@sandbox.zazamail.link"))
        self.assertTrue(is_disposable("x@sub.mailinator.com"))

    def test_a_real_domain_is_not_caught_by_the_subdomain_rule(self):
        # The suffix walk must not match on a shared TLD, or every .com address would be disposable.
        for good in ("owner@poliaxis.co", "keith@juniorbay.net", "hi@notmailinator.com"):
            with self.subTest(good=good):
                self.assertFalse(is_disposable(good))

    def test_debounce_fails_open_on_every_failure_mode(self):
        # A validator that blocks signup during its own outage is worse than no validator.
        def boom(_url, timeout=None):
            raise OSError("down")

        for opener, key in ((boom, "k"), (boom, "")):
            with self.subTest(key=bool(key)):
                result = check_email("a@b.co", api_key=key, opener=opener)
                self.assertTrue(result["allowed"])
                self.assertFalse(result["checked"], "an unanswered check must not look like a pass")

    def _debounce(self, body):
        class R:
            def read(self_inner):
                return body
        return check_email("a@b.co", api_key="k", opener=lambda *_a, **_k: R())

    def test_it_keys_on_the_result_string_not_the_numeric_code(self):
        # Verified against the live API 2026-09-06: code 5 returns "Safe to Send" for keith@juniorbay.net
        # and "Risky" for support@juniorbay.net. The SAME code, different results — so the code alone
        # cannot decide, and an earlier version of this keyed on codes and let mailinator straight through.
        safe = self._debounce(b'{"debounce":{"code":"5","result":"Safe to Send","reason":"Deliverable"}}')
        risky = self._debounce(b'{"debounce":{"code":"5","result":"Risky","reason":"Role"}}')
        self.assertTrue(safe["allowed"])
        self.assertTrue(risky["allowed"])

    def test_role_addresses_are_allowed(self):
        # support@, info@, hello@ are role addresses, which Debounce marks Risky — and a role address at
        # the company domain is exactly what a business email usually IS. Blocking Risky would refuse the
        # archetypal correct answer, including Google's and Stripe's own contact addresses.
        result = self._debounce(b'{"debounce":{"code":"4","result":"Risky","reason":"Accept All, Role"}}')
        self.assertTrue(result["allowed"])
        self.assertTrue(result["catch_all"], "reported, never blocking")

    def test_invalid_and_disposable_are_refused(self):
        disposable = self._debounce(b'{"debounce":{"code":"3","result":"Invalid","reason":"Disposable"}}')
        syntax = self._debounce(b'{"debounce":{"code":"1","result":"Invalid","reason":"Syntax"}}')
        self.assertFalse(disposable["allowed"])
        self.assertIn("disposable", disposable["reason"].lower())
        self.assertFalse(syntax["allowed"])


if __name__ == "__main__":
    unittest.main()
