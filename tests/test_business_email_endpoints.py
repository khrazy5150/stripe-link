"""The two verification steps: send a code to the NEW address, then confirm it.

The code goes to the address being claimed, which is the whole point — it proves the tenant controls the
mailbox they are asking us to put in every Reply-To.
"""

import json
import unittest

from handlers.profile import confirm_business_email, start_business_email_verification


class FakeRepo:
    def __init__(self, profile):
        self.profile, self.puts = profile, []

    def get(self, *_a):
        return self.profile

    def put(self, doc):
        self.puts.append(doc)
        self.profile = doc
        return doc


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, **kw):
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kw)


def event(body):
    # tenant_id travels in the BODY on a POST — tenant_id_from_event checks body, then query, then headers.
    return {"httpMethod": "POST", "body": json.dumps({"tenant_id": "t1", **body})}


def profile():
    return {"tenant_id": "t1", "user_id": "u1", "business": {"name": "Poliaxis"}}


ALLOW = lambda _e: {"allowed": True, "reason": "", "catch_all": False, "checked": True}
CATCH_ALL = lambda _e: {"allowed": True, "reason": "", "catch_all": True, "checked": True}
REJECT = lambda _e: {"allowed": False, "reason": "That address does not look valid.",
                     "catch_all": False, "checked": True}


class StartTests(unittest.TestCase):
    def test_it_emails_the_code_to_the_new_address(self):
        repo, mailer = FakeRepo(profile()), FakeMailer()
        res = start_business_email_verification(
            event({"user_id": "u1", "email": "owner@poliaxis.co"}), repo,
            mailer_send=mailer, now_fn=lambda: 1000, code_fn=lambda: 123456, validator=ALLOW)
        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(mailer.sent[0]["to"], "owner@poliaxis.co")
        self.assertIn("123456", mailer.sent[0]["text"])

    def test_the_code_is_stored_hashed_not_in_the_clear(self):
        repo = FakeRepo(profile())
        start_business_email_verification(
            event({"user_id": "u1", "email": "owner@poliaxis.co"}), repo,
            mailer_send=FakeMailer(), now_fn=lambda: 1000, code_fn=lambda: 123456, validator=ALLOW)
        self.assertNotIn("123456", json.dumps(repo.puts[0]))

    def test_the_address_is_not_usable_until_confirmed(self):
        repo = FakeRepo(profile())
        start_business_email_verification(
            event({"user_id": "u1", "email": "owner@poliaxis.co"}), repo,
            mailer_send=FakeMailer(), now_fn=lambda: 1000, code_fn=lambda: 123456, validator=ALLOW)
        business = repo.puts[0]["business"]
        self.assertNotIn("email_verified", business)
        self.assertNotEqual(business.get("email"), "owner@poliaxis.co", "pending is not the live value")

    def test_obvious_rubbish_never_reaches_the_validator(self):
        for email in ("not-an-email", "x@mailinator.com"):
            with self.subTest(email=email):
                def boom(_e):
                    raise AssertionError("validator should not have been called")
                res = start_business_email_verification(
                    event({"user_id": "u1", "email": email}), FakeRepo(profile()),
                    mailer_send=FakeMailer(), validator=boom)
                self.assertEqual(res["statusCode"], 400)

    def test_a_rejected_address_is_refused(self):
        res = start_business_email_verification(
            event({"user_id": "u1", "email": "ghost@poliaxis.co"}), FakeRepo(profile()),
            mailer_send=FakeMailer(), validator=REJECT)
        self.assertEqual(res["statusCode"], 400)

    def test_catch_all_is_reported_and_still_proceeds(self):
        mailer = FakeMailer()
        res = start_business_email_verification(
            event({"user_id": "u1", "email": "info@poliaxis.co"}), FakeRepo(profile()),
            mailer_send=mailer, code_fn=lambda: 111111, validator=CATCH_ALL)
        self.assertEqual(res["statusCode"], 200)
        self.assertTrue(json.loads(res["body"])["catch_all"])
        self.assertEqual(len(mailer.sent), 1, "a catch-all domain still gets its code")

    def test_a_failed_send_is_reported(self):
        res = start_business_email_verification(
            event({"user_id": "u1", "email": "owner@poliaxis.co"}), FakeRepo(profile()),
            mailer_send=FakeMailer(fail=True), code_fn=lambda: 111111, validator=ALLOW)
        self.assertEqual(res["statusCode"], 502)


class ConfirmTests(unittest.TestCase):
    def _started(self, now=1000):
        repo = FakeRepo(profile())
        start_business_email_verification(
            event({"user_id": "u1", "email": "owner@poliaxis.co"}), repo,
            mailer_send=FakeMailer(), now_fn=lambda: now, code_fn=lambda: 123456, validator=ALLOW)
        return repo

    def test_the_right_code_verifies_the_address(self):
        repo = self._started()
        res = confirm_business_email(event({"user_id": "u1", "code": "123456"}), repo, now_fn=lambda: 1010)
        self.assertEqual(res["statusCode"], 200)
        business = repo.profile["business"]
        self.assertEqual(business["email"], "owner@poliaxis.co")
        self.assertTrue(business["email_verified"])
        self.assertNotIn("email_verification", business, "the pending record is consumed")

    def test_a_wrong_code_counts_against_the_cap(self):
        # Counting only on success would make the cap advisory.
        repo = self._started()
        confirm_business_email(event({"user_id": "u1", "code": "000000"}), repo, now_fn=lambda: 1010)
        self.assertEqual(repo.profile["business"]["email_verification"]["attempts"], 1)

    def test_an_expired_code_is_refused(self):
        repo = self._started()
        res = confirm_business_email(event({"user_id": "u1", "code": "123456"}), repo, now_fn=lambda: 1000 + 301)
        self.assertEqual(res["statusCode"], 400)
        self.assertNotIn("email_verified", repo.profile["business"])


if __name__ == "__main__":
    unittest.main()
