"""Transactional SMS via AWS End User Messaging (``pinpoint-sms-voice-v2``).

Sends from a single platform-owned 10DLC origination identity (a phone-pool ARN or an
E.164 number). The identity is resolved at RUNTIME from a per-environment Secrets Manager
secret (``SMS_ORIGINATION_SECRET_NAME`` → ``jb/sms-origination/{env}``), so the approved
number can be set or rotated with ``deploy/sms-origination-secrets.sh`` without an app
redeploy. Mirrors ``mailer.py``: one thin adapter with injectable clients for tests.

US A2P 10DLC brand + campaign registration is a prerequisite for live delivery. The code is
fully exercised against fakes until the number is provisioned; STOP/HELP keyword handling
and the carrier opt-out list are managed by End User Messaging itself.
"""

import json
import os
from typing import Any


class SmsError(RuntimeError):
    pass


# Cached per-secret payload. Only successful, configured loads are cached, so an unset
# number is re-checked each sweep and picked up promptly once the secret is populated.
_ORIGINATION_CACHE: dict[str, dict[str, Any]] = {}


def _region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


def _sms_client():
    import boto3

    return boto3.client("pinpoint-sms-voice-v2", region_name=_region())


def _load_origination_secret(secret_name: str, *, client=None) -> dict[str, Any]:
    cached = _ORIGINATION_CACHE.get(secret_name)
    if cached:
        return cached
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=_region())
    try:
        response = client.get_secret_value(SecretId=secret_name)
        data = json.loads(response.get("SecretString") or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception:  # noqa: BLE001 - a missing/denied secret simply means SMS stays off
        data = {}
    if data.get("origination_identity"):
        _ORIGINATION_CACHE[secret_name] = data
    return data


def resolve_origination(*, secrets_client=None) -> tuple[str, str]:
    """Resolve ``(origination_identity, configuration_set)`` for SMS.

    Order of precedence: explicit ``SMS_ORIGINATION_IDENTITY`` / ``SMS_CONFIGURATION_SET``
    env vars (local/testing override), then the Secrets Manager JSON secret named by
    ``SMS_ORIGINATION_SECRET_NAME``. Returns empty identity when nothing is configured.
    """
    identity = os.environ.get("SMS_ORIGINATION_IDENTITY", "").strip()
    config_set = os.environ.get("SMS_CONFIGURATION_SET", "").strip()
    if identity:
        return identity, config_set
    secret_name = os.environ.get("SMS_ORIGINATION_SECRET_NAME", "").strip()
    if not secret_name:
        return "", config_set
    data = _load_origination_secret(secret_name, client=secrets_client)
    return (
        str(data.get("origination_identity") or "").strip(),
        str(data.get("configuration_set") or config_set or "").strip(),
    )


def send_sms(
    *,
    to: str,
    body: str,
    origination: str = "",
    configuration_set: str = "",
    client: Any | None = None,
) -> dict[str, Any]:
    recipient = str(to or "").strip()
    if not recipient:
        raise SmsError("Recipient phone number is required.")
    message = str(body or "").strip()
    if not message:
        raise SmsError("SMS body is required.")
    if not origination:
        origination, resolved_config_set = resolve_origination()
        configuration_set = configuration_set or resolved_config_set
    if not origination:
        raise SmsError("SMS origination identity is not configured.")

    request: dict[str, Any] = {
        "DestinationPhoneNumber": recipient,
        "MessageBody": message,
        "OriginationIdentity": origination,
    }
    config_set = str(configuration_set or "").strip()
    if config_set:
        request["ConfigurationSetName"] = config_set

    client = client or _sms_client()
    return client.send_text_message(**request)
