"""The PLATFORM's Shippo key, used for one thing: asking what became of a parcel.

**Why a platform key at all, when shipping is BYOK per tenant.** Every tenant brings their own Shippo
account for rates and labels, so a tracker registered with their key reports to a webhook configured on
*their* account -- which is not ours, and which no tenant is going to paste a URL into. Worse, registration
would still succeed, so `guarantee_due.observable` would count those parcels as visible to us while no
delivery ever arrived: a sweep could then report a delivery guarantee due on a parcel the buyer already
has. The gate would be reporting on parcels it cannot actually see, which is the exact fault it exists to
prevent.

So tracking moves to ONE account we control, with ONE webhook registered once. Shippo's Tracking API
tracks parcels "created outside of Shippo", by carrier and tracking number, which is what makes this
possible at all.

**It covers the tenant who has no Shippo account.** That was written off as permanently unsolvable: someone
who posts at their local counter and types the number in has nothing to register with. Now we register it.
They are probably the largest group of sellers here, and they were the group the guarantee sweep could
never see.

**It costs.** Shippo includes tracking for shipments created on the account and charges per tracking number
for everything else, which is what a tenant's label is from this account's point of view. That is the price
of the coverage and it is paid per parcel, so this module is built to do exactly one registration per
shipment and never poll.

**Two keys, because Shippo's test mode is the rehearsal.** A live key tracks real parcels; a test key
accepts Shippo's mock tracking numbers and costs nothing. They are selected by the STRIPE mode of the
shipment, so a test-mode order never burns a paid track on a parcel that does not exist.

**Absent means off.** No secret, no key for this mode, or an unreachable Secrets Manager all return None,
and `tracking.register` treats that as "nothing to register" -- the parcel carries no feed, which is where
every parcel started. Nothing fails, and the sweep stays silent on it by the gate's own rule.
"""
import json
import os
from typing import Any

from stripe_link.domain.shipping_providers import ProviderError, provider_for

_KEY_CACHE: dict[str, str] = {}


def _region() -> str:
    return os.environ.get("AWS_REGION", "us-west-2")


def load_key(mode: str, *, client=None) -> str:
    """The platform tracking key for this Stripe mode, or "" when tracking is not configured.

    Not an environment variable, for `email_validation.load_api_key`'s reason: a key in the template is a
    key in git and in every deploy log. Cached per process and per mode.
    """
    secret_name = os.environ.get("SHIPPO_TRACKING_SECRET_NAME", "")
    if not secret_name:
        return ""
    field = "live_key" if str(mode or "").strip().lower() == "live" else "test_key"
    cache_key = f"{secret_name}:{field}"
    if cache_key in _KEY_CACHE:
        return _KEY_CACHE[cache_key]
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=_region())
    try:
        response = client.get_secret_value(SecretId=secret_name)
        data = json.loads(response.get("SecretString") or "{}")
        key = str((data or {}).get(field) or "").strip()
    except Exception:  # noqa: BLE001 - a missing or denied secret leaves tracking off, never failing
        key = ""
    if key:
        _KEY_CACHE[cache_key] = key
    return key


def platform_tracker(mode: str, *, secrets_client=None) -> Any | None:
    """A Shippo client bound to the PLATFORM key, for registering trackers. None when tracking is off.

    Deliberately the same `ShippoProvider` the tenant paths use rather than a second client: the only
    method called on it is `register_tracking`, and a parallel implementation of the same HTTP plumbing is
    how two callers of one API come to disagree about timeouts and error shapes.

    A caller must treat None as "no feed for this parcel" and never as "the parcel did not arrive" --
    `guarantee_due.observable` is the one that depends on the difference.
    """
    key = load_key(mode, client=secrets_client)
    if not key:
        return None
    try:
        return provider_for("shippo", key)
    except ProviderError:
        return None
