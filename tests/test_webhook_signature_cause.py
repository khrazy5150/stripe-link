"""A refused webhook says WHICH thing was wrong, because the two fixes are unrelated.

The rejection log used to read `"secret mismatch or stale timestamp"` — one guessed message covering two
problems. Measured 2026-10-12: 16 distinct test-mode events a day were being dropped in both silos, and
the only way to guess at the cause was to count retries by hand.

The distinction that matters, and the reason the HMAC is now computed even for a stale delivery:

* **stale + signature matched** — the stored secret is CORRECT. Nobody should go looking in Secrets
  Manager. It is a late or retried delivery, and the tolerance refused it.
* **stale + signature did not match** — the secret is wrong as well.
* **fresh + no match** — the secret is wrong, and that is the one a Secrets Manager update fixes.
"""
import hashlib
import hmac
import json
import unittest

from handlers.stripe_webhook import (SIGNATURE_TOLERANCE_SECONDS, _signature_check, _signature_detail,
                                     _signature_is_valid)

NOW = 1_800_000_000
SECRET = "whsec_the_right_one"
BODY = json.dumps({"id": "evt_1", "type": "invoice.paid", "livemode": False})


def header(secret=SECRET, age=0, body=BODY):
    ts = NOW - age
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def check(signature_header, secret=SECRET, body=BODY):
    return _signature_check(body=body, signature_header=signature_header, secret=secret,
                            now_fn=lambda: NOW)


class ItNamesTheCause(unittest.TestCase):
    def test_a_good_signature_passes(self):
        self.assertTrue(check(header())["ok"])

    def test_a_fresh_delivery_we_cannot_verify_is_a_secret_mismatch(self):
        got = check(header(secret="whsec_wrong"))
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "secret_mismatch")
        self.assertIn("secret does not match", _signature_detail(got))
        self.assertIn("fresh", _signature_detail(got))

    def test_a_stale_delivery_with_the_RIGHT_secret_says_the_secret_is_correct(self):
        """The counter-intuitive one, and the whole reason the HMAC is computed when stale. Reporting
        this as "secret mismatch or stale timestamp" sends someone to rotate a secret that is fine."""
        got = check(header(age=SIGNATURE_TOLERANCE_SECONDS + 1000))
        self.assertFalse(got["ok"], "still refused -- the tolerance is replay protection")
        self.assertEqual(got["reason"], "stale_timestamp")
        self.assertTrue(got["signature_matched"])
        self.assertIn("SECRET IS CORRECT", _signature_detail(got))
        self.assertIn("not a configuration problem", _signature_detail(got))

    def test_a_stale_delivery_with_the_wrong_secret_says_both(self):
        got = check(header(secret="whsec_wrong", age=SIGNATURE_TOLERANCE_SECONDS + 1000))
        self.assertEqual(got["reason"], "stale_timestamp")
        self.assertFalse(got["signature_matched"])
        detail = _signature_detail(got)
        self.assertIn("does not match", detail)
        self.assertIn("old", detail)
        self.assertNotIn("SECRET IS CORRECT", detail)

    def test_a_malformed_header_is_its_own_cause(self):
        self.assertEqual(check("nonsense")["reason"], "malformed_signature_header")
        self.assertEqual(check("")["reason"], "malformed_signature_header")

    def test_the_age_is_reported_so_the_margin_is_visible(self):
        got = check(header(age=4000))
        self.assertEqual(got["age_seconds"], 4000)
        self.assertIn("4000s", _signature_detail(got))


class AStaleSignatureIsStillRefused(unittest.TestCase):
    """Knowing why we refused is not a reason to stop refusing. The tolerance is replay protection."""

    def test_even_when_the_signature_itself_is_valid(self):
        self.assertFalse(check(header(age=SIGNATURE_TOLERANCE_SECONDS + 1))["ok"])

    def test_just_inside_the_tolerance_still_passes(self):
        self.assertTrue(check(header(age=SIGNATURE_TOLERANCE_SECONDS - 1))["ok"])

    def test_a_future_timestamp_is_refused_too(self):
        """Clock skew cuts both ways, and `abs()` is what makes a forged future timestamp fail."""
        self.assertFalse(check(header(age=-(SIGNATURE_TOLERANCE_SECONDS + 1)))["ok"])

    def test_a_tampered_body_never_verifies(self):
        self.assertFalse(check(header(), body=BODY.replace("invoice.paid", "invoice.voided"))["ok"])


class TheBoolFormStillWorksForItsOneCaller(unittest.TestCase):
    """`platform_billing_webhook` has no use for the reason and still asks a yes/no question."""

    def test_it_agrees_with_the_detailed_check(self):
        for hdr in (header(), header(secret="whsec_wrong"), header(age=9999), "nonsense"):
            self.assertEqual(
                _signature_is_valid(body=BODY, signature_header=hdr, secret=SECRET, now_fn=lambda: NOW),
                check(hdr)["ok"])

    def test_the_platform_billing_webhook_still_imports_it(self):
        from handlers.platform_billing_webhook import _signature_is_valid as imported
        self.assertIs(imported, _signature_is_valid)


class SecretsManagerIsNotReReadForAStaleDelivery(unittest.TestCase):
    """Re-reading cannot help a delivery that is simply too old, and doing it on every retry turns a pool
    of doomed retries into a pool of doomed retries plus a GetSecretValue each."""

    def test_the_refresh_is_gated_on_the_signature_not_matching(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "src" / "handlers" / "stripe_webhook.py").read_text()
        self.assertIn('if signature_header and not check["signature_matched"] else None', src)


if __name__ == "__main__":
    unittest.main()
