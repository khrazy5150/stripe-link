"""Per-Site Reply-To: proving the mailbox one business's replies reach (plans/SITE_AS_BUSINESS_IDENTITY.md §P3).

P2 made the display name the Site's and left Reply-To the tenant's, deliberately: SES will mail from any
Reply-To it is handed, so the platform is the only thing that can refuse an address nobody has proven. This
phase proves them per Site, which is what the author chose over name-only.

Four properties, and each is one mistake away from a tenant receiving another business's customer replies:

1. **A code is valid for ONE Site.** It is salted with `tenant_id|site_id`, so a tenant who controls one
   address does not thereby verify every Site they own.
2. **`email_verified` is server-owned.** The Sites editor posts the whole `organization` back, so anything
   a client can send is something a client can assert. The write boundary discards it.
3. **Changing the address drops the proof.** The code proved "someone reads mail at THIS address", and
   that finding does not travel — the same rule sameAs verification has for re-pointed URLs.
4. **The fallback is the TENANT's verified address, never the Site's unverified one.** A half-set-up second
   Site must not send replies nowhere.
"""
import json
import unittest

from handlers.sites import confirm_site_email, create_site, start_site_email_verification
from tests.fakes import FakeSubdomainRegistry
from stripe_link.domain.business_email import (
    check_code,
    email_identity,
    hash_code,
    preserve_email_verification,
    start_verification,
    verification_scope,
)

ALLOW = lambda _email: {"allowed": True, "reason": "", "catch_all": False}  # noqa: E731
PROFILE = {"email": "owner@signup.test",
           "business": {"name": "Poliaxis Nutrition", "email": "hi@poliaxis.test", "email_verified": True}}


def site(site_id="site_qui", **org):
    return {"schema_version": "2026-07-20", "document_type": "site", "tenant_id": "t1",
            "site_id": site_id, "name": "Quill", "status": "active", "stripe_mode": "test",
            "hosting": {"type": "platform", "platform_hostname": "quill.jbay.uk"},
            "organization": {"name": "Quill", **org}}


class Repo:
    def __init__(self, *sites):
        self.docs = {(s["tenant_id"], s["site_id"]): dict(s) for s in sites}
        self.fail = False

    def get(self, tenant_id, site_id):
        doc = self.docs.get((tenant_id, site_id))
        return dict(doc) if doc else None

    def put(self, doc):
        if self.fail:
            raise RuntimeError("throttled")
        self.docs[(doc["tenant_id"], doc["site_id"])] = dict(doc)
        return dict(doc)


def event(body=None, tenant_id="t1"):
    return {"httpMethod": "POST", "queryStringParameters": {"tenant_id": tenant_id},
            "body": json.dumps(body or {})}


class ACodeIsValidForONESiteTests(unittest.TestCase):
    def test_the_scope_separates_two_sites_of_one_tenant(self):
        self.assertNotEqual(verification_scope("t1", "site_a"), verification_scope("t1", "site_b"))

    def test_a_bare_tenant_scope_is_UNCHANGED(self):
        """The tenant-level flow keeps working, stored hashes included — it is the fallback this phase
        depends on, and re-salting it would have silently unverified every tenant."""
        self.assertEqual(verification_scope("t1"), "t1")
        self.assertEqual(hash_code("123456", tenant_id="t1"),
                         __import__("hashlib").sha256(b"t1|123456").hexdigest())

    def test_a_code_for_one_site_does_NOT_confirm_another(self):
        pending = start_verification("hi@quill.test", tenant_id="t1", code="123456", now=0,
                                     site_id="site_qui")
        ok, _ = check_code(pending, "123456", tenant_id="t1", now=10, site_id="site_qui")
        self.assertTrue(ok)
        wrong, reason = check_code(pending, "123456", tenant_id="t1", now=10, site_id="site_pol")
        self.assertFalse(wrong)
        self.assertEqual(reason, "That code is not right.")

    def test_a_site_code_does_not_confirm_the_TENANT_address_either(self):
        pending = start_verification("hi@quill.test", tenant_id="t1", code="123456", now=0,
                                     site_id="site_qui")
        ok, _ = check_code(pending, "123456", tenant_id="t1", now=10)
        self.assertFalse(ok)


class TheRoundTripTests(unittest.TestCase):
    def _start(self, repo, email="hi@quill.test", code="123456"):
        sent = []
        response = start_site_email_verification(
            event({"email": email}), repo, "site_qui",
            mailer_send=lambda **kw: sent.append(kw) or {"MessageId": "m"},
            now_fn=lambda: 1000, code_fn=lambda: code, validator=ALLOW)
        return response, sent

    def test_the_code_goes_to_the_NEW_address_not_the_stored_one(self):
        """The whole point: it proves the tenant reads mail at the address they are asking us to publish
        as this business's reply address."""
        repo = Repo(site(email="old@quill.test", email_verified=True))
        response, sent = self._start(repo, email="new@quill.test")
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertEqual(sent[0]["to"], "new@quill.test")
        self.assertFalse(sent[0]["signature"], "platform->tenant mail carries no store sign-off")

    def test_the_stored_address_is_untouched_until_the_code_is_confirmed(self):
        """Pending is not verified. A tenant who types an address and never confirms it must not be able
        to send from it."""
        repo = Repo(site(email="old@quill.test", email_verified=True))
        self._start(repo, email="new@quill.test")
        org = repo.get("t1", "site_qui")["organization"]
        self.assertEqual(org["email"], "old@quill.test")
        self.assertEqual(org["email_verification"]["pending_email"], "new@quill.test")

    def test_confirming_promotes_the_address_and_clears_the_pending_record(self):
        repo = Repo(site())
        self._start(repo)
        response = confirm_site_email(event({"code": "123456"}), repo, "site_qui", now_fn=lambda: 1100)
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        org = repo.get("t1", "site_qui")["organization"]
        self.assertEqual(org["email"], "hi@quill.test")
        self.assertTrue(org["email_verified"])
        self.assertEqual(org["email_verified_at"], 1100)
        self.assertNotIn("email_verification", org)

    def test_a_wrong_code_COUNTS_THE_ATTEMPT(self):
        """Counted before returning, or the cap is advisory."""
        repo = Repo(site())
        self._start(repo)
        for n in (1, 2, 3):
            response = confirm_site_email(event({"code": "000000"}), repo, "site_qui",
                                          now_fn=lambda: 1100)
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(repo.get("t1", "site_qui")["organization"]["email_verification"]["attempts"], n)

    def test_the_attempt_cap_closes_the_door(self):
        repo = Repo(site())
        self._start(repo)
        for _ in range(5):
            confirm_site_email(event({"code": "000000"}), repo, "site_qui", now_fn=lambda: 1100)
        body = json.loads(confirm_site_email(event({"code": "123456"}), repo, "site_qui",
                                             now_fn=lambda: 1100)["body"])
        self.assertIn("Too many attempts", body["message"])

    def test_an_expired_code_is_refused_even_when_right(self):
        repo = Repo(site())
        self._start(repo)
        body = json.loads(confirm_site_email(event({"code": "123456"}), repo, "site_qui",
                                             now_fn=lambda: 1000 + 10_000)["body"])
        self.assertIn("expired", body["message"])

    def test_confirming_with_no_pending_record_says_what_to_do(self):
        repo = Repo(site())
        body = json.loads(confirm_site_email(event({"code": "123456"}), repo, "site_qui")["body"])
        self.assertIn("Request a new code", body["message"])

    def test_a_disposable_address_is_refused(self):
        """Refused by the local list BEFORE Debounce is called — no validator is passed here on purpose,
        so a test that reached the network would fail rather than quietly make one."""
        repo = Repo(site())
        response = start_site_email_verification(
            event({"email": "nobody@mailinator.com"}), repo, "site_qui",
            mailer_send=lambda **kw: None, code_fn=lambda: "123456")
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "disposable_email")

    def test_a_failed_send_is_REPORTED_not_swallowed(self):
        """A code the tenant never receives is a dead end, and they are sitting in front of the screen."""
        repo = Repo(site())

        def explode(**_kw):
            raise RuntimeError("ses down")

        response = start_site_email_verification(
            event({"email": "hi@quill.test"}), repo, "site_qui", mailer_send=explode,
            code_fn=lambda: "123456", validator=ALLOW)
        self.assertEqual(response["statusCode"], 502)

    def test_another_tenants_site_is_not_found(self):
        repo = Repo(site())
        response = start_site_email_verification(
            event({"email": "hi@quill.test"}, tenant_id="t2"), repo, "site_qui",
            mailer_send=lambda **kw: None, code_fn=lambda: "1", validator=ALLOW)
        self.assertEqual(response["statusCode"], 404)


class TheStateIsServerOwnedTests(unittest.TestCase):
    """The Sites editor posts the whole `organization` back, so anything a client can put in the payload is
    something a client can assert."""

    def test_a_client_CANNOT_assert_email_verified(self):
        self.assertEqual(
            preserve_email_verification({"email": "anyone@quill.test", "email_verified": True}, {}),
            {"email_verified": False, "email_verified_at": None, "email_verification": None})

    def test_an_unchanged_address_KEEPS_its_proof(self):
        stored = {"email": "hi@quill.test", "email_verified": True, "email_verified_at": 99}
        merged = preserve_email_verification({"email": "hi@quill.test"}, stored)
        self.assertTrue(merged["email_verified"])
        self.assertEqual(merged["email_verified_at"], 99)

    def test_RE_POINTING_the_address_drops_the_proof(self):
        """The code proved "someone reads mail at THIS address"; that finding does not travel. Same rule
        sameAs verification has for a re-pointed URL."""
        stored = {"email": "hi@quill.test", "email_verified": True, "email_verified_at": 99}
        merged = preserve_email_verification({"email": "new@quill.test"}, stored)
        self.assertFalse(merged["email_verified"])
        self.assertIsNone(merged["email_verified_at"])

    def test_re_pointing_also_drops_the_PENDING_code(self):
        """Or yesterday's unconfirmed code for one address could confirm a different one."""
        stored = {"email": "hi@quill.test", "email_verification": {"pending_email": "hi@quill.test"}}
        self.assertIsNone(preserve_email_verification({"email": "other@quill.test"}, stored)["email_verification"])

    def test_case_and_whitespace_do_not_count_as_a_change(self):
        stored = {"email": "hi@quill.test", "email_verified": True}
        self.assertTrue(preserve_email_verification({"email": "  HI@Quill.test "}, stored)["email_verified"])

    def test_CLEARING_the_address_drops_the_proof(self):
        stored = {"email": "hi@quill.test", "email_verified": True}
        self.assertFalse(preserve_email_verification({}, stored)["email_verified"])

    def test_the_SAVE_PATH_applies_it(self):
        """End to end through `create_site`, because the merge only protects anything if the write boundary
        actually calls it."""
        repo = Repo(site(email="hi@quill.test", email_verified=True, email_verified_at=99))
        forged = site(email="attacker@elsewhere.test", email_verified=True, email_verified_at=1)
        response = create_site({"httpMethod": "PUT", "queryStringParameters": {"tenant_id": "t1"},
                                "body": json.dumps(forged)}, repo, registry=FakeSubdomainRegistry(), mode="test")
        self.assertEqual(response["statusCode"], 201, response.get("body"))
        org = json.loads(response["body"])["site"]["organization"]
        self.assertEqual(org["email"], "attacker@elsewhere.test")   # the address is theirs to edit
        self.assertFalse(org["email_verified"])                      # the PROOF is not


class TheReplyToFallbackTests(unittest.TestCase):
    def test_a_verified_site_address_wins(self):
        identity = email_identity(PROFILE, {"name": "Quill", "email": "hi@quill.test",
                                            "email_verified": True})
        self.assertEqual(identity["reply_to"], "hi@quill.test")
        self.assertEqual(identity["business_name"], "Quill")

    def test_an_UNVERIFIED_site_address_is_ignored(self):
        """The hole the gate exists to close. Falling back is also what keeps a half-set-up second Site
        from sending replies nowhere."""
        identity = email_identity(PROFILE, {"name": "Quill", "email": "hi@quill.test"})
        self.assertEqual(identity["reply_to"], "hi@poliaxis.test")

    def test_a_site_with_no_address_falls_back(self):
        self.assertEqual(email_identity(PROFILE, {"name": "Quill"})["reply_to"], "hi@poliaxis.test")

    def test_neither_verified_means_NO_reply_to_rather_than_a_guess(self):
        identity = email_identity({"business": {"name": "P", "email": "unverified@p.test"}},
                                  {"name": "Quill", "email": "hi@quill.test"})
        self.assertEqual(identity["reply_to"], "")


if __name__ == "__main__":
    unittest.main()
