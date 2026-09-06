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

    def test_debounce_fails_open_on_every_failure_mode(self):
        # A validator that blocks signup during its own outage is worse than no validator.
        def boom(_url, timeout=None):
            raise OSError("down")

        for opener, key in ((boom, "k"), (boom, "")):
            with self.subTest(key=bool(key)):
                result = check_email("a@b.co", api_key=key, opener=opener)
                self.assertTrue(result["allowed"])
                self.assertFalse(result["checked"], "an unanswered check must not look like a pass")

    def test_catch_all_is_reported_not_blocked(self):
        class R:
            def read(self):
                return b'{"debounce":{"code":"4"}}'

        result = check_email("a@b.co", api_key="k", opener=lambda *_a, **_k: R())
        self.assertTrue(result["allowed"], "catch-all domains belong to real businesses")
        self.assertTrue(result["catch_all"])


if __name__ == "__main__":
    unittest.main()
