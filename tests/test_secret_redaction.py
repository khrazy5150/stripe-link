import unittest

from handlers.stripe_keys import prepare_stripe_keys_document
from stripe_link.security import (
    REDACTED,
    SENSITIVE_FIELDS,
    redact_sensitive_fields,
    restore_redacted_fields,
)


class FakeCipher:
    def encrypt(self, value, **_kwargs):
        return f"kms:v1:ENC({value})"


STORED = {
    "tenant_id": "tenant-1",
    "mode": "live",
    "connect_access_token_ref": "kms:v1:REAL_ACCESS",
    "connect_refresh_token_ref": "kms:v1:REAL_REFRESH",
    "secret_key_ref": "kms:v1:REAL_SECRET",
    "webhook_secret_ref": "kms:v1:REAL_WEBHOOK",
    "publishable_key": "pk_live_abc123",
    "connect_account_id": "acct_123",
}


class SecretRedactionTests(unittest.TestCase):
    def test_every_credential_ref_is_in_the_denylist(self):
        # SENSITIVE_FIELDS started as the BYO-key fields only. When Connect OAuth landed, its two
        # token refs were not added, so they shipped to the browser in full ciphertext. Pin the whole
        # set: adding a *_ref that holds a credential must mean adding it here too.
        self.assertEqual(
            SENSITIVE_FIELDS,
            {
                "secret_key",
                "secret_key_ref",
                "webhook_secret",
                "webhook_secret_ref",
                "connect_access_token_ref",
                "connect_refresh_token_ref",
            },
        )

    def test_connect_token_refs_never_reach_a_response(self):
        out = redact_sensitive_fields(STORED)
        self.assertEqual(out["connect_access_token_ref"], REDACTED)
        self.assertEqual(out["connect_refresh_token_ref"], REDACTED)
        self.assertEqual(out["secret_key_ref"], REDACTED)
        self.assertEqual(out["webhook_secret_ref"], REDACTED)
        self.assertNotIn("kms:v1:", str(out))

    def test_public_fields_are_left_alone(self):
        # A publishable key is meant to be public -- it ships in every checkout page's client JS.
        out = redact_sensitive_fields(STORED)
        self.assertEqual(out["publishable_key"], "pk_live_abc123")
        self.assertEqual(out["connect_account_id"], "acct_123")

    def test_a_redacted_round_trip_cannot_destroy_a_credential(self):
        # Redaction is only safe if the mask can never be written back: a client that GETs a document
        # and POSTs it unchanged must not persist "********" over the stored ciphertext.
        echoed = redact_sensitive_fields(STORED)
        saved = prepare_stripe_keys_document(echoed, STORED, FakeCipher())
        self.assertEqual(saved["connect_access_token_ref"], "kms:v1:REAL_ACCESS")
        self.assertEqual(saved["connect_refresh_token_ref"], "kms:v1:REAL_REFRESH")
        self.assertEqual(saved["secret_key_ref"], "kms:v1:REAL_SECRET")
        self.assertNotIn(REDACTED, saved.values())

    def test_mask_with_nothing_stored_is_dropped_not_persisted(self):
        saved = prepare_stripe_keys_document(
            {"tenant_id": "t2", "mode": "test", "connect_access_token_ref": REDACTED}, None, FakeCipher()
        )
        self.assertNotIn("connect_access_token_ref", saved)

    def test_a_genuinely_new_secret_still_gets_stored(self):
        cleaned = restore_redacted_fields({"secret_key_ref": "sk_test_new"}, STORED)
        self.assertEqual(cleaned["secret_key_ref"], "sk_test_new")
        saved = prepare_stripe_keys_document(
            {"tenant_id": "tenant-1", "mode": "live", "secret_key_ref": "sk_test_new"}, STORED, FakeCipher()
        )
        self.assertEqual(saved["secret_key_ref"], "kms:v1:ENC(sk_test_new)")


if __name__ == "__main__":
    unittest.main()
