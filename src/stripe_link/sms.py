"""Transactional SMS via AWS End User Messaging (``pinpoint-sms-voice-v2``).

Sends from a single platform-owned 10DLC origination identity (a phone pool or number
ARN in ``SMS_ORIGINATION_IDENTITY``) through an optional configuration set. Mirrors
``mailer.py``: one thin adapter with an injectable client for tests.

US A2P 10DLC brand + campaign registration is a prerequisite for live delivery. The code
is fully exercised against a fake client until the origination number is provisioned; STOP
/HELP keyword handling and the carrier opt-out list are managed by End User Messaging itself.
"""

import os
from typing import Any


class SmsError(RuntimeError):
    pass


def _sms_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return boto3.client("pinpoint-sms-voice-v2", region_name=region)


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
    origination = str(origination or os.environ.get("SMS_ORIGINATION_IDENTITY", "")).strip()
    if not origination:
        raise SmsError("SMS origination identity is not configured.")

    request: dict[str, Any] = {
        "DestinationPhoneNumber": recipient,
        "MessageBody": message,
        "OriginationIdentity": origination,
    }
    config_set = str(configuration_set or os.environ.get("SMS_CONFIGURATION_SET", "")).strip()
    if config_set:
        request["ConfigurationSetName"] = config_set

    client = client or _sms_client()
    return client.send_text_message(**request)
