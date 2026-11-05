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
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

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


class TheAddressIsVETTEDBeforeAnyCodeGoesOutTests(unittest.TestCase):
    """Ported from the retired `test_business_email_endpoints.py` when the tenant-level endpoint was
    deleted (§P4). These four properties belong to the RULES about codes, which both endpoints always
    shared -- they were only ever asserted through the tenant one, so retiring that file without moving
    them would have dropped the coverage silently.
    """

    def test_the_code_is_stored_HASHED_not_in_the_clear(self):
        """The security property. A pending record sits in a document the dashboard reads back, and a
        plaintext code there is a code anybody with read access can use."""
        repo = Repo(site())
        start_site_email_verification(
            event({"email": "hi@quill.test"}), repo, "site_qui",
            mailer_send=lambda **kw: {"MessageId": "m"}, now_fn=lambda: 1000,
            code_fn=lambda: "123456", validator=ALLOW)
        self.assertNotIn("123456", json.dumps(repo.get("t1", "site_qui"), default=str))

    def test_obvious_rubbish_never_reaches_the_VALIDATOR(self):
        """Shape and disposable are decided locally. Sending them to Debounce spends a paid lookup to
        learn what the string itself already said."""
        for email in ("not-an-email", "x@mailinator.com"):
            with self.subTest(email=email):
                def boom(_email):
                    raise AssertionError("the validator should not have been called")

                response = start_site_email_verification(
                    event({"email": email}), Repo(site()), "site_qui",
                    mailer_send=lambda **kw: None, code_fn=lambda: "123456", validator=boom)
                self.assertEqual(response["statusCode"], 400)

    def test_an_address_the_validator_REJECTS_gets_no_code(self):
        """Debounce fails open on an outage but is obeyed on a verdict: a mailbox it says does not exist
        would cost SES 14 hours of retries and return a bounce."""
        sent = []
        response = start_site_email_verification(
            event({"email": "ghost@quill.test"}), Repo(site()), "site_qui",
            mailer_send=lambda **kw: sent.append(kw), code_fn=lambda: "123456",
            validator=lambda _e: {"allowed": False, "reason": "No such mailbox.", "catch_all": False})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "rejected_email")
        self.assertEqual(sent, [], "a rejected address must not be mailed")

    def test_a_CATCH_ALL_domain_is_reported_and_still_gets_its_code(self):
        """A catch-all accepts everything, so Debounce cannot tell whether the mailbox is real -- which is
        exactly what the code then settles. Blocking here would lock out every tenant on a catch-all
        domain; reporting it lets the dashboard say why the answer was soft."""
        sent = []
        response = start_site_email_verification(
            event({"email": "info@quill.test"}), Repo(site()), "site_qui",
            mailer_send=lambda **kw: sent.append(kw) or {"MessageId": "m"},
            code_fn=lambda: "111111",
            validator=lambda _e: {"allowed": True, "reason": "", "catch_all": True})
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertTrue(json.loads(response["body"])["catch_all"])
        self.assertEqual(len(sent), 1)


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
    """Two sources since §P4 deleted the account-level business email: the Site's VERIFIED address, then
    the SIGNUP address. `PROFILE` still carries a verified `business.email` on purpose -- it is what a
    pre-P4 tenant's stored document looks like, and these assert that it is no longer consulted."""

    def test_a_verified_site_address_wins(self):
        identity = email_identity(PROFILE, {"name": "Quill", "email": "hi@quill.test",
                                            "email_verified": True})
        self.assertEqual(identity["reply_to"], "hi@quill.test")
        self.assertEqual(identity["business_name"], "Quill")

    def test_an_UNVERIFIED_site_address_is_ignored(self):
        """The hole the gate exists to close: SES mails from any Reply-To it is handed, so an address
        nobody proved must not become one."""
        identity = email_identity(PROFILE, {"name": "Quill", "email": "hi@quill.test"})
        self.assertEqual(identity["reply_to"], "owner@signup.test")

    def test_a_site_with_no_address_falls_back_to_the_SIGNUP_address(self):
        """Not nowhere. A customer answering a receipt has to reach the merchant, and the Cognito account
        address is proof of reachability obtained by a stronger flow than the code."""
        self.assertEqual(email_identity(PROFILE, {"name": "Quill"})["reply_to"], "owner@signup.test")

    def test_the_tenants_OWN_business_email_is_NEVER_consulted(self):
        """§P4, stated as a test rather than left as an absence. The stored block still holds a verified
        address for every tenant who ever ran the retired flow; reading it would re-create the bug the
        phase exists to remove -- one business's address on another business's mail."""
        identity = email_identity(
            {"email": "owner@signup.test",
             "business": {"name": "Poliaxis Nutrition", "email": "hi@poliaxis.test",
                          "email_verified": True}},
            {"name": "Quill"})
        self.assertEqual(identity["reply_to"], "owner@signup.test")
        self.assertNotEqual(identity["reply_to"], "hi@poliaxis.test")

    def test_no_signup_address_means_NO_reply_to_rather_than_a_guess(self):
        """A message with no Reply-To is worse than one the platform invents a Reply-To for -- but only
        just, and inventing one sends a customer to a mailbox that cannot help them."""
        identity = email_identity({"business": {"name": "P", "email": "unverified@p.test"}},
                                  {"name": "Quill", "email": "hi@quill.test"})
        self.assertEqual(identity["reply_to"], "")


class TheBUILDERGateReadsTheSiteTooTests(unittest.TestCase):
    """The same gate, one layer up, and it had the same bug.

    `LandingPages.vue` disables the "Sends an email with the file" ribbon action when the business cannot
    send, so the tenant learns BEFORE uploading a file and writing copy for a button that would refuse.
    It read `profile.business.email_verified` — the field §P4 deleted — and told the tenant to *"go to
    your Profile page to enter a business email"*, a screen that no longer offers one. Left alone it would
    have disabled the action for every tenant forever while pointing at the one place that cannot fix it.
    """

    BUILDER = (ROOT / "dashboard/src/components/LandingPages.vue").read_text(encoding="utf-8")

    def test_it_no_longer_reads_the_deleted_PROFILE_field(self):
        self.assertNotIn("profile?.business?.email_verified", self.BUILDER)

    def test_it_reads_the_SELECTED_SITES_organization(self):
        block = self.BUILDER.split("const businessEmailVerified", 1)[1].split("\n});", 1)[0]
        self.assertIn("selectedSite.value?.organization", block)
        self.assertIn("email_verified", block)

    def test_an_UNKNOWN_site_is_PERMITTED_not_accused(self):
        """Before a Site is chosen, and while the list is still loading, there is nothing to judge. A
        notice has to be actionable, and the send-time gate decides properly either way."""
        block = self.BUILDER.split("const businessEmailVerified", 1)[1].split("\n});", 1)[0]
        self.assertIn("if (!org) return true;", block)

    def test_the_hint_names_the_screen_that_can_FIX_it(self):
        self.assertNotIn("Go to your Profile page to enter a business email", self.BUILDER)
        self.assertIn("Sites \u2192 Edit \u2192 Business", self.BUILDER)


if __name__ == "__main__":
    unittest.main()
