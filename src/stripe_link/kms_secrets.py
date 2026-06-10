import base64
import os
from functools import cached_property
from typing import Any


ENCRYPTED_SECRET_PREFIX = "kms:v1:"
LEGACY_SECRET_PREFIX = "kms://"


def is_encrypted_secret_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.startswith(ENCRYPTED_SECRET_PREFIX) or value.startswith(LEGACY_SECRET_PREFIX)


class KmsSecretCipher:
    def __init__(self, key_id: str | None = None, client: Any | None = None):
        self.key_id = key_id or os.environ.get("STRIPE_KEYS_KMS_KEY_ID", "")
        self._client = client

    @cached_property
    def client(self):
        if self._client is not None:
            return self._client
        import boto3

        self._client = boto3.client("kms")
        return self._client

    def encrypt(self, plaintext: str, *, tenant_id: str, mode: str, field: str) -> str:
        if not plaintext:
            return ""
        if is_encrypted_secret_ref(plaintext):
            return plaintext
        if not self.key_id:
            raise ValueError("STRIPE_KEYS_KMS_KEY_ID is required to store Stripe secrets.")
        response = self.client.encrypt(
            KeyId=self.key_id,
            Plaintext=plaintext.encode("utf-8"),
            EncryptionContext=self._context(tenant_id, mode, field),
        )
        ciphertext = base64.b64encode(response["CiphertextBlob"]).decode("ascii")
        return f"{ENCRYPTED_SECRET_PREFIX}{ciphertext}"

    def decrypt(self, secret_ref: str, *, tenant_id: str, mode: str, field: str) -> str:
        if not secret_ref:
            return ""
        if secret_ref.startswith(LEGACY_SECRET_PREFIX):
            raise ValueError("Legacy KMS secret references cannot be decrypted by this runtime.")
        if not secret_ref.startswith(ENCRYPTED_SECRET_PREFIX):
            return secret_ref
        ciphertext = base64.b64decode(secret_ref[len(ENCRYPTED_SECRET_PREFIX):])
        response = self.client.decrypt(
            CiphertextBlob=ciphertext,
            EncryptionContext=self._context(tenant_id, mode, field),
        )
        return response["Plaintext"].decode("utf-8")

    @staticmethod
    def _context(tenant_id: str, mode: str, field: str) -> dict[str, str]:
        return {
            "tenant_id": tenant_id,
            "mode": mode,
            "field": field,
            "service": "stripe-link",
        }
